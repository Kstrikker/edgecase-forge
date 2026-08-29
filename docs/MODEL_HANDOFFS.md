# Model handoff prompts

Copy only the relevant bounded task. Save every answer under `trajectories/reviews/` with the model name, date, input, output, and integration decision.

## Claude — baseline fairness review

> Review this frozen single-agent baseline for fairness. Identify anything that makes it artificially weak or accidentally includes a later specialized capability. Do not rewrite the system. Return: risks, required corrections, and final pass/fail.

## Gemini — blind adversarial review

> You are evaluating a FastAPI repository without access to the seeded mutant answer key. List likely business invariants and propose executable tests. Separate verified facts from hypotheses. Return JSON only in the supplied format.

## Grok — provider compatibility review

> Run the exact supplied provider contract. Report schema, tool-call, timeout, rate-limit, and response-normalization incompatibilities. Do not suggest architecture changes outside the adapter boundary.

## Copilot — bounded coding task

> Complete only the named function or test stub. Preserve public interfaces and existing tests. Do not add dependencies or refactor adjacent modules.

