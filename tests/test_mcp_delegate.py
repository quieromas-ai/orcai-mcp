"""Tests for the restricted delegate MCP endpoint."""

from src.mcp_delegate import delegate_mcp

ALLOWED_TOOLS = {"delegate_task", "check_task_status", "get_agents", "get_agent_logs"}
EXCLUDED_TOOLS = {"add_agent", "update_agent", "install_skill", "prompt_agent"}


def test_delegate_mcp_exposes_only_allowed_tools() -> None:
    tool_names = {t.name for t in delegate_mcp._tool_manager.list_tools()}
    assert tool_names == ALLOWED_TOOLS


def test_delegate_mcp_excludes_mutation_tools() -> None:
    tool_names = {t.name for t in delegate_mcp._tool_manager.list_tools()}
    assert tool_names.isdisjoint(EXCLUDED_TOOLS)


def test_delegate_mcp_name() -> None:
    assert delegate_mcp.name == "orcai-mcp-delegate"
