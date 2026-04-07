import json
import os
from typing import Any

import aiosqlite

_db: aiosqlite.Connection | None = None

CREATE_AGENTS = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idle',
    system_prompt TEXT NOT NULL DEFAULT '',
    model_preference TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    runner TEXT NOT NULL DEFAULT 'api',
    skills TEXT NOT NULL DEFAULT '[]',
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
    completed_at TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
)
"""

CREATE_SKILLS = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    installed_at TEXT NOT NULL
)
"""


async def init_database(db_path: str = "") -> None:
    global _db
    if not db_path:
        data_dir = os.environ.get("DATA_DIR", "/data")
        db_path = os.path.join(data_dir, "orcai.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute(CREATE_AGENTS)
    await _db.execute(CREATE_TASKS)
    await _db.execute(CREATE_SKILLS)
    await _db.commit()


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialised — call init_database() first")
    return _db


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
