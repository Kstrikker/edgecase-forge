import pytest
from fastapi.testclient import TestClient
from main import app, reset_state, STATE

@pytest.fixture(autouse=True)
def clean_state():
    reset_state()

def test_webhook_signature_bypass():
    client = TestClient(app)
    headers = {"Authorization": "Bearer buyer-a", "Idempotency-Key": "key-1"}
    order_resp = client.post("/orders", json={"product_id": 1, "quantity": 1}, headers=headers)
    assert order_resp.status_code == 201
    order_id = order_resp.json()["id"]
    
    webhook_data = {
        "event_id": "evt_1",
        "event_type": "payment.failed",
        "order_id": order_id
    }
    webhook_headers = {"X-Signature": "invalid-signature-here"}
    resp = client.post("/payments/webhook", json=webhook_data, headers=webhook_headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "processed"}
    
    order_check = client.get(f"/orders/{order_id}", headers={"Authorization": "Bearer buyer-a"})
    assert order_check.json()["status"] == "failed"

def test_payment_timeout_stock_consistency():
    client = TestClient(app)
    STATE.stock = 1
    
    headers_a = {"Authorization": "Bearer buyer-a", "Idempotency-Key": "idemp-a"}
    resp_a1 = client.post("/orders", json={"product_id": 1, "quantity": 1, "payment_token": "timeout-once"}, headers=headers_a)
    assert resp_a1.status_code == 504
    assert "idemp-a" in STATE.payment.charges
    
    headers_b = {"Authorization": "Bearer buyer-b", "Idempotency-Key": "idemp-b"}
    resp_b = client.post("/orders", json={"product_id": 1, "quantity": 1, "payment_token": "approved"}, headers=headers_b)
    assert resp_b.status_code == 201
    assert STATE.stock == 0
    
    resp_a2 = client.post("/orders", json={"product_id": 1, "quantity": 1, "payment_token": "timeout-once"}, headers=headers_a)
    assert resp_a2.status_code == 409
