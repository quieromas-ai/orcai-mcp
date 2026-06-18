import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.agent_registry import (
    _agents_dir,
    _slugify,
    get_agent,
    list_agents,
    list_skills,
    write_agent,
)
from src.agent_registry import (
    update_agent as _update_agent_file,
)
from src.config import settings
from src.database import get_db, parse_json_fields, row_to_dict
from src.skill_manager import install_skill as _install_skill
from src.task_engine import QueueFullError, task_engine

_allowed_hosts = [h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(_allowed_hosts),
    allowed_hosts=_allowed_hosts,
)

mcp = FastMCP(
    "orcai-mcp",
    instructions="Manage sub-agents, delegate tasks, install skills",
    transport_security=_transport_security,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


async def _get_task(task_id: str) -> dict[str, Any]:
    db = await get_db()
    async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise ValueError(f"Task '{task_id}' not found")
    return parse_json_fields(row_to_dict(row), "input_context", "output")


async def _enrich_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not agents:
        return agents
    db = await get_db()
    slugs = [a["id"] for a in agents]
    placeholders = ",".join("?" * len(slugs))
    async with db.execute(
        f"SELECT slug, status FROM agents_state WHERE slug IN ({placeholders})", slugs
    ) as cur:
        rows = await cur.fetchall()
    state_map = {r[0]: r[1] for r in rows}
    for agent in agents:
        agent["status"] = state_map.get(agent["id"], "idle")
    return agents


async def _get_agent_logs(agent: str, tail: int) -> dict[str, Any]:
    get_agent(agent)  # raises ValueError if not found
    tail = min(max(tail, 1), 200)
    db = await get_db()
    async with db.execute(
        "SELECT * FROM tasks WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
        (agent, tail),
    ) as cur:
        rows = await cur.fetchall()
    logs = []
    for row in rows:
        task = parse_json_fields(row_to_dict(row), "output")
        output = task.get("output") or {}
        logs.append({
            "task_id": task["id"],
            "status": task["status"],
            "description": task["description"],
            "response": output.get("text"),
            "error": task.get("error"),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
        })
    return {"agent_id": agent, "total": len(logs), "logs": logs}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def add_agent(
    name: str,
    role: str = "",
    system_prompt: str = "",
    model_preference: str = "claude-sonnet-4-6",
    config: dict[str, Any] | None = None,
    memory: str | None = None,
) -> dict[str, Any]:
    """Register a new sub-agent by writing .claude/agents/<slug>.md.

    Args:
        name: Human-readable label; also used as the filename slug.
        role: Functional role used for filtering (e.g. "backend", "reviewer").
        system_prompt: Instructions prepended to every task this agent receives.
        model_preference: Claude model slug (default: claude-sonnet-4-6).
        config: Optional overrides — most useful key is "runner": "cli" to use the
                Claude Code CLI subprocess instead of the Anthropic Messages API.
        memory: Persistent memory scope — "user", "project", or "local". When set,
                the agent reads/writes a MEMORY.md file and receives its contents in
                every system prompt.

    Returns:
        {"id", "name", "status": "idle", "created_at"}
    """
    cfg = config or {}
    slug = _slugify(name)
    if os.path.isfile(os.path.join(_agents_dir(), f"{slug}.md")):
        raise ValueError(f"Agent '{slug}' already exists — use update_agent to modify it")
    agent = write_agent(
        slug,
        name=name,
        role=role,
        system_prompt=system_prompt,
        model=model_preference,
        runner=cfg.get("runner", "api"),
        memory=memory,
    )
    return {
        "id": agent["id"], "name": agent["name"], "status": "idle",
        "created_at": agent["created_at"],
    }


@mcp.tool()
async def update_agent(
    agent: str,
    name: str | None = None,
    role: str | None = None,
    system_prompt: str | None = None,
    model_preference: str | None = None,
    status: str | None = None,
    config: dict[str, Any] | None = None,
    memory: str | None = None,
) -> dict[str, Any]:
    """Update any field on an existing agent. Pass only the fields to change.

    Args:
        agent: Slug of the agent to update (e.g. "team-leader").
        status: Valid values are "idle", "busy", or "disabled". Stored in agents_state.
        config: Merged into the existing config dict.
        memory: Persistent memory scope — "user", "project", or "local". When set,
                the agent reads/writes a MEMORY.md file and receives its contents in
                every system prompt.

    Returns:
        Full updated agent record.
    """
    updated = _update_agent_file(
        agent,
        name=name,
        role=role,
        system_prompt=system_prompt,
        model=model_preference,
        config=config,
        memory=memory,
    )
    if status is not None:
        db = await get_db()
        now = _now()
        await db.execute(
            """
            INSERT INTO agents_state (slug, status, last_run_at)
            VALUES (?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET status=excluded.status, last_run_at=excluded.last_run_at
            """,
            (agent, status, now),
        )
        await db.commit()
        updated["status"] = status
    return updated


@mcp.tool()
async def get_agents(
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List all registered agents. Optionally filter by role or status."""
    agents = await _enrich_agents(list_agents())
    if role:
        agents = [a for a in agents if a.get("role") == role]
    if status:
        agents = [a for a in agents if a.get("status") == status]
    return {"agents": agents, "total": len(agents)}


@mcp.tool()
async def get_active_agents() -> dict[str, Any]:
    """List only agents currently executing a task (status=busy)."""
    result = await get_agents(status="busy")
    return {
        "agents": result["agents"],
        "active_count": result["total"],
        "queue_depth": task_engine.queue_depth(),
    }


@mcp.tool()
async def delegate_task(
    agent: str,
    description: str,
    input_context: dict[str, Any] | None = None,
    priority: int = 3,
    max_retries: int = 0,
) -> dict[str, Any]:
    """Assign a task to a specific agent. Returns immediately — the task runs in the
    background. Use check_task_status to poll for completion.

    Args:
        agent: Target agent slug (e.g. "team-leader").
        description: The task instruction sent to the agent as its user message.
        input_context: Optional JSON dict injected below the description.
        priority: 1 (lowest) – 5 (highest). Default 3.
        max_retries: How many times to automatically retry on failure. Default 0.

    Returns:
        {"task_id", "status": "queued"|"running", "position": <queue depth>}
        or {"error", "status": "rejected"} if the queue is full.
    """
    get_agent(agent)  # raises ValueError if not found
    db = await get_db()
    task_id = str(uuid.uuid4())
    now = _now()
    ctx = input_context or {}

    await db.execute(
        """
        INSERT INTO tasks (id, agent_id, description, status, priority,
                           input_context, max_retries, created_at)
        VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
        """,
        (task_id, agent, description, priority, json.dumps(ctx), max_retries, now),
    )
    await db.commit()

    try:
        await task_engine.submit(task_id, priority)
    except QueueFullError as exc:
        await db.execute(
            "UPDATE tasks SET status='failed', error=? WHERE id=?", (str(exc), task_id)
        )
        await db.commit()
        return {"error": str(exc), "status": "rejected"}

    await asyncio.sleep(0)  # yield to event loop so worker can pick up the task
    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    task_status = row[0] if row else "queued"
    return {"task_id": task_id, "status": task_status, "position": task_engine.queue_depth()}


@mcp.tool()
async def check_task_status(task_id: str) -> dict[str, Any]:
    """Check the current status of a delegated task.

    Returns:
        {"task_id", "status": "queued"|"running"|"completed"|"failed"|"cancelled",
         "output": {"text", "tokens_used"} | null,
         "error": str | null, "started_at", "completed_at"}
    """
    task = await _get_task(task_id)
    return {
        "task_id": task["id"],
        "status": task["status"],
        "output": task.get("output"),
        "error": task.get("error"),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at"),
    }


@mcp.tool()
async def get_agent_logs(
    agent: str,
    tail: int = 50,
) -> dict[str, Any]:
    """Return the last N task records for an agent as a structured activity log.

    Args:
        agent: Agent slug to retrieve logs for (e.g. "devops").
        tail: Number of most-recent entries to return (default 50, max 200).

    Returns:
        {"agent_id", "total": int,
         "logs": [{"task_id", "status", "description", "response": str|null,
                   "error": str|null, "started_at", "completed_at"}]}
    """
    return await _get_agent_logs(agent, tail)


@mcp.tool()
async def install_skill(
    name: str,
    description: str = "",
    content: str = "",
    version: str = "1.0.0",
    assign_to: list[str] | None = None,
) -> dict[str, Any]:
    """Install a skill into .claude/skills/<name>/SKILL.md.

    Args:
        name: Unique skill identifier — also used as the directory name.
        description: One-line summary shown when listing available skills.
        content: Full markdown content of the skill.
        version: Semantic version string. Default "1.0.0".
        assign_to: Optional list of agent slugs to immediately attach this skill to.

    Returns:
        {"skill_id", "file_path", "assigned_to": [slug, ...]}
    """
    return _install_skill(name, description, content, version, assign_to)


@mcp.tool()
async def prompt_agent(
    agent: str,
    message: str,
    context: dict[str, Any] | None = None,
    wait: bool = True,
) -> dict[str, Any]:
    """Send an ad-hoc prompt to an agent.

    Args:
        agent: Target agent slug (e.g. "team-leader").
        message: The prompt to send.
        context: Optional JSON dict appended to the message as extra context.
        wait: If True (default), polls until the task completes (up to 5 minutes).
              Set to False to return immediately — poll via check_task_status.

    Returns:
        wait=True:  {"agent_id", "response": str, "tokens_used": int,
                     "status": "completed"|"failed"|"cancelled", "error": str | null}
        wait=False: {"task_id", "status": "running"}
    """
    result = await delegate_task(
        agent=agent,
        description=message,
        input_context=context,
        priority=4,
    )
    if not wait:
        return {"task_id": result.get("task_id"), "status": "running"}

    task_id = result.get("task_id")
    if not task_id:
        return cast(dict[str, Any], result)

    task_status_resp: dict[str, Any] = {}
    for _ in range(300):
        await asyncio.sleep(1)
        task_status_resp = await check_task_status(task_id)
        if task_status_resp["status"] in ("completed", "failed", "cancelled"):
            break

    output = task_status_resp.get("output") or {}
    return {
        "agent_id": agent,
        "response": output.get("text", ""),
        "tokens_used": output.get("tokens_used", 0),
        "status": task_status_resp["status"],
        "error": task_status_resp.get("error"),
    }


@mcp.tool()
async def schedule_wakeup(
    agent: str,
    delay_seconds: int,
    prompt: str,
    reason: str = "",
) -> dict[str, Any]:
    """Schedule a future task for an agent after a delay.

    The MCP server persists the wakeup in SQLite and re-delegates it as a new
    task when the delay expires — no process needs to stay alive on the agent side.

    Args:
        agent: Target agent slug (e.g. "team-leader").
        delay_seconds: Seconds to wait before dispatching the task. Clamped to [60, 86400].
        prompt: Task description sent to the agent when the wakeup fires.
        reason: Human-readable reason logged alongside the wakeup.

    Returns:
        {"wakeup_id", "agent_id", "wake_at", "delay_seconds"}
    """
    try:
        get_agent(agent)
    except ValueError:
        return {"error": f"Agent '{agent}' not found", "status": "rejected"}
    clamped = max(60, min(delay_seconds, settings.wakeup_max_delay_seconds))
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = _now()
    wake_at = (datetime.now(UTC) + timedelta(seconds=clamped)).isoformat(timespec="microseconds")

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (wakeup_id, agent, prompt, reason or None, clamped, wake_at, now),
    )
    await db.commit()
    return {
        "wakeup_id": wakeup_id,
        "agent_id": agent,
        "wake_at": wake_at,
        "delay_seconds": clamped,
        "clamped": clamped != delay_seconds,
    }


@mcp.tool()
async def cancel_wakeup(wakeup_id: str) -> dict[str, Any]:
    """Cancel a pending wakeup before it fires.

    Args:
        wakeup_id: The ID returned by schedule_wakeup.

    Returns:
        {"wakeup_id", "status": "cancelled" | "not_found" | "fired" | "already_cancelled"}
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE scheduled_wakeups SET status='cancelled' WHERE id=? AND status='pending'",
        (wakeup_id,),
    )
    await db.commit()

    if cursor.rowcount > 0:
        return {"wakeup_id": wakeup_id, "status": "cancelled"}

    # Row was not pending — report its real status (or not_found).
    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    return {"wakeup_id": wakeup_id, "status": row[0] if row else "not_found"}


@mcp.tool()
async def list_wakeups(
    agent: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List scheduled wakeups, optionally filtered by agent slug or status.

    Args:
        agent: Filter by agent slug. Omit to list all agents.
        status: Filter by status — "pending", "fired", or "cancelled". Omit for all.

    Returns:
        {"wakeups": [{wakeup_id, agent_id, prompt, reason, delay_seconds,
                      wake_at, status, created_at, fired_at}], "total": int}
    """
    db = await get_db()
    query = "SELECT id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at, fired_at FROM scheduled_wakeups"
    params: list[str] = []
    conditions: list[str] = []
    if agent:
        conditions.append("agent_id=?")
        params.append(agent)
    if status:
        conditions.append("status=?")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"

    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()

    wakeups = [
        {
            "wakeup_id": r[0], "agent_id": r[1], "prompt": r[2], "reason": r[3],
            "delay_seconds": r[4], "wake_at": r[5], "status": r[6],
            "created_at": r[7], "fired_at": r[8],
        }
        for r in rows
    ]
    return {"wakeups": wakeups, "total": len(wakeups)}


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("agents://list")
async def list_agents_resource() -> str:
    """All registered agents as JSON (read-only context for LLM)."""
    result = await get_agents()
    return json.dumps(result, indent=2)


@mcp.resource("agents://{agent_id}")
async def get_agent_resource(agent_id: str) -> str:
    """Single agent details including skills and task history."""
    agent = get_agent(agent_id)
    return json.dumps(agent, indent=2)


@mcp.resource("tasks://active")
async def active_tasks_resource() -> str:
    """All running and queued tasks."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM tasks WHERE status IN ('running','queued') ORDER BY priority DESC"
    ) as cur:
        rows = await cur.fetchall()
    tasks = [parse_json_fields(row_to_dict(r), "input_context", "output") for r in rows]
    return json.dumps({"tasks": tasks, "total": len(tasks)}, indent=2)


@mcp.resource("skills://available")
async def available_skills_resource() -> str:
    """All installed skills with descriptions."""
    skills = list_skills()
    return json.dumps({"skills": skills, "total": len(skills)}, indent=2)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@mcp.prompt()
def delegate_task_prompt(task_description: str, preferred_role: str = "") -> str:
    """Generate a structured delegation prompt that helps the LLM pick the right agent."""
    role_hint = f" with role '{preferred_role}'" if preferred_role else ""
    return f"""You are orchestrating a team of sub-agents. A new task has arrived:

Task: {task_description}

Steps:
1. Call get_agents({f'role="{preferred_role}"' if preferred_role else ''}) to list available agents\
{role_hint}.
2. Pick the most suitable idle agent based on their role and system prompt.
3. Call delegate_task(agent=<chosen_slug>, description="{task_description}") to assign the work.
4. Return the task_id and confirm the assignment.

If no suitable agent is idle, check the queue depth and either wait or create a new agent."""


@mcp.prompt()
def agent_setup_prompt(role: str, project_context: str = "") -> str:
    """Generate a prompt for creating a well-configured agent for a given role."""
    ctx = f"\n\nProject context: {project_context}" if project_context else ""
    return f"""Create a new sub-agent for the role: {role}{ctx}

Call add_agent with:
- name: A descriptive name (e.g. "{role.title()} Agent")
- role: "{role}"
- system_prompt: A detailed system prompt tailored to this role. Include:
  - The agent's primary responsibility
  - Technologies and tools it should use
  - Output format expectations
  - Any constraints or coding standards
- model_preference: "claude-sonnet-4-6" (or adjust for the task complexity)
- config: {{"runner": "api"}} for API-based execution or {{"runner": "cli"}} for Claude Code CLI

Return the created agent's slug for future task delegation."""
