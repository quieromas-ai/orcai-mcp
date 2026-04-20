"""Integration tests for cli/migrate.py.

Seeds a legacy SQLite schema (agents + skills + tasks tables) using raw sqlite3,
then runs the migration and asserts the resulting filesystem + DB state.
"""
import os
import sqlite3
import uuid
from pathlib import Path

import frontmatter

from cli.migrate import run as run_migration

# ---------------------------------------------------------------------------
# Legacy schema DDL (matches what old orcai-mcp wrote)
# ---------------------------------------------------------------------------

_DDL_AGENTS = """
CREATE TABLE agents (
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
);
"""

_DDL_SKILLS = """
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    installed_at TEXT NOT NULL
);
"""

_DDL_TASKS = """
CREATE TABLE tasks (
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
);
"""


def _seed_legacy_db(db_path: str, tmp_path: Path) -> dict:
    """Create a legacy DB with 2 agents, 1 skill, 3 tasks and return inserted IDs."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_DDL_AGENTS + _DDL_SKILLS + _DDL_TASKS)

    agent1_id = str(uuid.uuid4())
    agent2_id = str(uuid.uuid4())
    now = "2024-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (agent1_id, "Backend Dev", "backend", "idle", "You write Python.", "claude-sonnet-4-6",
         "api", "[]", "{}", now, now),
    )
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (agent2_id, "Frontend Dev", "frontend", "idle", "You write React.", "claude-sonnet-4-6",
         "cli", "[]", '{"runner": "cli"}', now, now),
    )

    # Write skill content to a real temp file so migration can read it
    skill_file = tmp_path / "old_skill.md"
    skill_file.write_text("# Test skill content")
    skill_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO skills VALUES (?,?,?,?,?,?)",
        (skill_id, "test-skill", "A test skill", str(skill_file), "1.2.3", now),
    )

    task1_id = str(uuid.uuid4())
    task2_id = str(uuid.uuid4())
    task3_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO tasks (id, agent_id, description, created_at) VALUES (?,?,?,?)",
        (task1_id, agent1_id, "Write an API", now),
    )
    conn.execute(
        "INSERT INTO tasks (id, agent_id, description, created_at) VALUES (?,?,?,?)",
        (task2_id, agent1_id, "Write tests", now),
    )
    conn.execute(
        "INSERT INTO tasks (id, agent_id, description, created_at) VALUES (?,?,?,?)",
        (task3_id, agent2_id, "Build UI", now),
    )
    conn.commit()
    conn.close()

    return {
        "agent1_id": agent1_id, "agent2_id": agent2_id,
        "task1_id": task1_id, "task2_id": task2_id, "task3_id": task3_id,
        "skill_id": skill_id,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    ids = _seed_legacy_db(db_path, tmp_path)
    claude_dir = claude_dir_path

    rc = run_migration(db_path, claude_dir, dry_run=False, backup=True)
    assert rc == 0

    # Agent .md files exist with expected slugs
    agents_dir = Path(claude_dir) / "agents"
    assert (agents_dir / "backend-dev.md").exists()
    assert (agents_dir / "frontend-dev.md").exists()

    # Frontmatter content correct
    with open(agents_dir / "backend-dev.md") as f:
        post = frontmatter.load(f)
    assert post.metadata["role"] == "backend"
    assert post.metadata["runner"] == "api"
    assert post.content == "You write Python."

    with open(agents_dir / "frontend-dev.md") as f:
        post2 = frontmatter.load(f)
    assert post2.metadata["runner"] == "cli"

    # Skill exported to .claude/skills/test-skill/SKILL.md
    skill_path = Path(claude_dir) / "skills" / "test-skill" / "SKILL.md"
    assert skill_path.exists()
    with open(skill_path) as f:
        sp = frontmatter.load(f)
    assert sp.metadata["name"] == "test-skill"
    assert sp.metadata["version"] == "1.2.3"
    assert sp.content == "# Test skill content"

    # tasks.agent_id rewritten to slugs
    conn = sqlite3.connect(db_path)
    rows = {r[0]: r[1] for r in conn.execute("SELECT id, agent_id FROM tasks").fetchall()}
    assert rows[ids["task1_id"]] == "backend-dev"
    assert rows[ids["task2_id"]] == "backend-dev"
    assert rows[ids["task3_id"]] == "frontend-dev"

    # agents and skills tables dropped; agents_state created
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "agents" not in tables
    assert "skills" not in tables
    assert "agents_state" in tables

    # Backup created
    assert os.path.exists(db_path + ".premigrate.bak")
    conn.close()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    ids = _seed_legacy_db(db_path, tmp_path)
    claude_dir = claude_dir_path

    rc = run_migration(db_path, claude_dir, dry_run=True, backup=False)
    assert rc == 0

    # No files written
    agents_dir = Path(claude_dir) / "agents"
    assert not any(agents_dir.iterdir()) if agents_dir.exists() else True

    # No backup
    assert not os.path.exists(db_path + ".premigrate.bak")

    # DB unchanged — tables still present
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "agents" in tables
    assert "skills" in tables

    # tasks.agent_id not modified
    rows = {r[0]: r[1] for r in conn.execute("SELECT id, agent_id FROM tasks").fetchall()}
    assert rows[ids["task1_id"]] == ids["agent1_id"]
    conn.close()


# ---------------------------------------------------------------------------
# Conflict detection: aborts without mutating DB
# ---------------------------------------------------------------------------


def test_conflict_aborts_without_db_mutation(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    ids = _seed_legacy_db(db_path, tmp_path)
    claude_dir = claude_dir_path

    # Pre-place a conflicting file
    conflict_path = Path(claude_dir) / "agents" / "backend-dev.md"
    conflict_path.write_text("existing file")

    rc = run_migration(db_path, claude_dir, dry_run=False, backup=False)
    assert rc == 1

    # No DB mutation — tasks still have old UUIDs
    conn = sqlite3.connect(db_path)
    rows = {r[0]: r[1] for r in conn.execute("SELECT id, agent_id FROM tasks").fetchall()}
    assert rows[ids["task1_id"]] == ids["agent1_id"]

    # Tables still present
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "agents" in tables
    conn.close()


# ---------------------------------------------------------------------------
# Empty agents table
# ---------------------------------------------------------------------------


def test_empty_agents_table(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(_DDL_AGENTS + _DDL_SKILLS + _DDL_TASKS)
    conn.commit()
    conn.close()

    rc = run_migration(db_path, claude_dir_path, dry_run=False, backup=False)
    assert rc == 0

    agents_dir = Path(claude_dir_path) / "agents"
    md_files = list(agents_dir.glob("*.md")) if agents_dir.exists() else []
    assert md_files == []

    conn2 = sqlite3.connect(db_path)
    tables = {r[0] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "agents_state" in tables
    conn2.close()


# ---------------------------------------------------------------------------
# No agents table at all
# ---------------------------------------------------------------------------


def test_no_agents_table(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.commit()
    conn.close()

    rc = run_migration(db_path, claude_dir_path, dry_run=False, backup=False)
    assert rc == 0


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def test_backup_created(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    _seed_legacy_db(db_path, tmp_path)

    run_migration(db_path, claude_dir_path, dry_run=False, backup=True)
    assert os.path.exists(db_path + ".premigrate.bak")


def test_no_backup_when_disabled(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    _seed_legacy_db(db_path, tmp_path)

    run_migration(db_path, claude_dir_path, dry_run=False, backup=False)
    assert not os.path.exists(db_path + ".premigrate.bak")


# ---------------------------------------------------------------------------
# Skill with missing old file_path (content falls back to empty)
# ---------------------------------------------------------------------------


def test_skill_with_missing_file(tmp_path, claude_dir_path):
    db_path = str(tmp_path / "orcai.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(_DDL_AGENTS + _DDL_SKILLS + _DDL_TASKS)
    agent_id = str(uuid.uuid4())
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (agent_id, "Solo Agent", "dev", "idle", "Solo.", "claude-sonnet-4-6",
         "api", "[]", "{}", now, now),
    )
    conn.execute(
        "INSERT INTO skills VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), "orphan-skill", "Orphan", "/nonexistent/path.md", "1.0.0", now),
    )
    conn.commit()
    conn.close()

    rc = run_migration(db_path, claude_dir_path, dry_run=False, backup=False)
    assert rc == 0

    skill_path = Path(claude_dir_path) / "skills" / "orphan-skill" / "SKILL.md"
    assert skill_path.exists()
    with open(skill_path) as f:
        post = frontmatter.load(f)
    assert post.content == ""
