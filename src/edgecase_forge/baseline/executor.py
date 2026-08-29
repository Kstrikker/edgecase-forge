from __future__ import annotations

import subprocess
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    executed: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


def run_generated_pytest(
    *,
    repo: Path,
    test_file: Path,
    timeout_seconds: int = 120,
) -> ExecutionResult:
    try:
        completed = subprocess.run(
            ["python", "-m", "pytest", "-q", str(test_file)],
            cwd=repo,
            text=True,
            capture_output=True,
            env=_safe_environment(repo),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            executed=True,
            exit_code=None,
            stdout=(exc.stdout or "")[-20_000:],
            stderr=(exc.stderr or "")[-20_000:],
            timed_out=True,
        )
    return ExecutionResult(
        executed=True,
        exit_code=completed.returncode,
        stdout=completed.stdout[-20_000:],
        stderr=completed.stderr[-20_000:],
    )


def _safe_environment(repo: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for secret_name in ("GEMINI_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"):
        environment.pop(secret_name, None)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(repo) + (os.pathsep + existing if existing else "")
    return environment
