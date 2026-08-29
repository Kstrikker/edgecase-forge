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
