import json
from pathlib import Path

from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.llm.mock import MockProvider


def test_mock_baseline_creates_reproducible_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("# fixture", encoding="utf-8")
    output = tmp_path / "results"

    run_dir = BaselineScanner(MockProvider()).scan(
        repo=repo,
        output_root=output,
        case_id="C00",
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    metadata = json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))
    assert report["case_id"] == "C00"
    assert report["tests_executed"] == 0
    assert metadata["agent_version"] == "baseline-v0"
    assert (run_dir / "trajectory.jsonl").exists()
    assert (run_dir / "execution.log").exists()

