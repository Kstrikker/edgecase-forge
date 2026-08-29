from edgecase_forge.baseline.executor import ExecutionResult, PytestNodeResult
from edgecase_forge.benchmark.differential import build_differential


def execution(*nodes: PytestNodeResult, exit_code: int = 0) -> ExecutionResult:
    return ExecutionResult(
        executed=True,
        exit_code=exit_code,
        stdout="",
        stderr="",
        nodes=nodes,
        junit_xml="<xml />",
    )


def node(name: str, outcome: str, failure_kind: str | None = None) -> PytestNodeResult:
    return PytestNodeResult(
        node_id=f"tests.test_generated::{name}",
        test_name=name,
        outcome=outcome,
        failure_kind=failure_kind,
    )


def test_clean_pass_and_claimed_mutant_assertion_is_candidate() -> None:
    result = build_differential(
        case_id="M01",
        clean=execution(node("test_stock", "passed")),
        mutant=execution(
            node("test_stock", "failed", "assertion_failure"), exit_code=1
        ),
        findings=[{"test_name": "test_stock"}],
        test_sha256="abc",
    )
    assert result["case_candidate_kill"] is True
    assert result["candidate_nodes"] == ["tests.test_generated::test_stock"]


def test_unclaimed_failure_and_runtime_error_never_kill() -> None:
    unclaimed = build_differential(
        case_id="M01",
        clean=execution(node("test_stock", "passed")),
        mutant=execution(
            node("test_stock", "failed", "assertion_failure"), exit_code=1
        ),
        findings=[{"test_name": "test_different"}],
        test_sha256="abc",
    )
    errored = build_differential(
        case_id="M01",
        clean=execution(node("test_stock", "passed")),
        mutant=execution(node("test_stock", "error", "test_exception"), exit_code=1),
        findings=[{"test_name": "test_stock"}],
        test_sha256="abc",
    )
    assert unclaimed["nodes"][0]["classification"] == "unmatched"
    assert errored["nodes"][0]["classification"] == "invalid"
    assert not unclaimed["case_candidate_kill"]
    assert not errored["case_candidate_kill"]


def test_clean_failure_is_false_positive_even_when_another_node_kills() -> None:
    result = build_differential(
        case_id="M01",
        clean=execution(
            node("test_kill", "passed"),
            node("test_bad", "failed", "assertion_failure"),
            exit_code=1,
        ),
        mutant=execution(
            node("test_kill", "failed", "assertion_failure"),
            node("test_bad", "failed", "assertion_failure"),
            exit_code=1,
        ),
        findings=[{"test_name": "test_kill"}, {"test_name": "test_bad"}],
        test_sha256="abc",
    )
    assert result["case_candidate_kill"] is True
    assert result["clean_false_positive_nodes"] == ["tests.test_generated::test_bad"]


def test_parameterized_node_maps_to_base_finding_name() -> None:
    result = build_differential(
        case_id="M06",
        clean=execution(node("test_quantity[0]", "passed")),
        mutant=execution(
            node("test_quantity[0]", "failed", "assertion_failure"), exit_code=1
        ),
        findings=[{"test_name": "test_quantity"}],
        test_sha256="abc",
    )
    assert result["case_candidate_kill"] is True
    assert result["nodes"][0]["finding_indexes"] == [0]


def test_partial_junit_from_timeout_or_interruption_cannot_kill() -> None:
    clean = execution(node("test_stock", "passed"))
    timed_out_mutant = ExecutionResult(
        executed=True,
        exit_code=None,
        stdout="",
        stderr="",
        timed_out=True,
        nodes=(node("test_stock", "failed", "assertion_failure"),),
        junit_xml="<partial />",
    )
    interrupted_mutant = ExecutionResult(
        executed=True,
        exit_code=2,
        stdout="",
        stderr="",
        nodes=(node("test_stock", "failed", "assertion_failure"),),
        junit_xml="<partial />",
    )
    for mutant in (timed_out_mutant, interrupted_mutant):
        result = build_differential(
            case_id="M01",
            clean=clean,
            mutant=mutant,
            findings=[{"test_name": "test_stock"}],
            test_sha256="abc",
        )
        assert result["case_candidate_kill"] is False
        assert result["nodes"][0]["reason"] == "mutant_harness_invalid"


def test_duplicate_finding_names_are_ambiguous_and_cannot_kill() -> None:
    result = build_differential(
        case_id="M01",
        clean=execution(node("test_stock", "passed")),
        mutant=execution(
            node("test_stock", "failed", "assertion_failure"), exit_code=1
        ),
        findings=[{"test_name": "test_stock"}, {"test_name": "test_stock"}],
        test_sha256="abc",
    )
    assert result["case_candidate_kill"] is False
    assert result["nodes"][0]["finding_mapping_status"] == "ambiguous"


def test_any_runtime_error_makes_the_execution_unscoreable() -> None:
    clean = execution(
        node("test_stock", "passed"),
        node("test_broken", "passed"),
    )
    mutant = execution(
        node("test_stock", "failed", "assertion_failure"),
        node("test_broken", "error", "test_exception"),
        exit_code=1,
    )
    result = build_differential(
        case_id="M01",
        clean=clean,
        mutant=mutant,
        findings=[{"test_name": "test_stock"}],
        test_sha256="abc",
    )
    assert result["case_candidate_kill"] is False
    assert all(
        item["reason"] == "mutant_harness_invalid" for item in result["nodes"]
    )
