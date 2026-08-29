from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    severity: str = Field(description="One of low, medium, high, critical")
    endpoint: str = Field(description="HTTP method and route, or unknown")
    claim: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    test_file: str = Field(description="Relative generated pytest path")
    test_name: str = Field(description="Generated pytest function name")
    reproduced: bool = False

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, value: object) -> object:
        if isinstance(value, str):
            return [value]
        return value


class BaselineAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    findings: list[Finding]
    generated_test_code: str = Field(
        description="Complete executable pytest module; empty only when no defect is found"
    )
