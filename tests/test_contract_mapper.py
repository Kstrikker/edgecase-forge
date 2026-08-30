import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from edgecase_forge.benchmark import run_flashcart_suite
from edgecase_forge.contract import ContractScanner, build_repository_map
from edgecase_forge.contract.schema import ContractAnalysis
from edgecase_forge.llm.base import LLMResult, Usage
from edgecase_forge.llm.mock import MockProvider
from edgecase_forge.llm.response_schema import flat_strict_schema


class ContractProvider:
    name = "contract-test"
    model = "static"

    def __init__(self) -> None:
        self.messages = None

    def generate_json(self, messages, response_model):
        self.messages = messages
        payload = {
            "summary": "Payment retry invariant mapped.",
            "invariants": [
                {
                    "invariant_id": "INV-01",
                    "endpoint": "POST /orders",
                    "category": "side_effect",
                    "invariant": "One logical checkout creates at most one charge.",
                    "evidence": ["Payment charge uses an operation key."],
                    "oracle": "Inspect the payment charge ledger after timeout and retry.",
                }
            ],
            "findings": [
                {
                    "invariant_id": "INV-01",
                    "title": "Retry duplicates charge",
                    "severity": "high",
                    "endpoint": "POST /orders",
                    "claim": "A retry can create two provider charges.",
                    "evidence": ["Retry operation identity changes."],
                    "test_file": "test_generated.py",
                    "test_name": "test_charge_once",
                    "reproduced": False,
                }
            ],
            "generated_test_code": "def test_charge_once():\n    assert True\n",
        }
        analysis = response_model.model_validate(payload)
        return analysis, LLMResult("{}", self.name, self.model, 0.0, Usage())


def test_mapper_surfaces_routes_state_effects_and_retry_risks() -> None:
    repo = Path("benchmarks/flashcart/generated/C00")
    repository_map = build_repository_map(repo)
    orders = next(
        route
        for route in repository_map.routes
        if route.method == "POST" and route.path == "/orders"
    )

    assert "STATE.stock" in orders.state_writes
    assert any(".charge(" in effect for effect in orders.external_effects)
    assert "external_side_effect" in orders.risk_signals
    assert "partial_failure_or_retry_after_effect" in orders.risk_signals
    assert "idempotency_identity" in orders.risk_signals
    assert "ROUTE POST /orders" in repository_map.render()
    assert "client_input_in_authoritative_total" not in orders.risk_signals
    assert repository_map.priority_targets == ()

    retry_mutant = build_repository_map(Path("benchmarks/flashcart/generated/M08"))
    assert retry_mutant.priority_targets[0].signal == "unstable_external_effect_identity"
    assert "ledger count" in retry_mutant.priority_targets[0].required_oracle

    mutant = build_repository_map(Path("benchmarks/flashcart/generated/M10"))
    mutant_orders = next(
        route
        for route in mutant.routes
        if route.method == "POST" and route.path == "/orders"
    )
    assert "client_input_in_authoritative_total" in mutant_orders.risk_signals
    assert mutant.priority_targets[0].signal == "client_input_in_authoritative_total"
    assert "provider amount" in mutant.priority_targets[0].required_oracle


def test_mapper_is_deterministic_and_ignores_private_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health(): return {'ok': True}\n",
        encoding="utf-8",
    )
    hidden = repo / "oracle"
    hidden.mkdir()
    (hidden / "answer.py").write_text("SECRET = 'answer'\n", encoding="utf-8")

    first = build_repository_map(repo)
    second = build_repository_map(repo)
    assert first == second
    assert first.analyzed_files == ("main.py",)
    assert [route.path for route in first.routes] == ["/health"]


def test_contract_schema_rejects_unlinked_findings() -> None:
    with pytest.raises(ValidationError, match="unknown invariant_id"):
        ContractAnalysis.model_validate(
            {
                "summary": "bad",
                "invariants": [],
                "findings": [
                    {
                        "invariant_id": "INV-404",
                        "title": "bad",
                        "severity": "high",
                        "endpoint": "GET /",
                        "claim": "bad",
                        "evidence": ["source"],
                        "test_file": "test.py",
                        "test_name": "test_bad",
                        "reproduced": False,
                    }
                ],
                "generated_test_code": "def test_bad():\n    assert True\n",
            }
        )


def test_contract_schema_stays_inside_flat_provider_subset() -> None:
    schema = flat_strict_schema(ContractAnalysis)
    encoded = json.dumps(schema)

    assert "$ref" not in encoded
    assert "$defs" not in encoded
    assert "anyOf" not in encoded
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_contract_scanner_writes_map_and_explicit_invariants(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.post('/orders')\n"
        "def create_order(): return {}\n",
        encoding="utf-8",
    )
    provider = ContractProvider()
    run_dir = ContractScanner(provider).scan(
        repo=repo, output_root=tmp_path / "results"
    )
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    metadata = json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))
    repository_map = json.loads(
        (run_dir / "repository-map.json").read_text(encoding="utf-8")
    )

    assert report["invariants"][0]["invariant_id"] == "INV-01"
    assert report["repository_map"] == "repository-map.json"
    assert metadata["agent_version"] == "contract-v1.1"
    assert repository_map["routes"][0]["path"] == "/orders"
    assert "DETERMINISTIC API CONTRACT MAP" in provider.messages[1].content


def test_contract_agent_mock_benchmark_is_frozen_separately(tmp_path: Path) -> None:
    suite = run_flashcart_suite(
        provider=MockProvider(),
        output_root=tmp_path,
        case_ids=["C00"],
        agent="contract",
    )
    config = json.loads((suite / "suite-config.json").read_text(encoding="utf-8"))
    summary = json.loads((suite / "suite-summary.json").read_text(encoding="utf-8"))

    assert config["frozen"]["agent"]["agent"] == "contract_mapper"
    assert config["frozen"]["agent"]["agent_version"] == "contract-v1.1"
    assert summary["agent"] == config["frozen"]["agent"]
