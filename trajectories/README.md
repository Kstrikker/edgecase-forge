# Representative Agent Trajectories

These traces document representative model, tool, validation, and execution paths used while developing EdgeCase Forge. The benchmark repository, users, authorization values, and payment data are synthetic.

| File | Agent / experiment | Why it is included |
| --- | --- | --- |
| `baseline-m08.jsonl` | Single-pass baseline agent | Shows the basic direct-analysis approach and its generated retry witness. |
| `contract-mapper-m10.jsonl` | Contract Mapper v1.1 | Shows invariant mapping for the client-controlled price trust boundary. |
| `stateful-attacker-m08.jsonl` | Stateful Attacker v1.0 | Shows the flagship duplicate-charge retry plan and state-ledger oracle. |
| `stateful-v11-removed-c00.jsonl` | Removed Stateful v1.1 experiment | Shows the clean-control regression produced by the later specialization. |
| `stateful-v11-removed-summary.json` | Removed-experiment suite evidence | Records the C00 failure, M06 model-output error, and decision evidence used in the changelog. |

Each JSONL record is one event. Depending on the run, events include prompt metadata, validated model output, token and transport accounting, generated test code, execution outcome, and evidence classification. API keys are not stored in these files. Values such as `Bearer buyer-a`, idempotency keys, and payment tokens are synthetic FlashCart fixtures, not credentials.

The final adjudicated score overlay is stored separately at `../evidence/official-adjudicated-run.json`.
