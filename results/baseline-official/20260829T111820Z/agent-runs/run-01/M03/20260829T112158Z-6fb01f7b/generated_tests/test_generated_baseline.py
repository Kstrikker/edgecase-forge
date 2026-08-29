import pytest
from fastapi.testclient import TestClient
from main import app, reset_state

def test_get_order_authorization_bypass():
    reset_state()
    client = TestClient(app)
    
    # Create an order as buyer-a
    res = client.post(
        "/orders",
        json={"product_id": 1, "quantity": 1},
        headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "key-1"}
    )
    assert res.status_code == 201
    order_id = res.json()["id"]
    
    # Attempt to access buyer-a's order as buyer-b
    res_b = client.get(
        f"/orders/{order_id}",
        headers={"Authorization": "Bearer buyer-b"}
    )
    # This should return 403 Forbidden because buyer-b does not own the order and is not an admin
    assert res_b.status_code == 403
