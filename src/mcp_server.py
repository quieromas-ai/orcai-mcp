import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.config import settings
from src.database import fetch_agent, get_db, parse_json_fields, row_to_dict
from src.skill_manager import get_skills
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
    return datetime.now(UTC).isoformat()


async def _get_agent(agent_id: str) -> dict[str, Any]:
    return await fetch_agent(agent_id)


async def _get_task(task_id: str) -> dict[str, Any]:
    db = await get_db()
    async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise ValueError(f"Task '{task_id}' not found")
    return parse_json_fields(row_to_dict(row), "input_context", "output")


async def _get_agent_logs(agent_id: str, tail: int) -> dict[str, Any]:
    await _get_agent(agent_id)
    tail = min(max(tail, 1), 200)
    db = await get_db()
    async with db.execute(
        "SELECT * FROM tasks WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
        (agent_id, tail),
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
    return {"agent_id": agent_id, "total": len(logs), "logs": logs}


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
) -> dict[str, Any]:
    """Register a new sub-agent.

    Args:
        name: Human-readable label for the agent.
        role: Functional role used for filtering (e.g. "backend", "reviewer").
        system_prompt: Instructions prepended to every task this agent receives.
        model_preference: Claude model slug (default: claude-sonnet-4-6).
        config: Optional overrides — most useful key is "runner": "cli" to use the
                Claude Code CLI subprocess instead of the Anthropic Messages API.

    Returns:
        {"id", "name", "status": "idle", "created_at"}
    """
    db = await get_db()
    agent_id = str(uuid.uuid4())
    now = _now()
    cfg = config or {}
    await db.execute(
        """
        INSERT INTO agents (id, name, role, status, system_prompt, model_preference,
                            runner, skills, config, created_at, updated_at)
        VALUES (?, ?, ?, 'idle', ?, ?, ?, '[]', ?, ?, ?)
        """,
        (
            agent_id, name, role, system_prompt, model_preference,
            cfg.get("runner", "api"), json.dumps(cfg), now, now,
        ),
    )
    await db.commit()
    return {"id": agent_id, "name": name, "status": "idle", "created_at": now}


@mcp.tool()
async def update_agent(
    agent_id: str,
    name: str | None = None,
    role: str | None = None,
    system_prompt: str | None = None,
    model_preference: str | None = None,
    status: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update any field on an existing agent. Pass only the fields to change.

    Args:
        agent_id: ID returned by add_agent.
        status: Valid values are "idle", "busy", or "offline".
        config: Merged (not replaced) into the existing config dict.

    Returns:
        Full updated agent record.
    """
    agent = await _get_agent(agent_id)
    db = await get_db()
    now = _now()

    updates: list[tuple[str, Any]] = [("updated_at", now)]
    if name is not None:
        updates.append(("name", name))
    if role is not None:
        updates.append(("role", role))
    if system_prompt is not None:
        updates.append(("system_prompt", system_prompt))
    if model_preference is not None:
        updates.append(("model_preference", model_preference))
    if status is not None:
        updates.append(("status", status))
    if config is not None:
        merged = {**agent["config"], **config}
        updates.append(("config", json.dumps(merged)))
        if "runner" in config:
            updates.append(("runner", config["runner"]))

    set_clause = ", ".join(f"{col}=?" for col, _ in updates)
    values = [v for _, v in updates] + [agent_id]
    await db.execute(f"UPDATE agents SET {set_clause} WHERE id=?", values)
    await db.commit()
    return await _get_agent(agent_id)


@mcp.tool()
async def get_agents(
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List all registered agents. Optionally filter by role or status."""
    db = await get_db()
    query = "SELECT * FROM agents WHERE 1=1"
    params: list[Any] = []
    if role:
        query += " AND role=?"
        params.append(role)
    if status:
        query += " AND status=?"
        params.append(status)
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    agents = [parse_json_fields(row_to_dict(r), "config", "skills") for r in rows]
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
    agent_id: str,
    description: str,
    input_context: dict[str, Any] | None = None,
    priority: int = 3,
    max_retries: int = 0,
) -> dict[str, Any]:
    """Assign a task to a specific agent. Returns immediately — the task runs in the
    background. If the agent is busy or the concurrency limit is reached the task is
    queued; use check_task_status to poll for completion.

    Args:
        agent_id: Target agent ID.
        description: The task instruction sent to the agent as its user message.
        input_context: Optional JSON dict injected below the description.
        priority: 1 (lowest) – 5 (highest). Default 3. Higher-priority tasks are
                  dequeued first when a worker slot opens.
        max_retries: How many times to automatically retry on failure. Default 0.

    Returns:
        {"task_id", "status": "queued"|"running", "position": <queue depth>}
        or {"error", "status": "rejected"} if the queue is full.
    """
    await _get_agent(agent_id)  # validates agent exists
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
        (task_id, agent_id, description, priority, json.dumps(ctx), max_retries, now),
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

    await asyncio.sleep(0)  # yield to let worker pick up task
    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    status = row[0] if row else "queued"
    return {"task_id": task_id, "status": status, "position": task_engine.queue_depth()}


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
    agent_id: str,
    tail: int = 50,
) -> dict[str, Any]:
    """Return the last N task records for an agent as a structured activity log.

    Args:
        agent_id: Agent to retrieve logs for.
        tail: Number of most-recent entries to return (default 50, max 200).

    Returns:
        {"agent_id", "total": int,
         "logs": [{"task_id", "status", "description", "response": str|null,
                   "error": str|null, "started_at", "completed_at"}]}
    """
    return await _get_agent_logs(agent_id, tail)


@mcp.tool()
async def install_skill(
    name: str,
    description: str = "",
    content: str = "",
    version: str = "1.0.0",
    assign_to: list[str] | None = None,
) -> dict[str, Any]:
    """Install a skill (markdown file) into the shared skills library.

    Args:
        name: Unique skill identifier — also used as the filename (<name>.md).
        description: One-line summary shown when listing available skills.
        content: Full markdown content of the skill.
        version: Semantic version string. Default "1.0.0".
        assign_to: Optional list of agent IDs to immediately attach this skill to.

    Returns:
        {"skill_id", "file_path", "assigned_to": [agent_id, ...]}
    """
    return await _install_skill(name, description, content, version, assign_to)


@mcp.tool()
async def prompt_agent(
    agent_id: str,
    message: str,
    context: dict[str, Any] | None = None,
    wait: bool = True,
) -> dict[str, Any]:
    """Send an ad-hoc prompt to an agent.

    Args:
        agent_id: Target agent ID.
        message: The prompt to send.
        context: Optional JSON dict appended to the message as extra context.
        wait: If True (default), polls until the task completes (up to 5 minutes)
              and returns the full response. Set to False to return immediately with
              just the task_id so you can poll via check_task_status yourself — useful
              for fire-and-forget jobs or when you want to run multiple agents in
              parallel without blocking.

    Returns:
        wait=True:  {"agent_id", "response": str, "tokens_used": int,
                     "status": "completed"|"failed"|"cancelled", "error": str | null}
        wait=False: {"task_id", "status": "running"}
    """
    result = await delegate_task(
        agent_id=agent_id,
        description=message,
        input_context=context,
        priority=4,
    )
    if not wait:
        return {"task_id": result.get("task_id"), "status": "running"}

    task_id = result.get("task_id")
    if not task_id:
        return cast(dict[str, Any], result)

    # Poll until done (max 5 min)
    status: dict[str, Any] = {"status": "running"}
    for _ in range(300):
        await asyncio.sleep(1)
        status = await check_task_status(task_id)
        if status["status"] in ("completed", "failed", "cancelled"):
            break

    output = status.get("output") or {}
    return {
        "agent_id": agent_id,
        "response": output.get("text", ""),
        "tokens_used": output.get("tokens_used", 0),
        "status": status["status"],
        "error": status.get("error"),
    }


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
    agent = await _get_agent(agent_id)
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
    skills = await get_skills()
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
3. Call delegate_task(agent_id=<chosen_id>, description="{task_description}") to assign the work.
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

Return the created agent's ID for future task delegation."""
