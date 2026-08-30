from __future__ import annotations

import ast

from pydantic import model_validator

from edgecase_forge.contract.schema import ContractAnalysis

from .plan import AttackPlan

HTTP_METHODS = {"delete", "get", "patch", "post", "put", "request"}
LEDGER_MARKERS = {"charges", "effects", "ledger", "payments", "transfers"}


def stateful_analysis_model(attack_plan: AttackPlan) -> type[ContractAnalysis]:
    """Create a provider-compatible model with plan-specific semantic validation."""

    class StatefulAnalysis(ContractAnalysis):
        @model_validator(mode="after")
        def validate_stateful_oracle(self) -> "StatefulAnalysis":
            if (
                attack_plan.target_signal == "unstable_external_effect_identity"
                and self.findings
            ):
                for finding in self.findings:
                    _validate_retry_oracle_order(
                        self.generated_test_code,
                        finding.test_name,
                    )
            return self

    StatefulAnalysis.__name__ = "StatefulAnalysis"
    StatefulAnalysis.__qualname__ = "StatefulAnalysis"
    return StatefulAnalysis


def _validate_retry_oracle_order(code: str, test_name: str) -> None:
    try:
        module = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError("generated_test_code is not valid Python") from exc
    function = next(
        (
            node
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == test_name
        ),
        None,
    )
    if function is None:
        raise ValueError(f"generated_test_code is missing {test_name}")

    response_assignments: list[tuple[int, str]] = []
    assertions: list[tuple[int, str]] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _is_http_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    response_assignments.append((node.lineno, target.id))
        elif isinstance(node, ast.Assert):
            assertions.append((node.lineno, _unparse(node.test).lower()))
    response_names = list(
        dict.fromkeys(name for _, name in sorted(response_assignments))
    )
    assertions.sort()
    if len(response_names) < 2:
        raise ValueError(
            "Stateful retry finding requires two HTTP requests with the same logical identity"
        )

    ledger_lines = [
        line
        for line, expression in assertions
        if any(marker in expression for marker in LEDGER_MARKERS)
    ]
    if not ledger_lines:
        raise ValueError(
            "Retry side-effect finding must assert the provider ledger or effect count"
        )
    retry_name = response_names[1].lower()
    retry_status_lines = [
        line
        for line, expression in assertions
        if retry_name in expression and "status_code" in expression
    ]
    if retry_status_lines and min(retry_status_lines) < min(ledger_lines):
        raise ValueError(
            "Primary oracle ordering violation: assert the provider ledger/effect count "
            "after the retry and before asserting the retry response status"
        )


def _is_http_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.lower() in HTTP_METHODS
    )


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ""
