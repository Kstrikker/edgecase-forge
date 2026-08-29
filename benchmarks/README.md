# FlashCart benchmark v1

This directory is evaluator infrastructure and must never be mounted into the repository shown to the agent.

The frozen target is one clean FastAPI service and ten opaque, single-fault mutants. Every generated test is evaluated against both the clean service and the selected mutant. A mutant is killed only when the test passes on clean, fails on the mutant, and demonstrates the intended invariant violation.

The initial stock is 5 and catalog price is INR 1000. Seed identities are two buyers and one admin. The external harness resets state; no public reset endpoint is part of the application contract.

`manifest.json` is the private answer key. Agent-visible checkouts must exclude this directory, `.git`, solution tests, mutation patches, and defect-revealing names.

