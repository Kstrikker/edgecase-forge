# EdgeCase Forge — Living Workflow

Last updated: 2026-08-29

## Winning claim

EdgeCase Forge improves bug discovery over a generic coding agent by combining business-invariant mapping, stateful adversarial tools, and executable verification. Every improvement is measured against the same frozen benchmark.

## Status board

| Stage | Status | Exit criterion |
|---|---|---|
| Benchmark contract | Complete | FlashCart v1 frozen: clean control, 10 opaque mutants, hashes and 20 oracle checks |
| Baseline | In progress | Full mock suite passes; locked live-model runs and adjudication pending |
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
- Generated tests execute only with explicit consent and only against trusted fixtures until Docker isolation lands.

## Checkpoint log

### Baseline foundation — complete

- Provider-neutral Gemini/Grok/OpenAI-compatible boundary implemented.
- Portable JSON-object validation and exact-error repair implemented.
- Frozen `baseline-v0` prompt, repository collector, report and trajectory writer implemented.
- External mutation-scoring contract implemented.
- Clean/mutant stock-race smoke fixtures reproduce the expected difference.
- Automated verification: 11 tests passing.

### Next checkpoint — FlashCart benchmark

- FlashCart service, private oracle and ten isolated transformations completed.
- All ten invariants pass on clean; each mutant fails its target oracle.
- Neutral export removes evaluator hooks and case identifiers.
- Variant hashes are frozen in `expected_hashes.json`.
- Next: run `baseline-v0` with one locked Gemini model three times per case.
- Freeze and adjudicate raw evidence before Iteration 1 begins.
