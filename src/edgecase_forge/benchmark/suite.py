from __future__ import annotations

import json
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.flashcart import build_all, export_agent_repo
from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.baseline.executor import run_generated_pytest
from edgecase_forge.llm.base import LLMProvider
from edgecase_forge.llm.errors import ResponseParseError, ResponseValidationError

CASE_IDS = ["C00", *(f"M{index:02d}" for index in range(1, 11))]


def run_flashcart_suite(
    *,
    provider: LLMProvider,
    output_root: Path,
    repetitions: int = 1,
    request_delay_seconds: float = 0.0,
    resume_dir: Path | None = None,
) -> Path:
    """Run the frozen agent on neutral cases and perform differential execution."""
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    hashes = build_all()
    if resume_dir is None:
        suite_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suite_dir = output_root / suite_id
        suite_dir.mkdir(parents=True, exist_ok=False)
        _write_json(
            suite_dir / "suite-config.json",
            {
                "suite_id": suite_id,
                "benchmark_version": "flashcart-v1.1.0",
                "provider": provider.name,
                "model": provider.model,
                "repetitions": repetitions,
                "request_delay_seconds": request_delay_seconds,
            },
        )
    else:
        suite_dir = resume_dir.resolve()
        config = json.loads((suite_dir / "suite-config.json").read_text(encoding="utf-8"))
        suite_id = config["suite_id"]
        expected = (provider.name, provider.model, repetitions)
        observed = (config["provider"], config["model"], config["repetitions"])
        if expected != observed:
            raise ValueError(
                "Resume configuration does not match provider, model, and repetitions"
            )
    scanner = BaselineScanner(provider)
    progress_path = suite_dir / "case-evaluations.jsonl"
    evaluations = _read_progress(progress_path)
    completed = {(item["repetition"], item["case_id"]) for item in evaluations}

    for repetition in range(1, repetitions + 1):
        for case_id in CASE_IDS:
            if (repetition, case_id) in completed:
                continue
            with tempfile.TemporaryDirectory(prefix="edgecase-case-") as temporary:
                temporary_root = Path(temporary)
                agent_repo = export_agent_repo(case_id, temporary_root / "case-under-test")
                run_output = suite_dir / "agent-runs" / f"run-{repetition:02d}" / case_id
                try:
                    run_dir = scanner.scan(
                        repo=agent_repo,
                        output_root=run_output,
                        case_id=case_id,
                        execute=False,
                    )
                except (ResponseParseError, ResponseValidationError) as exc:
                    evaluation = {
                        "repetition": repetition,
                        "case_id": case_id,
                        "source_sha256": hashes[case_id],
                        "run_directory": None,
                        "status": "model_output_error",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2000],
                        "test_generated": False,
                        "passes_clean": False,
                        "fails_mutant": False,
                        "candidate_kill": False,
                        "confirmed_kill": False,
                        "requires_invariant_adjudication": False,
                        "clean_false_positive": False,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "runtime_seconds": 0.0,
                    }
                    evaluations.append(evaluation)
                    with progress_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(evaluation) + "\n")
                    if request_delay_seconds:
                        time.sleep(request_delay_seconds)
                    continue
                generated_test = run_dir / "generated_tests" / "test_generated_baseline.py"
                generated = generated_test.exists()
                clean_result = None
                mutant_result = None

                if generated:
                    clean_repo = export_agent_repo("C00", temporary_root / "clean-control")
                    clean_result = run_generated_pytest(repo=clean_repo, test_file=generated_test)
                    if case_id != "C00":
                        mutant_repo = export_agent_repo(
                            case_id, temporary_root / "mutant-control"
                        )
                        mutant_result = run_generated_pytest(
                            repo=mutant_repo, test_file=generated_test
                        )

                passes_clean = bool(clean_result and clean_result.exit_code == 0)
                fails_mutant = bool(
                    mutant_result and mutant_result.exit_code not in {None, 0}
                )
                candidate_kill = (
                    case_id != "C00" and generated and passes_clean and fails_mutant
                )
                clean_false_positive = case_id == "C00" and generated and not passes_clean
                report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
                evaluation = {
                    "repetition": repetition,
                    "case_id": case_id,
                    "source_sha256": hashes[case_id],
                    "run_directory": str(run_dir),
                    "status": "completed",
                    "test_generated": generated,
                    "passes_clean": passes_clean,
                    "fails_mutant": fails_mutant,
                    "candidate_kill": candidate_kill,
                    "confirmed_kill": False,
                    "requires_invariant_adjudication": candidate_kill,
                    "clean_false_positive": clean_false_positive,
                    "input_tokens": report["input_tokens"],
                    "output_tokens": report["output_tokens"],
                    "runtime_seconds": report["runtime_seconds"],
                }
                evaluations.append(evaluation)
                with progress_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(evaluation) + "\n")
            if request_delay_seconds:
                time.sleep(request_delay_seconds)

    mutants = [item for item in evaluations if item["case_id"] != "C00"]
    candidate_kills = sum(int(item["candidate_kill"]) for item in mutants)
    repetition_scores = []
    for repetition in range(1, repetitions + 1):
        repetition_mutants = [
            item for item in mutants if item["repetition"] == repetition
        ]
        kills = sum(int(item["candidate_kill"]) for item in repetition_mutants)
        score = kills / len(repetition_mutants) if repetition_mutants else 0.0
        repetition_scores.append(
            {"repetition": repetition, "candidate_kills": kills, "score": score}
        )
    score_values = [item["score"] for item in repetition_scores]
    summary = {
        "suite_id": suite_id,
        "benchmark_version": "flashcart-v1.1.0",
        "provider": provider.name,
        "model": provider.model,
        "repetitions": repetitions,
        "cases": evaluations,
        "candidate_kills": candidate_kills,
        "candidate_mutation_score": statistics.median(score_values),
        "candidate_mutation_score_range": [min(score_values), max(score_values)],
        "repetition_scores": repetition_scores,
        "confirmed_kills": 0,
        "confirmed_mutation_score": 0.0,
        "clean_false_positives": sum(
            int(item["clean_false_positive"]) for item in evaluations
        ),
        "model_output_errors": sum(
            int(item["status"] == "model_output_error") for item in evaluations
        ),
        "input_tokens": sum(item["input_tokens"] for item in evaluations),
        "output_tokens": sum(item["output_tokens"] for item in evaluations),
        "runtime_seconds": round(sum(item["runtime_seconds"] for item in evaluations), 4),
        "note": "Candidate kills require independent invariant adjudication before confirmation.",
    }
    _write_json(suite_dir / "suite-summary.json", summary)
    return suite_dir


def _read_progress(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
