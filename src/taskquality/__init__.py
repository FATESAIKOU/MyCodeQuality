"""Deterministic ticket-level task quality metrics (stdlib only, no LLM)."""

from taskquality.formats import ToolError

__version__ = "0.4.0"
SCHEMA_VERSION = 1

__all__ = ["__version__", "SCHEMA_VERSION", "ToolError"]
