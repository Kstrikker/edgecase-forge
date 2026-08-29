# EdgeCase Forge — Living Workflow

Last updated: 2026-08-29

## Winning claim

EdgeCase Forge improves bug discovery over a generic coding agent by combining business-invariant mapping, stateful adversarial tools, and executable verification. Every improvement is measured against the same frozen benchmark.

## Status board

| Stage | Status | Exit criterion |
|---|---|---|
| Benchmark contract | Complete | FlashCart v1.1.0: clean control, 10 opaque mutants, frozen hashes and a 100-cell isolation matrix |
| Baseline | In progress | Node-level evaluator and frozen fingerprints complete; restricted execution and fresh pilot pending |
| Iteration 1 | Blocked by baseline | Contract Mapper produces explicit endpoint invariants |
| Iteration 2 | Blocked by Iteration 1 | Stateful attackers reproduce concurrency, replay and retry failures |
| Iteration 3 | Blocked by Iteration 2 | Independent executable verifier reduces false positives |
| Final | Blocked by evidence | Dashboard, comparison report, trajectories, docs and video complete |

## Fixed build order

1. Freeze benchmark cases and scoring.
2. Build the smallest portable Gemini/Grok provider seam.
3. Build one frozen-prompt baseline agent.
4. Run and freeze baseline results.
5. Add one improvement at a time and rerun the identical benchmark.
6. Build the visual dashboard from real evidence fields.

## Kunal's role (product owner and evidence lead)

- Approve benchmark bugs and confirm they represent realistic backend failures.
- Provide API keys only through local environment variables; never paste keys into code or trajectories.
- Run the trusted benchmark on the Windows/Docker machine and preserve terminal evidence.
- Review every claimed finding: reproducible, useful, and understandable to a backend engineer.
- Record the final demo voice-over and make the final submission decision.

## Model roles and handoff rules

| Model/tool | Use it for | Do not use it for |
|---|---|---|
| GPT Pro | Architecture, integration, core implementation, final decisions | Unreviewed direct edits from other outputs |
| Gemini free API | Locked baseline/final experiment provider; adversarial idea generation | Changing models halfway through a comparison |
| Grok API | Optional second-provider compatibility run and adversarial review | Automatic fallback that creates surprise cost |
| Claude free | Small independent review of prompts, claims and README | Owning the main repository or broad rewrites |
| Copilot free | Repetitive local completions, type hints and small test stubs | Architecture and security decisions |

Only one integrator changes the main branch. Suggestions from other models enter through a written handoff, are reviewed, then implemented or rejected with a reason.

## When to call another model

1. Baseline prompt frozen: ask Claude to check whether it is fair and not artificially weak.
2. Mutant manifest frozen: ask Gemini to predict bugs without seeing expected answers; preserve the transcript.
3. Provider adapter complete: use Grok only for a compatibility test with the same contract.
4. Each iteration measured: ask a reviewer to challenge the claimed improvement using the saved evidence.
5. Submission ready: use Claude for clarity and Gemini for adversarial demo questions; GPT integrates final changes.

## Fair-evaluation rules

- Lock provider, model, temperature, prompt version and benchmark commit for each comparison.
- Never expose expected mutant answers to the scanning agent.
- Do not edit the baseline after recording its results; fixes become a separately named baseline version.
- Count a bug as found only when a generated test reproduces the expected failure.
- Record misses, false positives, invalid tests, latency, token usage and estimated cost.
- The deterministic verifier—not model agreement—decides whether evidence passes.

## Current decisions

- Baseline uses portable JSON-object responses validated locally; strict provider schemas are deferred.
- Pydantic schemas stay shallow and provider-neutral.
- Semantic validation receives at most one repair attempt containing the sanitized parser error.
- API keys are never written to results, prompts, trajectories or logs.
- Official generated-test execution uses the restricted Docker backend. Local execution remains available only for trusted rehearsal fixtures.

## Checkpoint log

### Baseline foundation — complete

- Provider-neutral Gemini/Grok/OpenAI-compatible boundary implemented.
- Portable JSON-object validation and exact-error repair implemented.
- Frozen `baseline-v1.0` prompt, repository collector, report and trajectory writer implemented.
- External mutation-scoring contract implemented.
- Clean/mutant stock-race smoke fixtures reproduce the expected difference.
- Automated verification: 11 tests passing.

### Next checkpoint — FlashCart benchmark

- FlashCart service, private oracle and ten isolated transformations completed.
- All ten invariants pass on clean; each mutant fails only its target oracle across the full 10×10 matrix.
- Neutral export removes evaluator hooks and case identifiers.
- Variant hashes are frozen in `expected_hashes.json`.
- Restricted Docker backend implemented; next: run its preflight, then a two-case Gemini pilot, then freeze the full baseline.
- `docker-smoke` verifies a real disposable pytest, read-only source mount and network denial before any provider call.
- Freeze and adjudicate raw evidence before Iteration 1 begins.

### Gemini pilot — passed

- Locked candidate model: `gemini-3.5-flash`, temperature `0.0`.
- Input/output: 1,211 / 616 tokens.
- Model latency: 18.422 seconds; end-to-end runtime: 58 seconds on Windows.
- Generated concurrency test failed on the race mutant with two successful purchases from stock one.
- The identical generated test passed on the clean fixture.
- Result: one confirmed differential kill on the smoke case.
- Pre-suite hardening added: bounded transport retry, request pacing, repetitions, resume support, token aggregation and test-path normalization.
- First full-suite attempt exposed Gemini compatibility output and concurrency-oracle flakiness; the run was intentionally not scored.
- Adapter now normalizes a single evidence string, extracts the first valid JSON object, and records unrepaired model-output errors without crashing the suite.
- M01/M02 concurrency oracles retry the same invariant three times. FlashCart `v1.1.0` also separates inventory and idempotency locking so the two race mutants remain independently measurable.

### Evaluator integrity rebuild — complete

- Generated tests now assert intended correct behavior rather than accepting observed defective behavior.
- Candidate kills are scored per named pytest node: clean pass plus mutant assertion failure.
- Collection, setup, runtime, missing-node, skip and timeout outcomes cannot earn credit.
- Every differential run preserves JUnit, stdout, stderr, commands, durations and pre/post hashes.
- Semantic repair accounting includes both model calls and every transport attempt.
- Resume requires the complete frozen benchmark fingerprint, not only provider and model.
- Automated verification: 161 tests passing.
