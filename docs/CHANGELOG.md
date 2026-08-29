# Changelog

## Unreleased

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
