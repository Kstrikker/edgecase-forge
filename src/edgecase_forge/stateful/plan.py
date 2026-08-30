from __future__ import annotations

from dataclasses import asdict, dataclass

from edgecase_forge.contract.mapper import RepositoryMap


@dataclass(frozen=True)
class AttackStep:
    sequence: int
    action: str
    purpose: str


@dataclass(frozen=True)
class AttackPlan:
    schema_version: str
    target_signal: str | None
    endpoint: str | None
    primary_oracle: str | None
    steps: tuple[AttackStep, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        if self.target_signal is None:
            return "=== STATEFUL ATTACK PLAN ===\nNo deterministic priority target.\n=== END ATTACK PLAN ==="
        lines = [
            "=== STATEFUL ATTACK PLAN ===",
            f"Target: {self.target_signal}",
            f"Endpoint: {self.endpoint}",
            f"Primary oracle: {self.primary_oracle}",
        ]
        lines.extend(
            f"Step {step.sequence}: {step.action} — {step.purpose}"
            for step in self.steps
        )
        lines.append("=== END ATTACK PLAN ===")
        return "\n".join(lines)


def build_attack_plan(repository_map: RepositoryMap) -> AttackPlan:
    if not repository_map.priority_targets:
        return AttackPlan("stateful-attack-plan-v1", None, None, None, ())
    target = repository_map.priority_targets[0]
    if target.signal == "unstable_external_effect_identity":
        steps = (
            AttackStep(1, "Reset observable application and provider state", "Establish an isolated ledger"),
            AttackStep(2, "Send a request that creates an external effect and returns a transient failure", "Create retry ambiguity"),
            AttackStep(3, "Retry the same logical operation with the same idempotency identity", "Exercise effect identity stability"),
            AttackStep(4, "Assert the provider effect ledger count", "Execute the primary business oracle first"),
            AttackStep(5, "Assert secondary HTTP outcomes", "Describe recovery behavior without masking the oracle"),
        )
    elif target.signal == "client_input_in_authoritative_total":
        steps = (
            AttackStep(1, "Read or identify the server catalog price", "Establish the authoritative value"),
            AttackStep(2, "Submit a conflicting client monetary value", "Exercise the trust boundary"),
            AttackStep(3, "Assert returned total equals server price multiplied by quantity", "Execute the primary integrity oracle"),
            AttackStep(4, "Assert the provider amount matches the same total", "Verify downstream consistency"),
        )
    else:
        steps = (
            AttackStep(1, "Establish isolated state", "Create a deterministic starting point"),
            AttackStep(2, "Execute the mapped adversarial sequence", "Exercise the priority boundary"),
            AttackStep(3, "Assert the mapped primary oracle", "Prove the invariant directly"),
        )
    return AttackPlan(
        schema_version="stateful-attack-plan-v1",
        target_signal=target.signal,
        endpoint=target.endpoint,
        primary_oracle=target.required_oracle,
        steps=steps,
    )
