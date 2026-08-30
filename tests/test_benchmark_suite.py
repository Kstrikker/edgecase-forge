import json
from pathlib import Path

import pytest

from edgecase_forge.benchmark import run_flashcart_suite
from edgecase_forge.benchmark import freeze as freeze_module
from edgecase_forge.llm.base import AttemptAccounting, LLMResult, Usage
from edgecase_forge.llm.mock import MockProvider
from edgecase_forge.llm.errors import ResponseValidationError
from edgecase_forge.llm.schemas import BaselineAnalysis


class StaticTestProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, test_code: str, *, findings: bool = True) -> None:
        self.test_code = test_code
        self.findings = findings
        self.calls = 0

    def generate_json(self, messages, response_model):
        self.calls += 1
        finding_items = []
        if self.findings:
            finding_items.append(
                {
                    "title": "Claim",
                    "severity": "high",
                    "endpoint": "POST /orders",
                    "claim": "Claimed behavior",
                    "evidence": ["source"],
                    "test_file": "test_generated.py",
                    "test_name": "test_claim",
                    "reproduced": False,
                }
            )
        analysis = BaselineAnalysis.model_validate(
            {
                "summary": "Static test response",
                "findings": finding_items,
                "generated_test_code": self.test_code,
            }
        )
        return analysis, LLMResult(
            "{}", self.name, self.model, 0.0, Usage(), f"request-{self.calls}"
        )


def test_mock_suite_runs_all_cases_without_leaking_answers(tmp_path: Path) -> None:
    suite_dir = run_flashcart_suite(provider=MockProvider(), output_root=tmp_path)
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert len(summary["cases"]) == 11
    assert summary["candidate_kills"] == 0
    assert summary["clean_control_claims_reported"] == 0
    assert summary["provider"] == "mock"


def test_suite_repetitions_and_resume_do_not_duplicate_cases(tmp_path: Path) -> None:
    suite_dir = run_flashcart_suite(
        provider=MockProvider(),
        output_root=tmp_path,
        repetitions=2,
    )
    first = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert len(first["cases"]) == 22
    assert len(first["repetition_scores"]) == 2

    resumed = run_flashcart_suite(
        provider=MockProvider(),
        output_root=tmp_path,
        repetitions=2,
        resume_dir=suite_dir,
    )
    second = json.loads((resumed / "suite-summary.json").read_text(encoding="utf-8"))
    assert len(second["cases"]) == 22


def test_suite_records_model_output_errors_and_continues(tmp_path: Path) -> None:
    class BrokenProvider:
        name = "broken"
        model = "broken-model"

        def generate_json(self, messages, response_model):
            error = ResponseValidationError(
                "evidence must be a list",
                AttemptAccounting(
                    usage=Usage(input_tokens=20, output_tokens=40),
                    latency_seconds=1.5,
                    semantic_attempts=2,
                    transport_attempts=2,
                    repair_used=True,
                    request_ids=("first", "repair"),
                    finish_reasons=("length", "stop"),
                ),
            )
            error.preserve_model_responses("first-invalid", "repair-invalid")
            raise error

    suite_dir = run_flashcart_suite(provider=BrokenProvider(), output_root=tmp_path)
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert len(summary["cases"]) == 11
    assert summary["model_output_errors"] == 11
    assert summary["candidate_kills"] == 0
    assert summary["input_tokens"] == 220
    assert summary["output_tokens"] == 440
    assert summary["semantic_attempts"] == 22
    assert summary["transport_attempts"] == 22
    assert summary["repair_used_evaluations"] == 11
    assert summary["cases"][0]["model_response_excerpts"] == [
        "first-invalid",
        "repair-invalid",
    ]
    assert len(summary["cases"][0]["model_response_sha256"]) == 2
    assert summary["cases"][0]["finish_reasons"] == ["length", "stop"]
    assert summary["candidate_mutation_score"] == 0.0
    assert "model_output_error" not in summary["official_score_blockers"]
    assert summary["evaluator_infrastructure_errors"] == 0


def test_suite_persists_node_level_differential_evidence(tmp_path: Path) -> None:
    suite_dir = run_flashcart_suite(
        provider=StaticTestProvider("def test_claim():\n    assert True\n"),
        output_root=tmp_path,
        case_ids=["M01"],
    )
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    case = summary["cases"][0]
    differential_path = suite_dir / case["differential_evidence"]
    differential = json.loads(differential_path.read_text(encoding="utf-8"))
    evidence_dir = differential_path.parent

    assert summary["status"] == "complete"
    assert summary["official_score_eligible"] is False
    assert differential["case_candidate_kill"] is False
    assert differential["integrity_errors"] == []
    assert (evidence_dir / "clean" / "execution.json").exists()
    assert (evidence_dir / "clean" / "junit.xml").exists()
    assert (evidence_dir / "clean" / "stdout.log").exists()
    assert (evidence_dir / "mutant" / "execution.json").exists()
    assert (evidence_dir / "mutant" / "junit.xml").exists()


def test_invalid_generated_test_is_a_scored_miss_not_an_infrastructure_blocker(
    tmp_path: Path,
) -> None:
    suite_dir = run_flashcart_suite(
        provider=StaticTestProvider("this is invalid python !!!\n"),
        output_root=tmp_path,
        case_ids=["M01"],
    )
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    case = summary["cases"][0]

    assert case["candidate_kill"] is False
    assert case["fails_mutant"] is False
    assert case["invalid_generated_test_count"] == 2
    assert case["evaluator_infrastructure_error_count"] == 0
    assert summary["invalid_generated_tests"] == 2
    assert "evaluator_infrastructure_error" not in summary["official_score_blockers"]


def test_resume_allows_operational_delay_change_and_records_it(tmp_path: Path) -> None:
    suite_dir = run_flashcart_suite(
        provider=MockProvider(),
        output_root=tmp_path,
        case_ids=["C00"],
    )
    run_flashcart_suite(
        provider=MockProvider(),
        output_root=tmp_path,
        case_ids=["C00"],
        request_delay_seconds=1.0,
        resume_dir=suite_dir,
    )
    events = [
        json.loads(line)
        for line in (suite_dir / "suite-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["event"] for item in events] == ["suite_started", "suite_resumed"]
    assert [item["request_delay_seconds"] for item in events] == [0.0, 1.0]


def test_clean_control_claim_is_counted_even_when_test_passes(tmp_path: Path) -> None:
    suite_dir = run_flashcart_suite(
        provider=StaticTestProvider("def test_claim():\n    assert True\n"),
        output_root=tmp_path,
        case_ids=["C00"],
    )
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert summary["clean_control_claims_reported"] == 1
    assert summary["clean_control_evaluations_with_claims"] == 1
    assert summary["evaluations_with_clean_assertion_failures"] == 0


def test_preflight_hash_mismatch_stops_before_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_hashes = tmp_path / "bad-hashes.json"
    bad_hashes.write_text(json.dumps({"C00": "0" * 64}), encoding="utf-8")
    monkeypatch.setattr(freeze_module, "EXPECTED_HASHES_PATH", bad_hashes)
    provider = StaticTestProvider("")
    with pytest.raises(RuntimeError, match="expected hashes"):
        run_flashcart_suite(
            provider=provider,
            output_root=tmp_path / "results",
            case_ids=["C00"],
        )
    assert provider.calls == 0


def test_resume_rejects_tampered_evidence_before_provider_call(tmp_path: Path) -> None:
    provider = StaticTestProvider("def test_claim():\n    assert True\n")
    suite_dir = run_flashcart_suite(
        provider=provider,
        output_root=tmp_path,
        case_ids=["M01"],
    )
    case = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))[
        "cases"
    ][0]
    stdout_path = (
        suite_dir
        / case["run_directory"]
        / "differential"
        / "clean"
        / "stdout.log"
    )
    stdout_path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="modified"):
        run_flashcart_suite(
            provider=provider,
            output_root=tmp_path,
            case_ids=["M01"],
            resume_dir=suite_dir,
        )
    assert provider.calls == 1


def test_resume_rejects_truncated_or_duplicate_progress(tmp_path: Path) -> None:
    first = run_flashcart_suite(
        provider=MockProvider(), output_root=tmp_path / "truncated", case_ids=["C00"]
    )
    with (first / "case-evaluations.jsonl").open("ab") as handle:
        handle.write(b'{"broken":')
    with pytest.raises(ValueError, match="truncated"):
        run_flashcart_suite(
            provider=MockProvider(),
            output_root=tmp_path,
            case_ids=["C00"],
            resume_dir=first,
        )

    second = run_flashcart_suite(
        provider=MockProvider(), output_root=tmp_path / "duplicate", case_ids=["C00"]
    )
    progress = second / "case-evaluations.jsonl"
    line = progress.read_text(encoding="utf-8")
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(line)
    with pytest.raises(ValueError, match="duplicates"):
        run_flashcart_suite(
            provider=MockProvider(),
            output_root=tmp_path,
            case_ids=["C00"],
            resume_dir=second,
        )


def test_partial_suite_does_not_publish_mutation_score(tmp_path: Path) -> None:
    class InterruptingProvider(MockProvider):
        def __init__(self) -> None:
            self.calls = 0

        def generate_json(self, messages, response_model):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic interruption")
            return super().generate_json(messages, response_model)

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        run_flashcart_suite(
            provider=InterruptingProvider(),
            output_root=tmp_path,
            case_ids=["C00", "M01"],
        )
    suite_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "partial"
    assert summary["candidate_mutation_score"] is None
    assert summary["repetition_scores"][0]["score"] is None


def test_clean_and_mutant_processes_observe_same_neutral_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "host-only"))
    (tmp_path / "private_oracle_sentinel.py").write_text(
        "ANSWER = 'leaked'\n", encoding="utf-8"
    )
    code = (
        "import json, os, sys\n"
        "from pathlib import Path\n\n"
        "def test_claim():\n"
        "    try:\n"
        "        import private_oracle_sentinel  # noqa: F401\n"
        "        imported = True\n"
        "    except ModuleNotFoundError:\n"
        "        imported = False\n"
        "    assert not imported\n"
        "    assert os.getenv('GEMINI_API_KEY') is None\n"
        "    assert os.getenv('AWS_SECRET_ACCESS_KEY') is None\n"
        "    assert os.getenv('DATABASE_URL') is None\n"
        "    observation = {\n"
        "        'cwd': str(Path.cwd()),\n"
        "        'file': str(Path(__file__).resolve()),\n"
        "        'argv': sys.argv,\n"
        "        'pythonpath': os.environ.get('PYTHONPATH'),\n"
        "        'temp': os.environ.get('TEMP'),\n"
        "        'environment_keys': sorted(os.environ),\n"
        "    }\n"
        "    raise AssertionError(json.dumps(observation, sort_keys=True))\n"
    )
    suite_dir = run_flashcart_suite(
        provider=StaticTestProvider(code),
        output_root=tmp_path / "results",
        case_ids=["M01"],
    )
    case = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))[
        "cases"
    ][0]
    evidence = suite_dir / case["run_directory"] / "differential"
    clean = json.loads((evidence / "clean" / "execution.json").read_text(encoding="utf-8"))
    mutant = json.loads((evidence / "mutant" / "execution.json").read_text(encoding="utf-8"))
    clean_message = clean["nodes"][0]["message"]
    mutant_message = mutant["nodes"][0]["message"]
    assert clean_message == mutant_message
    for leaked_label in ("C00", "M01", "clean-control", "mutant-control", "agent-runs"):
        assert leaked_label not in clean_message
