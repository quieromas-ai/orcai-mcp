import json
import os
from typing import Any

import aiosqlite

from src.agent_registry import get_agent
from src.config import settings

_db: aiosqlite.Connection | None = None

CREATE_AGENTS_STATE = """
CREATE TABLE IF NOT EXISTS agents_state (
    slug TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'idle',
    last_run_at TEXT,
    last_task_id TEXT
)
"""

CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 3,
    input_context TEXT NOT NULL DEFAULT '{}',
    output TEXT,
    error TEXT,
    max_retries INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
)
"""

CREATE_SCHEDULED_WAKEUPS = """
CREATE TABLE IF NOT EXISTS scheduled_wakeups (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    reason TEXT,
    delay_seconds INTEGER NOT NULL,
    wake_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    fired_at TEXT
)
"""


async def init_database(db_path: str = "") -> None:
    global _db
    if not db_path:
        db_path = os.path.join(settings.data_dir, "orcai.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute(CREATE_AGENTS_STATE)
    await _db.execute(CREATE_TASKS)
    await _db.execute(CREATE_SCHEDULED_WAKEUPS)
    await _db.execute(
        "CREATE INDEX IF NOT EXISTS idx_scheduled_wakeups_poll "
        "ON scheduled_wakeups (status, wake_at)"
    )
    await _db.commit()
    await _migrate_remove_agents_fk(_db)


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialised — call init_database() first")
    return _db


async def _migrate_remove_agents_fk(db: aiosqlite.Connection) -> None:
    """Drop the stale FOREIGN KEY (agent_id) REFERENCES agents(id) from tasks.

    The agents table was removed when the registry moved to .claude/ files, but
    old DBs still have the FK defined. With foreign_keys=ON every INSERT fails.
    SQLite has no DROP CONSTRAINT, so we recreate the table without it.
    """
    query = "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
    async with db.execute(query) as cur:
        row = await cur.fetchone()
    if row and "REFERENCES agents" in row[0]:
        await db.execute("ALTER TABLE tasks RENAME TO tasks_old")
        await db.execute(CREATE_TASKS)
        await db.execute(
            "INSERT INTO tasks SELECT id, agent_id, description, status, priority, "
            "input_context, output, error, max_retries, retry_count, created_at, "
            "started_at, completed_at FROM tasks_old"
        )
        await db.execute("DROP TABLE tasks_old")
        await db.commit()


async def close_database() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


def row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


def parse_json_fields(d: dict[str, Any], *fields: str) -> dict[str, Any]:
    for field in fields:
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = {} if field not in ("skills",) else []
    return d


async def fetch_agent(slug: str) -> dict[str, Any]:
    """Load an agent by slug from the registry, enriched with runtime status."""
    agent = get_agent(slug)  # raises ValueError if not found
    db = await get_db()
    async with db.execute(
        "SELECT status FROM agents_state WHERE slug=?", (slug,)
    ) as cur:
        row = await cur.fetchone()
    if row:
        agent["status"] = row[0]
    return agent
