from __future__ import annotations

from threading import Lock

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Ticket Store")


class Purchase(BaseModel):
    quantity: int = Field(gt=0, le=10)


stock = {1: 1}
stock_lock = Lock()


@app.get("/products/{product_id}")
def get_product(product_id: int) -> dict[str, int]:
    if product_id not in stock:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"id": product_id, "stock": stock[product_id]}


@app.post("/orders/{product_id}", status_code=201)
def create_order(product_id: int, purchase: Purchase) -> dict[str, int | str]:
    if product_id not in stock:
        raise HTTPException(status_code=404, detail="Product not found")
    with stock_lock:
        if stock[product_id] < purchase.quantity:
            raise HTTPException(status_code=409, detail="Out of stock")
        stock[product_id] -= purchase.quantity
        remaining = stock[product_id]
    return {"status": "confirmed", "quantity": purchase.quantity, "remaining": remaining}


def reset_fixture() -> None:
    with stock_lock:
        stock[1] = 1

