from __future__ import annotations

from collections.abc import Sequence

from edgecase_forge.baseline.executor import ExecutionResult, PytestNodeResult


def build_differential(
    *,
    case_id: str,
    clean: ExecutionResult,
    mutant: ExecutionResult | None,
    findings: Sequence[dict],
    test_sha256: str,
) -> dict:
    finding_table = []
    finding_indexes: dict[str, list[int]] = {}
    for index, finding in enumerate(findings):
        name = str(finding.get("test_name", ""))
        base_name = base_test_name(name)
        finding_table.append(
            {
                "finding_index": index,
                "title": str(finding.get("title", "")),
                "endpoint": str(finding.get("endpoint", "")),
                "claim": str(finding.get("claim", "")),
                "test_name": name,
                "base_test_name": base_name,
            }
        )
        if base_name:
            finding_indexes.setdefault(base_name, []).append(index)
    clean_nodes = _unique_nodes(clean.nodes)
    mutant_nodes = _unique_nodes(mutant.nodes) if mutant else {}
    keys = sorted(set(clean_nodes) | set(mutant_nodes))
    nodes = [
        _classify_node(
            key=key,
            clean=clean_nodes.get(key),
            mutant=mutant_nodes.get(key),
            finding_indexes=finding_indexes,
            clean_only=mutant is None,
            clean_harness_valid=clean.scoreable_harness,
            mutant_harness_valid=(mutant.scoreable_harness if mutant else False),
        )
        for key in keys
    ]
    candidate_nodes = [
        node["node_key"] for node in nodes if node["classification"] == "candidate_kill"
    ]
    false_positive_nodes = [
        node["node_key"]
        for node in nodes
        if node["classification"] == "clean_false_positive"
    ]
    return {
        "schema_version": "differential-evidence-v1",
        "case_id": case_id,
        "test_sha256": test_sha256,
        "clean_harness_status": clean.harness_status,
        "mutant_harness_status": mutant.harness_status if mutant else None,
        "findings": finding_table,
        "nodes": nodes,
        "candidate_nodes": candidate_nodes,
        "clean_false_positive_nodes": false_positive_nodes,
        "case_candidate_kill": bool(mutant and candidate_nodes),
        "case_confirmed_kill": False,
    }


def base_test_name(test_name: str) -> str:
    return test_name.split("[", 1)[0]


def _unique_nodes(nodes: tuple[PytestNodeResult, ...]) -> dict[str, PytestNodeResult]:
    indexed: dict[str, PytestNodeResult] = {}
    duplicates: set[str] = set()
    for node in nodes:
        if node.node_id in indexed:
            duplicates.add(node.node_id)
        indexed[node.node_id] = node
    for key in duplicates:
        original = indexed[key]
        indexed[key] = PytestNodeResult(
            node_id=key,
            test_name=original.test_name,
            outcome="error",
            failure_kind="duplicate_node_key",
            message="JUnit contained a duplicate node key",
        )
    return indexed


def _classify_node(
    *,
    key: str,
    clean: PytestNodeResult | None,
    mutant: PytestNodeResult | None,
    finding_indexes: dict[str, list[int]],
    clean_only: bool,
    clean_harness_valid: bool,
    mutant_harness_valid: bool,
) -> dict:
    node = clean or mutant
    assert node is not None
    base_name = base_test_name(node.test_name)
    matched_finding_indexes = finding_indexes.get(base_name, [])
    maps_to_finding = len(matched_finding_indexes) == 1
    if maps_to_finding:
        mapping_status = "mapped"
    elif matched_finding_indexes:
        mapping_status = "ambiguous"
    else:
        mapping_status = "unmapped"

    if not clean_harness_valid:
        classification, reason = "invalid", "clean_harness_invalid"
    elif not clean_only and not mutant_harness_valid:
        classification, reason = "invalid", "mutant_harness_invalid"
    elif clean is None:
        classification, reason = "invalid", "missing_on_clean"
    elif clean.failure_kind == "assertion_failure":
        classification, reason = "clean_false_positive", "clean_assertion_failure"
    elif not clean.eligible_for_differential:
        classification, reason = "invalid", "clean_node_not_eligible"
    elif clean_only:
        classification, reason = "clean_pass", "clean_control_has_no_mutant"
    elif mutant is None:
        classification, reason = "invalid", "missing_on_mutant"
    elif not mutant.eligible_for_differential:
        classification, reason = "invalid", "mutant_node_not_eligible"
    elif mutant.failure_kind == "assertion_failure" and maps_to_finding:
        classification, reason = "candidate_kill", "clean_pass_mutant_assertion_failure"
    elif mutant.failure_kind == "assertion_failure":
        classification, reason = "unmatched", "failure_not_mapped_to_finding"
    else:
        classification, reason = "survived", "clean_and_mutant_pass"

    return {
        "node_key": key,
        "base_name": base_name,
        "maps_to_finding": maps_to_finding,
        "finding_indexes": matched_finding_indexes,
        "finding_mapping_status": mapping_status,
        "clean_outcome": clean.outcome if clean else None,
        "mutant_outcome": mutant.outcome if mutant else None,
        "mutant_failure_kind": mutant.failure_kind if mutant else None,
        "classification": classification,
        "reason": reason,
        "adjudication": "pending" if classification == "candidate_kill" else "not_applicable",
        "adjudication_reason": None,
    }
