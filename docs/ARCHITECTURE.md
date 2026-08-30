# EdgeCase Forge architecture

## Runtime connection

```text
CLI
 ├─ BaselineScanner (frozen control)
 ├─ ContractScanner (Iteration 1)
 └─ StatefulScanner (Iterations 2–3)
     ├─ Repository collector (read-only, secret-aware)
     ├─ Deterministic AST contract mapper
     │   ├─ Routes and reachable handlers
     │   ├─ Guards and resource ownership
     │   ├─ Shared-state reads/writes
     │   └─ External effects and retry identities
     ├─ Stateful attack-plan builder
     ├─ Plan-specific response validator
     │   └─ Exact-error bounded semantic repair
     ├─ Frozen baseline prompt
     ├─ LLMProvider protocol
     │   ├─ MockProvider
     │   └─ OpenAICompatibleProvider
     │       ├─ Gemini profile
     │       ├─ Grok profile
     │       └─ OpenAI profile
     ├─ Local Pydantic validation + one semantic repair
     ├─ Optional trusted-repository pytest execution
     └─ Report, metadata, trajectory and execution log
```

The benchmark evaluator sits outside this runtime. It gives the agent an opaque repository, then independently runs the generated tests against clean and mutant builds. A candidate requires the same named node to pass clean, fail by assertion on the mutant and map to a reported finding. This prevents the model from seeing the answer key and prevents prose-only or broken-test claims from earning credit.

## Provider boundary

The core depends only on `LLMProvider.generate_json(messages, response_model)`. Provider profiles configure base URL, key environment variable, locked model and optional reasoning effort. Schema-capable providers receive a normalized, flat strict JSON Schema without references or unions; every response is still parsed by the standard JSON decoder and validated locally with Pydantic. Finish reasons are retained so length-limited output can receive one concise repair and remain distinguishable from malformed JSON.

Provider capabilities are explicit. Unsupported strict schema or tool behavior must fail locally rather than silently degrading or producing provider-specific baseline behavior.

## Security boundary

- Repository collection excludes common secrets, virtual environments, Git data, evaluator oracles and solution directories.
- API keys are read from environment variables and never enter request trajectories.
- Generated test code is written beneath the run artifact directory.
- Test execution requires an explicit flag and is currently restricted to trusted fixtures.
- Official benchmark execution uses a networkless Docker container with read-only source, bounded resources and dropped capabilities. Production-source write protection remains required before arbitrary repositories are supported.

## Artifact contract

Every run writes:

```text
results/baseline/<run-id>/
├── generated_tests/
├── report.json
├── run-metadata.json
├── trajectory.jsonl
└── execution.log
```

Contract runs additionally write `repository-map.json`; `report.json` contains the model-derived invariants and the map hash. The mapper never imports or executes repository code. Route source files are prioritized within the same bounded context budget used by the baseline collector. Deterministic high-risk flows are ranked before model analysis, and every priority includes the concrete business oracle that generated code must execute before secondary HTTP assertions.

Stateful runs add `attack-plan.json`. Plan-specific Pydantic validation inspects the generated pytest AST before it is accepted. A retry-side-effect test must issue two requests, contain a provider-ledger assertion, and execute that assertion before checking the retry response status. A numeric-boundary test must exercise zero and a negative value, assert HTTP 422 for both responses, and prove unchanged stock plus empty order and charge ledgers. Invalid evidence enters the existing one-repair provider loop with the concrete parser error.

Benchmark case runs also write `differential/clean` and `differential/mutant` evidence directories containing `execution.json`, `junit.xml`, `stdout.log` and `stderr.log`, plus one atomic `differential.json` classification manifest.

The dashboard will consume these files later. It will not invent a separate evidence format.
