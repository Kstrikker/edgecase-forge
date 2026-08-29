from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.flashcart import build_all, export_agent_repo
from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.baseline.executor import run_generated_pytest
from edgecase_forge.llm.base import LLMProvider

CASE_IDS = ["C00", *(f"M{index:02d}" for index in range(1, 11))]


def run_flashcart_suite(
    *,
    provider: LLMProvider,
    output_root: Path,
) -> Path:
    """Run the frozen agent on neutral cases and perform differential execution."""
    hashes = build_all()
    suite_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root / suite_id
    suite_dir.mkdir(parents=True, exist_ok=False)
    scanner = BaselineScanner(provider)
    evaluations: list[dict] = []

    for case_id in CASE_IDS:
        with tempfile.TemporaryDirectory(prefix="edgecase-case-") as temporary:
            temporary_root = Path(temporary)
            agent_repo = export_agent_repo(case_id, temporary_root / "case-under-test")
            run_dir = scanner.scan(
                repo=agent_repo,
                output_root=suite_dir / "agent-runs" / case_id,
                case_id=case_id,
                execute=False,
            )
            generated_test = run_dir / "generated_tests" / "test_generated_baseline.py"
            generated = generated_test.exists()
            clean_result = None
            mutant_result = None

            if generated:
                clean_repo = export_agent_repo("C00", temporary_root / "clean-control")
                clean_result = run_generated_pytest(repo=clean_repo, test_file=generated_test)
                if case_id != "C00":
                    mutant_repo = export_agent_repo(case_id, temporary_root / "mutant-control")
                    mutant_result = run_generated_pytest(repo=mutant_repo, test_file=generated_test)

            passes_clean = bool(clean_result and clean_result.exit_code == 0)
            fails_mutant = bool(mutant_result and mutant_result.exit_code not in {None, 0})
            candidate_kill = case_id != "C00" and generated and passes_clean and fails_mutant
            clean_false_positive = case_id == "C00" and generated and not passes_clean
            evaluations.append(
                {
                    "case_id": case_id,
                    "source_sha256": hashes[case_id],
                    "run_directory": str(run_dir),
                    "test_generated": generated,
                    "passes_clean": passes_clean,
                    "fails_mutant": fails_mutant,
                    "candidate_kill": candidate_kill,
                    "confirmed_kill": False,
                    "requires_invariant_adjudication": candidate_kill,
                    "clean_false_positive": clean_false_positive,
                }
            )

    mutants = [item for item in evaluations if item["case_id"] != "C00"]
    candidate_kills = sum(int(item["candidate_kill"]) for item in mutants)
    summary = {
        "suite_id": suite_id,
        "benchmark_version": "flashcart-v1",
        "provider": provider.name,
        "model": provider.model,
        "cases": evaluations,
        "candidate_kills": candidate_kills,
        "candidate_mutation_score": candidate_kills / len(mutants),
        "confirmed_kills": 0,
        "confirmed_mutation_score": 0.0,
        "clean_false_positives": sum(
            int(item["clean_false_positive"]) for item in evaluations
        ),
        "note": "Candidate kills require independent invariant adjudication before confirmation.",
    }
    (suite_dir / "suite-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return suite_dir

