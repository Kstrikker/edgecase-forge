from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

INITIAL_STOCK = 5
CATALOG_PRICE = 1000
WEBHOOK_SECRET = b"flashcart-benchmark-secret"

app = FastAPI(title="FlashCart API", version="1.1.0")


class OrderStatus(StrEnum):
    PAYMENT_PENDING = "payment_pending"
    PAYMENT_FAILED = "payment_failed"
    PAID = "paid"
    CANCELLED = "cancelled"


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
    lock: RLock = field(default_factory=RLock)

    def reset(self) -> None:
        with self.lock:
            self.charges.clear()
            self.timeout_keys.clear()

    def charge(self, operation_key: str, amount: int, token: str) -> dict:
        with self.lock:
            existing = self.charges.get(operation_key)
            if existing:
                return existing
            if token == "decline":
                raise HTTPException(status_code=402, detail="Payment declined")

            charge = {"id": f"ch_{len(self.charges) + 1}", "amount": amount}
            self.charges[operation_key] = charge
            if token == "timeout-once" and operation_key not in self.timeout_keys:
                self.timeout_keys.add(operation_key)
                raise HTTPException(status_code=504, detail="Payment provider timed out")
            return charge


@dataclass
class StoreState:
    stock: int = INITIAL_STOCK
    price: int = CATALOG_PRICE
    orders: dict[str, dict] = field(default_factory=dict)
    idempotency: dict[tuple[str, str], str] = field(default_factory=dict)
    processed_events: set[str] = field(default_factory=set)
    webhook_effects: dict[str, int] = field(default_factory=dict)
    payment: PaymentStub = field(default_factory=PaymentStub)
    state_lock: RLock = field(default_factory=RLock)
    inventory_lock: RLock = field(default_factory=RLock)
    idempotency_locks: dict[tuple[str, str], RLock] = field(default_factory=dict)


STATE = StoreState()


def reset_state() -> None:
    """Restore canonical state without invalidating imported references."""
    with STATE.state_lock, STATE.inventory_lock:
        STATE.stock = INITIAL_STOCK
        STATE.price = CATALOG_PRICE
        STATE.orders.clear()
        STATE.idempotency.clear()
        STATE.processed_events.clear()
        STATE.webhook_effects.clear()
        STATE.idempotency_locks.clear()
        STATE.payment.reset()


def _user_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    if token not in {"buyer-a", "buyer-b", "admin"}:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return token


def _request_fingerprint(payload: OrderRequest) -> tuple[int, int, int | None, str]:
    return (
        payload.product_id,
        payload.quantity,
        payload.quoted_total,
        payload.payment_token,
    )


def _identity_lock(identity: tuple[str, str]) -> RLock:
    with STATE.state_lock:
        return STATE.idempotency_locks.setdefault(identity, RLock())


def _reserve_inventory(quantity: int) -> None:
    with STATE.inventory_lock:
        if STATE.stock < quantity:
            raise HTTPException(status_code=409, detail="Out of stock")
        STATE.stock -= quantity


def _release_inventory_once(order: dict) -> None:
    with STATE.inventory_lock:
        if order["inventory_released"]:
            return
        STATE.stock += order["quantity"]
        order["inventory_released"] = True


def _public_order(order: dict) -> dict:
    private_fields = {
        "request_fingerprint",
        "payment_key",
        "payment_token",
        "inventory_released",
        "failure_status",
    }
    return {key: value for key, value in order.items() if key not in private_fields}


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
    identity = (user, idempotency_key)
    with _identity_lock(identity):
        return _create_order_core(user, idempotency_key, payload)


def _create_order_core(user: str, idempotency_key: str, payload: OrderRequest) -> dict:
    identity = (user, idempotency_key)
    fingerprint = _request_fingerprint(payload)
    existing_order_id = STATE.idempotency.get(identity)

    if existing_order_id:
        order = STATE.orders[existing_order_id]
        if order["request_fingerprint"] != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency-Key payload mismatch")
        if order["status"] == OrderStatus.PAYMENT_FAILED:
            raise HTTPException(status_code=order["failure_status"], detail="Payment declined")
        if order["status"] != OrderStatus.PAYMENT_PENDING:
            return _public_order(order)
    else:
        if payload.product_id != 1:
            raise HTTPException(status_code=404, detail="Product not found")
        _reserve_inventory(payload.quantity)
        order_id = f"ord_{uuid4().hex[:10]}"
        order = {
            "id": order_id,
            "owner": user,
            "product_id": payload.product_id,
            "quantity": payload.quantity,
            "total": STATE.price * payload.quantity,
            "charge_id": None,
            "status": OrderStatus.PAYMENT_PENDING,
            "request_fingerprint": fingerprint,
            "payment_key": f"checkout:{order_id}",
            "payment_token": payload.payment_token,
            "inventory_released": False,
            "failure_status": None,
        }
        STATE.orders[order_id] = order
        STATE.idempotency[identity] = order_id

    try:
        charge = STATE.payment.charge(
            order["payment_key"], order["total"], order["payment_token"]
        )
    except HTTPException as exc:
        if exc.status_code == 402:
            order["status"] = OrderStatus.PAYMENT_FAILED
            order["failure_status"] = 402
            _release_inventory_once(order)
        raise

    order["charge_id"] = charge["id"]
    order["status"] = OrderStatus.PAID
    return _public_order(order)


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
    return _public_order(order)


@app.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    user = _user_from_header(authorization)
    with STATE.state_lock:
        order = STATE.orders.get(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if user != "admin" and order["owner"] != user:
            raise HTTPException(status_code=403, detail="Order belongs to another user")
        if order["status"] == OrderStatus.CANCELLED:
            return _public_order(order)
        if order["status"] != OrderStatus.PAID:
            raise HTTPException(status_code=409, detail="Only paid orders can be cancelled")
        order["status"] = OrderStatus.CANCELLED
        _release_inventory_once(order)
        return _public_order(order)


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

    with STATE.state_lock:
        if payload.event_id in STATE.processed_events:
            return {"status": "duplicate"}
        order = STATE.orders.get(payload.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order["status"] == OrderStatus.PAYMENT_PENDING:
            if payload.event_type == "payment.succeeded":
                order["status"] = OrderStatus.PAID
                charge = STATE.payment.charges.get(order["payment_key"])
                if charge:
                    order["charge_id"] = charge["id"]
            else:
                order["status"] = OrderStatus.PAYMENT_FAILED
                order["failure_status"] = 402
                _release_inventory_once(order)

        STATE.webhook_effects[payload.event_id] = (
            STATE.webhook_effects.get(payload.event_id, 0) + 1
        )
        STATE.processed_events.add(payload.event_id)
    return {"status": "processed"}


def evaluator_snapshot() -> dict:
    """Private oracle hook. This function is removed from agent-visible builds."""
    with STATE.state_lock, STATE.inventory_lock, STATE.payment.lock:
        return {
            "stock": STATE.stock,
            "orders": {key: value.copy() for key, value in STATE.orders.items()},
            "charges": {key: value.copy() for key, value in STATE.payment.charges.items()},
            "processed_events": sorted(STATE.processed_events),
            "webhook_effects": STATE.webhook_effects.copy(),
        }
