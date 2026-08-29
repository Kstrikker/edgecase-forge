from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]


def _load(name: str):
    path = ROOT / "benchmarks" / "fixtures" / name / "main.py"
    spec = spec_from_file_location(f"fixture_{name}", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _concurrent_successes(module) -> tuple[int, int]:
    module.reset_fixture()
    client = TestClient(module.app)
    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(
            pool.map(lambda _: client.post("/orders/1", json={"quantity": 1}), range(20))
        )
    successes = sum(response.status_code == 201 for response in responses)
    final_stock = client.get("/products/1").json()["stock"]
    return successes, final_stock


def test_clean_fixture_allows_exactly_one_purchase() -> None:
    successes, final_stock = _concurrent_successes(_load("stock_race_clean"))
    assert successes == 1
    assert final_stock == 0


def test_mutant_reproduces_overselling_claim() -> None:
    successes, final_stock = _concurrent_successes(_load("stock_race_mutant"))
    assert successes > 1
    assert final_stock == 0

