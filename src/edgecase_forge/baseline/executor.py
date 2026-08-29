from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PytestNodeResult:
    node_id: str
    test_name: str
    outcome: str
    failure_kind: str | None = None
    message: str = ""
    duration_seconds: float = 0.0

    @property
    def eligible_for_differential(self) -> bool:
        return self.outcome == "passed" or self.failure_kind == "assertion_failure"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    executed: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_seconds: float = 0.0
    started_at: str | None = None
    timeout_seconds: int | None = None
    command: tuple[str, ...] = ()
    nodes: tuple[PytestNodeResult, ...] = ()
    junit_xml: str = field(default="", repr=False, compare=False)

    @property
    def valid_test_run(self) -> bool:
        return self.harness_status in {"complete", "complete_with_node_errors"}

    @property
    def scoreable_harness(self) -> bool:
        return self.harness_status == "complete"

    @property
    def invalid_generated_test(self) -> bool:
        """Whether agent-authored test code failed to produce scoreable evidence."""
        return self.harness_status in {
            "timeout",
            "interrupted",
            "no_tests",
            "complete_with_node_errors",
        }

    @property
    def evaluator_infrastructure_error(self) -> bool:
        """Whether the evaluator, rather than the submitted test, failed."""
        return self.harness_status in {
            "not_executed",
            "internal_error",
            "usage_error",
            "spawn_error",
            "junit_error",
        }

    @property
    def harness_status(self) -> str:
        if not self.executed:
            return "not_executed"
        if self.timed_out:
            return "timeout"
        if self.exit_code == 2:
            return "interrupted"
        if self.exit_code == 3:
            return "internal_error"
        if self.exit_code == 4:
            return "usage_error"
        if self.exit_code == 5:
            return "no_tests"
        if self.exit_code not in {0, 1}:
            return "spawn_error"
        if not self.junit_xml or not self.nodes:
            return "junit_error"
        if any(node.outcome == "error" for node in self.nodes):
            return "complete_with_node_errors"
        return "complete"


def run_generated_pytest(
    *,
    repo: Path,
    test_file: Path,
    timeout_seconds: int = 120,
    junit_path: Path | None = None,
) -> ExecutionResult:
    """Execute generated pytest code and retain node-level evidence.

    This local runner is intended only for trusted, synthetic fixtures. The official
    benchmark wraps the same command contract in the restricted execution backend.
    """
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1")

    with tempfile.TemporaryDirectory(prefix="edgecase-pytest-") as temporary:
        resolved_junit = junit_path or Path(temporary) / "junit.xml"
        resolved_junit.parent.mkdir(parents=True, exist_ok=True)
        command = (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--runxfail",
            "-p",
            "no:cacheprovider",
            "--junitxml",
            str(resolved_junit),
            str(test_file),
        )
        started_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=repo,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_safe_environment(repo),
                **_process_group_options(),
            )
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(process)
            stdout, stderr = process.communicate()
            duration = time.monotonic() - started
            junit_xml = _read_junit(resolved_junit)
            return ExecutionResult(
                executed=True,
                exit_code=None,
                stdout=stdout or _decode_timeout_output(exc.stdout),
                stderr=stderr or _decode_timeout_output(exc.stderr),
                timed_out=True,
                duration_seconds=round(duration, 4),
                started_at=started_at,
                timeout_seconds=timeout_seconds,
                command=command,
                nodes=_parse_junit(junit_xml),
                junit_xml=junit_xml,
            )
        except OSError as exc:
            return ExecutionResult(
                executed=True,
                exit_code=None,
                stdout="",
                stderr=_tail(str(exc)),
                duration_seconds=round(time.monotonic() - started, 4),
                started_at=started_at,
                timeout_seconds=timeout_seconds,
                command=command,
            )

        duration = time.monotonic() - started
        junit_xml = _read_junit(resolved_junit)
        return ExecutionResult(
            executed=True,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, 4),
            started_at=started_at,
            timeout_seconds=timeout_seconds,
            command=command,
            nodes=_parse_junit(junit_xml),
            junit_xml=junit_xml,
        )


def execution_payload(result: ExecutionResult) -> dict:
    return {
        "executed": result.executed,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
        "duration_seconds": result.duration_seconds,
        "started_at": result.started_at,
        "timeout_seconds": result.timeout_seconds,
        "command": list(result.command),
        "valid_test_run": result.valid_test_run,
        "scoreable_harness": result.scoreable_harness,
        "harness_status": result.harness_status,
        "invalid_generated_test": result.invalid_generated_test,
        "evaluator_infrastructure_error": result.evaluator_infrastructure_error,
        "nodes": [
            {
                "node_id": node.node_id,
                "test_name": node.test_name,
                "outcome": node.outcome,
                "failure_kind": node.failure_kind,
                "message": node.message,
                "duration_seconds": node.duration_seconds,
                "eligible_for_differential": node.eligible_for_differential,
            }
            for node in result.nodes
        ],
    }


def _safe_environment(repo: Path) -> dict[str, str]:
    allowed_names = {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
    }
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in allowed_names
    }
    environment["PYTHONPATH"] = str(repo)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    neutral_temp = repo.parent / "tmp"
    neutral_temp.mkdir(parents=True, exist_ok=True)
    environment["TEMP"] = str(neutral_temp)
    environment["TMP"] = str(neutral_temp)
    environment["TMPDIR"] = str(neutral_temp)
    return environment


def _process_group_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        subprocess.run(
            [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _parse_junit(xml_text: str) -> tuple[PytestNodeResult, ...]:
    if not xml_text:
        return ()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ()

    nodes: list[PytestNodeResult] = []
    for testcase in root.iter("testcase"):
        classname = testcase.attrib.get("classname", "")
        test_name = testcase.attrib.get("name", "unknown")
        node_id = f"{classname}::{test_name}" if classname else test_name
        duration = _float_or_zero(testcase.attrib.get("time"))
        failure = testcase.find("failure")
        error = testcase.find("error")
        skipped = testcase.find("skipped")
        if error is not None:
            outcome = "error"
            failure_kind = "infrastructure_or_test_error"
            message = _xml_message(error)
        elif failure is not None:
            message = _xml_message(failure)
            if _is_assertion_failure(message):
                outcome = "failed"
                failure_kind = "assertion_failure"
            else:
                outcome = "error"
                failure_kind = "test_exception"
        elif skipped is not None:
            outcome = "skipped"
            failure_kind = None
            message = _xml_message(skipped)
        else:
            outcome = "passed"
            failure_kind = None
            message = ""
        nodes.append(
            PytestNodeResult(
                node_id=node_id,
                test_name=test_name,
                outcome=outcome,
                failure_kind=failure_kind,
                message=message,
                duration_seconds=duration,
            )
        )
    return tuple(nodes)


def _xml_message(element: ET.Element) -> str:
    values = [element.attrib.get("message", ""), element.text or ""]
    return _tail("\n".join(value for value in values if value), limit=4000)


def _is_assertion_failure(message: str) -> bool:
    location_types = re.findall(
        r"(?m)^.*\.(?:py|pyw):\d+:\s+([A-Za-z_][\w.]*)", message
    )
    if location_types:
        return location_types[-1] in {"AssertionError", "Failed"}
    return bool(
        re.search(r"(?m)^(?:E\s+)?AssertionError(?::|$)", message)
        or re.search(r"(?m)^(?:E\s+)?Failed(?::|$)", message)
    )


def _read_junit(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return ""


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _tail(value: str, *, limit: int = 20_000) -> str:
    return value[-limit:]


def _float_or_zero(value: str | None) -> float:
    try:
        return float(value or 0.0)
    except ValueError:
        return 0.0
