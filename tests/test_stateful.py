import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from edgecase_forge.benchmark import run_flashcart_suite
from edgecase_forge.contract import build_repository_map
from edgecase_forge.llm.base import Message
from edgecase_forge.llm.capabilities import STRICT_OPENAI_COMPATIBLE
from edgecase_forge.llm.mock import MockProvider
from edgecase_forge.llm.openai_compatible import OpenAICompatibleProvider
from edgecase_forge.stateful import StatefulScanner, build_attack_plan
from edgecase_forge.stateful.validation import stateful_analysis_model


BAD_TEST = """\
def test_retry_charge_count():
    response1 = client.post('/orders')
    assert response1.status_code == 504
    response2 = client.post('/orders')
    assert response2.status_code == 201
    assert len(STATE.payment.charges) == 1
"""

GOOD_TEST = """\
def test_retry_charge_count():
    response1 = client.post('/orders')
    assert response1.status_code == 504
    response2 = client.post('/orders')
    assert len(STATE.payment.charges) == 1
    assert response2.status_code == 201
"""


def _payload(code: str) -> dict:
    return {
        "summary": "Retry may duplicate an external charge.",
        "invariants": [
            {
                "invariant_id": "INV-01",
                "endpoint": "POST /orders",
                "category": "side_effect",
                "invariant": "One logical checkout creates one provider charge.",
                "evidence": ["The effect identity contains a volatile UUID."],
                "oracle": "Inspect the charge ledger after timeout and retry.",
            }
        ],
        "findings": [
            {
                "invariant_id": "INV-01",
                "title": "Duplicate retry charge",
                "severity": "critical",
                "endpoint": "POST /orders",
                "claim": "A retry can create a second provider charge.",
                "evidence": ["The effect key changes on every call."],
                "test_file": "test_generated.py",
                "test_name": "test_retry_charge_count",
                "reproduced": False,
            }
        ],
        "generated_test_code": code,
    }


@pytest.fixture(scope="module")
def retry_plan():
    repository_map = build_repository_map(Path("benchmarks/flashcart/generated/M08"))
    return build_attack_plan(repository_map)


def test_attack_plan_places_primary_ledger_oracle_before_http_outcome(retry_plan) -> None:
    assert retry_plan.target_signal == "unstable_external_effect_identity"
    assert [step.sequence for step in retry_plan.steps] == [1, 2, 3, 4, 5]
    assert "ledger count" in retry_plan.steps[3].action.lower()
    assert "http" in retry_plan.steps[4].action.lower()


def test_stateful_schema_rejects_masked_ledger_oracle(retry_plan) -> None:
    model = stateful_analysis_model(retry_plan)
    with pytest.raises(ValidationError, match="Primary oracle ordering violation"):
        model.model_validate(_payload(BAD_TEST))

    accepted = model.model_validate(_payload(GOOD_TEST))
    assert accepted.findings[0].test_name == "test_retry_charge_count"


def test_provider_repair_receives_exact_oracle_order_error(retry_plan) -> None:
    model = stateful_analysis_model(retry_plan)
    requests: list[httpx.Request] = []

    def response(payload: dict) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return response(_payload(BAD_TEST))
        repair = json.loads(request.content)["messages"][-1]["content"]
        assert "Primary oracle ordering violation" in repair
        return response(_payload(GOOD_TEST))

    provider = OpenAICompatibleProvider(
        name="gemini",
        model="test-model",
        api_key="test-key",
        base_url="https://example.test/v1",
        capabilities=STRICT_OPENAI_COMPATIBLE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    parsed, result = provider.generate_json([Message("user", "scan")], model)

    assert parsed.generated_test_code == GOOD_TEST
    assert len(requests) == 2
    assert result.semantic_attempts == 2
    assert result.repair_used is True


def test_stateful_scanner_writes_attack_plan(tmp_path: Path) -> None:
    run_dir = StatefulScanner(MockProvider()).scan(
        repo=Path("benchmarks/flashcart/generated/M08"),
        output_root=tmp_path,
    )
    metadata = json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    attack_plan = json.loads((run_dir / "attack-plan.json").read_text(encoding="utf-8"))

    assert metadata["agent_version"] == "stateful-v1.0"
    assert report["attack_target_signal"] == "unstable_external_effect_identity"
    assert attack_plan["steps"][3]["action"] == "Assert the provider effect ledger count"


def test_stateful_agent_has_separate_frozen_benchmark_identity(tmp_path: Path) -> None:
    suite = run_flashcart_suite(
        provider=MockProvider(),
        output_root=tmp_path,
        case_ids=["C00"],
        agent="stateful",
    )
    config = json.loads((suite / "suite-config.json").read_text(encoding="utf-8"))
    assert config["frozen"]["agent"]["agent"] == "stateful_attacker"
    assert config["frozen"]["agent"]["agent_version"] == "stateful-v1.0"
