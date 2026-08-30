from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edgecase_forge.llm.schemas import Finding


class InvariantTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invariant_id: str = Field(description="Short stable identifier such as INV-01")
    endpoint: str = Field(description="HTTP method and route")
    category: str = Field(
        description="One of validation, authorization, concurrency, idempotency, replay, or side_effect"
    )
    invariant: str = Field(description="Correct behavior that must always hold")
    evidence: list[str] = Field(description="Concrete source observations")
    oracle: str = Field(description="Observable assertion that directly proves the invariant")

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, value: object) -> object:
        if isinstance(value, str):
            return [value]
        return value


class ContractFinding(Finding):
    invariant_id: str = Field(description="InvariantTarget identifier proved by this finding")


class ContractAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Concise summary of the repository analysis")
    invariants: list[InvariantTarget] = Field(
        description="Highest-value contracts derived from source; empty only when none are defensible"
    )
    findings: list[ContractFinding] = Field(
        description="Defects supported by source evidence and linked to an invariant"
    )
    generated_test_code: str = Field(
        description="One complete executable pytest module; empty only when no defect is found"
    )

    @model_validator(mode="after")
    def validate_invariant_links(self) -> "ContractAnalysis":
        invariant_ids = [item.invariant_id for item in self.invariants]
        if len(set(invariant_ids)) != len(invariant_ids):
            raise ValueError("invariant_id values must be unique")
        known = set(invariant_ids)
        for finding in self.findings:
            if finding.invariant_id not in known:
                raise ValueError(
                    f"finding references unknown invariant_id {finding.invariant_id}"
                )
            signature = f"def {finding.test_name}("
            async_signature = f"async def {finding.test_name}("
            if signature not in self.generated_test_code and async_signature not in self.generated_test_code:
                raise ValueError(
                    f"generated_test_code is missing {finding.test_name}"
                )
        if self.findings and not self.generated_test_code.strip():
            raise ValueError("findings require generated_test_code")
        return self
