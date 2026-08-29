from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

FLASHCART = Path(__file__).parents[1]
GENERATED = FLASHCART / "generated"
MUTANT_IDS = [f"M{index:02d}" for index in range(1, 11)]


def load_case(case_id: str):
    path = GENERATED / case_id / "main.py"
    module_name = f"flashcart_{case_id}_{id(path)}_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module.reset_state()
    return module


def headers(user: str = "buyer-a", key: str = "key-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {user}", "Idempotency-Key": key}


def order_payload(**overrides) -> dict:
    payload = {"product_id": 1, "quantity": 1, "payment_token": "approved"}
    payload.update(overrides)
    return payload


def create_paid_order(client: TestClient, *, key: str = "order-1") -> dict:
    response = client.post(
        "/orders",
        headers=headers(key=key),
        json=order_payload(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def signed_webhook(module, payload: dict, *, valid: bool = True) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(module.WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    if not valid:
        signature = "0" * len(signature)
    return body, signature


def post_webhook(client: TestClient, module, payload: dict, *, valid: bool = True):
    body, signature = signed_webhook(module, payload, valid=valid)
    return client.post(
        "/payments/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )


def check_m01(module) -> bool:
    """Inventory reservation is atomic across distinct checkout identities."""
    for attempt in range(3):
        module.reset_state()
        client = TestClient(module.app)
        with ThreadPoolExecutor(max_workers=20) as pool:
            responses = list(
                pool.map(
                    lambda index: client.post(
                        "/orders",
                        headers=headers(key=f"stock-race-{attempt}-{index}"),
                        json=order_payload(),
                    ),
                    range(20),
                )
            )
        successes = sum(response.status_code == 201 for response in responses)
        snapshot = module.evaluator_snapshot()
        if successes > 5 or snapshot["stock"] < 0 or len(snapshot["orders"]) > 5:
            return False
    return True


def check_m02(module) -> bool:
    """Concurrent retries of one idempotency identity create one logical order."""
    for attempt in range(3):
        module.reset_state()
        client = TestClient(module.app)
        with ThreadPoolExecutor(max_workers=10) as pool:
            responses = list(
                pool.map(
                    lambda _: client.post(
                        "/orders",
                        headers=headers(key=f"same-key-{attempt}"),
                        json=order_payload(),
                    ),
                    range(10),
                )
            )
        successful_ids = {
            response.json().get("id")
            for response in responses
            if response.status_code == 201
        }
        snapshot = module.evaluator_snapshot()
        if (
            len(successful_ids) != 1
            or len(snapshot["orders"]) != 1
            or len(snapshot["charges"]) != 1
            or snapshot["stock"] != 4
        ):
            return False
    return True


def check_m03(module) -> bool:
    client = TestClient(module.app)
    order = create_paid_order(client)
    response = client.get(
        f"/orders/{order['id']}",
        headers={"Authorization": "Bearer buyer-b"},
    )
    return response.status_code == 403


def check_m04(module) -> bool:
    client = TestClient(module.app)
    order = create_paid_order(client)
    payload = {
        "event_id": "evt-bad-signature",
        "event_type": "payment.failed",
        "order_id": order["id"],
    }
    response = post_webhook(client, module, payload, valid=False)
    snapshot = module.evaluator_snapshot()
    return (
        response.status_code == 401
        and payload["event_id"] not in snapshot["processed_events"]
        and payload["event_id"] not in snapshot["webhook_effects"]
    )


def check_m05(module) -> bool:
    client = TestClient(module.app)
    order = create_paid_order(client)
    payload = {
        "event_id": "evt-replay",
        "event_type": "payment.succeeded",
        "order_id": order["id"],
    }
    first = post_webhook(client, module, payload)
    second = post_webhook(client, module, payload)
    snapshot = module.evaluator_snapshot()
    return (
        first.status_code == 200
        and first.json() == {"status": "processed"}
        and second.status_code == 200
        and second.json() == {"status": "duplicate"}
        and snapshot["webhook_effects"].get(payload["event_id"]) == 1
    )


def check_m06(module) -> bool:
    client = TestClient(module.app)
    before = module.evaluator_snapshot()
    zero = client.post("/orders", headers=headers(key="zero"), json=order_payload(quantity=0))
    negative = client.post(
        "/orders", headers=headers(key="negative"), json=order_payload(quantity=-2)
    )
    after = module.evaluator_snapshot()
    return (
        zero.status_code == 422
        and negative.status_code == 422
        and before["stock"] == after["stock"]
        and not after["orders"]
        and not after["charges"]
    )


def check_m07(module) -> bool:
    """A definite decline releases inventory while retaining an audit record."""
    client = TestClient(module.app)
    before = module.evaluator_snapshot()
    response = client.post(
        "/orders",
        headers=headers(key="decline"),
        json=order_payload(payment_token="decline"),
    )
    after = module.evaluator_snapshot()
    orders = list(after["orders"].values())
    return (
        response.status_code == 402
        and before["stock"] == after["stock"]
        and len(orders) == 1
        and orders[0]["status"] == module.OrderStatus.PAYMENT_FAILED
        and orders[0]["inventory_released"] is True
        and not after["charges"]
    )


def check_m08(module) -> bool:
    """An ambiguous provider timeout is retried with one stable payment operation."""
    client = TestClient(module.app)
    payload = order_payload(payment_token="timeout-once")
    first = client.post("/orders", headers=headers(key="retry-key"), json=payload)
    after_first = module.evaluator_snapshot()
    first_orders = list(after_first["orders"].values())
    if (
        first.status_code != 504
        or len(first_orders) != 1
        or first_orders[0]["status"] != module.OrderStatus.PAYMENT_PENDING
        or after_first["stock"] != 4
        or len(after_first["charges"]) != 1
    ):
        return False
    order_id = first_orders[0]["id"]
    second = client.post("/orders", headers=headers(key="retry-key"), json=payload)
    after_second = module.evaluator_snapshot()
    return (
        second.status_code == 201
        and second.json()["id"] == order_id
        and second.json()["status"] == module.OrderStatus.PAID
        and after_second["stock"] == 4
        and len(after_second["orders"]) == 1
        and len(after_second["charges"]) == 1
    )


def check_m09(module) -> bool:
    client = TestClient(module.app)
    order = create_paid_order(client)
    first = client.post(
        f"/orders/{order['id']}/cancel",
        headers={"Authorization": "Bearer buyer-a"},
    )
    stock_after_first = module.evaluator_snapshot()["stock"]
    second = client.post(
        f"/orders/{order['id']}/cancel",
        headers={"Authorization": "Bearer buyer-a"},
    )
    stock_after_second = module.evaluator_snapshot()["stock"]
    return (
        first.status_code == 200
        and second.status_code == 200
        and first.json()["status"] == module.OrderStatus.CANCELLED
        and second.json()["status"] == module.OrderStatus.CANCELLED
        and stock_after_first == stock_after_second == module.INITIAL_STOCK
    )


def check_m10(module) -> bool:
    client = TestClient(module.app)
    response = client.post(
        "/orders",
        headers=headers(key="server-price"),
        json=order_payload(quantity=2, quoted_total=1),
    )
    if response.status_code != 201:
        return False
    order = response.json()
    charge = next(iter(module.evaluator_snapshot()["charges"].values()))
    return order["total"] == 2000 and charge["amount"] == 2000


CHECKS = {
    "M01": check_m01,
    "M02": check_m02,
    "M03": check_m03,
    "M04": check_m04,
    "M05": check_m05,
    "M06": check_m06,
    "M07": check_m07,
    "M08": check_m08,
    "M09": check_m09,
    "M10": check_m10,
}


def test_reset_preserves_imported_state_reference() -> None:
    module = load_case("C00")
    imported_state = module.STATE
    imported_state.stock = 0
    module.reset_state()
    assert module.STATE is imported_state
    assert imported_state.stock == module.INITIAL_STOCK


def test_missing_order_webhook_does_not_consume_event() -> None:
    module = load_case("C00")
    client = TestClient(module.app)
    order_id = "ord_1234567890"
    payload = {
        "event_id": "evt-before-order",
        "event_type": "payment.succeeded",
        "order_id": order_id,
    }
    missing = post_webhook(client, module, payload)
    assert missing.status_code == 404
    assert payload["event_id"] not in module.evaluator_snapshot()["processed_events"]

    with patch.object(module, "uuid4", return_value=SimpleNamespace(hex="1234567890abcdef")):
        pending = client.post(
            "/orders",
            headers=headers(key="late-order"),
            json=order_payload(payment_token="timeout-once"),
        )
    assert pending.status_code == 504
    retried = post_webhook(client, module, payload)
    assert retried.status_code == 200
    assert retried.json() == {"status": "processed"}
    assert client.get(
        f"/orders/{order_id}", headers={"Authorization": "Bearer buyer-a"}
    ).json()["status"] == module.OrderStatus.PAID


def test_timeout_preserves_order_reservation_and_single_charge() -> None:
    module = load_case("C00")
    client = TestClient(module.app)
    payload = order_payload(quantity=3, payment_token="timeout-once")
    first = client.post("/orders", headers=headers(key="timeout"), json=payload)
    assert first.status_code == 504
    after_timeout = module.evaluator_snapshot()
    pending_order = next(iter(after_timeout["orders"].values()))
    assert pending_order["status"] == module.OrderStatus.PAYMENT_PENDING
    assert after_timeout["stock"] == 2
    assert len(after_timeout["charges"]) == 1

    other = client.post(
        "/orders",
        headers=headers(user="buyer-b", key="other-buyer"),
        json=order_payload(quantity=2),
    )
    assert other.status_code == 201
    retry = client.post("/orders", headers=headers(key="timeout"), json=payload)
    final = module.evaluator_snapshot()
    assert retry.status_code == 201
    assert retry.json()["id"] == pending_order["id"]
    assert final["stock"] == 0
    assert len(final["orders"]) == 2
    assert len(final["charges"]) == 2


def test_same_idempotency_key_rejects_different_payload() -> None:
    module = load_case("C00")
    client = TestClient(module.app)
    first = client.post("/orders", headers=headers(key="same"), json=order_payload(quantity=1))
    second = client.post("/orders", headers=headers(key="same"), json=order_payload(quantity=2))
    snapshot = module.evaluator_snapshot()
    assert first.status_code == 201
    assert second.status_code == 409
    assert len(snapshot["orders"]) == 1
    assert len(snapshot["charges"]) == 1
    assert snapshot["stock"] == 4


def test_terminal_paid_order_does_not_regress_from_late_webhook() -> None:
    module = load_case("C00")
    client = TestClient(module.app)
    order = create_paid_order(client)
    response = post_webhook(
        client,
        module,
        {
            "event_id": "evt-late-failure",
            "event_type": "payment.failed",
            "order_id": order["id"],
        },
    )
    stored = client.get(
        f"/orders/{order['id']}", headers={"Authorization": "Bearer buyer-a"}
    )
    assert response.status_code == 200
    assert stored.json()["status"] == module.OrderStatus.PAID
    assert module.evaluator_snapshot()["stock"] == 4


@pytest.mark.parametrize("oracle_id", MUTANT_IDS)
def test_clean_control_satisfies_every_oracle(oracle_id: str) -> None:
    assert CHECKS[oracle_id](load_case("C00")), oracle_id


@pytest.mark.parametrize("case_id", MUTANT_IDS)
@pytest.mark.parametrize("oracle_id", MUTANT_IDS)
def test_each_mutant_is_isolated(case_id: str, oracle_id: str) -> None:
    expected = case_id != oracle_id
    assert CHECKS[oracle_id](load_case(case_id)) is expected, (
        f"{case_id} unexpectedly {'passed' if not expected else 'failed'} {oracle_id}"
    )
