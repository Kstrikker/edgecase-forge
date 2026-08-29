import pytest

from edgecase_forge.llm.capabilities import validate_tool_schema
from edgecase_forge.llm.errors import ToolSchemaError


def test_tool_schema_requires_nested_parameter_descriptions() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one repository file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
    with pytest.raises(ToolSchemaError, match="description"):
        validate_tool_schema(tool)


def test_valid_tool_schema_passes() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one repository file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative file path",
                    }
                },
                "required": ["path"],
            },
        },
    }
    validate_tool_schema(tool)

