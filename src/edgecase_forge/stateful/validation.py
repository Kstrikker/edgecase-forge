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
            if (
                attack_plan.target_signal == "missing_numeric_request_boundary"
                and self.findings
            ):
                for finding in self.findings:
                    _validate_numeric_boundary_oracle(
                        self.generated_test_code,
                        finding.test_name,
                    )
            return self

    StatefulAnalysis.__name__ = "StatefulAnalysis"
    StatefulAnalysis.__qualname__ = "StatefulAnalysis"
    return StatefulAnalysis


def _validate_retry_oracle_order(code: str, test_name: str) -> None:
    function = _test_function(code, test_name)

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


def _validate_numeric_boundary_oracle(code: str, test_name: str) -> None:
    function = _test_function(code, test_name)
    boundary_values = _quantity_boundary_values(function)
    if 0 not in boundary_values or not any(value < 0 for value in boundary_values):
        raise ValueError(
            "Numeric boundary finding must submit both quantity zero and a negative quantity"
        )

    response_assignments = _http_response_assignments(function)
    if len(response_assignments) < 2:
        raise ValueError(
            "Numeric boundary finding requires separate HTTP requests for zero and "
            "negative quantity"
        )
    response_names = [name for _, name in response_assignments[:2]]
    assertions = sorted(
        (node.lineno, node.test)
        for node in ast.walk(function)
        if isinstance(node, ast.Assert)
    )
    missing_status = [
        name
        for name in response_names
        if not any(_asserts_status(test, name, 422) for _, test in assertions)
    ]
    if missing_status:
        raise ValueError(
            "Numeric boundary finding must assert HTTP 422 for both invalid responses"
        )

    final_request_line = max(line for line, _ in response_assignments[:2])
    stock_lines = [
        line
        for line, test in assertions
        if line > final_request_line and _asserts_equality(test, "stock")
    ]
    orders_lines = [
        line
        for line, test in assertions
        if line > final_request_line and _asserts_empty(test, "orders")
    ]
    charges_lines = [
        line
        for line, test in assertions
        if line > final_request_line and _asserts_empty(test, "charges")
    ]
    if not stock_lines or not orders_lines or not charges_lines:
        raise ValueError(
            "Numeric boundary finding must prove unchanged stock and empty orders and "
            "charges after both invalid requests"
        )


def _test_function(
    code: str, test_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
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
    return function


def _http_response_assignments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[int, str]]:
    assignments: list[tuple[int, str]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or not _is_http_call(node.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                assignments.append((node.lineno, target.id))
    return sorted(assignments)


def _quantity_boundary_values(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[int]:
    values: set[int] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "quantity"
                    and (number := _integer_literal(value)) is not None
                ):
                    values.add(number)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg == "quantity"
                    and (number := _integer_literal(keyword.value)) is not None
                ):
                    values.add(number)
    return values


def _integer_literal(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(
        node.value, bool
    ):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and not isinstance(node.operand.value, bool)
    ):
        return -node.operand.value
    return None


def _asserts_status(test: ast.AST, response_name: str, status: int) -> bool:
    expression = _unparse(test)
    return (
        response_name in expression
        and "status_code" in expression
        and isinstance(test, ast.Compare)
        and any(isinstance(operator, ast.Eq) for operator in test.ops)
        and any(
            isinstance(node, ast.Constant) and node.value == status
            for node in ast.walk(test)
        )
    )


def _asserts_equality(test: ast.AST, marker: str) -> bool:
    return (
        marker in _unparse(test).lower()
        and isinstance(test, ast.Compare)
        and any(isinstance(operator, ast.Eq) for operator in test.ops)
    )


def _asserts_empty(test: ast.AST, marker: str) -> bool:
    expression = _unparse(test).lower()
    if marker not in expression:
        return False
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    if not isinstance(test, ast.Compare) or not any(
        isinstance(operator, ast.Eq) for operator in test.ops
    ):
        return False
    for node in (test.left, *test.comparators):
        if isinstance(node, ast.Constant) and node.value == 0:
            return True
        if isinstance(node, ast.Dict) and not node.keys:
            return True
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and not node.elts:
            return True
    return False


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
