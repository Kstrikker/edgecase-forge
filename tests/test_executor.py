from pathlib import Path

from edgecase_forge.baseline.executor import ExecutionResult, run_generated_pytest


def write_test(tmp_path: Path, source: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_generated.py"
    test_file.write_text(source, encoding="utf-8")
    return repo, test_file


def test_executor_uses_current_python_and_classifies_assertions(tmp_path: Path) -> None:
    repo, test_file = write_test(
        tmp_path,
        "def test_pass():\n    assert True\n\n"
        "def test_fail():\n    assert False\n",
    )
    result = run_generated_pytest(repo=repo, test_file=test_file)
    outcomes = {node.test_name: node for node in result.nodes}
    assert result.exit_code == 1
    assert result.harness_status == "complete"
    assert result.command[0]
    assert outcomes["test_pass"].outcome == "passed"
    assert outcomes["test_fail"].failure_kind == "assertion_failure"


def test_executor_rejects_runtime_exception_as_differential_failure(tmp_path: Path) -> None:
    repo, test_file = write_test(
        tmp_path,
        "def test_error():\n    raise ValueError('broken test')\n",
    )
    result = run_generated_pytest(repo=repo, test_file=test_file)
    assert result.exit_code == 1
    assert result.nodes[0].outcome == "error"
    assert result.nodes[0].failure_kind == "test_exception"
    assert result.nodes[0].eligible_for_differential is False


def test_runtime_exception_cannot_spoof_assertion_text(tmp_path: Path) -> None:
    repo, test_file = write_test(
        tmp_path,
        "def test_error():\n    raise ValueError('AssertionError')\n",
    )
    result = run_generated_pytest(repo=repo, test_file=test_file)
    assert result.nodes[0].failure_kind == "test_exception"
    assert result.nodes[0].eligible_for_differential is False


def test_pytest_fail_is_an_assertion_failure(tmp_path: Path) -> None:
    repo, test_file = write_test(
        tmp_path,
        "import pytest\n\ndef test_fail():\n    pytest.fail('contract violated')\n",
    )
    result = run_generated_pytest(repo=repo, test_file=test_file)
    assert result.nodes[0].failure_kind == "assertion_failure"


def test_executor_marks_collection_failure_invalid(tmp_path: Path) -> None:
    repo, test_file = write_test(tmp_path, "this is invalid python !!!\n")
    result = run_generated_pytest(repo=repo, test_file=test_file)
    assert result.exit_code == 2
    assert result.harness_status == "interrupted"
    assert result.valid_test_run is False
    assert result.invalid_generated_test is True
    assert result.evaluator_infrastructure_error is False


def test_executor_timeout_is_unscoreable(tmp_path: Path) -> None:
    repo, test_file = write_test(
        tmp_path,
        "import time\n\ndef test_slow():\n    time.sleep(5)\n",
    )
    result = run_generated_pytest(
        repo=repo, test_file=test_file, timeout_seconds=1
    )
    assert result.timed_out is True
    assert result.harness_status == "timeout"
    assert result.scoreable_harness is False
    assert result.invalid_generated_test is True
    assert result.evaluator_infrastructure_error is False


def test_executor_preserves_unicode_output(tmp_path: Path) -> None:
    repo, test_file = write_test(
        tmp_path,
        "def test_unicode():\n    print('evidence ✓')\n    assert False\n",
    )
    result = run_generated_pytest(repo=repo, test_file=test_file)
    assert "✓" in result.stdout


def test_executor_distinguishes_evaluator_failure_from_agent_miss() -> None:
    result = ExecutionResult(
        executed=True,
        exit_code=3,
        stdout="",
        stderr="pytest internal error",
    )
    assert result.harness_status == "internal_error"
    assert result.evaluator_infrastructure_error is True
    assert result.invalid_generated_test is False
