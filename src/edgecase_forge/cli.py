from __future__ import annotations

import json
import tempfile
from pathlib import Path

import typer

from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.baseline.executor import execution_payload
from edgecase_forge.baseline.restricted import ensure_runner_image, run_restricted_pytest
from edgecase_forge.benchmark import run_flashcart_suite
from benchmarks.flashcart import export_agent_repo
from edgecase_forge.llm.registry import PROVIDERS, build_provider

app = typer.Typer(no_args_is_help=True, help="Evidence-first adversarial API testing")


@app.command("docker-smoke")
def docker_smoke() -> None:
    """Run a disposable pytest through the restricted Docker backend."""
    ensure_runner_image()
    with tempfile.TemporaryDirectory(prefix="edgecase-docker-smoke-") as temporary:
        root = Path(temporary)
        repo = export_agent_repo("C00", root / "repo")
        test_file = repo / "test_generated.py"
        test_file.write_text(
            "import socket\n"
            "from pathlib import Path\n\n"
            "def test_read_only_repo_and_network_boundary():\n"
            "    assert Path('main.py').exists()\n"
            "    probe = socket.socket()\n"
            "    probe.settimeout(0.2)\n"
            "    try:\n"
            "        probe.connect(('example.com', 80))\n"
            "    except OSError:\n"
            "        return\n"
            "    finally:\n"
            "        probe.close()\n"
            "    raise AssertionError('network unexpectedly reachable')\n",
            encoding="utf-8",
        )
        result = run_restricted_pytest(
            repo=repo,
            test_file=test_file,
            junit_path=root / "artifacts" / "junit.xml",
        )
        typer.echo(json.dumps(execution_payload(result), indent=2))
        if not result.scoreable_harness or not result.nodes or any(
            node.outcome != "passed" for node in result.nodes
        ):
            raise typer.Exit(code=1)


@app.command("providers")
def providers() -> None:
    """List configured provider profiles."""
    typer.echo("mock\tAPI-free deterministic plumbing test")
    for name, profile in PROVIDERS.items():
        typer.echo(f"{name}\tdefault={profile['default_model']}\tkey={profile['api_key_env']}")


@app.command("baseline-scan")
def baseline_scan(
    repo: Path = typer.Option(..., exists=True, file_okay=False, resolve_path=True),
    provider: str = typer.Option("mock"),
    model: str | None = typer.Option(None),
    output: Path = typer.Option(Path("results/baseline")),
    case_id: str = typer.Option("local-case"),
    execute: bool = typer.Option(
        False,
        help="Execute generated code. Use only with trusted benchmark repositories.",
    ),
) -> None:
    """Run the frozen generic baseline agent."""
    scanner = BaselineScanner(build_provider(provider, model))
    run_dir = scanner.scan(
        repo=repo,
        output_root=output,
        case_id=case_id,
        execute=execute,
    )
    typer.echo(f"Baseline run saved: {run_dir}")


@app.command("benchmark-run")
def benchmark_run(
    provider: str = typer.Option("mock"),
    model: str | None = typer.Option(None),
    output: Path = typer.Option(Path("results/benchmark")),
    repetitions: int = typer.Option(1, min=1, max=10),
    request_delay: float = typer.Option(0.0, min=0.0),
    case: list[str] | None = typer.Option(
        None,
        "--case",
        help="Run only selected case IDs. Repeat the option for a pilot subset.",
    ),
    resume: Path | None = typer.Option(
        None,
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Existing interrupted suite directory to resume.",
    ),
    execution_backend: str = typer.Option(
        "docker",
        "--execution-backend",
        help="Docker for official runs; local is for trusted rehearsal only.",
    ),
) -> None:
    """Run baseline-v1.0 across the frozen FlashCart suite."""
    suite_dir = run_flashcart_suite(
        provider=build_provider(provider, model),
        output_root=output,
        repetitions=repetitions,
        request_delay_seconds=request_delay,
        resume_dir=resume,
        case_ids=case,
        execution_backend=execution_backend,
    )
    typer.echo(f"Benchmark suite saved: {suite_dir}")


if __name__ == "__main__":
    app()
