"""Restricted MCP endpoint for agent-to-agent delegation.

Exposes only the tools a sub-agent needs to discover siblings and delegate
work — no agent creation, mutation, skill installation, or blocking prompts.
"""

from mcp.server.fastmcp import FastMCP

from src.mcp_server import (
    check_task_status,
    delegate_task,
    get_agent_logs,
    get_agents,
)

delegate_mcp = FastMCP(
    "orcai-mcp-delegate",
    instructions="Delegate tasks to sibling agents and check their status",
)

delegate_mcp.tool()(get_agents)
delegate_mcp.tool()(delegate_task)
delegate_mcp.tool()(check_task_status)
delegate_mcp.tool()(get_agent_logs)
