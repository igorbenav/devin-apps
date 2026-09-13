"""Shared platform layer: roles, permissions, audit trail, tool registry, UI shell.

Every internal tool under ``src.modules.tools`` depends on this module and
nothing depends on the tools themselves.
"""

from .registry import ToolSpec, register, registered_tools, tools_for

__all__ = ["ToolSpec", "register", "registered_tools", "tools_for"]
