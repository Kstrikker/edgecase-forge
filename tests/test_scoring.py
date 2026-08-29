from edgecase_forge.benchmark.scoring import CaseEvaluation, summarize


def test_mutant_requires_clean_pass_and_expected_failure() -> None:
    cases = [
        CaseEvaluation(
            case_id="C00",
            is_clean_control=True,
            generated_test_executed=True,
            passes_clean=True,
            fails_mutant=False,
            matches_expected_invariant=False,
        ),
        CaseEvaluation(
            case_id="M01",
            is_clean_control=False,
            generated_test_executed=True,
            passes_clean=True,
            fails_mutant=True,
            matches_expected_invariant=True,
        ),
        CaseEvaluation(
            case_id="M02",
            is_clean_control=False,
            generated_test_executed=True,
            passes_clean=False,
            fails_mutant=True,
            matches_expected_invariant=True,
        ),
    ]
    summary = summarize(cases)
    assert summary.killed_mutants == 1
    assert summary.mutation_score == 0.5
    assert summary.clean_false_positives == 0

