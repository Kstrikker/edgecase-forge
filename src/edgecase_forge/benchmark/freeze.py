from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from benchmarks.flashcart import build_all
from edgecase_forge.llm.base import LLMProvider

from .artifacts import file_sha256, json_sha256

BENCHMARK_VERSION = "flashcart-v1.1.0"
CASE_IDS = ("C00", *(f"M{index:02d}" for index in range(1, 11)))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_HASHES_PATH = PROJECT_ROOT / "benchmarks/flashcart/expected_hashes.json"
MANIFEST_PATH = PROJECT_ROOT / "benchmarks/manifest.json"


def frozen_config(
    *,
    provider: LLMProvider,
    repetitions: int,
    selected_cases: tuple[str, ...],
    source_hashes: dict[str, str],
    manifest_sha256: str,
) -> dict:
    artifact_hashes = _frozen_artifact_hashes()
    runtime_versions = _runtime_versions()
    provider_config = _provider_experiment_config(provider)
    git_state = _git_state()
    fingerprint_payload = {
        "benchmark_version": BENCHMARK_VERSION,
        "source_hashes": source_hashes,
        "artifact_hashes": artifact_hashes,
        "runtime_versions": runtime_versions,
        "provider": provider_config,
        "manifest_sha256": manifest_sha256,
        "git_state": git_state,
    }
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "provider": provider_config,
        "repetitions": repetitions,
        "selected_cases": list(selected_cases),
        "source_hashes": source_hashes,
        "benchmark_manifest_sha256": manifest_sha256,
        "artifact_hashes": artifact_hashes,
        "source_tree_sha256": json_sha256(artifact_hashes),
        "runtime_versions": runtime_versions,
        "git_state": git_state,
        "suite_fingerprint_sha256": json_sha256(fingerprint_payload),
    }


def validate_cases(case_ids: Sequence[str] | None) -> tuple[str, ...]:
    selected = tuple(case_ids) if case_ids is not None else CASE_IDS
    if not selected:
        raise ValueError("At least one case must be selected")
    if len(set(selected)) != len(selected):
        raise ValueError("Case selection contains duplicates")
    unknown = sorted(set(selected) - set(CASE_IDS))
    if unknown:
        raise ValueError(f"Unknown FlashCart cases: {', '.join(unknown)}")
    return selected


def preflight_flashcart() -> tuple[dict[str, str], dict, str]:
    observed = build_all()
    expected = json.loads(EXPECTED_HASHES_PATH.read_text(encoding="utf-8"))
    if set(expected) != set(CASE_IDS) or any(
        not isinstance(value, str) or len(value) != 64 for value in expected.values()
    ):
        raise RuntimeError("Frozen FlashCart expected hashes are malformed")
    if observed != expected:
        raise RuntimeError("Built FlashCart variants do not match frozen expected hashes")

    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes)
    _validate_manifest(manifest)
    fingerprint = json_sha256({"source_hashes": observed, "manifest": manifest})
    _run_oracle_preflight(fingerprint)
    return observed, manifest, hashlib.sha256(manifest_bytes).hexdigest()


def expected_case(manifest: dict, case_id: str) -> dict | None:
    if case_id == "C00":
        return None
    for item in manifest["mutants"]:
        if item["id"] == case_id:
            return {
                "id": item["id"],
                "category": item["category"],
                "invariant": item["invariant"],
                "oracle": item["oracle"],
            }
    raise RuntimeError(f"Missing manifest contract for {case_id}")


def _frozen_artifact_hashes() -> dict[str, str]:
    relative_paths: set[str] = {"pyproject.toml", "benchmarks/manifest.json"}
    relative_paths.update(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src/edgecase_forge").rglob("*.py")
    )
    relative_paths.update(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "benchmarks/flashcart").rglob("*")
        if path.is_file()
        and "generated" not in path.parts
        and path.suffix in {".py", ".json", ".toml"}
    )
    return {
        relative: file_sha256(PROJECT_ROOT / relative)
        for relative in sorted(relative_paths)
    }


def _runtime_versions() -> dict[str, str]:
    packages = ("fastapi", "httpx", "pydantic", "pytest", "starlette")
    versions = {"python": sys.version.split()[0]}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _provider_experiment_config(provider: LLMProvider) -> dict:
    configured = getattr(provider, "experiment_config", None)
    if isinstance(configured, dict):
        return configured
    return {
        "provider": provider.name,
        "model": provider.model,
        "implementation": f"{type(provider).__module__}.{type(provider).__qualname__}",
    }


@lru_cache(maxsize=4)
def _run_oracle_preflight(fingerprint: str) -> None:
    del fingerprint
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "benchmarks/flashcart/oracle/test_oracles.py",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        details = (completed.stdout + "\n" + completed.stderr)[-4000:]
        raise RuntimeError(f"FlashCart oracle preflight failed:\n{details}")


def _validate_manifest(manifest: dict) -> None:
    if manifest.get("benchmark_version") != BENCHMARK_VERSION:
        raise RuntimeError("Benchmark manifest version does not match evaluator")
    if manifest.get("status") != "frozen":
        raise RuntimeError("Benchmark manifest is not frozen")
    if manifest.get("clean_control") != "C00":
        raise RuntimeError("Benchmark manifest clean control must be C00")
    mutants = manifest.get("mutants")
    if not isinstance(mutants, list):
        raise RuntimeError("Benchmark manifest mutants must be a list")
    ids = [item.get("id") for item in mutants if isinstance(item, dict)]
    if ids != list(CASE_IDS[1:]):
        raise RuntimeError("Benchmark manifest mutant IDs are incomplete or reordered")
    for item in mutants:
        required = ("category", "invariant", "oracle")
        if not all(str(item.get(field, "")).strip() for field in required):
            raise RuntimeError(f"Benchmark manifest case {item.get('id')} is incomplete")


def _git_state() -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if commit.returncode != 0:
        return {"available": False, "commit": None, "dirty": None, "status_sha256": None}
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "pyproject.toml",
            "src",
            "benchmarks",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    status_text = status.stdout if status.returncode == 0 else "status-unavailable"
    return {
        "available": True,
        "commit": commit.stdout.strip(),
        "dirty": bool(status_text),
        "status_sha256": hashlib.sha256(status_text.encode("utf-8")).hexdigest(),
    }
