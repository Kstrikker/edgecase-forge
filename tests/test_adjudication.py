import hashlib
import json
import shutil
from pathlib import Path

import pytest

from edgecase_forge.benchmark import adjudicate_suite, run_flashcart_suite
from edgecase_forge.llm.base import LLMResult, Usage
from edgecase_forge.llm.schemas import BaselineAnalysis


TEST_CODE = """\
from fastapi.testclient import TestClient
from main import app, reset_state

def test_claim():
    reset_state()
    client = TestClient(app)
    created = client.post(
        "/orders",
        headers={"Authorization": "Bearer buyer-a", "Idempotency-Key": "owner-check"},
        json={"product_id": 1, "quantity": 1},
    )
    assert created.status_code == 201
    response = client.get(
        f"/orders/{created.json()['id']}",
        headers={"Authorization": "Bearer buyer-b"},
    )
    assert response.status_code == 403
"""


class AuthorizationProvider:
    name = "fake"
    model = "fake-model"

    def generate_json(self, messages, response_model):
        analysis = BaselineAnalysis.model_validate(
            {
                "summary": "Cross-buyer authorization test",
                "findings": [
                    {
                        "title": "Cross-buyer order read",
                        "severity": "high",
                        "endpoint": "GET /orders/{order_id}",
                        "claim": "A buyer can read another buyer's order.",
                        "evidence": ["Missing owner comparison"],
                        "test_file": "test_generated.py",
                        "test_name": "test_claim",
                        "reproduced": False,
                    }
                ],
                "generated_test_code": TEST_CODE,
            }
        )
        return analysis, LLMResult("{}", self.name, self.model, 0.0, Usage())


@pytest.fixture(scope="module")
def candidate_suite(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("adjudication-source")
    return run_flashcart_suite(
        provider=AuthorizationProvider(),
        output_root=root,
        case_ids=["M03"],
        execution_backend="local",
    )


def _copy_suite(candidate_suite: Path, tmp_path: Path) -> Path:
    destination = tmp_path / candidate_suite.name
    shutil.copytree(candidate_suite, destination)
    return destination


def _decision_payload(suite: Path, decision: str = "confirmed") -> dict:
    config = json.loads((suite / "suite-config.json").read_text(encoding="utf-8"))
    case = json.loads((suite / "suite-summary.json").read_text(encoding="utf-8"))[
        "cases"
    ][0]
    return {
        "schema_version": "adjudication-decisions-v1",
        "suite_id": config["suite_id"],
        "suite_fingerprint_sha256": config["frozen"]["suite_fingerprint_sha256"],
        "reviewer": "test-reviewer",
        "review_policy": "Direct invariant evidence only.",
        "decisions": [
            {
                "repetition": 1,
                "case_id": "M03",
                "test_sha256": case["test_sha256"],
                "differential_sha256": case["differential_sha256"],
                "decision": decision,
                "reason": "The test directly checks the frozen authorization invariant.",
            }
        ],
    }


def _write_decisions(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_adjudication_confirms_score_without_mutating_raw_evidence(
    candidate_suite: Path, tmp_path: Path
) -> None:
    suite = _copy_suite(candidate_suite, tmp_path)
    raw_summary = suite / "suite-summary.json"
    before = hashlib.sha256(raw_summary.read_bytes()).hexdigest()
    decisions = _write_decisions(tmp_path, _decision_payload(suite))

    adjudication_path, summary_path = adjudicate_suite(
        suite_dir=suite, decisions_path=decisions
    )
    adjudicated = json.loads(summary_path.read_text(encoding="utf-8"))

    assert adjudication_path.name == "adjudication.json"
    assert adjudicated["confirmed_kills"] == 1
    assert adjudicated["rejected_candidate_kills"] == 0
    assert adjudicated["confirmed_mutation_score"] == 1.0
    assert "subset_selection" in adjudicated["official_score_blockers"]
    assert "pending_adjudication" not in adjudicated["official_score_blockers"]
    assert hashlib.sha256(raw_summary.read_bytes()).hexdigest() == before

    assert adjudicate_suite(suite_dir=suite, decisions_path=decisions) == (
        adjudication_path,
        summary_path,
    )


def test_rejected_candidate_counts_as_a_confirmed_score_miss(
    candidate_suite: Path, tmp_path: Path
) -> None:
    suite = _copy_suite(candidate_suite, tmp_path)
    decisions = _write_decisions(tmp_path, _decision_payload(suite, "rejected"))
    _, summary_path = adjudicate_suite(suite_dir=suite, decisions_path=decisions)
    adjudicated = json.loads(summary_path.read_text(encoding="utf-8"))

    assert adjudicated["confirmed_kills"] == 0
    assert adjudicated["rejected_candidate_kills"] == 1
    assert adjudicated["confirmed_mutation_score"] == 0.0


def test_adjudication_rejects_incomplete_or_mismatched_decisions(
    candidate_suite: Path, tmp_path: Path
) -> None:
    suite = _copy_suite(candidate_suite, tmp_path)
    payload = _decision_payload(suite)
    payload["decisions"] = []
    decisions = _write_decisions(tmp_path, payload)
    with pytest.raises(ValueError, match="exactly match candidate kills"):
        adjudicate_suite(suite_dir=suite, decisions_path=decisions)

    payload = _decision_payload(suite)
    payload["decisions"][0]["test_sha256"] = "0" * 64
    decisions = _write_decisions(tmp_path, payload)
    with pytest.raises(ValueError, match="test hash"):
        adjudicate_suite(suite_dir=suite, decisions_path=decisions)


def test_adjudication_detects_modified_raw_evidence(
    candidate_suite: Path, tmp_path: Path
) -> None:
    suite = _copy_suite(candidate_suite, tmp_path)
    case = json.loads((suite / "suite-summary.json").read_text(encoding="utf-8"))[
        "cases"
    ][0]
    stdout = suite / case["run_directory"] / "differential" / "clean" / "stdout.log"
    stdout.write_text("tampered", encoding="utf-8")
    decisions = _write_decisions(tmp_path, _decision_payload(suite))

    with pytest.raises(ValueError, match="modified"):
        adjudicate_suite(suite_dir=suite, decisions_path=decisions)
