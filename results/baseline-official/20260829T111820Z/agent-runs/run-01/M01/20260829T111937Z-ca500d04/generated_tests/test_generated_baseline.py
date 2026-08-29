import asyncio
import httpx
import pytest
from main import app, reset_state, STATE

def test_concurrency_oversell():
    reset_state()
    assert STATE.stock == 5
    
    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            req1 = client.post(
                "/orders",
                json={"product_id": 1, "quantity": 3},
                headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "key-1"}
            )
            req2 = client.post(
                "/orders",
                json={"product_id": 1, "quantity": 3},
                headers={"Authorization": "Bearer buyer-b", "Idempotency-Key": "key-2"}
            )
            return await asyncio.gather(req1, req2)
            
    responses = asyncio.run(run())
    status_codes = [r.status_code for r in responses]
    
    # If both succeeded, we have an oversell bug!
    assert 409 in status_codes, f"One of the requests should have failed with 409 Out of Stock, got {status_codes}"
    assert STATE.stock >= 0, f"Stock should not be negative, got {STATE.stock}"

def test_concurrent_same_idempotency_key():
    reset_state()
    assert STATE.stock == 5
    
    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            req1 = client.post(
                "/orders",
                json={"product_id": 1, "quantity": 3},
                headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "same-key"}
            )
            req2 = client.post(
                "/orders",
                json={"product_id": 1, "quantity": 3},
                headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "same-key"}
            )
            return await asyncio.gather(req1, req2)
            
    responses = asyncio.run(run())
    
    # Both responses should return 201 Created (or one returns the cached response of the other)
    assert responses[0].status_code == 201
    assert responses[1].status_code == 201
    
    # But only 1 order should actually be created in the state, and stock should only be decremented once
    assert len(STATE.orders) == 1, f"Expected exactly 1 order, but got {len(STATE.orders)}"
    assert STATE.stock == 2, f"Expected stock to be 2, but got {STATE.stock}"
