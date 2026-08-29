from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FLASHCART = Path(__file__).parents[1]
GENERATED = FLASHCART / "generated"
CASES = [f"M{index:02d}" for index in range(1, 11)]


def load_case(case_id: str):
    path = GENERATED / case_id / "main.py"
    module_name = f"flashcart_{case_id}_{id(path)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module.reset_state()
    return module


def headers(user: str = "buyer-a", key: str = "key-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {user}", "Idempotency-Key": key}


def create_paid_order(client: TestClient, *, key: str = "order-1") -> dict:
    response = client.post(
        "/orders",
        headers=headers(key=key),
        json={"product_id": 1, "quantity": 1, "payment_token": "approved"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def signed_webhook(module, payload: dict, *, valid: bool = True) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(module.WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    if not valid:
        signature = "0" * len(signature)
    return body, signature


def check_m01(module) -> bool:
    client = TestClient(module.app)
    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(
            pool.map(
                lambda i: client.post(
                    "/orders",
                    headers=headers(key=f"race-{i}"),
                    json={"product_id": 1, "quantity": 1},
                ),
                range(20),
            )
        )
    successes = sum(response.status_code == 201 for response in responses)
    return successes <= 5 and module.evaluator_snapshot()["stock"] >= 0


def check_m02(module) -> bool:
    client = TestClient(module.app)
    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    "/orders",
                    headers=headers(key="same-key"),
                    json={"product_id": 1, "quantity": 1},
                ),
                range(10),
            )
        )
    ids = {response.json().get("id") for response in responses if response.status_code == 201}
    snapshot = module.evaluator_snapshot()
    return len(ids) == 1 and len(snapshot["orders"]) == 1 and len(snapshot["charges"]) == 1


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
    payload = {"event_id": "evt-bad", "event_type": "payment.failed", "order_id": order["id"]}
    body, signature = signed_webhook(module, payload, valid=False)
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )
    snapshot = module.evaluator_snapshot()
    return response.status_code == 401 and "evt-bad" not in snapshot["processed_events"]


def check_m05(module) -> bool:
    client = TestClient(module.app)
    order = create_paid_order(client)
    payload = {"event_id": "evt-replay", "event_type": "payment.succeeded", "order_id": order["id"]}
    body, signature = signed_webhook(module, payload)
    request_headers = {"Content-Type": "application/json", "X-Signature": signature}
    first = client.post("/payments/webhook", content=body, headers=request_headers)
    second = client.post("/payments/webhook", content=body, headers=request_headers)
    snapshot = module.evaluator_snapshot()
    return (
        first.status_code == 200
        and second.status_code == 200
        and second.json()["status"] == "duplicate"
        and snapshot["webhook_effects"].get("evt-replay") == 1
    )


def check_m06(module) -> bool:
    client = TestClient(module.app)
    before = module.evaluator_snapshot()["stock"]
    zero = client.post("/orders", headers=headers(key="zero"), json={"quantity": 0})
    negative = client.post("/orders", headers=headers(key="negative"), json={"quantity": -2})
    after = module.evaluator_snapshot()["stock"]
    return zero.status_code == 422 and negative.status_code == 422 and before == after


def check_m07(module) -> bool:
    client = TestClient(module.app)
    before = module.evaluator_snapshot()
    response = client.post(
        "/orders",
        headers=headers(key="decline"),
        json={"quantity": 1, "payment_token": "decline"},
    )
    after = module.evaluator_snapshot()
    return (
        response.status_code == 402
        and before["stock"] == after["stock"]
        and not after["orders"]
        and not after["charges"]
    )


def check_m08(module) -> bool:
    client = TestClient(module.app)
    payload = {"quantity": 1, "payment_token": "timeout-once"}
    first = client.post("/orders", headers=headers(key="retry-key"), json=payload)
    second = client.post("/orders", headers=headers(key="retry-key"), json=payload)
    snapshot = module.evaluator_snapshot()
    return first.status_code == 504 and second.status_code == 201 and len(snapshot["charges"]) == 1


def check_m09(module) -> bool:
    client = TestClient(module.app)
    order = create_paid_order(client)
    first = client.post(f"/orders/{order['id']}/cancel", headers=headers())
    stock_after_first = module.evaluator_snapshot()["stock"]
    second = client.post(f"/orders/{order['id']}/cancel", headers=headers())
    stock_after_second = module.evaluator_snapshot()["stock"]
    return first.status_code == 200 and second.status_code == 200 and stock_after_first == stock_after_second == 5


def check_m10(module) -> bool:
    client = TestClient(module.app)
    response = client.post(
        "/orders",
        headers=headers(key="price"),
        json={"quantity": 2, "quoted_total": 1},
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


@pytest.mark.parametrize("case_id", CASES)
def test_clean_control_satisfies_every_oracle(case_id: str) -> None:
    assert CHECKS[case_id](load_case("C00")), case_id


@pytest.mark.parametrize("case_id", CASES)
def test_each_mutant_violates_its_target_oracle(case_id: str) -> None:
    assert not CHECKS[case_id](load_case(case_id)), case_id

