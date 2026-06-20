from pathlib import Path

import frontmatter
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
    assert result["id"] == "devagent"  # slug-based id


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
async def test_get_agents_excludes_untagged(db_path, claude_dir_path) -> None:
    # add_agent auto-stamps the discovery flag -> discoverable
    await add_agent(name="Mine", role="dev")
    # a foreign (e.g. Slack-only) agent with no flag must not be discovered
    foreign = Path(claude_dir_path) / "agents" / "foreign.md"
    foreign.write_text(frontmatter.dumps(frontmatter.Post("body", name="foreign")))

    result = await get_agents()
    slugs = [a["id"] for a in result["agents"]]
    assert "mine" in slugs
    assert "foreign" not in slugs
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_add_agent_then_get_agents_shows_it(db_path) -> None:
    await add_agent(name="NewOne", role="dev")
    result = await get_agents()
    assert "newone" in [a["id"] for a in result["agents"]]


@pytest.mark.asyncio
async def test_update_agent(db_path) -> None:
    await add_agent(name="UpdAgent", role="old-role")
    agent_slug = "updagent"

    updated = await update_agent(agent=agent_slug, role="new-role")
    assert updated["role"] == "new-role"


@pytest.mark.asyncio
async def test_update_agent_status(db_path) -> None:
    await add_agent(name="StatusAgent", role="dev")
    slug = "statusagent"
    updated = await update_agent(agent=slug, status="disabled")
    assert updated["status"] == "disabled"


@pytest.mark.asyncio
async def test_update_agent_not_found(db_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await update_agent(agent="nonexistent", role="x")


@pytest.mark.asyncio
async def test_get_active_agents(db_path) -> None:
    result = await get_active_agents()
    assert result["active_count"] == 0
    assert "queue_depth" in result


@pytest.mark.asyncio
async def test_delegate_task_queues(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="Delegatee", role="worker")
    result = await delegate_task(
        agent=agent["id"],
        description="Do work",
        priority=3,
    )
    assert result["task_id"]
    assert result["status"] in ("queued", "running")


@pytest.mark.asyncio
async def test_check_task_status(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="Checker")
    task = await delegate_task(agent=agent["id"], description="Check me")
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
    assert result["skill_id"] == "react-component"
    assert "SKILL.md" in result["file_path"]
    assert result["assigned_to"] == []


@pytest.mark.asyncio
async def test_get_agent_logs_empty(db_path) -> None:
    agent = await add_agent(name="LogAgent", role="tester")
    result = await get_agent_logs(agent=agent["id"])
    assert result["agent_id"] == agent["id"]
    assert result["total"] == 0
    assert result["logs"] == []


@pytest.mark.asyncio
async def test_get_agent_logs_with_tasks(db_path, started_engine, mock_api_runner) -> None:
    agent = await add_agent(name="LogAgent2", role="worker")
    await delegate_task(agent=agent["id"], description="Task one")
    await delegate_task(agent=agent["id"], description="Task two")

    result = await get_agent_logs(agent=agent["id"])
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
        await delegate_task(agent=agent["id"], description=f"Task {i}")

    result = await get_agent_logs(agent=agent["id"], tail=3)
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_get_agent_logs_tail_capped(db_path) -> None:
    agent = await add_agent(name="LogAgent4", role="worker")
    result = await _get_agent_logs(agent["id"], tail=9999)
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_get_agent_logs_not_found(db_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        await get_agent_logs(agent="nonexistent")


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


@pytest.mark.asyncio
async def test_add_agent_with_memory(db_path) -> None:
    result = await add_agent(name="MemAgent", role="writer", memory="project")
    assert result["id"] == "memagent"
    agents = await get_agents()
    agent = next(a for a in agents["agents"] if a["id"] == "memagent")
    assert agent["memory"] == "project"


@pytest.mark.asyncio
async def test_update_agent_memory(db_path) -> None:
    await add_agent(name="MemUpdate", role="dev")
    updated = await update_agent(agent="memupdate", memory="user")
    assert updated["memory"] == "user"


@pytest.mark.asyncio
async def test_update_agent_memory_project(db_path) -> None:
    await add_agent(name="MemProject", role="dev")
    updated = await update_agent(agent="memproject", memory="project")
    assert updated["memory"] == "project"


@pytest.mark.asyncio
async def test_update_agent_memory_local(db_path) -> None:
    await add_agent(name="MemLocal", role="dev")
    updated = await update_agent(agent="memlocal", memory="local")
    assert updated["memory"] == "local"


@pytest.mark.asyncio
async def test_update_agent_memory_persists_across_reads(db_path) -> None:
    await add_agent(name="MemPersist", role="dev")
    await update_agent(agent="mempersist", memory="project")
    agents = await get_agents()
    agent = next(a for a in agents["agents"] if a["id"] == "mempersist")
    assert agent["memory"] == "project"


@pytest.mark.asyncio
async def test_update_agent_memory_none_leaves_existing(db_path) -> None:
    await add_agent(name="MemNone", role="dev", memory="user")
    updated = await update_agent(agent="memnone", role="writer")
    assert updated["memory"] == "user"
