from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from threading import RLock
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="FlashCart API", version="1.0.0")
WEBHOOK_SECRET = b"flashcart-benchmark-secret"


class OrderRequest(BaseModel):
    product_id: int = 1
    quantity: int = Field(gt=0, le=5)
    quoted_total: int | None = None
    payment_token: str = "approved"


class WebhookPayload(BaseModel):
    event_id: str
    event_type: Literal["payment.succeeded", "payment.failed"]
    order_id: str


@dataclass
class PaymentStub:
    charges: dict[str, dict] = field(default_factory=dict)
    timeout_keys: set[str] = field(default_factory=set)

    def charge(self, idempotency_key: str, amount: int, token: str) -> dict:
        if idempotency_key in self.charges:
            return self.charges[idempotency_key]
        if token == "decline":
            raise HTTPException(status_code=402, detail="Payment declined")
        charge = {"id": f"ch_{len(self.charges) + 1}", "amount": amount}
        self.charges[idempotency_key] = charge
        if token == "timeout-once" and idempotency_key not in self.timeout_keys:
            self.timeout_keys.add(idempotency_key)
            raise HTTPException(status_code=504, detail="Payment provider timed out")
        return charge


@dataclass
class StoreState:
    stock: int = 5
    price: int = 1000
    orders: dict[str, dict] = field(default_factory=dict)
    idempotency: dict[tuple[str, str], str] = field(default_factory=dict)
    processed_events: set[str] = field(default_factory=set)
    webhook_effects: dict[str, int] = field(default_factory=dict)
    payment: PaymentStub = field(default_factory=PaymentStub)
    lock: RLock = field(default_factory=RLock)


STATE = StoreState()


def reset_state() -> None:
    global STATE
    STATE = StoreState()


def _user_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    if token not in {"buyer-a", "buyer-b", "admin"}:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return token


@app.get("/products/{product_id}")
def get_product(product_id: int) -> dict:
    if product_id != 1:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"id": 1, "price": STATE.price, "stock": STATE.stock}


@app.post("/orders", status_code=201)
def create_order(
    payload: OrderRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    user = _user_from_header(authorization)
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    with STATE.lock:
        return _create_order_core(user, idempotency_key, payload)


def _create_order_core(user: str, idempotency_key: str, payload: OrderRequest) -> dict:
    idempotency_identity = (user, idempotency_key)
    existing_order_id = STATE.idempotency.get(idempotency_identity)
    if existing_order_id:
        return STATE.orders[existing_order_id]
    if payload.product_id != 1:
        raise HTTPException(status_code=404, detail="Product not found")
    if STATE.stock < payload.quantity:
        raise HTTPException(status_code=409, detail="Out of stock")

    amount = STATE.price * payload.quantity
    charge = STATE.payment.charge(idempotency_key, amount, payload.payment_token)
    STATE.stock -= payload.quantity

    order_id = f"ord_{uuid4().hex[:10]}"
    order = {
        "id": order_id,
        "owner": user,
        "product_id": payload.product_id,
        "quantity": payload.quantity,
        "total": amount,
        "charge_id": charge["id"],
        "status": "paid",
    }
    STATE.orders[order_id] = order
    STATE.idempotency[idempotency_identity] = order_id
    return order


@app.get("/orders/{order_id}")
def get_order(
    order_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    user = _user_from_header(authorization)
    order = STATE.orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if user != "admin" and order["owner"] != user:
        raise HTTPException(status_code=403, detail="Order belongs to another user")
    return order


@app.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    user = _user_from_header(authorization)
    with STATE.lock:
        order = STATE.orders.get(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if user != "admin" and order["owner"] != user:
            raise HTTPException(status_code=403, detail="Order belongs to another user")
        if order["status"] == "cancelled":
            return order
        order["status"] = "cancelled"
        STATE.stock += order["quantity"]
        return order


@app.post("/payments/webhook")
async def payment_webhook(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
) -> dict:
    raw_body = await request.body()
    expected = hmac.new(WEBHOOK_SECRET, raw_body, hashlib.sha256).hexdigest()
    if not x_signature or not hmac.compare_digest(x_signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    payload = WebhookPayload.model_validate(json.loads(raw_body))
    with STATE.lock:
        if payload.event_id in STATE.processed_events:
            return {"status": "duplicate"}
        STATE.processed_events.add(payload.event_id)
        order = STATE.orders.get(payload.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        STATE.webhook_effects[payload.event_id] = (
            STATE.webhook_effects.get(payload.event_id, 0) + 1
        )
        order["status"] = "paid" if payload.event_type == "payment.succeeded" else "failed"
    return {"status": "processed"}


def evaluator_snapshot() -> dict:
    """Private oracle hook. This function is removed from agent-visible builds."""
    with STATE.lock:
        return {
            "stock": STATE.stock,
            "orders": {key: value.copy() for key, value in STATE.orders.items()},
            "charges": {key: value.copy() for key, value in STATE.payment.charges.items()},
            "processed_events": sorted(STATE.processed_events),
            "webhook_effects": STATE.webhook_effects.copy(),
        }

