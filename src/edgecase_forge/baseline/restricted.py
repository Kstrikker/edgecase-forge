from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .executor import ExecutionResult, _parse_junit, _process_group_options, _read_junit, _terminate_process_tree

DEFAULT_IMAGE = "edgecase-forge-runner:flashcart-v1.1"
DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "runner.Dockerfile"
PROJECT_ROOT = DOCKERFILE.parents[1]


def docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def ensure_runner_image(image: str = DEFAULT_IMAGE) -> None:
    if not docker_available():
        raise RuntimeError("Docker Desktop is unavailable; restricted execution is required")
    inspected = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, timeout=15, check=False
    )
    if inspected.returncode == 0:
        return
    built = subprocess.run(
        ["docker", "build", "--tag", image, "--file", str(DOCKERFILE), str(PROJECT_ROOT)],
        text=True, timeout=600, check=False,
    )
    if built.returncode != 0:
        raise RuntimeError("Could not build the restricted execution image")


def run_restricted_pytest(
    *, repo: Path, test_file: Path, timeout_seconds: int = 120,
    junit_path: Path | None = None, image: str = DEFAULT_IMAGE,
) -> ExecutionResult:
    """Run generated tests in a networkless, read-only Docker container."""
    if not repo.is_dir() or not test_file.is_file():
        raise ValueError("Restricted runner requires an existing repository and test file")
    relative_test = test_file.resolve().relative_to(repo.resolve()).as_posix()
    artifacts = (junit_path or repo.parent / "junit.xml").resolve().parent
    artifacts.mkdir(parents=True, exist_ok=True)
    command = (
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "128", "--cpus", "1.0", "--memory", "512m",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--mount", f"type=bind,source={repo.resolve()},target=/workspace/repo,readonly",
        "--mount", f"type=bind,source={artifacts},target=/workspace/artifacts",
        "--workdir", "/workspace/repo", image, "-m", "pytest", "-q",
        "--runxfail", "-p", "no:cacheprovider", "--junitxml",
        "/workspace/artifacts/junit.xml", relative_test,
    )
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/workspace/repo",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "TMPDIR": "/tmp",
    }
    try:
        process = subprocess.Popen(
            command, cwd=repo, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            **_process_group_options(),
        )
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        junit_xml = _read_junit(artifacts / "junit.xml")
        return ExecutionResult(
            executed=True, exit_code=None, stdout=stdout or str(exc.stdout or ""),
            stderr=stderr or str(exc.stderr or ""), timed_out=True,
            duration_seconds=round(time.monotonic() - started, 4), started_at=started_at,
            timeout_seconds=timeout_seconds, command=command,
            nodes=_parse_junit(junit_xml), junit_xml=junit_xml,
        )
    except OSError as exc:
        return ExecutionResult(
            executed=False, exit_code=None, stdout="", stderr=str(exc),
            duration_seconds=round(time.monotonic() - started, 4), started_at=started_at,
            timeout_seconds=timeout_seconds, command=command,
        )
    junit_xml = _read_junit(artifacts / "junit.xml")
    return ExecutionResult(
        executed=True, exit_code=process.returncode, stdout=stdout, stderr=stderr,
        duration_seconds=round(time.monotonic() - started, 4), started_at=started_at,
        timeout_seconds=timeout_seconds, command=command,
        nodes=_parse_junit(junit_xml), junit_xml=junit_xml,
    )
