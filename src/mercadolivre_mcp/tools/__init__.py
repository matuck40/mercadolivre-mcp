"""Tool registry. Later modules add their tools to ``TOOLS``."""

from .read import READ_TOOLS
from .registry import Tool, validate_arguments
from .write import WRITE_TOOLS

TOOLS: dict[str, Tool] = {}

for _tool in (*READ_TOOLS, *WRITE_TOOLS):
    TOOLS[_tool.name] = _tool

__all__ = ["TOOLS", "Tool", "validate_arguments"]
