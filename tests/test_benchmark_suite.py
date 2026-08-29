import json
from pathlib import Path

from edgecase_forge.benchmark import run_flashcart_suite
from edgecase_forge.llm.mock import MockProvider


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
