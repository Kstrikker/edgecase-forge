import json
from pathlib import Path

from benchmarks.flashcart import build_all, export_agent_repo

ROOT = Path(__file__).parents[1]


def test_agent_export_contains_one_neutral_repo_without_oracle(tmp_path: Path) -> None:
    hashes = build_all()
    expected = json.loads(
        (ROOT / "benchmarks" / "flashcart" / "expected_hashes.json").read_text(
            encoding="utf-8"
        )
    )
    assert hashes == expected
    assert set(hashes) == {"C00", *(f"M{index:02d}" for index in range(1, 11))}
    destination = export_agent_repo("M01", tmp_path / "case-under-test")
    source = (destination / "main.py").read_text(encoding="utf-8")
    assert "evaluator_snapshot" not in source
    assert "M01" not in source
    assert "mutation" not in (destination / "README.md").read_text(encoding="utf-8").lower()
