import asyncio
import httpx
import pytest
from main import app, reset_state, STATE

@pytest.mark.asyncio
async def test_concurrent_idempotency_race():
    reset_state()
    STATE.stock = 5
    
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        headers = {
            "Authorization": "Bearer buyer-a",
            "Idempotency-Key": "same-key-123"
        }
        payload = {
            "product_id": 1,
            "quantity": 3,
            "payment_token": "approved"
        }
        
        # Send two concurrent requests with the same idempotency key
        responses = await asyncio.gather(
            client.post("/orders", json=payload, headers=headers),
            client.post("/orders", json=payload, headers=headers)
        )
        
        # If idempotency was respected, only one order should have been created,
        # or both should return the exact same order ID.
        order_ids = [r.json().get("id") for r in responses if r.status_code == 201]
        
        # Assert that we did not create multiple distinct orders
        assert len(set(order_ids)) == 1, f"Created multiple orders for the same idempotency key: {order_ids}"
        assert STATE.stock >= 2, f"Stock went below expected level: {STATE.stock}"

@pytest.mark.asyncio
async def test_concurrent_stock_oversell():
    reset_state()
    STATE.stock = 5
    
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        # Two different buyers requesting 4 items each concurrently
        req1 = client.post(
            "/orders",
            json={"product_id": 1, "quantity": 4},
            headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "key-a"}
        )
        req2 = client.post(
            "/orders",
            json={"product_id": 1, "quantity": 4},
            headers={"Authorization": "Bearer buyer-b", "Idempotency-Key": "key-b"}
        )
        
        responses = await asyncio.gather(req1, req2)
        
        status_codes = [r.status_code for r in responses]
        # One of the requests must fail with 409 Out of stock
        assert 409 in status_codes, f"Neither request failed with 409. Statuses: {status_codes}"
        assert STATE.stock >= 0, f"Stock went negative: {STATE.stock}"
