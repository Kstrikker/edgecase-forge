from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Ticket Store")


class Purchase(BaseModel):
    quantity: int = Field(gt=0, le=10)


stock = {1: 1}


@app.get("/products/{product_id}")
def get_product(product_id: int) -> dict[str, int]:
    if product_id not in stock:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"id": product_id, "stock": stock[product_id]}


@app.post("/orders/{product_id}", status_code=201)
def create_order(product_id: int, purchase: Purchase) -> dict[str, int | str]:
    if product_id not in stock:
        raise HTTPException(status_code=404, detail="Product not found")
    available = stock[product_id]
    if available < purchase.quantity:
        raise HTTPException(status_code=409, detail="Out of stock")
    time.sleep(0.02)
    stock[product_id] = available - purchase.quantity
    return {
        "status": "confirmed",
        "quantity": purchase.quantity,
        "remaining": stock[product_id],
    }


def reset_fixture() -> None:
    stock[1] = 1

