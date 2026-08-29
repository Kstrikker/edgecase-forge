from __future__ import annotations

from pathlib import Path

import typer

from edgecase_forge.baseline import BaselineScanner
from edgecase_forge.benchmark import run_flashcart_suite
from edgecase_forge.llm.registry import PROVIDERS, build_provider

app = typer.Typer(no_args_is_help=True, help="Evidence-first adversarial API testing")


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
    resume: Path | None = typer.Option(
        None,
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Existing interrupted suite directory to resume.",
    ),
) -> None:
    """Run baseline-v0 across the frozen FlashCart suite."""
    suite_dir = run_flashcart_suite(
        provider=build_provider(provider, model),
        output_root=output,
        repetitions=repetitions,
        request_delay_seconds=request_delay,
        resume_dir=resume,
    )
    typer.echo(f"Benchmark suite saved: {suite_dir}")


if __name__ == "__main__":
    app()
