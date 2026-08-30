from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .artifacts import (
    file_sha256,
    json_sha256,
    read_progress,
    write_json_atomic,
)

DECISIONS_SCHEMA_VERSION = "adjudication-decisions-v1"
ADJUDICATION_SCHEMA_VERSION = "suite-adjudication-v1"
SUMMARY_SCHEMA_VERSION = "adjudicated-summary-v1"


class AdjudicationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repetition: int = Field(ge=1)
    case_id: str = Field(pattern=r"^M\d{2}$")
    test_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    differential_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["confirmed", "rejected"]
    reason: str = Field(min_length=1)


class AdjudicationDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[DECISIONS_SCHEMA_VERSION]
    suite_id: str = Field(min_length=1)
    suite_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    review_policy: str = Field(min_length=1)
    decisions: list[AdjudicationDecision]


def adjudicate_suite(*, suite_dir: Path, decisions_path: Path) -> tuple[Path, Path]:
    """Validate frozen evidence and write an immutable adjudication overlay."""
    suite_dir = suite_dir.resolve()
    decisions_path = decisions_path.resolve()
    config_path = suite_dir / "suite-config.json"
    progress_path = suite_dir / "case-evaluations.jsonl"
    raw_summary_path = suite_dir / "suite-summary.json"
    for path in (config_path, progress_path, raw_summary_path, decisions_path):
        if not path.is_file():
            raise ValueError(f"Required adjudication input is missing: {path}")

    config = _read_object(config_path, "suite configuration")
    if config.get("config_schema_version") != "suite-config-v2":
        raise ValueError("Suite uses an unsupported configuration schema")
    frozen = config.get("frozen")
    if not isinstance(frozen, dict):
        raise ValueError("Suite configuration has no frozen contract")
    repetitions = _positive_int(frozen.get("repetitions"), "repetitions")
    selected_cases = _string_tuple(frozen.get("selected_cases"), "selected_cases")
    source_hashes = frozen.get("source_hashes")
    if not isinstance(source_hashes, dict) or not set(selected_cases).issubset(source_hashes):
        raise ValueError("Suite configuration has invalid source hashes")
    fingerprint = frozen.get("suite_fingerprint_sha256")
    if not isinstance(fingerprint, str):
        raise ValueError("Suite configuration has no fingerprint")

    evaluations = read_progress(
        progress_path,
        suite_dir=suite_dir,
        repetitions=repetitions,
        selected_cases=selected_cases,
        source_hashes=source_hashes,
    )
    expected_pairs = {
        (repetition, case_id)
        for repetition in range(1, repetitions + 1)
        for case_id in selected_cases
    }
    observed_pairs = {(item["repetition"], item["case_id"]) for item in evaluations}
    if observed_pairs != expected_pairs:
        raise ValueError("Only a complete suite can be adjudicated")

    raw_summary = _read_object(raw_summary_path, "suite summary")
    if raw_summary.get("suite_id") != config.get("suite_id"):
        raise ValueError("Suite summary ID conflicts with its configuration")
    if raw_summary.get("status") != "complete":
        raise ValueError("Only a complete suite summary can be adjudicated")
    if raw_summary.get("cases") != evaluations:
        raise ValueError("Suite summary conflicts with the verified progress ledger")

    decisions = _read_decisions(decisions_path)
    if decisions.suite_id != config.get("suite_id"):
        raise ValueError("Decision file targets a different suite ID")
    if decisions.suite_fingerprint_sha256 != fingerprint:
        raise ValueError("Decision file targets a different suite fingerprint")

    candidates = {
        (item["repetition"], item["case_id"]): item
        for item in evaluations
        if item["candidate_kill"]
    }
    indexed_decisions: dict[tuple[int, str], AdjudicationDecision] = {}
    for decision in decisions.decisions:
        key = (decision.repetition, decision.case_id)
        if key in indexed_decisions:
            raise ValueError(f"Decision file duplicates candidate {key}")
        indexed_decisions[key] = decision
    if set(indexed_decisions) != set(candidates):
        missing = sorted(set(candidates) - set(indexed_decisions))
        extra = sorted(set(indexed_decisions) - set(candidates))
        raise ValueError(
            f"Decision coverage must exactly match candidate kills; missing={missing}, extra={extra}"
        )

    case_decisions: list[dict] = []
    for key in sorted(candidates):
        evaluation = candidates[key]
        decision = indexed_decisions[key]
        if decision.test_sha256 != evaluation["test_sha256"]:
            raise ValueError(f"Decision test hash does not match candidate {key}")
        if decision.differential_sha256 != evaluation["differential_sha256"]:
            raise ValueError(f"Decision evidence hash does not match candidate {key}")
        case_decisions.append(
            {
                "repetition": decision.repetition,
                "case_id": decision.case_id,
                "test_sha256": decision.test_sha256,
                "differential_sha256": decision.differential_sha256,
                "decision": decision.decision,
                "confirmed_kill": decision.decision == "confirmed",
                "reason": decision.reason.strip(),
            }
        )

    adjudication = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "suite_id": decisions.suite_id,
        "suite_fingerprint_sha256": decisions.suite_fingerprint_sha256,
        "reviewer": decisions.reviewer.strip(),
        "review_policy": decisions.review_policy.strip(),
        "source_config_sha256": file_sha256(config_path),
        "source_progress_sha256": file_sha256(progress_path),
        "source_summary_sha256": file_sha256(raw_summary_path),
        "source_decisions_sha256": file_sha256(decisions_path),
        "candidate_kills_reviewed": len(case_decisions),
        "decisions": case_decisions,
    }
    adjudication_path = suite_dir / "adjudication.json"
    _write_once(adjudication_path, adjudication)

    adjudicated_summary = _build_adjudicated_summary(
        config=config,
        raw_summary=raw_summary,
        case_decisions=case_decisions,
        adjudication_sha256=json_sha256(adjudication),
        source_summary_sha256=adjudication["source_summary_sha256"],
    )
    adjudicated_summary_path = suite_dir / "adjudicated-summary.json"
    _write_once(adjudicated_summary_path, adjudicated_summary)
    return adjudication_path, adjudicated_summary_path


def _build_adjudicated_summary(
    *,
    config: dict,
    raw_summary: dict,
    case_decisions: list[dict],
    adjudication_sha256: str,
    source_summary_sha256: str,
) -> dict:
    frozen = config["frozen"]
    repetitions = frozen["repetitions"]
    selected_mutants = [case for case in frozen["selected_cases"] if case != "C00"]
    confirmed_by_repetition: dict[int, int] = {
        repetition: 0 for repetition in range(1, repetitions + 1)
    }
    for decision in case_decisions:
        if decision["confirmed_kill"]:
            confirmed_by_repetition[decision["repetition"]] += 1
    repetition_scores = [
        {
            "repetition": repetition,
            "expected_mutants": len(selected_mutants),
            "confirmed_kills": confirmed_by_repetition[repetition],
            "score": (
                confirmed_by_repetition[repetition] / len(selected_mutants)
                if selected_mutants
                else None
            ),
        }
        for repetition in range(1, repetitions + 1)
    ]
    values = [item["score"] for item in repetition_scores if item["score"] is not None]
    blockers = [
        blocker
        for blocker in raw_summary.get("official_score_blockers", [])
        if blocker != "pending_adjudication"
    ]
    confirmed = sum(int(item["confirmed_kill"]) for item in case_decisions)
    rejected = len(case_decisions) - confirmed
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "suite_id": config["suite_id"],
        "suite_fingerprint_sha256": frozen["suite_fingerprint_sha256"],
        "benchmark_version": raw_summary["benchmark_version"],
        "provider": raw_summary["provider"],
        "model": raw_summary["model"],
        "repetitions": repetitions,
        "selected_cases": list(frozen["selected_cases"]),
        "source_summary_sha256": source_summary_sha256,
        "adjudication_sha256": adjudication_sha256,
        "official_score_eligible": not blockers,
        "official_score_blockers": blockers,
        "candidate_kills": raw_summary["candidate_kills"],
        "candidate_mutation_score": raw_summary["candidate_mutation_score"],
        "confirmed_kills": confirmed,
        "rejected_candidate_kills": rejected,
        "confirmed_mutation_score": statistics.median(values) if values else None,
        "confirmed_mutation_score_range": [min(values), max(values)] if values else None,
        "repetition_scores": repetition_scores,
        "clean_control_claims_reported": raw_summary["clean_control_claims_reported"],
        "evaluations_with_clean_assertion_failures": raw_summary[
            "evaluations_with_clean_assertion_failures"
        ],
        "model_output_errors": raw_summary["model_output_errors"],
        "invalid_generated_tests": raw_summary["invalid_generated_tests"],
        "evaluator_infrastructure_errors": raw_summary[
            "evaluator_infrastructure_errors"
        ],
        "decisions": case_decisions,
        "note": "Confirmed score is an immutable overlay; raw suite evidence is unchanged.",
    }


def _read_decisions(path: Path) -> AdjudicationDecisions:
    try:
        return AdjudicationDecisions.model_validate_json(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValidationError) as exc:
        raise ValueError("Decision file does not match adjudication-decisions-v1") from exc


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label}: expected an object")
    return value


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"Suite configuration has invalid {label}")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ValueError(f"Suite configuration has invalid {label}")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise ValueError(f"Suite configuration has duplicate {label}")
    return result


def _write_once(path: Path, payload: dict) -> None:
    if path.exists():
        existing = _read_object(path, path.name)
        if existing != payload:
            raise ValueError(f"Refusing to replace existing immutable {path.name}")
        return
    write_json_atomic(path, payload)
