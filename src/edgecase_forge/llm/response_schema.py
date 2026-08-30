from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

_REMOVED_KEYWORDS = frozenset(
    {
        "$defs",
        "$ref",
        "allOf",
        "anyOf",
        "default",
        "examples",
        "maxItems",
        "maxLength",
        "minItems",
        "minLength",
        "oneOf",
        "title",
    }
)


def flat_strict_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Build the small JSON Schema subset shared by supported providers."""
    source = response_model.model_json_schema()
    definitions = source.get("$defs", {})
    resolved = _resolve_local_refs(source, definitions, active=())
    normalized = _normalize(resolved)
    if not isinstance(normalized, dict):
        raise ValueError("Response model must produce an object schema")
    return normalized


def _resolve_local_refs(
    value: Any,
    definitions: dict[str, Any],
    *,
    active: tuple[str, ...],
) -> Any:
    if isinstance(value, list):
        return [_resolve_local_refs(item, definitions, active=active) for item in value]
    if not isinstance(value, dict):
        return value

    reference = value.get("$ref")
    if reference is not None:
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise ValueError(f"Unsupported response schema reference: {reference}")
        name = reference.removeprefix(prefix)
        if name in active:
            raise ValueError("Recursive response schemas are not supported")
        target = definitions.get(name)
        if target is None:
            raise ValueError(f"Unknown response schema reference: {reference}")
        merged = deepcopy(target)
        merged.update({key: item for key, item in value.items() if key != "$ref"})
        return _resolve_local_refs(merged, definitions, active=(*active, name))

    return {
        key: _resolve_local_refs(item, definitions, active=active)
        for key, item in value.items()
        if key != "$defs"
    }


def _normalize(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if not isinstance(value, dict):
        return value

    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in _REMOVED_KEYWORDS:
            continue
        if key == "properties" and isinstance(item, dict):
            result[key] = {name: _normalize(schema) for name, schema in item.items()}
        else:
            result[key] = _normalize(item)
    if result.get("type") == "object":
        properties = result.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("Object response schema properties must be an object")
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result
