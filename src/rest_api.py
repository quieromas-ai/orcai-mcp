import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from fastapi import APIRouter, HTTPException

from src.config import settings
from src.database import get_db, parse_json_fields, row_to_dict
from src.mcp_server import (
    add_agent,
    check_task_status,
    delegate_task,
    get_active_agents,
    get_agents,
    install_skill,
    prompt_agent,
    update_agent,
)
from src.models import AgentCreate, AgentUpdate, DashboardStats, SkillCreate, TaskCreate
from src.skill_manager import get_skills
from src.task_engine import task_engine

router = APIRouter()


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(role: str | None = None, status: str | None = None) -> dict[str, Any]:
    return cast(dict[str, Any], await get_agents(role=role, status=status))


@router.post("/agents", status_code=201)
async def create_agent(body: AgentCreate) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        await add_agent(
            name=body.name,
            role=body.role,
            system_prompt=body.system_prompt,
            model_preference=body.model_preference,
            config=body.config,
        ),
    )


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentUpdate) -> dict[str, Any]:
    try:
        return cast(
            dict[str, Any],
            await update_agent(
                agent_id=agent_id,
                name=body.name,
                role=body.role,
                system_prompt=body.system_prompt,
                model_preference=body.model_preference,
                status=body.status,
                config=body.config,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str) -> None:
    db = await get_db()
    async with db.execute("SELECT id FROM agents WHERE id=?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    await db.execute("DELETE FROM agents WHERE id=?", (agent_id,))
    await db.commit()


@router.get("/agents/active")
async def list_active_agents() -> dict[str, Any]:
    return cast(dict[str, Any], await get_active_agents())


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    db = await get_db()
    async with db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return parse_json_fields(row_to_dict(row), "config", "skills")


@router.post("/agents/{agent_id}/prompt")
async def prompt_agent_endpoint(
    agent_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        return cast(
            dict[str, Any],
            await prompt_agent(
                agent_id=agent_id,
                message=body.get("message", ""),
                context=body.get("context"),
                wait=body.get("wait", True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/agents/{agent_id}/health")
async def agent_health(agent_id: str) -> dict[str, Any]:
    db = await get_db()
    async with db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    agent = parse_json_fields(row_to_dict(row), "config", "skills")

    config: dict[str, Any] = agent.get("config") or {}
    default_runner = "cli" if settings.ide_target == "claude" else "api"
    runner_type = config.get("runner", default_runner)

    if runner_type == "api":
        api_key = settings.anthropic_api_key
        if not api_key:
            return {"agent_id": agent_id, "healthy": False, "reason": "ANTHROPIC_API_KEY not set"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
            return {"agent_id": agent_id, "healthy": r.status_code == 200}
        except Exception as exc:
            return {"agent_id": agent_id, "healthy": False, "reason": str(exc)}
    else:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return {"agent_id": agent_id, "healthy": proc.returncode == 0}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.post("/tasks/delegate", status_code=202)
async def delegate(body: TaskCreate) -> dict[str, Any]:
    try:
        return cast(
            dict[str, Any],
            await delegate_task(
                agent_id=body.agent_id,
                description=body.description,
                input_context=body.input_context,
                priority=body.priority,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/tasks/{task_id}/status")
async def task_status(task_id: str) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], await check_task_status(task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    db = await get_db()
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status=?"
        params.append(status)
    if agent_id:
        query += " AND agent_id=?"
        params.append(agent_id)
    query += " ORDER BY created_at DESC LIMIT 200"
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    tasks = [parse_json_fields(row_to_dict(r), "input_context", "output") for r in rows]
    return {"tasks": tasks, "total": len(tasks)}


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


@router.post("/skills/install", status_code=201)
async def install_skill_endpoint(body: SkillCreate) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        await install_skill(
            name=body.name,
            description=body.description,
            content=body.content,
            version=body.version,
            assign_to=body.assign_to,
        ),
    )


@router.get("/skills")
async def list_skills() -> dict[str, Any]:
    skills = await get_skills()
    return {"skills": skills, "total": len(skills)}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard/stats")
async def dashboard_stats() -> DashboardStats:
    db = await get_db()
    today = datetime.now(UTC).date().isoformat()
    async with db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM agents)                                    AS total_agents,
            (SELECT COUNT(*) FROM agents WHERE status='busy')               AS active_agents,
            (SELECT COUNT(*) FROM tasks WHERE status='queued')              AS queued_tasks,
            (SELECT COUNT(*) FROM skills)                                    AS total_skills,
            (SELECT COUNT(*) FROM tasks WHERE date(created_at)=?)           AS tasks_today
        """,
        (today,),
    ) as cur:
        row = await cur.fetchone()
    return DashboardStats(
        total_agents=row[0] if row else 0,
        active_agents=row[1] if row else 0,
        queued_tasks=row[2] if row else 0,
        total_skills=row[3] if row else 0,
        tasks_today=row[4] if row else 0,
        queue_depth=task_engine.queue_depth(),
    )
