"""HTTP-level e2e tests using the async_client fixture.

Each test drives the full ASGI stack (FastAPI + FastMCP) in-process.
All tests verify that the filesystem (not the DB) is the source of truth for agents/skills.
"""
import sqlite3
from pathlib import Path

import frontmatter
import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


async def test_health_returns_ok(async_client):
    r = await async_client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


async def test_health_counts_agents_from_filesystem(async_client, claude_dir_path):
    # No agents yet
    r = await async_client.get("/health")
    assert r.json()["agents"] == 0

    # Create two agents directly on disk
    import src.agent_registry as reg
    reg.write_agent("h1", name="H1")
    reg.write_agent("h2", name="H2")

    r = await async_client.get("/health")
    assert r.json()["agents"] == 2


# ---------------------------------------------------------------------------
# POST /api/v1/agents — create
# ---------------------------------------------------------------------------


async def test_create_agent_writes_md_file(async_client, claude_dir_path):
    r = await async_client.post("/api/v1/agents", json={
        "name": "Backend Dev",
        "role": "backend",
        "system_prompt": "You write Python.",
        "config": {"runner": "api"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "backend-dev"
    assert body["name"] == "Backend Dev"
    assert body["status"] == "idle"

    # Verify .md file exists on disk with correct frontmatter
    md_path = Path(claude_dir_path) / "agents" / "backend-dev.md"
    assert md_path.exists()
    with open(md_path) as f:
        post = frontmatter.load(f)
    assert post.metadata["role"] == "backend"
    assert post.metadata["runner"] == "api"
    assert post.content == "You write Python."


async def test_create_agent_conflict_returns_error(async_client, claude_dir_path):
    await async_client.post("/api/v1/agents", json={"name": "Dupe Agent"})
    r2 = await async_client.post("/api/v1/agents", json={"name": "Dupe Agent"})
    assert r2.status_code >= 400


# ---------------------------------------------------------------------------
# GET /api/v1/agents — list
# ---------------------------------------------------------------------------


async def test_list_agents_reflects_filesystem(async_client, claude_dir_path):
    import src.agent_registry as reg
    reg.write_agent("list-agent", name="List Agent", role="tester")

    r = await async_client.get("/api/v1/agents")
    assert r.status_code == 200
    slugs = [a["id"] for a in r.json()["agents"]]
    assert "list-agent" in slugs


async def test_list_agents_filter_by_role(async_client, claude_dir_path):
    import src.agent_registry as reg
    reg.write_agent("ra1", name="RA1", role="backend")
    reg.write_agent("ra2", name="RA2", role="frontend")

    r = await async_client.get("/api/v1/agents", params={"role": "backend"})
    assert r.status_code == 200
    slugs = [a["id"] for a in r.json()["agents"]]
    assert "ra1" in slugs
    assert "ra2" not in slugs


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{id} — single agent
# ---------------------------------------------------------------------------


async def test_get_single_agent(async_client, claude_dir_path):
    import src.agent_registry as reg
    reg.write_agent("single", name="Single Agent", system_prompt="Do one thing.")

    r = await async_client.get("/api/v1/agents/single")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "single"
    assert data["system_prompt"] == "Do one thing."


async def test_get_agent_not_found(async_client, claude_dir_path):
    r = await async_client.get("/api/v1/agents/does-not-exist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/agents/{id} — update
# ---------------------------------------------------------------------------


async def test_patch_agent_updates_md_frontmatter(async_client, claude_dir_path):
    import src.agent_registry as reg
    reg.write_agent("patch-me", name="Patch Me", role="old", system_prompt="Old prompt.")

    r = await async_client.patch("/api/v1/agents/patch-me", json={"role": "new"})
    assert r.status_code == 200
    assert r.json()["role"] == "new"

    # Verify disk
    md_path = Path(claude_dir_path) / "agents" / "patch-me.md"
    with open(md_path) as f:
        post = frontmatter.load(f)
    assert post.metadata["role"] == "new"
    assert post.content == "Old prompt."


async def test_patch_system_prompt_preserves_frontmatter(async_client, claude_dir_path):
    import src.agent_registry as reg
    reg.write_agent("sp-test", name="SP Test", role="worker", system_prompt="Old body.")

    r = await async_client.patch("/api/v1/agents/sp-test", json={"system_prompt": "New body."})
    assert r.status_code == 200

    md_path = Path(claude_dir_path) / "agents" / "sp-test.md"
    with open(md_path) as f:
        post = frontmatter.load(f)
    assert post.content == "New body."
    assert post.metadata["role"] == "worker"


async def test_patch_agent_not_found(async_client, claude_dir_path):
    r = await async_client.patch("/api/v1/agents/ghost", json={"role": "x"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/agents/{id}
# ---------------------------------------------------------------------------


async def test_delete_agent_removes_file_and_state(async_client, claude_dir_path, db_path):
    import src.agent_registry as reg
    reg.write_agent("del-me", name="Del Me")

    r = await async_client.delete("/api/v1/agents/del-me")
    assert r.status_code == 204

    # File removed
    md_path = Path(claude_dir_path) / "agents" / "del-me.md"
    assert not md_path.exists()

    # agents_state row removed
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT slug FROM agents_state WHERE slug='del-me'").fetchone()
    assert row is None
    conn.close()


async def test_delete_agent_not_found(async_client, claude_dir_path):
    r = await async_client.delete("/api/v1/agents/ghost")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/tasks/delegate + GET status
# ---------------------------------------------------------------------------


async def test_delegate_task_completes(async_client, claude_dir_path, mock_api_runner):
    # Create an agent first
    await async_client.post("/api/v1/agents", json={
        "name": "Task Runner",
        "role": "worker",
        "config": {"runner": "api"},
    })

    # Delegate a task
    r = await async_client.post("/api/v1/tasks/delegate", json={
        "agent_id": "task-runner",
        "description": "Do something useful.",
        "priority": 3,
    })
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    assert task_id

    # Poll for completion (mock runner is instant)
    import asyncio
    for _ in range(20):
        status_r = await async_client.get(f"/api/v1/tasks/{task_id}/status")
        if status_r.json()["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.05)

    status_r = await async_client.get(f"/api/v1/tasks/{task_id}/status")
    assert status_r.json()["status"] == "completed"
    assert status_r.json()["output"]["text"] == "Mock agent response"


async def test_delegate_to_missing_agent_returns_404(async_client, claude_dir_path):
    r = await async_client.post("/api/v1/tasks/delegate", json={
        "agent_id": "nonexistent",
        "description": "Do something.",
    })
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/skills/install
# ---------------------------------------------------------------------------


async def test_install_skill_writes_skill_md(async_client, claude_dir_path):
    r = await async_client.post("/api/v1/skills/install", json={
        "name": "my-skill",
        "description": "A great skill",
        "content": "# Skill\nDo great things.",
        "version": "1.2.3",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["skill_id"] == "my-skill"

    skill_path = Path(claude_dir_path) / "skills" / "my-skill" / "SKILL.md"
    assert skill_path.exists()
    with open(skill_path) as f:
        post = frontmatter.load(f)
    assert post.metadata["version"] == "1.2.3"
    assert "Do great things" in post.content


async def test_install_skill_assigns_to_agent(async_client, claude_dir_path):
    # Create agent first
    await async_client.post("/api/v1/agents", json={
        "name": "Skill Receiver",
        "role": "tester",
    })

    r = await async_client.post("/api/v1/skills/install", json={
        "name": "assigned-skill",
        "description": "Assigned skill",
        "content": "Skill content.",
        "assign_to": ["skill-receiver"],
    })
    assert r.status_code == 201
    assert "skill-receiver" in r.json()["assigned_to"]

    # Verify agent .md frontmatter updated on disk
    md_path = Path(claude_dir_path) / "agents" / "skill-receiver.md"
    with open(md_path) as f:
        post = frontmatter.load(f)
    assert "assigned-skill" in post.metadata["skills"]


# ---------------------------------------------------------------------------
# GET /api/v1/skills
# ---------------------------------------------------------------------------


async def test_list_skills_returns_installed(async_client, claude_dir_path):
    await async_client.post("/api/v1/skills/install", json={
        "name": "list-skill",
        "description": "Listed",
        "content": "Content.",
    })
    r = await async_client.get("/api/v1/skills")
    assert r.status_code == 200
    names = [s["id"] for s in r.json()["skills"]]
    assert "list-skill" in names


# ---------------------------------------------------------------------------
# GET /api/v1/dashboard/stats
# ---------------------------------------------------------------------------


async def test_dashboard_stats(async_client, claude_dir_path):
    import src.agent_registry as reg
    reg.write_agent("stat-agent", name="Stat Agent")

    r = await async_client.get("/api/v1/dashboard/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_agents"] >= 1
    assert "queued_tasks" in data
    assert "active_agents" in data
