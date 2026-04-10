import pytest

from src.mcp_server import (
    _get_agent_logs,
    add_agent,
    check_task_status,
    delegate_task,
    get_active_agents,
    get_agent_logs,
    get_agents,
    install_skill,
    update_agent,
)


@pytest.mark.asyncio
async def test_add_agent(db_path) -> None:
    result = await add_agent(
        name="DevAgent",
        role="backend",
        system_prompt="You write Python.",
        model_preference="claude-sonnet-4-6",
    )
    assert result["name"] == "DevAgent"
    assert result["status"] == "idle"
    assert "id" in result


@pytest.mark.asyncio
async def test_get_agents(db_path) -> None:
    await add_agent(name="A", role="frontend")
    await add_agent(name="B", role="backend")

    result = await get_agents()
    assert result["total"] == 2

    result = await get_agents(role="frontend")
    assert result["total"] == 1
    assert result["agents"][0]["name"] == "A"


@pytest.mark.asyncio
async def test_update_agent(db_path) -> None:
    created = await add_agent(name="UpdAgent", role="old-role")
    agent_id = created["id"]

    updated = await update_agent(agent_id=agent_id, role="new-role", status="disabled")
    assert updated["role"] == "new-role"
    assert updated["status"] == "disabled"


@pytest.mark.asyncio
async def test_update_agent_not_found(db_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await update_agent(agent_id="nonexistent", role="x")


@pytest.mark.asyncio
async def test_get_active_agents(db_path) -> None:
    result = await get_active_agents()
    assert result["active_count"] == 0
    assert "queue_depth" in result


@pytest.mark.asyncio
async def test_delegate_task_queues(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="Delegatee", role="worker")
    result = await delegate_task(
        agent_id=agent["id"],
        description="Do work",
        priority=3,
    )
    assert result["task_id"]
    assert result["status"] in ("queued", "running")


@pytest.mark.asyncio
async def test_check_task_status(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="Checker")
    task = await delegate_task(agent_id=agent["id"], description="Check me")
    status = await check_task_status(task["task_id"])
    assert status["task_id"] == task["task_id"]
    assert "status" in status


@pytest.mark.asyncio
async def test_check_task_status_not_found(db_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await check_task_status("nonexistent")


@pytest.mark.asyncio
async def test_install_skill(db_path) -> None:
    result = await install_skill(
        name="react-component",
        description="Creates React components",
        content="# React Component Skill\nCreate functional components.",
        version="1.0.0",
    )
    assert result["skill_id"]
    assert "react-component.md" in result["file_path"]
    assert result["assigned_to"] == []


@pytest.mark.asyncio
async def test_get_agent_logs_empty(db_path) -> None:
    agent = await add_agent(name="LogAgent", role="tester")
    result = await get_agent_logs(agent_id=agent["id"])
    assert result["agent_id"] == agent["id"]
    assert result["total"] == 0
    assert result["logs"] == []


@pytest.mark.asyncio
async def test_get_agent_logs_with_tasks(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="LogAgent2", role="worker")
    await delegate_task(agent_id=agent["id"], description="Task one")
    await delegate_task(agent_id=agent["id"], description="Task two")

    result = await get_agent_logs(agent_id=agent["id"])
    assert result["total"] == 2
    log_descriptions = [e["description"] for e in result["logs"]]
    assert "Task one" in log_descriptions
    assert "Task two" in log_descriptions
    first = result["logs"][0]
    assert "task_id" in first
    assert "status" in first
    assert "started_at" in first
    assert "completed_at" in first
    assert "error" in first
    assert "response" in first


@pytest.mark.asyncio
async def test_get_agent_logs_tail(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="LogAgent3", role="worker")
    for i in range(5):
        await delegate_task(agent_id=agent["id"], description=f"Task {i}")

    result = await get_agent_logs(agent_id=agent["id"], tail=3)
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_get_agent_logs_tail_capped(db_path) -> None:
    agent = await add_agent(name="LogAgent4", role="worker")
    # tail > 200 should be silently capped — no error
    result = await _get_agent_logs(agent["id"], tail=9999)
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_get_agent_logs_not_found(db_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await get_agent_logs(agent_id="nonexistent")


@pytest.mark.asyncio
async def test_install_skill_and_assign(db_path) -> None:
    agent = await add_agent(name="FrontendDev", role="frontend")
    result = await install_skill(
        name="tailwind",
        description="Tailwind helpers",
        content="# Tailwind",
        assign_to=[agent["id"]],
    )
    assert agent["id"] in result["assigned_to"]
