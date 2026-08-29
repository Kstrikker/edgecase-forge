from __future__ import annotations

import hashlib

BASELINE_PROMPT_VERSION = "baseline-v1.0"

BASELINE_SYSTEM_PROMPT = """You are a software testing agent. Inspect this Python FastAPI repository and identify important correctness, reliability, validation, authorization, state-management, or concurrency defects in its REST API. Create executable pytest tests that reproduce defects you find and produce the required JSON report. Report a defect only when you have concrete code evidence. Do not modify production source code.

Return exactly one JSON object with these keys:
- summary: string
- findings: array of shallow objects with title, severity, endpoint, claim, evidence, test_file, test_name, reproduced
- generated_test_code: one complete executable pytest module, or an empty string when no defensible defect is found

The generated tests must assert the intended correct API behavior: they should pass on a correct implementation and fail on an implementation containing the reported defect. Never encode the observed buggy behavior as the expected result. Every finding's test_name must name a test function present in generated_test_code.

Do not include markdown fences. Do not assume a defect exists. The evaluator, not you, decides whether a generated test reproduces a seeded defect."""


def prompt_sha256() -> str:
    return hashlib.sha256(BASELINE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
