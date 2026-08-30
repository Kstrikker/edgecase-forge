# EdgeCase Forge — Living Workflow

Last updated: 2026-08-29

## Winning claim

EdgeCase Forge improves bug discovery over a generic coding agent by combining business-invariant mapping, stateful adversarial tools, and executable verification. Every improvement is measured against the same frozen benchmark.

## Status board

| Stage | Status | Exit criterion |
|---|---|---|
| Benchmark contract | Complete | FlashCart v1.1.0: clean control, 10 opaque mutants, frozen hashes and a 100-cell isolation matrix |
| Baseline | Complete | Official run adjudicated: 8/10 confirmed kills, 80% mutation score, zero blockers |
| Iteration 1 | Complete | Contract v1.1 adds one confirmed M10 kill; projected full-suite score 90% |
| Iteration 2 | Complete | Stateful v1.0 achieved 9/10 confirmed kills, 90% mutation score and zero blockers |
| Iteration 3 | Ready for pilot | Stateful v1.1 adds deterministic zero/negative boundary attacks with state-preservation proof |
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
- Frozen `baseline-v1.2` prompt, repository collector, report and trajectory writer implemented.
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

### Official baseline — complete

- One full 11-case Gemini run completed with no model-output or infrastructure errors.
- Nine candidate kills were independently reviewed against frozen invariants.
- Eight were confirmed; M08 was rejected because its test did not observe provider charge count.
- Confirmed mutation score: 80%; official score blockers: none.
- The immutable adjudication overlay preserves all raw evidence hashes.

### Iteration 1 contract mapper — ready for pilot

- A deterministic AST mapper discovers FastAPI routes and reachable local handlers without executing repository code.
- The map surfaces guards, state reads/writes, external effects, retry identity and high-value risk signals.
- Route-bearing files are prioritized within a fixed repository-context budget.
- Every generated finding must reference an explicit invariant and an actual generated pytest function.
- Side-effect tests are instructed to inspect ledgers, counts, amounts or final state rather than infer impact from HTTP status.
- Agent name, version and prompt hash are frozen into every suite fingerprint.
- First measurement target: M08 and M10 only; proceed to all 11 cases only if the pilot evidence is valid.

### Iteration 1 first pilot — reviewed

- C00 produced no finding and its generated behavioral test passed.
- M08 became a candidate, but strict review rejected it because the mutant failed on a retry-status assertion before reaching the charge-count oracle.
- M10's deterministic map correctly emitted `client_input_in_authoritative_total`, but the model selected an unrelated pending-cancellation behavior that survived both implementations.
- No invalid tests, model-output errors or evaluator infrastructure errors occurred.
- Contract v1.1 now converts volatile effect identities and client-controlled monetary totals into ranked mandatory targets.
- Required business-oracle assertions must execute before secondary response-status assertions.
- The first pilot remains preserved and is not retroactively rescored.

### Iteration 1 v1.1 pilot — complete

- C00 remained clean with no reported finding.
- M10 passed clean and first failed on the authoritative order-total assertion; it is confirmed.
- M08 remained rejected because the retry-status assertion failed before its charge-ledger assertion executed.
- The adjudicated subset score is 1/2; `subset_selection` correctly prevents official-score eligibility.
- No model-output, invalid-test, integrity or evaluator-infrastructure errors occurred.

### Iteration 2 stateful attacker — ready for pilot

- Deterministic attack plans encode stimulus order and the primary business oracle.
- Retry tests must issue two HTTP calls and assert an observable provider ledger/effect count.
- Generated pytest AST validation rejects retry-status assertions that mask the primary ledger oracle.
- The exact ordering error is passed into the existing single semantic repair attempt.
- Stateful artifacts and agent identity are independently frozen for fair comparison.
