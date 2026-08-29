# EdgeCase Forge

EdgeCase Forge is an evidence-first AI QA agent for compatible FastAPI repositories. It inspects a repository, proposes adversarial tests, executes generated pytest tests against trusted benchmark fixtures, and records reproducible evidence.

## Current milestone: baseline

The current implementation is intentionally simple: one frozen prompt, one model, ordinary repository context, local Pydantic validation, and one optional pytest execution step. It excludes the specialized contract mapper, concurrency attacker, replay tools, database inspector, and independent verifier planned for later iterations.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev,benchmark]"
edgecase-forge providers
edgecase-forge baseline-scan --repo ./path/to/trusted/repository --provider mock
pytest
```

Use `--provider gemini` with `GEMINI_API_KEY`, or `--provider grok` with `XAI_API_KEY`. The mock provider is deterministic and requires no network or key.

Generated tests are code. Baseline execution is disabled unless `--execute` is supplied, and should only be used with trusted benchmark repositories. Docker isolation is a later iteration.

Project decisions and progress live in [docs/WORKFLOW.md](docs/WORKFLOW.md).
