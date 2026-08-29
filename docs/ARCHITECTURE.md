# Baseline architecture

## Runtime connection

```text
CLI
 └─ BaselineScanner
     ├─ Repository collector (read-only, secret-aware)
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

The core depends only on `LLMProvider.generate_json(messages, response_model)`. Provider profiles configure base URL, key environment variable and locked model. Baseline requests portable JSON-object output and validates locally instead of sending a complex provider-specific JSON Schema.

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

Benchmark case runs also write `differential/clean` and `differential/mutant` evidence directories containing `execution.json`, `junit.xml`, `stdout.log` and `stderr.log`, plus one atomic `differential.json` classification manifest.

The dashboard will consume these files later. It will not invent a separate evidence format.
