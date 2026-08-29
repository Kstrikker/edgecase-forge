import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from main import app, reset_state, STATE

def test_webhook_duplicate_processing():
    reset_state()
    client = TestClient(app)
    
    # Create an order first
    headers = {
        "Authorization": "Bearer buyer-a",
        "Idempotency-Key": "key-1"
    }
    order_resp = client.post("/orders", json={"quantity": 2}, headers=headers)
    assert order_resp.status_code == 201
    order_id = order_resp.json()["id"]
    
    # Prepare webhook payload
    payload = {
        "event_id": "evt_123",
        "event_type": "payment.succeeded",
        "order_id": order_id
    }
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(b"flashcart-benchmark-secret", body, hashlib.sha256).hexdigest()
    
    # Send webhook first time
    resp1 = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Signature": signature, "Content-Type": "application/json"}
    )
    assert resp1.status_code == 200
    assert resp1.json() == {"status": "processed"}
    
    # Send webhook second time (duplicate)
    resp2 = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Signature": signature, "Content-Type": "application/json"}
    )
    # It should return duplicate, but due to the bug it returns processed
    assert resp2.json() == {"status": "duplicate"}

def test_cancelled_order_webhook_stock_duplication():
    reset_state()
    client = TestClient(app)
    
    # 1. Check initial stock
    prod_resp = client.get("/products/1")
    assert prod_resp.json()["stock"] == 5
    
    # 2. Create order for 3 items
    headers = {
        "Authorization": "Bearer buyer-a",
        "Idempotency-Key": "key-2"
    }
    order_resp = client.post("/orders", json={"quantity": 3}, headers=headers)
    assert order_resp.status_code == 201
    order_id = order_resp.json()["id"]
    
    # Stock should be 2
    prod_resp = client.get("/products/1")
    assert prod_resp.json()["stock"] == 2
    
    # 3. Cancel the order
    cancel_resp = client.post(f"/orders/{order_id}/cancel", headers={"Authorization": "Bearer buyer-a"})
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
    
    # Stock should be restored to 5
    prod_resp = client.get("/products/1")
    assert prod_resp.json()["stock"] == 5
    
    # 4. Send webhook payment.succeeded for the cancelled order
    payload = {
        "event_id": "evt_456",
        "event_type": "payment.succeeded",
        "order_id": order_id
    }
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(b"flashcart-benchmark-secret", body, hashlib.sha256).hexdigest()
    
    webhook_resp = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Signature": signature, "Content-Type": "application/json"}
    )
    assert webhook_resp.status_code == 200
    
    # The order status should NOT be changed back to paid
    order_get = client.get(f"/orders/{order_id}", headers={"Authorization": "Bearer buyer-a"})
    assert order_get.json()["status"] == "cancelled"
    
    # If the bug is present, the status becomes "paid", allowing us to cancel again and duplicate stock
    client.post(f"/orders/{order_id}/cancel", headers={"Authorization": "Bearer buyer-a"})
    prod_resp = client.get("/products/1")
    assert prod_resp.json()["stock"] <= 5
