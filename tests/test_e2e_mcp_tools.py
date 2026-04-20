"""MCP protocol-level e2e tests.

Verifies tool surface (all 8 documented tools present), end-to-end task flow
via Python function calls into the MCP tool layer, negative cases, and the
regression guard for the agent_id → agent parameter rename.
"""
import asyncio
import inspect

import pytest

from src.mcp_server import (
    add_agent,
    check_task_status,
    delegate_task,
    get_active_agents,
    get_agent_logs,
    get_agents,
    install_skill,
    mcp,
    prompt_agent,
    update_agent,
)

_DOCUMENTED_TOOLS = {
    "add_agent",
    "update_agent",
    "get_agents",
    "get_active_agents",
    "delegate_task",
    "check_task_status",
    "install_skill",
    "prompt_agent",
}


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_documented_tools_registered(db_path):
    """All 8 tools from README are present in the FastMCP registry."""
    tool_names = {t.name for t in (await mcp.list_tools())}
    assert _DOCUMENTED_TOOLS <= tool_names, (
        f"Missing tools: {_DOCUMENTED_TOOLS - tool_names}"
    )


# ---------------------------------------------------------------------------
# /mcp endpoint reachability (HTTP level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_endpoint_reachable(async_client):
    """POST /mcp returns a response (not 404/500)."""
    r = await async_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05",
                         "capabilities": {},
                         "clientInfo": {"name": "test", "version": "0"}}},
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    assert r.status_code not in (404, 500)


# ---------------------------------------------------------------------------
# Full task lifecycle: add → delegate → poll → completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_task_lifecycle(db_path, started_engine, mock_api_runner, claude_dir_path):
    agent = await add_agent(
        name="Lifecycle Agent",
        role="worker",
        system_prompt="You complete tasks.",
    )
    assert agent["id"] == "lifecycle-agent"
    assert agent["status"] == "idle"

    task = await delegate_task(
        agent=agent["id"],
        description="Do the lifecycle thing",
        priority=4,
    )
    task_id = task["task_id"]
    assert task_id
    assert task["status"] in ("queued", "running")

    for _ in range(40):
        status = await check_task_status(task_id)
        if status["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.05)

    status = await check_task_status(task_id)
    assert status["status"] == "completed"
    assert status["output"]["text"] == "Mock agent response"
    assert status["error"] is None
    assert status["started_at"] is not None
    assert status["completed_at"] is not None


# ---------------------------------------------------------------------------
# install_skill updates agent slugs in get_agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_skill_agent_skills_updated(db_path, claude_dir_path):
    agent = await add_agent(name="Skilled Agent", role="expert")
    result = await install_skill(
        name="typing-tutor",
        description="Teaches typing",
        content="# Typing Tutor",
        version="1.0.0",
        assign_to=[agent["id"]],
    )
    assert "typing-tutor" in result["assigned_to"] or agent["id"] in result["assigned_to"]

    agents_result = await get_agents()
    skilled = next((a for a in agents_result["agents"] if a["id"] == agent["id"]), None)
    assert skilled is not None
    assert "typing-tutor" in skilled["skills"]


# ---------------------------------------------------------------------------
# Negative: missing agent returns clean ValueError (not 500 / unhandled exc)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_to_missing_agent_raises_value_error(
    db_path, started_engine, claude_dir_path
):
    with pytest.raises(ValueError, match="not found"):
        await delegate_task(agent="does-not-exist", description="Do something")


@pytest.mark.asyncio
async def test_check_status_missing_task_raises_value_error(db_path, claude_dir_path):
    with pytest.raises(ValueError, match="not found"):
        await check_task_status("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_get_logs_missing_agent_raises_value_error(db_path, claude_dir_path):
    with pytest.raises(ValueError, match="not found"):
        await get_agent_logs(agent="ghost-agent")


# ---------------------------------------------------------------------------
# Regression guard: agent_id → agent parameter rename
# ---------------------------------------------------------------------------


def test_delegate_task_has_no_agent_id_param():
    """Regression: delegate_task must accept 'agent', not 'agent_id'."""
    sig = inspect.signature(delegate_task)
    params = set(sig.parameters)
    assert "agent" in params, "delegate_task must have 'agent' parameter"
    assert "agent_id" not in params, "delegate_task must NOT have 'agent_id' parameter"


def test_update_agent_has_no_agent_id_param():
    sig = inspect.signature(update_agent)
    params = set(sig.parameters)
    assert "agent" in params
    assert "agent_id" not in params


def test_get_agent_logs_has_no_agent_id_param():
    sig = inspect.signature(get_agent_logs)
    params = set(sig.parameters)
    assert "agent" in params
    assert "agent_id" not in params


def test_prompt_agent_has_no_agent_id_param():
    sig = inspect.signature(prompt_agent)
    params = set(sig.parameters)
    assert "agent" in params
    assert "agent_id" not in params


# ---------------------------------------------------------------------------
# add_agent: duplicate slug raises clean error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_agent_duplicate_slug_raises(db_path, claude_dir_path):
    await add_agent(name="Duplicate Me", role="dev")
    with pytest.raises(ValueError, match="already exists"):
        await add_agent(name="Duplicate Me", role="dev")


# ---------------------------------------------------------------------------
# get_agents filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agents_filter_by_role(db_path, claude_dir_path):
    await add_agent(name="Backend One", role="backend")
    await add_agent(name="Frontend One", role="frontend")

    result = await get_agents(role="backend")
    assert all(a["role"] == "backend" for a in result["agents"])
    slugs = [a["id"] for a in result["agents"]]
    assert "backend-one" in slugs
    assert "frontend-one" not in slugs


@pytest.mark.asyncio
async def test_get_active_agents_structure(db_path, claude_dir_path):
    result = await get_active_agents()
    assert "agents" in result
    assert "active_count" in result
    assert "queue_depth" in result
