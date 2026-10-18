"""Shared error mapping for the MCP tools."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

from supertonic_server.mcp.client import SupertonicApiError


def fail(exc: SupertonicApiError) -> ToolError:
    """Turn a REST API error into a tool error that keeps the machine-readable code."""
    return ToolError(f"{exc.message} (code: {exc.code})")
