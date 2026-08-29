import json
from pathlib import Path

from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.llm.mock import MockProvider
from edgecase_forge.llm.base import LLMResult, Usage
from edgecase_forge.llm.schemas import BaselineAnalysis


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
    assert metadata["agent_version"] == "baseline-v1.0"
    assert (run_dir / "trajectory.jsonl").exists()
    assert (run_dir / "execution.log").exists()


def test_scanner_normalizes_model_test_filename(tmp_path: Path) -> None:
    class FindingProvider:
        name = "fake"
        model = "fake-model"

        def generate_json(self, messages, response_model):
            analysis = BaselineAnalysis.model_validate(
                {
                    "summary": "finding",
                    "findings": [
                        {
                            "title": "Example",
                            "severity": "high",
                            "endpoint": "GET /",
                            "claim": "Example claim",
                            "evidence": ["source"],
                            "test_file": "invented_name.py",
                            "test_name": "test_example",
                            "reproduced": False,
                        }
                    ],
                    "generated_test_code": "def test_example():\n    assert True\n",
                }
            )
            return analysis, LLMResult("{}", "fake", "fake-model", 0.0, Usage())

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("# fixture", encoding="utf-8")
    run_dir = BaselineScanner(FindingProvider()).scan(
        repo=repo,
        output_root=tmp_path / "results",
    )
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["findings"][0]["test_file"] == "generated_tests/test_generated_baseline.py"
