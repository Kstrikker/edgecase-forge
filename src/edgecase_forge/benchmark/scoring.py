from __future__ import annotations

from pydantic import BaseModel, ConfigDict, computed_field


class CaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    is_clean_control: bool
    generated_test_executed: bool
    passes_clean: bool
    fails_mutant: bool
    matches_expected_invariant: bool
    runtime_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @computed_field
    @property
    def killed(self) -> bool:
        return (
            not self.is_clean_control
            and self.generated_test_executed
            and self.passes_clean
            and self.fails_mutant
            and self.matches_expected_invariant
        )


class EvaluationSummary(BaseModel):
    total_mutants: int
    killed_mutants: int
    mutation_score: float
    clean_false_positives: int
    executable_cases: int
    runtime_seconds: float
    input_tokens: int
    output_tokens: int


def summarize(cases: list[CaseEvaluation]) -> EvaluationSummary:
    mutants = [case for case in cases if not case.is_clean_control]
    clean_false_positives = sum(
        1
        for case in cases
        if case.is_clean_control and case.generated_test_executed and not case.passes_clean
    )
    killed = sum(int(case.killed) for case in mutants)
    return EvaluationSummary(
        total_mutants=len(mutants),
        killed_mutants=killed,
        mutation_score=(killed / len(mutants) if mutants else 0.0),
        clean_false_positives=clean_false_positives,
        executable_cases=sum(int(case.generated_test_executed) for case in cases),
        runtime_seconds=round(sum(case.runtime_seconds for case in cases), 4),
        input_tokens=sum(case.input_tokens for case in cases),
        output_tokens=sum(case.output_tokens for case in cases),
    )

