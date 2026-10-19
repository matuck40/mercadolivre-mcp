"""Tool definition and a small JSON Schema subset validator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..errors import ToolInputError

if TYPE_CHECKING:
    from ..client import MLClient


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict
    annotations: dict
    handler: Callable[[MLClient, dict], dict]

    def to_mcp(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": self.annotations,
        }


_TYPE_NAMES = {
    "string": "a string",
    "integer": "an integer",
    "boolean": "a boolean",
    "object": "an object",
}


def _is_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _fail(what: str) -> ToolInputError:
    return ToolInputError(f"Invalid arguments: {what}")


def _check_value(name: str, value: Any, spec: dict) -> None:
    expected = spec.get("type")
    if expected is not None and not _is_type(value, expected):
        raise _fail(f"'{name}' must be {_TYPE_NAMES.get(expected, expected)}")
    if "enum" in spec and value not in spec["enum"]:
        options = ", ".join(repr(o) for o in spec["enum"])
        raise _fail(f"'{name}' must be one of {options}")
    if expected == "integer":
        if "minimum" in spec and value < spec["minimum"]:
            raise _fail(f"'{name}' must be >= {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise _fail(f"'{name}' must be <= {spec['maximum']}")
    if expected == "string":
        if "minLength" in spec and len(value) < spec["minLength"]:
            raise _fail(f"'{name}' must be at least {spec['minLength']} characters")
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            raise _fail(f"'{name}' must be at most {spec['maxLength']} characters")


def validate_arguments(schema: dict, args: Any) -> dict:
    """Validate ``args`` against ``schema`` and return a new dict with defaults applied."""
    if not isinstance(args, dict):
        raise _fail("arguments must be an object")
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            raise _fail(f"missing required argument '{name}'")
    if schema.get("additionalProperties") is False:
        for name in args:
            if name not in props:
                raise _fail(f"unknown argument '{name}'")
    result = dict(args)
    for name, spec in props.items():
        if name in result:
            _check_value(name, result[name], spec)
        elif "default" in spec:
            result[name] = spec["default"]
    return result
