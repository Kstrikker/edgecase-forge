# EdgeCase Forge

EdgeCase Forge is an evidence-first AI QA agent for compatible FastAPI repositories. It inspects a repository, proposes adversarial tests, executes generated pytest tests against trusted benchmark fixtures, and records reproducible evidence.

## Current milestone: Iteration 1 contract mapper

The frozen baseline remains available for comparison. Iteration 1 adds a deterministic, read-only Python AST mapper that discovers FastAPI routes, reachable handlers, guards, shared-state transitions, external effects and risk signals. One model call receives that map plus prioritized source and must link every finding and generated test to an explicit invariant.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev,benchmark]"
edgecase-forge providers
edgecase-forge baseline-scan --repo ./path/to/trusted/repository --provider mock
edgecase-forge contract-scan --repo ./path/to/trusted/repository --provider mock
edgecase-forge docker-smoke
edgecase-forge benchmark-run --provider mock
pytest
```

Use `--provider gemini` with `GEMINI_API_KEY`, or `--provider grok` with `XAI_API_KEY`. The mock provider is deterministic and requires no network or key.

Generated tests are code. Generic baseline execution is disabled unless `--execute` is supplied. Official benchmark runs use the restricted Docker backend; local execution is only for trusted rehearsal.

Project decisions and progress live in [docs/WORKFLOW.md](docs/WORKFLOW.md).

The frozen FlashCart benchmark contains one clean control and ten isolated mutants. `benchmark-run` exports one neutral case at a time, runs the frozen baseline, and records node-level clean-versus-mutant evidence. Candidate kills require independent invariant adjudication before they count toward the final mutation score.

Select the agent explicitly for measured comparisons:

```bash
edgecase-forge benchmark-run --agent baseline --provider mock --case C00
edgecase-forge benchmark-run --agent contract --provider mock --case C00
```

Contract runs add `repository-map.json` and an `invariants` section to each report. High-risk flows such as volatile external-effect identities and client-controlled monetary totals become ranked priority targets with required executable oracles. Agent name, version and prompt hash are included in the frozen suite fingerprint, so a baseline suite cannot be resumed as an Iteration 1 suite.

For a low-cost rehearsal, select individual cases by repeating `--case`, for example `--case C00 --case M01`. A subset run is always marked ineligible for an official score.

Official baseline configuration (run only after the restricted-execution preflight is complete):

```bash
edgecase-forge benchmark-run \
  --provider gemini \
  --model gemini-3.5-flash \
  --repetitions 3 \
  --request-delay 5 \
  --output results/baseline-official
```

Docker Desktop must be running. The runner uses `--network none`, a read-only repository mount, dropped capabilities, and CPU/memory/process limits. Use `--execution-backend local` only for a fast local rehearsal.

If a rate limit interrupts the suite, rerun the identical command with `--resume <suite-directory>`. Completed cases are not called again. API keys are removed from the environment before generated pytest code executes.
