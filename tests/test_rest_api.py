import os

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(async_client: AsyncClient) -> None:
    r = await async_client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "agents" in data


@pytest.mark.asyncio
async def test_create_and_list_agent(async_client: AsyncClient) -> None:
    r = await async_client.post(
        "/api/v1/agents",
        json={"name": "TestAgent", "role": "tester", "system_prompt": "You are a tester."},
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]
    assert agent_id

    r = await async_client.get("/api/v1/agents")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["agents"][0]["name"] == "TestAgent"


@pytest.mark.asyncio
async def test_patch_agent(async_client: AsyncClient) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "PatchMe", "role": "dev"})
    agent_id = r.json()["id"]

    r = await async_client.patch(f"/api/v1/agents/{agent_id}", json={"role": "frontend"})
    assert r.status_code == 200
    assert r.json()["role"] == "frontend"


@pytest.mark.asyncio
async def test_delete_agent(async_client: AsyncClient) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "DeleteMe"})
    agent_id = r.json()["id"]

    r = await async_client.delete(f"/api/v1/agents/{agent_id}")
    assert r.status_code == 204

    r = await async_client.get("/api/v1/agents")
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_patch_agent_not_found(async_client: AsyncClient) -> None:
    r = await async_client.patch("/api/v1/agents/nonexistent", json={"role": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delegate_task_and_check_status(async_client: AsyncClient, mock_api_runner) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "Worker", "role": "worker"})
    agent_id = r.json()["id"]

    r = await async_client.post(
        "/api/v1/tasks/delegate",
        json={"agent_id": agent_id, "description": "Do something", "priority": 3},
    )
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    assert task_id

    r = await async_client.get(f"/api/v1/tasks/{task_id}/status")
    assert r.status_code == 200
    assert r.json()["task_id"] == task_id


@pytest.mark.asyncio
async def test_delegate_task_agent_not_found(async_client: AsyncClient) -> None:
    r = await async_client.post(
        "/api/v1/tasks/delegate",
        json={"agent_id": "doesnotexist", "description": "nope"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks(async_client: AsyncClient, mock_api_runner) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "Lister"})
    agent_id = r.json()["id"]
    await async_client.post(
        "/api/v1/tasks/delegate",
        json={"agent_id": agent_id, "description": "task1"},
    )

    r = await async_client.get("/api/v1/tasks")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


@pytest.mark.asyncio
async def test_install_and_list_skills(async_client: AsyncClient) -> None:
    r = await async_client.post(
        "/api/v1/skills/install",
        json={"name": "my-skill", "description": "A test skill", "content": "# Skill\nDo X"},
    )
    assert r.status_code == 201
    assert r.json()["skill_id"]

    r = await async_client.get("/api/v1/skills")
    assert r.status_code == 200
    assert r.json()["total"] == 1


@pytest.mark.asyncio
async def test_dashboard_stats(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/dashboard/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_agents" in data
    assert "active_agents" in data
    assert "queue_depth" in data


@pytest.mark.asyncio
async def test_agent_logs_empty(async_client: AsyncClient) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "LogAgent", "role": "tester"})
    agent_id = r.json()["id"]

    r = await async_client.get(f"/api/v1/agents/{agent_id}/logs")
    assert r.status_code == 200
    data = r.json()
    assert data["agent_id"] == agent_id
    assert data["total"] == 0
    assert data["logs"] == []


@pytest.mark.asyncio
async def test_agent_logs_with_tasks(async_client: AsyncClient, mock_api_runner) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "LogWorker", "role": "worker"})
    agent_id = r.json()["id"]

    for desc in ("First task", "Second task"):
        await async_client.post(
            "/api/v1/tasks/delegate",
            json={"agent_id": agent_id, "description": desc},
        )

    r = await async_client.get(f"/api/v1/agents/{agent_id}/logs")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    entry = data["logs"][0]
    assert "task_id" in entry
    assert "status" in entry
    assert "description" in entry
    assert "response" in entry
    assert "error" in entry
    assert "started_at" in entry
    assert "completed_at" in entry


@pytest.mark.asyncio
async def test_agent_logs_tail(async_client: AsyncClient, mock_api_runner) -> None:
    r = await async_client.post("/api/v1/agents", json={"name": "TailAgent", "role": "worker"})
    agent_id = r.json()["id"]

    for i in range(5):
        await async_client.post(
            "/api/v1/tasks/delegate",
            json={"agent_id": agent_id, "description": f"Task {i}"},
        )

    r = await async_client.get(f"/api/v1/agents/{agent_id}/logs?tail=2")
    assert r.status_code == 200
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_agent_logs_not_found(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/agents/nonexistent/logs")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_active_agents(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/agents/active")
    assert r.status_code == 200
    assert "active_count" in r.json()


@pytest.mark.asyncio
async def test_ui_served(async_client: AsyncClient) -> None:
    """GET /ui should return 200 when the React build exists."""
    build_dir = os.path.join(os.path.dirname(__file__), "..", "ui", "build")
    if not os.path.isdir(build_dir):
        pytest.skip("UI build not present")
    # The MCP catch-all mount at "/" intercepts "/ui" before Starlette's
    # redirect_slashes can redirect it to "/ui/", so request "/ui/" directly.
    r = await async_client.get("/ui/")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_mcp_endpoint_reachable(async_client: AsyncClient) -> None:
    """GET /mcp should respond (MCP handshake or redirect — not 404)."""
    r = await async_client.get("/mcp", follow_redirects=False)
    assert r.status_code != 404
