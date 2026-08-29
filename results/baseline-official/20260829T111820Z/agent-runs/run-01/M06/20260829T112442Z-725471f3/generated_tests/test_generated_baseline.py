import pytest
from fastapi.testclient import TestClient
import hmac
import hashlib
import json

from main import app, reset_state, STATE, WEBHOOK_SECRET

@pytest.fixture(autouse=True)
def run_around_tests():
    reset_state()
    yield

def test_payment_timeout_retry_stock_depletion():
    client = TestClient(app)
    STATE.stock = 1
    
    headers_a = {
        "Authorization": "Bearer buyer-a",
        "Idempotency-Key": "key-a"
    }
    payload_a = {
        "product_id": 1,
        "quantity": 1,
        "payment_token": "timeout-once"
    }
    response = client.post("/orders", json=payload_a, headers=headers_a)
    assert response.status_code == 504
    assert "key-a" in STATE.payment.charges
    
    headers_b = {
        "Authorization": "Bearer buyer-b",
        "Idempotency-Key": "key-b"
    }
    payload_b = {
        "product_id": 1,
        "quantity": 1,
        "payment_token": "approved"
    }
    response = client.post("/orders", json=payload_b, headers=headers_b)
    assert response.status_code == 201
    assert STATE.stock == 0
    
    response = client.post("/orders", json=payload_a, headers=headers_a)
    assert response.status_code == 409

def test_webhook_transitions_cancelled_order_to_paid():
    client = TestClient(app)
    STATE.stock = 5
    
    headers = {
        "Authorization": "Bearer buyer-a",
        "Idempotency-Key": "key-1"
    }
    payload = {
        "product_id": 1,
        "quantity": 2,
        "payment_token": "approved"
    }
    response = client.post("/orders", json=payload, headers=headers)
    assert response.status_code == 201
    order_id = response.json()["id"]
    assert STATE.stock == 3
    
    response = client.post(f"/orders/{order_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert STATE.stock == 5
    assert response.json()["status"] == "cancelled"
    
    webhook_data = {
        "event_id": "evt-1",
        "event_type": "payment.succeeded",
        "order_id": order_id
    }
    body_bytes = json.dumps(webhook_data).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET, body_bytes, hashlib.sha256).hexdigest()
    
    response = client.post(
        "/payments/webhook",
        content=body_bytes,
        headers={"X-Signature": sig, "Content-Type": "application/json"}
    )
    assert response.status_code == 200
    
    order_response = client.get(f"/orders/{order_id}", headers=headers)
    assert order_response.json()["status"] == "paid"
    assert STATE.stock == 5

def test_webhook_event_id_marked_processed_on_404():
    client = TestClient(app)
    
    webhook_data = {
        "event_id": "evt-1",
        "event_type": "payment.succeeded",
        "order_id": "non-existent-order"
    }
    body_bytes = json.dumps(webhook_data).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET, body_bytes, hashlib.sha256).hexdigest()
    
    response = client.post(
        "/payments/webhook",
        content=body_bytes,
        headers={"X-Signature": sig, "Content-Type": "application/json"}
    )
    assert response.status_code == 404
    
    headers = {
        "Authorization": "Bearer buyer-a",
        "Idempotency-Key": "key-1"
    }
    payload = {
        "product_id": 1,
        "quantity": 1,
        "payment_token": "approved"
    }
    create_response = client.post("/orders", json=payload, headers=headers)
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]
    
    webhook_data["order_id"] = order_id
    body_bytes = json.dumps(webhook_data).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET, body_bytes, hashlib.sha256).hexdigest()
    
    response = client.post(
        "/payments/webhook",
        content=body_bytes,
        headers={"X-Signature": sig, "Content-Type": "application/json"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "duplicate"}

def test_global_payment_idempotency_leak():
    client = TestClient(app)
    
    headers_a = {
        "Authorization": "Bearer buyer-a",
        "Idempotency-Key": "shared-key"
    }
    payload_a = {
        "product_id": 1,
        "quantity": 1,
        "payment_token": "approved"
    }
    res_a = client.post("/orders", json=payload_a, headers=headers_a)
    assert res_a.status_code == 201
    charge_id_a = res_a.json()["charge_id"]
    
    headers_b = {
        "Authorization": "Bearer buyer-b",
        "Idempotency-Key": "shared-key"
    }
    payload_b = {
        "product_id": 1,
        "quantity": 1,
        "payment_token": "approved"
    }
    res_b = client.post("/orders", json=payload_b, headers=headers_b)
    assert res_b.status_code == 201
    charge_id_b = res_b.json()["charge_id"]
    
    assert charge_id_a == charge_id_b
