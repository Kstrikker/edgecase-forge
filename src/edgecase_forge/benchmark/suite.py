from __future__ import annotations

import hashlib
import json
import shutil
import statistics
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.flashcart import export_agent_repo
from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.baseline.executor import ExecutionResult, run_generated_pytest
from edgecase_forge.baseline.restricted import ensure_runner_image, run_restricted_pytest
from edgecase_forge.llm.base import LLMProvider
from edgecase_forge.llm.errors import ResponseParseError, ResponseValidationError

from .artifacts import (
    append_jsonl,
    file_sha256,
    integrity_errors,
    invalidate_differential,
    read_progress,
    tree_sha256,
    write_execution_evidence,
    write_json_atomic,
)
from .differential import build_differential
from .freeze import (
    BENCHMARK_VERSION,
    CASE_IDS,
    expected_case,
    frozen_config,
    preflight_flashcart,
    validate_cases,
)


def run_flashcart_suite(
    *,
    provider: LLMProvider,
    output_root: Path,
    repetitions: int = 1,
    request_delay_seconds: float = 0.0,
    resume_dir: Path | None = None,
    case_ids: Sequence[str] | None = None,
    execution_backend: str = "local",
) -> Path:
    """Run the frozen baseline and preserve clean-versus-mutant node evidence."""
    selected_cases = validate_cases(case_ids)
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    if execution_backend not in {"local", "docker"}:
        raise ValueError("execution_backend must be 'local' or 'docker'")
    if execution_backend == "docker":
        ensure_runner_image()

    source_hashes, manifest, manifest_sha256 = preflight_flashcart()
    suite_frozen_config = frozen_config(
        provider=provider,
        repetitions=repetitions,
        selected_cases=selected_cases,
        source_hashes=source_hashes,
        manifest_sha256=manifest_sha256,
        execution_backend=execution_backend,
    )
    if resume_dir is None:
        suite_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suite_dir = output_root / suite_id
        suite_dir.mkdir(parents=True, exist_ok=False)
        write_json_atomic(
            suite_dir / "suite-config.json",
            {
                "config_schema_version": "suite-config-v2",
                "suite_id": suite_id,
                "frozen": suite_frozen_config,
            },
        )
        event_name = "suite_started"
    else:
        suite_dir = resume_dir.resolve()
        config = json.loads((suite_dir / "suite-config.json").read_text(encoding="utf-8"))
        if config.get("config_schema_version") != "suite-config-v2":
            raise ValueError("Resume suite uses an unsupported configuration schema")
        suite_id = config["suite_id"]
        if config.get("frozen") != suite_frozen_config:
            raise ValueError(
                "Resume configuration or frozen benchmark fingerprint does not match"
            )
        event_name = "suite_resumed"

    scanner = BaselineScanner(provider)
    progress_path = suite_dir / "case-evaluations.jsonl"
    evaluations = read_progress(
        progress_path,
        suite_dir=suite_dir,
        repetitions=repetitions,
        selected_cases=selected_cases,
        source_hashes=source_hashes,
    )
    append_jsonl(
        suite_dir / "suite-events.jsonl",
        {
            "event": event_name,
            "occurred_at": datetime.now(UTC).isoformat(),
            "request_delay_seconds": request_delay_seconds,
            "completed_evaluations": len(evaluations),
        },
    )
    completed = {(item["repetition"], item["case_id"]) for item in evaluations}

    for repetition in range(1, repetitions + 1):
        for case_id in selected_cases:
            if (repetition, case_id) in completed:
                continue
            evaluation = _run_case(
                scanner=scanner,
                suite_dir=suite_dir,
                repetition=repetition,
                case_id=case_id,
                source_hashes=source_hashes,
                expected_case=expected_case(manifest, case_id),
                manifest_sha256=manifest_sha256,
                execution_backend=execution_backend,
            )
            evaluations.append(evaluation)
            append_jsonl(progress_path, evaluation)
            _write_summary(
                suite_dir=suite_dir,
                suite_id=suite_id,
                provider=provider,
                repetitions=repetitions,
                selected_cases=selected_cases,
                evaluations=evaluations,
            )
            if request_delay_seconds:
                time.sleep(request_delay_seconds)

    return suite_dir


def _run_case(
    *,
    scanner: BaselineScanner,
    suite_dir: Path,
    repetition: int,
    case_id: str,
    source_hashes: dict[str, str],
    expected_case: dict | None,
    manifest_sha256: str,
    execution_backend: str,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="edgecase-case-") as temporary:
        temporary_root = Path(temporary)
        agent_repo = export_agent_repo(case_id, temporary_root / "case-under-test")
        agent_repo_sha256 = tree_sha256(agent_repo)
        run_output = suite_dir / "agent-runs" / f"run-{repetition:02d}" / case_id
        try:
            run_dir = scanner.scan(
                repo=agent_repo,
                output_root=run_output,
                case_id=case_id,
                execute=False,
            )
        except (ResponseParseError, ResponseValidationError) as exc:
            return _model_output_error(
                repetition=repetition,
                case_id=case_id,
                source_sha256=source_hashes[case_id],
                agent_repo_sha256=agent_repo_sha256,
                error=exc,
            )

        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        generated_test = run_dir / "generated_tests" / "test_generated_baseline.py"
        if not generated_test.exists():
            return _no_test_evaluation(
                repetition=repetition,
                case_id=case_id,
                source_sha256=source_hashes[case_id],
                agent_repo_sha256=agent_repo_sha256,
                run_dir=run_dir,
                suite_dir=suite_dir,
                report=report,
            )

        generated_test_bytes = generated_test.read_bytes()
        test_sha256 = hashlib.sha256(generated_test_bytes).hexdigest()
        evidence_dir = run_dir / "differential"
        execution_root = temporary_root / "neutral-execution"
        (
            clean_result,
            clean_repo_before,
            clean_repo_after,
            test_after_clean,
        ) = _run_neutral_execution(
            case_id="C00",
            execution_root=execution_root,
            generated_test_bytes=generated_test_bytes,
            execution_backend=execution_backend,
        )
        write_execution_evidence(
            role="clean",
            directory=evidence_dir / "clean",
            result=clean_result,
            repo_sha256=clean_repo_before,
            repo_sha256_after=clean_repo_after,
            test_sha256=test_sha256,
            test_sha256_after=test_after_clean,
        )

        mutant_result: ExecutionResult | None = None
        mutant_repo_before: str | None = None
        mutant_repo_after: str | None = None
        test_after_mutant = test_after_clean
        if case_id != "C00":
            (
                mutant_result,
                mutant_repo_before,
                mutant_repo_after,
                test_after_mutant,
            ) = _run_neutral_execution(
                case_id=case_id,
                execution_root=execution_root,
                generated_test_bytes=generated_test_bytes,
                execution_backend=execution_backend,
            )
            write_execution_evidence(
                role="mutant",
                directory=evidence_dir / "mutant",
                result=mutant_result,
                repo_sha256=mutant_repo_before,
                repo_sha256_after=mutant_repo_after,
                test_sha256=test_sha256,
                test_sha256_after=test_after_mutant,
            )

        differential = build_differential(
            case_id=case_id,
            clean=clean_result,
            mutant=mutant_result,
            findings=report["findings"],
            test_sha256=test_sha256,
        )
        case_integrity_errors = integrity_errors(
            expected_test_hash=test_sha256,
            observed_test_hashes=(test_after_clean, test_after_mutant),
            repo_hash_pairs=(
                ("clean", clean_repo_before, clean_repo_after),
                ("mutant", mutant_repo_before, mutant_repo_after),
            ),
        )
        if case_integrity_errors:
            invalidate_differential(differential, case_integrity_errors)
        differential.update(
            {
                "clean_execution": "clean/execution.json",
                "mutant_execution": (
                    "mutant/execution.json" if mutant_result is not None else None
                ),
                "integrity_errors": case_integrity_errors,
                "benchmark_manifest_sha256": manifest_sha256,
                "expected_case": expected_case,
            }
        )
        differential_path = evidence_dir / "differential.json"
        write_json_atomic(differential_path, differential)
        differential_sha256 = file_sha256(differential_path)
        run_artifacts_sha256 = tree_sha256(run_dir)

        candidate_kill = bool(differential["case_candidate_kill"])
        clean_assertion_failure = bool(differential["clean_false_positive_nodes"])
        invalid_generated_test_count = int(clean_result.invalid_generated_test) + int(
            mutant_result is not None and mutant_result.invalid_generated_test
        )
        evaluator_infrastructure_error_count = int(
            clean_result.evaluator_infrastructure_error
        ) + int(
            mutant_result is not None
            and mutant_result.evaluator_infrastructure_error
        )
        return {
            "evaluation_schema_version": "case-evaluation-v2",
            "repetition": repetition,
            "case_id": case_id,
            "source_sha256": source_hashes[case_id],
            "agent_repo_sha256": agent_repo_sha256,
            "test_sha256": test_sha256,
            "run_directory": run_dir.relative_to(suite_dir).as_posix(),
            "differential_evidence": differential_path.relative_to(suite_dir).as_posix(),
            "differential_sha256": differential_sha256,
            "run_artifacts_sha256": run_artifacts_sha256,
            "status": "completed",
            "reported_findings": len(report["findings"]),
            "integrity_error_count": len(case_integrity_errors),
            "invalid_generated_test_count": invalid_generated_test_count,
            "evaluator_infrastructure_error_count": (
                evaluator_infrastructure_error_count
            ),
            "test_generated": True,
            "passes_clean": _all_nodes_pass(clean_result),
            "fails_mutant": bool(
                mutant_result
                and mutant_result.scoreable_harness
                and any(
                    node.failure_kind == "assertion_failure"
                    for node in mutant_result.nodes
                )
            ),
            "candidate_kill": candidate_kill,
            "candidate_nodes": len(differential["candidate_nodes"]),
            "invalid_nodes": sum(
                node["classification"] in {"invalid", "unmatched"}
                for node in differential["nodes"]
            ),
            "confirmed_kill": False,
            "requires_invariant_adjudication": candidate_kill,
            "clean_assertion_failure": clean_assertion_failure,
            "clean_assertion_failure_nodes": len(
                differential["clean_false_positive_nodes"]
            ),
            "input_tokens": report["input_tokens"],
            "output_tokens": report["output_tokens"],
            "model_latency_seconds": report["model_latency_seconds"],
            "semantic_attempts": report["semantic_attempts"],
            "transport_attempts": report["transport_attempts"],
            "repair_used": report["repair_used"],
            "request_ids": report["request_ids"],
            "finish_reasons": report["finish_reasons"],
            "runtime_seconds": report["runtime_seconds"],
            "execution_runtime_seconds": round(
                clean_result.duration_seconds
                + (mutant_result.duration_seconds if mutant_result else 0.0),
                4,
            ),
        }


def _run_neutral_execution(
    *,
    case_id: str,
    execution_root: Path,
    generated_test_bytes: bytes,
    execution_backend: str,
) -> tuple[ExecutionResult, str, str, str]:
    """Run either side at the same opaque paths so role labels cannot leak."""
    if execution_root.exists():
        shutil.rmtree(execution_root)
    repo = export_agent_repo(case_id, execution_root / "repo")
    repo_before = tree_sha256(repo)
    test_file = repo / "test_generated.py"
    test_file.write_bytes(generated_test_bytes)
    runner = run_restricted_pytest if execution_backend == "docker" else run_generated_pytest
    result = runner(
        repo=repo, test_file=test_file,
        junit_path=execution_root / "artifacts" / "junit.xml",
    )
    test_after = file_sha256(test_file) if test_file.exists() else "missing"
    repo_after = tree_sha256(repo, excluded_relative_paths={"test_generated.py"})
    return result, repo_before, repo_after, test_after


def _all_nodes_pass(result: ExecutionResult) -> bool:
    return result.valid_test_run and bool(result.nodes) and all(
        node.outcome == "passed" for node in result.nodes
    )


def _model_output_error(
    *,
    repetition: int,
    case_id: str,
    source_sha256: str,
    agent_repo_sha256: str,
    error: Exception,
) -> dict:
    accounting = getattr(error, "accounting", None)
    usage = accounting.usage if accounting is not None else None
    return {
        "evaluation_schema_version": "case-evaluation-v2",
        "repetition": repetition,
        "case_id": case_id,
        "source_sha256": source_sha256,
        "agent_repo_sha256": agent_repo_sha256,
        "run_directory": None,
        "differential_evidence": None,
        "differential_sha256": None,
        "run_artifacts_sha256": None,
        "status": "model_output_error",
        "reported_findings": 0,
        "integrity_error_count": 0,
        "invalid_generated_test_count": 0,
        "evaluator_infrastructure_error_count": 0,
        "error_type": type(error).__name__,
        "error": str(error)[:2000],
        "model_response_sha256": list(
            getattr(error, "model_response_sha256", ())
        ),
        "model_response_excerpts": list(
            getattr(error, "model_response_excerpts", ())
        ),
        "test_generated": False,
        "passes_clean": False,
        "fails_mutant": False,
        "candidate_kill": False,
        "candidate_nodes": 0,
        "invalid_nodes": 0,
        "confirmed_kill": False,
        "requires_invariant_adjudication": False,
        "clean_assertion_failure": False,
        "clean_assertion_failure_nodes": 0,
        "input_tokens": usage.input_tokens if usage is not None else 0,
        "output_tokens": usage.output_tokens if usage is not None else 0,
        "model_latency_seconds": (
            round(accounting.latency_seconds, 4) if accounting is not None else 0.0
        ),
        "semantic_attempts": (
            accounting.semantic_attempts if accounting is not None else 0
        ),
        "transport_attempts": (
            accounting.transport_attempts if accounting is not None else 0
        ),
        "repair_used": accounting.repair_used if accounting is not None else False,
        "request_ids": list(accounting.request_ids) if accounting is not None else [],
        "finish_reasons": (
            list(accounting.finish_reasons) if accounting is not None else []
        ),
        "runtime_seconds": (
            round(accounting.latency_seconds, 4) if accounting is not None else 0.0
        ),
        "execution_runtime_seconds": 0.0,
    }


def _no_test_evaluation(
    *,
    repetition: int,
    case_id: str,
    source_sha256: str,
    agent_repo_sha256: str,
    run_dir: Path,
    suite_dir: Path,
    report: dict,
) -> dict:
    return {
        "evaluation_schema_version": "case-evaluation-v2",
        "repetition": repetition,
        "case_id": case_id,
        "source_sha256": source_sha256,
        "agent_repo_sha256": agent_repo_sha256,
        "run_directory": run_dir.relative_to(suite_dir).as_posix(),
        "differential_evidence": None,
        "differential_sha256": None,
        "run_artifacts_sha256": tree_sha256(run_dir),
        "status": "completed",
        "reported_findings": len(report["findings"]),
        "integrity_error_count": 0,
        "invalid_generated_test_count": 0,
        "evaluator_infrastructure_error_count": 0,
        "test_generated": False,
        "passes_clean": False,
        "fails_mutant": False,
        "candidate_kill": False,
        "candidate_nodes": 0,
        "invalid_nodes": 0,
        "confirmed_kill": False,
        "requires_invariant_adjudication": False,
        "clean_assertion_failure": False,
        "clean_assertion_failure_nodes": 0,
        "input_tokens": report["input_tokens"],
        "output_tokens": report["output_tokens"],
        "model_latency_seconds": report["model_latency_seconds"],
        "semantic_attempts": report["semantic_attempts"],
        "transport_attempts": report["transport_attempts"],
        "repair_used": report["repair_used"],
        "request_ids": report["request_ids"],
        "finish_reasons": report["finish_reasons"],
        "runtime_seconds": report["runtime_seconds"],
        "execution_runtime_seconds": 0.0,
    }


def _write_summary(
    *,
    suite_dir: Path,
    suite_id: str,
    provider: LLMProvider,
    repetitions: int,
    selected_cases: tuple[str, ...],
    evaluations: list[dict],
) -> None:
    mutants = [item for item in evaluations if item["case_id"] != "C00"]
    selected_mutants = tuple(case for case in selected_cases if case != "C00")
    expected_pairs = {
        (repetition, case_id)
        for repetition in range(1, repetitions + 1)
        for case_id in selected_cases
    }
    observed_pairs = {(item["repetition"], item["case_id"]) for item in evaluations}
    complete = observed_pairs == expected_pairs
    repetition_scores = []
    for repetition in range(1, repetitions + 1):
        repetition_mutants = [
            item for item in mutants if item["repetition"] == repetition
        ]
        kills = sum(int(item["candidate_kill"]) for item in repetition_mutants)
        repetition_complete = all(
            (repetition, case_id) in observed_pairs for case_id in selected_cases
        )
        score = (
            kills / len(selected_mutants)
            if repetition_complete and selected_mutants
            else None
        )
        repetition_scores.append(
            {
                "repetition": repetition,
                "status": "complete" if repetition_complete else "partial",
                "evaluated_mutants": len(repetition_mutants),
                "expected_mutants": len(selected_mutants),
                "candidate_kills": kills,
                "score": score,
            }
        )
    score_values = [
        item["score"] for item in repetition_scores if item["score"] is not None
    ]
    score_available = complete and bool(selected_mutants)
    full_benchmark = selected_cases == CASE_IDS
    git_state = json.loads((suite_dir / "suite-config.json").read_text(encoding="utf-8"))[
        "frozen"
    ]["git_state"]
    blockers: list[str] = []
    if not full_benchmark:
        blockers.append("subset_selection")
    if not complete:
        blockers.append("incomplete_case_matrix")
    if any(item["integrity_error_count"] for item in evaluations):
        blockers.append("integrity_check_failed")
    if any(item["evaluator_infrastructure_error_count"] for item in evaluations):
        blockers.append("evaluator_infrastructure_error")
    if not git_state.get("available") or git_state.get("dirty"):
        blockers.append("unfrozen_git_state")
    if any(item["requires_invariant_adjudication"] for item in evaluations):
        blockers.append("pending_adjudication")

    clean_controls = [
        item
        for item in evaluations
        if item["case_id"] == "C00" and item["status"] == "completed"
    ]
    clean_controls_with_claims = [
        item for item in clean_controls if item["reported_findings"] > 0
    ]
    clean_claims = sum(item["reported_findings"] for item in clean_controls)
    summary = {
        "suite_id": suite_id,
        "benchmark_version": BENCHMARK_VERSION,
        "status": "complete" if complete else "partial",
        "official_score_eligible": not blockers,
        "official_score_blockers": blockers,
        "provider": provider.name,
        "model": provider.model,
        "repetitions": repetitions,
        "selected_cases": list(selected_cases),
        "cases": evaluations,
        "candidate_kills": sum(int(item["candidate_kill"]) for item in mutants),
        "candidate_mutation_score": (
            statistics.median(score_values) if score_available else None
        ),
        "candidate_mutation_score_range": (
            [min(score_values), max(score_values)] if score_available else None
        ),
        "repetition_scores": repetition_scores,
        "confirmed_kills": 0,
        "confirmed_mutation_score": None,
        "clean_control_evaluations_expected": repetitions if "C00" in selected_cases else 0,
        "clean_control_evaluations_completed": len(clean_controls),
        "clean_control_evaluations_with_claims": len(clean_controls_with_claims),
        "clean_control_claims_reported": clean_claims,
        "clean_control_claim_frequency": (
            len(clean_controls_with_claims) / len(clean_controls)
            if clean_controls
            else None
        ),
        "clean_control_claims_per_completed_evaluation": (
            clean_claims / len(clean_controls) if clean_controls else None
        ),
        "evaluations_with_clean_assertion_failures": sum(
            int(item["clean_assertion_failure"]) for item in evaluations
        ),
        "clean_assertion_failure_nodes": sum(
            item["clean_assertion_failure_nodes"] for item in evaluations
        ),
        "invalid_nodes": sum(item["invalid_nodes"] for item in evaluations),
        "model_output_errors": sum(
            int(item["status"] == "model_output_error") for item in evaluations
        ),
        "invalid_generated_tests": sum(
            item["invalid_generated_test_count"] for item in evaluations
        ),
        "evaluator_infrastructure_errors": sum(
            item["evaluator_infrastructure_error_count"] for item in evaluations
        ),
        "input_tokens": sum(item["input_tokens"] for item in evaluations),
        "output_tokens": sum(item["output_tokens"] for item in evaluations),
        "model_latency_seconds": round(
            sum(item["model_latency_seconds"] for item in evaluations), 4
        ),
        "semantic_attempts": sum(item["semantic_attempts"] for item in evaluations),
        "transport_attempts": sum(item["transport_attempts"] for item in evaluations),
        "repair_used_evaluations": sum(
            int(item["repair_used"]) for item in evaluations
        ),
        "runtime_seconds": round(sum(item["runtime_seconds"] for item in evaluations), 4),
        "execution_runtime_seconds": round(
            sum(item["execution_runtime_seconds"] for item in evaluations), 4
        ),
        "note": "Candidate kills require independent invariant adjudication before confirmation.",
    }
    write_json_atomic(suite_dir / "suite-summary.json", summary)
