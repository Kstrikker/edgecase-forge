import json
from pathlib import Path

from edgecase_forge.benchmark import run_flashcart_suite
from edgecase_forge.llm.mock import MockProvider
from edgecase_forge.llm.errors import ResponseValidationError


def test_mock_suite_runs_all_cases_without_leaking_answers(tmp_path: Path) -> None:
    suite_dir = run_flashcart_suite(provider=MockProvider(), output_root=tmp_path)
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert len(summary["cases"]) == 11
    assert summary["candidate_kills"] == 0
    assert summary["clean_false_positives"] == 0
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
            raise ResponseValidationError("evidence must be a list")

    suite_dir = run_flashcart_suite(provider=BrokenProvider(), output_root=tmp_path)
    summary = json.loads((suite_dir / "suite-summary.json").read_text(encoding="utf-8"))
    assert len(summary["cases"]) == 11
    assert summary["model_output_errors"] == 11
    assert summary["candidate_kills"] == 0
