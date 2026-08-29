from __future__ import annotations

import subprocess
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

