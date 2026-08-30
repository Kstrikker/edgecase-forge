from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from edgecase_forge.baseline.repository import IGNORED_NAMES, MAX_FILE_BYTES

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put"}
MUTATING_METHODS = {
    "add",
    "append",
    "clear",
    "commit",
    "delete",
    "discard",
    "extend",
    "pop",
    "remove",
    "setdefault",
    "update",
}
EFFECT_METHODS = {
    "charge",
    "commit",
    "execute",
    "publish",
    "refund",
    "send",
    "transfer",
}
BOUNDARY_FIELD_TOKENS = {
    "count",
    "items",
    "quantity",
    "seats",
    "tickets",
    "units",
}


@dataclass(frozen=True)
class RouteContract:
    method: str
    path: str
    handler: str
    source: str
    line: int
    parameters: tuple[str, ...]
    state_reads: tuple[str, ...]
    state_writes: tuple[str, ...]
    external_effects: tuple[str, ...]
    guards: tuple[str, ...]
    risk_signals: tuple[str, ...]


@dataclass(frozen=True)
class PriorityTarget:
    rank: int
    signal: str
    endpoint: str
    evidence: str
    required_oracle: str


@dataclass(frozen=True)
class RepositoryMap:
    schema_version: str
    repository_sha256: str
    analyzed_files: tuple[str, ...]
    routes: tuple[RouteContract, ...]
    priority_targets: tuple[PriorityTarget, ...]
    parse_errors: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        lines = [
            "=== DETERMINISTIC API CONTRACT MAP ===",
            f"Files analyzed: {len(self.analyzed_files)}",
            f"Routes discovered: {len(self.routes)}",
            f"Priority targets: {len(self.priority_targets)}",
        ]
        for target in self.priority_targets:
            lines.extend(
                [
                    "",
                    f"PRIORITY {target.rank}: {target.signal} at {target.endpoint}",
                    f"Evidence: {target.evidence}",
                    f"Required oracle: {target.required_oracle}",
                ]
            )
        for route in self.routes:
            lines.extend(
                [
                    "",
                    f"ROUTE {route.method} {route.path}",
                    f"Handler: {route.handler} ({route.source}:{route.line})",
                    f"Parameters: {_joined(route.parameters)}",
                    f"State reads: {_joined(route.state_reads)}",
                    f"State writes: {_joined(route.state_writes)}",
                    f"External effects: {_joined(route.external_effects)}",
                    f"Guards: {_joined(route.guards)}",
                    f"Risk signals: {_joined(route.risk_signals)}",
                ]
            )
        if self.parse_errors:
            lines.extend(["", f"Parse errors: {_joined(self.parse_errors)}"])
        lines.append("=== END DETERMINISTIC MAP ===")
        return "\n".join(lines)


def build_repository_map(repo: Path) -> RepositoryMap:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"Repository does not exist: {repo}")
    analyzed: list[str] = []
    errors: list[str] = []
    routes: list[RouteContract] = []
    digest = hashlib.sha256()
    for path in sorted(repo.rglob("*.py")):
        relative = path.relative_to(repo)
        if any(part in IGNORED_NAMES or part.startswith(".env") for part in relative.parts):
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        relative_text = relative.as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_text)
        except (UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{relative_text}:{type(exc).__name__}")
            continue
        analyzed.append(relative_text)
        digest.update(relative_text.encode("utf-8"))
        digest.update(source.encode("utf-8"))
        routes.extend(_module_routes(tree, relative_text))
    routes.sort(key=lambda item: (item.path, item.method, item.source, item.line))
    return RepositoryMap(
        schema_version="repository-map-v2",
        repository_sha256=digest.hexdigest(),
        analyzed_files=tuple(analyzed),
        routes=tuple(routes),
        priority_targets=_priority_targets(routes),
        parse_errors=tuple(errors),
    )


def _module_routes(tree: ast.Module, source: str) -> list[RouteContract]:
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    unbounded_models = _unbounded_numeric_model_fields(tree)
    discovered: list[RouteContract] = []
    for handler in functions.values():
        route = _route_decorator(handler)
        if route is None:
            continue
        method, path = route
        reachable = _reachable_functions(handler, functions)
        parameters = tuple(argument.arg for argument in (*handler.args.posonlyargs, *handler.args.args, *handler.args.kwonlyargs))
        facts = _Facts(set(parameters))
        for function in reachable:
            facts.visit(function)
        unbounded_fields = _used_unbounded_request_fields(
            handler,
            reachable,
            unbounded_models,
        )
        risks = _risk_signals(reachable, facts, unbounded_fields)
        discovered.append(
            RouteContract(
                method=method.upper(),
                path=path,
                handler=handler.name,
                source=source,
                line=handler.lineno,
                parameters=parameters,
                state_reads=tuple(sorted(facts.state_reads - facts.state_writes)),
                state_writes=tuple(sorted(facts.state_writes)),
                external_effects=tuple(sorted(facts.external_effects)),
                guards=tuple(sorted(facts.guards)),
                risk_signals=tuple(sorted(risks)),
            )
        )
    return discovered


def _route_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, str] | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in HTTP_METHODS or not decorator.args:
            continue
        value = decorator.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return method, value.value
    return None


def _reachable_functions(
    root: ast.FunctionDef | ast.AsyncFunctionDef,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    queue = [root]
    seen: set[str] = set()
    result: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    while queue:
        current = queue.pop(0)
        if current.name in seen:
            continue
        seen.add(current.name)
        result.append(current)
        called = sorted(
            {
                call.func.id
                for call in ast.walk(current)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
        )
        queue.extend(functions[name] for name in called if name in functions and name not in seen)
    return tuple(result)


class _Facts(ast.NodeVisitor):
    def __init__(self, request_parameters: set[str]) -> None:
        self.request_parameters = request_parameters
        self.state_reads: set[str] = set()
        self.state_writes: set[str] = set()
        self.external_effects: set[str] = set()
        self.guards: set[str] = set()
        self.has_if = False
        self.has_raise = False
        self.has_lock = False
        self.client_total_assignment = False
        self.unstable_effects: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = _attribute_chain(node)
        if chain.startswith("STATE."):
            if isinstance(node.ctx, ast.Store):
                self.state_writes.add(chain)
            else:
                self.state_reads.add(chain)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        chain = _safe_unparse(node.value)
        if chain.startswith("STATE."):
            if isinstance(node.ctx, ast.Store):
                self.state_writes.add(chain)
            else:
                self.state_reads.add(chain)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        expression = _safe_unparse(node)
        terminal = _call_terminal(node.func)
        chain = _safe_unparse(node.func)
        if terminal in EFFECT_METHODS:
            self.external_effects.add(expression)
            if _contains_unstable_identity(node):
                self.unstable_effects.add(expression)
        if terminal in MUTATING_METHODS and chain.startswith("STATE."):
            self.state_writes.add(chain.rsplit(".", 1)[0])
        if terminal == "HTTPException":
            self.guards.add(expression)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.has_if = True
        self.guards.add(f"if {_safe_unparse(node.test)}")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.has_raise = True
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        expressions = " | ".join(_safe_unparse(item.context_expr) for item in node.items)
        if "lock" in expressions.lower():
            self.has_lock = True
            self.guards.add(f"lock {expressions}")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            key_value = key.value if isinstance(key, ast.Constant) else None
            if (
                isinstance(key_value, str)
                and _is_money_name(key_value)
                and _contains_client_money(value, self.request_parameters)
            ):
                self.client_total_assignment = True
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(_is_money_name(_safe_unparse(target)) for target in node.targets) and _contains_client_money(
            node.value, self.request_parameters
        ):
            self.client_total_assignment = True
        self.generic_visit(node)


def _risk_signals(
    functions: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...],
    facts: _Facts,
    unbounded_fields: tuple[str, ...],
) -> set[str]:
    text = " ".join(_safe_unparse(function) for function in functions).lower()
    risks: set[str] = set()
    if facts.state_writes:
        risks.add("shared_state_transition")
        if facts.has_if and not facts.has_lock:
            risks.add("check_then_write_without_visible_lock")
    if facts.external_effects:
        risks.add("external_side_effect")
        if facts.has_raise:
            risks.add("partial_failure_or_retry_after_effect")
    if facts.unstable_effects:
        risks.add("unstable_external_effect_identity")
    if "idempot" in text or "operation_key" in text:
        risks.add("idempotency_identity")
    if "webhook" in text or "event_id" in text:
        risks.add("webhook_replay_or_authenticity")
    if "authorization" in text or "owner" in text or "bearer" in text:
        risks.add("resource_ownership")
    if facts.external_effects and facts.client_total_assignment:
        risks.add("client_input_in_authoritative_total")
    if unbounded_fields and facts.state_writes:
        risks.add("missing_numeric_request_boundary")
    return risks


def _unbounded_numeric_model_fields(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    models: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not any(
            _safe_unparse(base).endswith("BaseModel") for base in node.bases
        ):
            continue
        fields: list[str] = []
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(
                statement.target, ast.Name
            ):
                continue
            name = statement.target.id
            if (
                _is_boundary_field_name(name)
                and _is_integer_annotation(statement.annotation)
                and not _has_explicit_lower_bound(statement)
            ):
                fields.append(name)
        if fields:
            models[node.name] = tuple(sorted(fields))
    return models


def _used_unbounded_request_fields(
    handler: ast.FunctionDef | ast.AsyncFunctionDef,
    reachable: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...],
    unbounded_models: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    reachable_text = " ".join(ast.unparse(function) for function in reachable)
    fields: set[str] = set()
    arguments = (*handler.args.posonlyargs, *handler.args.args, *handler.args.kwonlyargs)
    for argument in arguments:
        model_name = _annotation_name(argument.annotation)
        for field in unbounded_models.get(model_name, ()):
            expression = f"{argument.arg}.{field}"
            if expression in reachable_text:
                fields.add(expression)
    return tuple(sorted(fields))


def _annotation_name(annotation: ast.expr | None) -> str:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return ""


def _is_boundary_field_name(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered.split("_") for token in BOUNDARY_FIELD_TOKENS)


def _is_integer_annotation(annotation: ast.expr) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "int"
        for node in ast.walk(annotation)
    )


def _has_explicit_lower_bound(statement: ast.AnnAssign) -> bool:
    nodes: tuple[ast.AST, ...] = (
        statement.annotation,
        *((statement.value,) if statement.value is not None else ()),
    )
    for root in nodes:
        for node in ast.walk(root):
            if not isinstance(node, ast.Call):
                continue
            terminal = _call_terminal(node.func).lower()
            if terminal not in {"field", "conint"}:
                continue
            if any(keyword.arg in {"ge", "gt"} for keyword in node.keywords):
                return True
    return False


def _attribute_chain(node: ast.Attribute) -> str:
    parts = [node.attr]
    value = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _call_terminal(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _contains_client_money(node: ast.AST, request_parameters: set[str]) -> bool:
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Attribute) or not _is_money_name(candidate.attr):
            continue
        chain = _attribute_chain(candidate)
        if chain.split(".", 1)[0] in request_parameters:
            return True
    return False


def _contains_unstable_identity(node: ast.AST) -> bool:
    expression = _safe_unparse(node).lower()
    return any(
        marker in expression
        for marker in ("nonce", "random", "time_ns", "token_urlsafe", "uuid")
    )


def _is_money_name(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("amount", "cost", "fee", "price", "total"))


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node).replace("\n", " ")[:300]
    except (AttributeError, ValueError):
        return type(node).__name__


def _joined(values: tuple[str, ...]) -> str:
    return "; ".join(values) if values else "none detected"


def _priority_targets(routes: list[RouteContract]) -> tuple[PriorityTarget, ...]:
    candidates: list[tuple[int, str, RouteContract, str]] = []
    for route in routes:
        signals = set(route.risk_signals)
        if "unstable_external_effect_identity" in signals:
            evidence = next(
                (
                    effect
                    for effect in route.external_effects
                    if any(marker in effect.lower() for marker in ("nonce", "random", "time_ns", "token_urlsafe", "uuid"))
                ),
                "External-effect identity contains a volatile value.",
            )
            candidates.append(
                (
                    0,
                    "unstable_external_effect_identity",
                    route,
                    evidence,
                )
            )
        if "client_input_in_authoritative_total" in signals:
            candidates.append(
                (
                    1,
                    "client_input_in_authoritative_total",
                    route,
                    "A request monetary field can become the authoritative order amount.",
                )
            )
        if "missing_numeric_request_boundary" in signals:
            candidates.append(
                (
                    2,
                    "missing_numeric_request_boundary",
                    route,
                    "A quantity-like integer request field reaches shared-state "
                    "mutation without an explicit lower bound.",
                )
            )
    candidates.sort(key=lambda item: (item[0], item[2].path, item[2].method))
    targets: list[PriorityTarget] = []
    for rank, (_, signal, route, evidence) in enumerate(candidates, start=1):
        if signal == "unstable_external_effect_identity":
            oracle = (
                "After timeout and retry, assert the provider effect ledger count "
                "before asserting secondary response statuses."
            )
        elif signal == "client_input_in_authoritative_total":
            oracle = (
                "Submit a manipulated monetary input and assert returned total and "
                "provider amount equal the server price multiplied by accepted quantity."
            )
        else:
            oracle = (
                "Submit zero and a negative quantity, assert both are rejected with "
                "422, and prove stock, orders, and provider charges are unchanged."
            )
        targets.append(
            PriorityTarget(
                rank=rank,
                signal=signal,
                endpoint=f"{route.method} {route.path}",
                evidence=evidence,
                required_oracle=oracle,
            )
        )
    return tuple(targets)


def repository_map_sha256(repository_map: RepositoryMap) -> str:
    canonical = json.dumps(repository_map.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
