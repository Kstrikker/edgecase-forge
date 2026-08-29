from pathlib import Path
from types import SimpleNamespace

from edgecase_forge.baseline import restricted


def test_docker_available_requires_successful_server_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        restricted.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="27.0\n"),
    )
    assert restricted.docker_available() is True


def test_restricted_runner_applies_container_boundaries(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    test_file = repo / "test_generated.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    captured: dict = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            captured["timeout"] = timeout
            return "output", ""

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(restricted.subprocess, "Popen", fake_popen)
    result = restricted.run_restricted_pytest(
        repo=repo, test_file=test_file, timeout_seconds=7, image="test-image"
    )

    command = list(captured["command"])
    assert result.executed is True
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "--memory" in command and "512m" in command
    assert "--cpus" in command and "1.0" in command
    assert captured["timeout"] == 7
    assert captured["kwargs"]["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
