"""Tool registry. Later modules add their tools to ``TOOLS``."""

from .registry import Tool, validate_arguments

TOOLS: dict[str, Tool] = {}

__all__ = ["TOOLS", "Tool", "validate_arguments"]
