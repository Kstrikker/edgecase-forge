import hmac
import hashlib
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from main import app, STATE, reset_state

@pytest.fixture(autouse=True)
def setup_and_teardown():
    reset_state()
    yield
    reset_state()

def test_webhook_idempotency_leak_on_404():
    client = TestClient(app)
    with patch("main.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "1234567890abcdef"
        expected_order_id = "ord_1234567890"
        payload = {
            "event_id": "evt_failed_123",
            "event_type": "payment.failed",
            "order_id": expected_order_id
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = hmac.new(b"flashcart-benchmark-secret", payload_bytes, hashlib.sha256).hexdigest()
        response = client.post(
            "/payments/webhook",
            content=payload_bytes,
            headers={"X-Signature": signature}
        )
        assert response.status_code == 404
        order_response = client.post(
            "/orders",
            json={"product_id": 1, "quantity": 1, "payment_token": "approved"},
            headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "idem_1"}
        )
        assert order_response.status_code == 201
        assert order_response.json()["id"] == expected_order_id
        assert order_response.json()["status"] == "paid"
        response_retry = client.post(
            "/payments/webhook",
            content=payload_bytes,
            headers={"X-Signature": signature}
        )
        assert response_retry.status_code == 200
        assert response_retry.json() == {"status": "duplicate"}
        get_response = client.get(
            f"/orders/{expected_order_id}",
            headers={"Authorization": "Bearer buyer-a"}
        )
        assert get_response.status_code == 200
        assert get_response.json()["status"] == "paid"

def test_payment_timeout_desync():
    client = TestClient(app)
    response = client.post(
        "/orders",
        json={"product_id": 1, "quantity": 3, "payment_token": "timeout-once"},
        headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "idem_timeout"}
    )
    assert response.status_code == 504
    assert "idem_timeout" in STATE.payment.charges
    assert len(STATE.orders) == 0
    assert STATE.stock == 5
    response_b = client.post(
        "/orders",
        json={"product_id": 1, "quantity": 3, "payment_token": "approved"},
        headers={"Authorization": "Bearer buyer-b", "Idempotency-Key": "idem_b"}
    )
    assert response_b.status_code == 201
    assert STATE.stock == 2
    response_retry = client.post(
        "/orders",
        json={"product_id": 1, "quantity": 3, "payment_token": "timeout-once"},
        headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "idem_timeout"}
    )
    assert response_retry.status_code == 409
    assert response_retry.json()["detail"] == "Out of stock"
    assert "idem_timeout" in STATE.payment.charges
    assert len(STATE.orders) == 1
