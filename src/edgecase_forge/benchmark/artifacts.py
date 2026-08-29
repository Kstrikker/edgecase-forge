from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from edgecase_forge.baseline.executor import ExecutionResult, execution_payload

EXECUTION_SCHEMA_VERSION = "pytest-execution-v1"


def write_execution_evidence(
    *,
    role: str,
    directory: Path,
    result: ExecutionResult,
    repo_sha256: str,
    repo_sha256_after: str,
    test_sha256: str,
    test_sha256_after: str,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    stdout_path = directory / "stdout.log"
    stderr_path = directory / "stderr.log"
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    junit_path = directory / "junit.xml"
    if result.junit_xml:
        junit_path.write_text(result.junit_xml, encoding="utf-8")

    payload = execution_payload(result)
    payload.update(
        {
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "role": role,
            "repo_sha256": repo_sha256,
            "repo_sha256_after": repo_sha256_after,
            "test_sha256": test_sha256,
            "test_sha256_after": test_sha256_after,
            "command": _portable_command(result.command),
            "stdout": _artifact_metadata(stdout_path),
            "stderr": _artifact_metadata(stderr_path),
            "junit": _artifact_metadata(junit_path) if junit_path.exists() else None,
        }
    )
    write_json_atomic(directory / "execution.json", payload)


def integrity_errors(
    *,
    expected_test_hash: str,
    observed_test_hashes: tuple[str, ...],
    repo_hash_pairs: tuple[tuple[str, str | None, str | None], ...],
) -> list[str]:
    errors = [
        "generated_test_changed_during_execution"
        for observed in observed_test_hashes
        if observed != expected_test_hash
    ]
    for role, before, after in repo_hash_pairs:
        if before is not None and after is not None and before != after:
            errors.append(f"{role}_repository_changed_during_execution")
    return sorted(set(errors))


def invalidate_differential(differential: dict, errors: list[str]) -> None:
    differential["candidate_nodes"] = []
    differential["case_candidate_kill"] = False
    for node in differential["nodes"]:
        node["classification"] = "invalid"
        node["reason"] = "integrity_check_failed"
        node["adjudication"] = "not_applicable"
        node["adjudication_reason"] = ",".join(errors)


def tree_sha256(
    root: Path, *, excluded_relative_paths: set[str] | None = None
) -> str:
    excluded = excluded_relative_paths or set()
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative_text = path.relative_to(root).as_posix()
        if relative_text in excluded or "__pycache__" in path.parts:
            continue
        relative = relative_text.encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha256(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_progress(
    path: Path,
    *,
    suite_dir: Path,
    repetitions: int,
    selected_cases: tuple[str, ...],
    source_hashes: dict[str, str],
) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("Progress JSONL has a truncated final line")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Progress JSONL is not valid UTF-8") from exc

    allowed = {
        (repetition, case_id)
        for repetition in range(1, repetitions + 1)
        for case_id in selected_cases
    }
    seen: set[tuple[int, str]] = set()
    evaluations: list[dict] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"Progress JSONL line {line_number} is blank")
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Progress JSONL line {line_number} is invalid") from exc
        if not isinstance(item, dict):
            raise ValueError(f"Progress JSONL line {line_number} is not an object")
        if item.get("evaluation_schema_version") != "case-evaluation-v2":
            raise ValueError(f"Progress JSONL line {line_number} has an unknown schema")
        key = (item.get("repetition"), item.get("case_id"))
        if key not in allowed:
            raise ValueError(f"Progress JSONL line {line_number} is outside the schedule")
        if key in seen:
            raise ValueError(f"Progress JSONL line {line_number} duplicates {key}")
        if item.get("source_sha256") != source_hashes[key[1]]:
            raise ValueError(f"Progress JSONL line {line_number} has a source mismatch")
        _validate_evaluation_artifacts(
            item=item,
            suite_dir=suite_dir,
            line_number=line_number,
        )
        seen.add(key)
        evaluations.append(item)
    return evaluations


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _portable_command(command: tuple[str, ...]) -> list[str]:
    portable: list[str] = []
    for index, value in enumerate(command):
        if index == 0:
            portable.append("<python>")
        elif value.endswith("junit.xml"):
            portable.append("<junit.xml>")
        elif value.endswith(("test_generated_baseline.py", "test_generated.py")):
            portable.append("<generated-test>")
        else:
            portable.append(value)
    return portable


def _artifact_metadata(path: Path) -> dict:
    content = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "truncated": False,
    }


def _validate_evaluation_artifacts(
    *, item: dict, suite_dir: Path, line_number: int
) -> None:
    status = item.get("status")
    if status not in {"completed", "model_output_error"}:
        raise ValueError(f"Progress JSONL line {line_number} has invalid status")
    for field in (
        "candidate_nodes",
        "invalid_nodes",
        "clean_assertion_failure_nodes",
        "reported_findings",
        "integrity_error_count",
        "invalid_generated_test_count",
        "evaluator_infrastructure_error_count",
        "input_tokens",
        "output_tokens",
        "semantic_attempts",
        "transport_attempts",
    ):
        value = item.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Progress JSONL line {line_number} has invalid {field}")
    for field in (
        "runtime_seconds",
        "execution_runtime_seconds",
        "model_latency_seconds",
    ):
        value = item.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Progress JSONL line {line_number} has invalid {field}")
    if not isinstance(item.get("repair_used"), bool):
        raise ValueError(f"Progress JSONL line {line_number} has invalid repair_used")
    if not isinstance(item.get("request_ids"), list) or not all(
        isinstance(value, str) for value in item["request_ids"]
    ):
        raise ValueError(f"Progress JSONL line {line_number} has invalid request_ids")

    if status == "model_output_error":
        if (
            item.get("run_directory") is not None
            or item.get("differential_evidence") is not None
        ):
            raise ValueError(
                f"Progress JSONL line {line_number} has impossible error artifacts"
            )
        return

    run_dir = _safe_suite_path(suite_dir, item.get("run_directory"), line_number)
    if not run_dir.is_dir():
        raise ValueError(f"Progress JSONL line {line_number} run directory is missing")
    if tree_sha256(run_dir) != item.get("run_artifacts_sha256"):
        raise ValueError(f"Progress JSONL line {line_number} run artifacts were modified")

    if not item.get("test_generated"):
        if item.get("differential_evidence") is not None:
            raise ValueError(
                f"Progress JSONL line {line_number} has unexpected differential evidence"
            )
        return

    differential_path = _safe_suite_path(
        suite_dir, item.get("differential_evidence"), line_number
    )
    if not differential_path.is_file():
        raise ValueError(
            f"Progress JSONL line {line_number} differential evidence is missing"
        )
    if file_sha256(differential_path) != item.get("differential_sha256"):
        raise ValueError(
            f"Progress JSONL line {line_number} differential evidence was modified"
        )
    differential = json.loads(differential_path.read_text(encoding="utf-8"))
    if (
        differential.get("case_id") != item.get("case_id")
        or differential.get("test_sha256") != item.get("test_sha256")
        or differential.get("case_candidate_kill") != item.get("candidate_kill")
    ):
        raise ValueError(
            f"Progress JSONL line {line_number} differential metadata conflicts"
        )
    for relative in (
        differential.get("clean_execution"),
        differential.get("mutant_execution"),
    ):
        if relative is None:
            continue
        execution_path = _safe_child_path(
            differential_path.parent, relative, line_number
        )
        if not execution_path.is_file():
            raise ValueError(
                f"Progress JSONL line {line_number} execution evidence is missing"
            )
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        _validate_execution_artifacts(execution_path.parent, execution, line_number)


def _validate_execution_artifacts(
    directory: Path, execution: dict, line_number: int
) -> None:
    for field in ("stdout", "stderr", "junit"):
        metadata = execution.get(field)
        if metadata is None and field == "junit":
            continue
        if not isinstance(metadata, dict):
            raise ValueError(
                f"Progress JSONL line {line_number} has invalid {field} metadata"
            )
        artifact = _safe_child_path(directory, metadata.get("path"), line_number)
        if not artifact.is_file():
            raise ValueError(f"Progress JSONL line {line_number} is missing {field}")
        content = artifact.read_bytes()
        if (
            len(content) != metadata.get("bytes")
            or hashlib.sha256(content).hexdigest() != metadata.get("sha256")
        ):
            raise ValueError(f"Progress JSONL line {line_number} has modified {field}")


def _safe_suite_path(suite_dir: Path, value: object, line_number: int) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"Progress JSONL line {line_number} has an invalid artifact path"
        )
    return _safe_child_path(suite_dir, value, line_number)


def _safe_child_path(root: Path, value: object, line_number: int) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Progress JSONL line {line_number} has an invalid child path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Progress JSONL line {line_number} has an unsafe path")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Progress JSONL line {line_number} path escapes its root")
    return resolved
