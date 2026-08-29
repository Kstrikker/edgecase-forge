from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import ToolSchemaError, UnsupportedCapabilityError

StructuredOutputMode = Literal["none", "json_object", "json_schema"]


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    structured_output: StructuredOutputMode
    strict_json_schema: bool
    tool_calling: bool
    parallel_tool_calls: bool
    streaming: bool
    supports_tool_choice: bool
    schema_unsupported_keywords: frozenset[str] = frozenset()

    def require_json(self) -> None:
        if self.structured_output == "none":
            raise UnsupportedCapabilityError("Provider does not support JSON output")


PORTABLE_OPENAI_COMPATIBLE = CapabilityProfile(
    structured_output="json_object",
    strict_json_schema=False,
    tool_calling=True,
    parallel_tool_calls=False,
    streaming=True,
    supports_tool_choice=True,
    schema_unsupported_keywords=frozenset({"$defs", "$ref", "anyOf", "oneOf"}),
)


def validate_tool_schema(tool: dict) -> None:
    function = tool.get("function")
    if not isinstance(function, dict):
        raise ToolSchemaError("Tool must contain a function object")
    if not str(function.get("name", "")).strip():
        raise ToolSchemaError("Tool function name is required")
    if not str(function.get("description", "")).strip():
        raise ToolSchemaError("Tool function description is required")

    parameters = function.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        raise ToolSchemaError("Tool parameters must be an object schema")
    _validate_property_descriptions(parameters, "parameters")


def _validate_property_descriptions(schema: dict, path: str) -> None:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ToolSchemaError(f"{path}.properties must be an object")
    for name, child in properties.items():
        child_path = f"{path}.{name}"
        if not isinstance(child, dict):
            raise ToolSchemaError(f"{child_path} must be a schema object")
        if not str(child.get("description", "")).strip():
            raise ToolSchemaError(f"{child_path} description is required")
        if "type" not in child:
            raise ToolSchemaError(f"{child_path} type is required")
        if child.get("type") == "object":
            _validate_property_descriptions(child, child_path)

