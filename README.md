# EdgeCase Forge

**Evidence-first adversarial API testing for stateful failures that ordinary tests miss.**

[Live Evidence Dashboard](https://edgecase-forge-dashboard.kthakur1221.chatgpt.site) · [Source Repository](https://github.com/Kstrikker/edgecase-forge)

EdgeCase Forge analyzes a Python API repository, maps business invariants, generates adversarial pytest witnesses, executes them inside a restricted Docker sandbox, and produces portable evidence artifacts. Its focus is not simply finding suspicious code: it proves observable failures such as race-condition overselling, broken idempotency, replayable webhooks, duplicate charges, and inventory/payment desynchronization.

### The problem

Traditional unit tests usually validate one request at a time. Production failures often happen across sequences:

- two buyers race for the final item;
- a timed-out payment is retried;
- the same webhook is delivered twice;
- a cancellation endpoint is replayed;
- a user accesses another user's order;
- a client-controlled price crosses a trust boundary.

These defects are difficult to detect because the code can look correct locally while the system-level invariant is violated.

### The solution

EdgeCase Forge turns repository analysis into evidence:

1. **Contract mapping** identifies endpoints, state transitions, trust boundaries, and business invariants.
2. **Stateful attack planning** converts an invariant into concurrent, retry, replay, or authorization sequences.
3. **Test generation** produces a linked pytest witness with a clear expected outcome.
4. **Restricted execution** runs generated tests with Docker limits, no network access, a read-only repository mount, dropped capabilities, and bounded CPU, memory, processes, and time.
5. **Differential verification** compares clean and mutated behavior at the individual pytest-node level.
6. **Independent adjudication** confirms only evidence that passes the clean implementation and fails the matching mutant for the expected invariant.
7. **Evidence visualization** validates the exported JSON locally in the browser and explains the attack, test witness, state difference, and adjudication status.

### Verified result

The frozen FlashCart v1.1.0 benchmark contains one canonical control and ten seeded mutants.

| Metric | Verified result |
| --- | ---: |
| Confirmed mutation score | **0.90** |
| Confirmed kills | **9/10** |
| Clean false positives | **0** |
| Model-output errors | **0** |
| Infrastructure errors | **0** |
| Input tokens | 54,955 |
| Output tokens | 8,403 |
| End-to-end runtime | 664.686 seconds |
| Container test execution | 50.766 seconds |

Official run: `20260830T114241Z` using `gemini-3.5-flash`. The artifact is independently adjudicated, has no official-score blockers, and leaves M06 as the sole survived mutant.

### Measured improvement over the baseline

The comparison below separates adjudicated score from diagnostic evidence. The baseline's frozen run produced an official confirmed score of 0.80 after adjudication; its pre-adjudication summary also recorded two clean assertion-failure nodes. The final run raised the confirmed score while eliminating clean false positives.

| Metric | Single-pass baseline | EdgeCase Forge final | Measured change |
| --- | ---: | ---: | ---: |
| Confirmed mutation score | 0.80 | **0.90** | **+0.10 points / 12.5% relative** |
| Confirmed mutant kills | 8/10 | **9/10** | **+1 confirmed kill** |
| Clean assertion-failure nodes | 2 | **0** | **2 eliminated** |
| Evidence boundary | Host-dependent generation/execution | **Restricted Docker + node-level differential evidence** | Stronger reproducibility and isolation |

This comparison does not relabel clean assertion failures as unique findings: multiple failed nodes can originate from one generated test file. Raw suite artifacts and adjudication overlays remain the source of truth.

### Improvement Changelog

Every score below is labeled as either a full-suite adjudicated result or a diagnostic subset result. Subset scores are experiments, not substitutes for the official full-suite comparison.

| Stage | What we tried and why | Evidence | Decision / learning |
| --- | --- | --- | --- |
| Baseline | Used one general-purpose, single-pass repository agent to generate pytest witnesses. This established the simplest reasonable approach on the full frozen 11-case suite. | After adjudication: **8/10 confirmed kills (0.80)**. The pre-adjudication summary recorded **2 clean assertion-failure nodes**. | Kept as the fair baseline. Plausible test generation alone was not a sufficient evidence boundary. |
| Iteration 1 - Contract Mapper v1.0 | Added explicit endpoint, trust-boundary, and invariant mapping before test generation to reduce unsupported bug claims. | Diagnostic subset C00/M08/M10: **1/2 mutant candidate kills**, C00 passed, **0 clean assertion-failure nodes**. | Kept the contract stage; it removed the clean-control regression, but initially missed price integrity in M10. |
| Iteration 2 - Contract Mapper v1.1 | Tightened the invariant-to-test contract and node-level evidence mapping to cover external side effects and price trust boundaries. | Same diagnostic subset: **2/2 mutant candidate kills**, C00 passed, **0 clean assertion-failure nodes**. | Kept. On the same subset, M10 moved from survived to candidate kill without introducing a clean failure. |
| Iteration 3 - Stateful Attacker v1.0 | Added ordered attack plans for retries, replay windows, and ledger transitions rather than generating a single isolated request. | Diagnostic C00/M08 subset: M08 candidate kill, C00 passed, **0 clean assertion-failure nodes**. | Kept. M08 became the flagship example because the witness checks charge-ledger state, not only HTTP status. |
| Removed experiment - targeted Stateful v1.1 | Tried a narrow quantity-boundary specialization to capture the remaining M06 survivor. | Diagnostic C00/M06 subset: **0 candidate kills**; C00 produced **1 clean assertion-failure node** and M06 ended in a **model-output error**. | **Removed.** Chasing one benchmark survivor with special-case prompting reduced general reliability. A truthful 0.90 with a clean control was stronger than a brittle attempt at 1.00. |
| Final | Combined contract mapping, stateful planning, restricted Docker execution, pytest-node differential evidence, and independent invariant adjudication. | Full frozen suite: **9/10 confirmed kills (0.90)**, **0 clean false positives**, **0 model-output errors**, no official-score blockers. | Locked as the final workflow. The main contribution was executable clean-pass/mutant-fail evidence with state-aware adjudication. |

### What existed before the competition

The task domain, standard Python/FastAPI/pytest/Docker components, and third-party model APIs existed beforehand. During the challenge, we built the EdgeCase Forge orchestration, provider capability profiles, flat validated response contracts, invariant-linked scanners, restricted execution backend, frozen mutation benchmark, node-level differential evidence, adjudication overlay, artifact format, and interactive evidence dashboard. All submitted benchmark data is synthetic.

### Key engineering insight and hot take

> **Failure mode:** A single-pass agent often anchors on an HTTP response code and stops. Stateful defects live underneath that response—in inventory, payment, idempotency, ownership, and replay ledgers across multiple requests.
>
> **Hot take:** **Agent consensus is not verification.** Multiple models can agree on the same plausible but incorrect claim. A reliability agent earns trust only when its executable witness passes the clean reference, fails the changed implementation for the expected invariant, and preserves the resulting state evidence for independent adjudication.

### Confirmed invariant failures

| Case | Category | Detected failure |
| --- | --- | --- |
| M01 | Concurrency | Concurrent inventory oversell |
| M02 | Idempotency | Idempotency race |
| M03 | Authorization | Missing order ownership check |
| M04 | Webhook security | Signature bypass |
| M05 | Replay safety | Webhook replay |
| M07 | Side effects | Inventory lost after payment decline |
| M08 | Payment integrity | Duplicate charge after timeout |
| M09 | State transition | Repeated cancellation restores stock twice |
| M10 | Price integrity | Client-controlled order price |

### Architecture

```text
Repository
   ↓
Contract Mapper → invariant-linked analysis
   ↓
Stateful Adversarial Planner → race / retry / replay sequence
   ↓
Pytest Witness Generator
   ↓
Restricted Docker Runner
   ↓
Clean vs Mutant Differential Evidence
   ↓
Independent Adjudicator
   ↓
Portable JSON → Evidence Dashboard
```

The LLM layer uses a unified OpenAI-compatible adapter. Provider capability profiles keep schemas flat, define tool parameters clearly, validate every structured response with Pydantic, and perform one repair attempt that includes the exact validation error. Core agents therefore consume the same validated contract regardless of provider.

### Install

Requirements:

- Python 3.12
- Docker Desktop for restricted execution
- A provider API key only for model-backed scans

```powershell
git clone https://github.com/Kstrikker/edgecase-forge.git
cd edgecase-forge
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,benchmark]"
python -m pytest
```

If `py -3.12` is unavailable but `python --version` reports Python 3.12, use `python -m venv .venv`.

Run commands from the project root with `.venv` activated. Prefer `python -m edgecase_forge.cli ...` so PowerShell uses the environment's installed package.

### Safe pipeline smoke test — zero API tokens

```powershell
python -m edgecase_forge.cli stateful-scan `
  --repo "." `
  --provider mock `
  --output ".\results\stateful-ui-smoke"
```

This validates the CLI-to-artifact workflow without using a provider API or executing generated code. A valid zero-finding report means the pipeline completed; it does **not** prove that the repository is defect-free.

Cross-platform single-line form for Bash, zsh, PowerShell, and Command Prompt:

```bash
python -m edgecase_forge.cli stateful-scan --repo "." --provider mock --output "./results/stateful-ui-smoke"
```

### Model-backed local scan

Set the provider API key in the local environment according to the selected provider, then run:

```powershell
python -m edgecase_forge.cli stateful-scan `
  --repo "C:\Path\To\Trusted\Repository" `
  --provider gemini `
  --model "gemini-3.5-flash" `
  --output ".\results\stateful" `
  --execute
```

`--execute` is opt-in. Use it only for a repository you trust because the generated pytest witness is executed locally. Omit it to generate evidence without test execution.

### Dashboard workflow

1. Open the [EdgeCase Forge Evidence Dashboard](https://edgecase-forge-dashboard.kthakur1221.chatgpt.site).
2. Select **New Scan**.
3. Configure the repository and provider; the browser generates the local CLI command.
4. Run the command on your machine. Repository code and API credentials never enter the dashboard.
5. Drop `report.json`, `suite-summary.json`, or `adjudicated-summary.json` into **Ingest evidence**.
6. The browser validates the schema, calculates a SHA-256 fingerprint, and loads the artifact with no partial render.
7. Explore the invariant matrix, differential proof, attack stages, test witness, trajectory, and replay trace.

Schema validity and a fingerprint prove that the loaded bytes are structurally accepted and unchanged during the session. Verified provenance comes from adjudication metadata—not from the filename or hash alone.

### CLI surface

```text
docker-smoke          Restricted Docker execution smoke test
providers             List configured provider profiles
baseline-scan         Run the frozen generic baseline agent
contract-scan         Map API invariants and generate linked tests
stateful-scan         Generate a stateful adversarial attack plan
benchmark-run         Run an agent across the frozen FlashCart suite
benchmark-adjudicate  Confirm candidate evidence and publish a score overlay
```

Use `python -m edgecase_forge.cli <command> --help` for the authoritative options. There is intentionally no generic `scan` command.

### Representative trajectories

[Representative Agent Trajectories](trajectories/)

The repository should preserve representative JSONL traces for every submitted agent role, including the model request/response boundary, validation or repair outcome, generated witness, execution result, and adjudication step. Trajectories must be redacted of API keys and other secrets but should retain tool responses and failure states needed to reproduce the reasoning path.

### Security model

- API keys stay in local environment variables and are never entered into the hosted UI.
- Repository source remains local.
- Generated test execution is disabled by default.
- The restricted runner uses no network, a read-only repository, dropped Linux capabilities, `no-new-privileges`, process/CPU/memory limits, a timeout, and an isolated temporary filesystem.
- Every imported dashboard artifact crosses an explicit schema-validation boundary before rendering.
- Model responses are untrusted until parsed and validated.

### Current scope

EdgeCase Forge currently targets Python API repositories and pytest-based evidence. The benchmark proves the approach against stateful commerce invariants. Future work can add richer repository discovery, more language runners, automated patch suggestions, and CI integrations without weakening the evidence boundary.
