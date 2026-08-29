# Changelog

## Unreleased

### Differential evaluator v1

- Score generated pytest nodes independently instead of treating any nonzero module exit as a mutant kill.
- Require a named test to pass clean, fail by assertion on the mutant and map to a reported finding.
- Persist JUnit XML, complete stdout/stderr, execution metadata, test hashes and clean/mutant repository hashes.
- Reject timeouts, collection errors, runtime exceptions, missing nodes, unclaimed failures and modified inputs as kills.
- Aggregate token, latency and attempt counts across semantic repair calls.
- Freeze prompt, schema, harness, oracle, mutation, source, dependency and Git fingerprints for new and resumed suites.
- Add repeatable `--case` options for inexpensive pilot subsets.

### Restricted execution v1

- Add a Docker runner with network disabled, read-only source mounts, dropped capabilities and bounded CPU, memory and process count.
- Block Docker-backed benchmark runs until Docker Desktop and the pinned runner image are available.
- Preserve the local backend for trusted, API-free rehearsal and unit tests.
- Harden the runner image by moving to the minimal Alpine Python base, avoiding Debian Perl runtime packages.

### FlashCart v1.1.0 integrity rebuild

- Replaced the clean checkout flow with an explicit payment state machine and durable inventory reservation.
- Kept the module-level state object stable across resets so imported test references remain valid.
- Made timeout retries reuse one order, reservation and payment operation.
- Stopped missing-order webhooks from consuming their event IDs and prevented terminal-state regression.
- Rebuilt all ten mutants as isolated, single-invariant faults.
- Added a 100-cell cross-oracle matrix plus clean regression tests; 115 FlashCart checks now pass.
- Invalidated v1.0.x benchmark runs as development evidence; they must not be included in the final score.

### Baseline compatibility hardening

- Accept a single evidence string and normalize it to a one-item list.
- Parse the first complete JSON object when a provider appends commentary.
- Record an unrepaired model-output error as a failed case instead of aborting the suite.
- Preserve bounded semantic repair at one attempt.

### FlashCart v1.0.1

- Increased the M02 duplicate-request race window from 20 ms to 100 ms.
- Repeated M01 and M02 concurrency oracles up to three times to reduce scheduler-dependent false negatives.
- Updated the frozen M02 source hash.
- Version was updated before any official baseline mutation score was accepted.
