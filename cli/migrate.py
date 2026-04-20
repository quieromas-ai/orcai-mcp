"""One-shot migration: export SQLite agents/skills → .claude/agents/*.md
and .claude/skills/*/SKILL.md. Drops agents/skills tables after export.
"""
import json
import os
import shutil
import sqlite3
import sys
from typing import Any

import frontmatter

from src.agent_registry import _slugify


def run(db_path: str, claude_dir: str, dry_run: bool = False, backup: bool = True) -> int:
    """Return 0 on success, 1 on conflict/error."""
    agents_dir = os.path.join(claude_dir, "agents")
    skills_dir = os.path.join(claude_dir, "skills")
    os.makedirs(agents_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "agents" not in tables:
        print("No 'agents' table found — nothing to migrate.")
        conn.close()
        return 0

    rows = conn.execute("SELECT * FROM agents").fetchall()
    if not rows:
        print("agents table is empty — nothing to migrate.")
        _drop_tables(conn, tables, dry_run)
        conn.close()
        return 0

    # --- Conflict check ---
    conflicts: list[str] = []
    agent_map: list[tuple[str, dict[str, Any]]] = []

    for row in rows:
        agent = dict(row)
        slug = _slugify(agent["name"])
        dest = os.path.join(agents_dir, f"{slug}.md")
        agent_map.append((slug, agent))
        if os.path.isfile(dest):
            conflicts.append(dest)

    if conflicts:
        print("ERROR: Migration aborted — the following files already exist:")
        for path in conflicts:
            print(f"  {path}")
        print("\nResolve conflicts manually then re-run the migration.")
        conn.close()
        return 1

    # --- Backup DB before any mutations ---
    if not dry_run and backup:
        backup_path = db_path + ".premigrate.bak"
        shutil.copy2(db_path, backup_path)
        print(f"  backed up DB to {backup_path}")

    # --- Write agent .md files ---
    for slug, agent in agent_map:
        runner = agent.get("runner") or "api"
        cfg: dict[str, Any] = {}
        try:
            cfg = json.loads(agent.get("config") or "{}")
        except Exception:
            pass
        runner = cfg.get("runner", runner)

        skills_raw = agent.get("skills") or "[]"
        try:
            skills = json.loads(skills_raw)
        except Exception:
            skills = []

        fm: dict[str, Any] = {
            "name": agent["name"],
            "description": f"{agent['role']} agent".strip(),
            "model": agent.get("model_preference") or "claude-sonnet-4-6",
            "role": agent.get("role") or "",
            "runner": runner,
            "skills": skills,
        }
        body = agent.get("system_prompt") or ""
        post = frontmatter.Post(body, **fm)
        dest = os.path.join(agents_dir, f"{slug}.md")

        if dry_run:
            print(f"  [dry-run] would write {dest}")
        else:
            with open(dest, "w") as f:
                f.write(frontmatter.dumps(post))
            print(f"  wrote {dest}")

    # --- Write skill .md files ---
    _export_skills(conn, tables, skills_dir, dry_run)

    # --- All SQL mutations in a single transaction ---
    if not dry_run:
        slug_by_old_id: dict[str, str] = {
            agent["id"]: agent_slug for agent_slug, agent in agent_map
        }

        cur = conn.execute("SELECT id, agent_id FROM tasks")
        updates = [
            (slug_by_old_id[old_agent_id], task_id)
            for task_id, old_agent_id in cur.fetchall()
            if old_agent_id in slug_by_old_id and slug_by_old_id[old_agent_id] != old_agent_id
        ]

        conn.execute("BEGIN")
        for new_slug, task_id in updates:
            conn.execute("UPDATE tasks SET agent_id=? WHERE id=?", (new_slug, task_id))
        print(f"  updated {len(updates)} tasks.agent_id to slugs")

        _drop_tables_in_tx(conn, tables)
        conn.execute("COMMIT")
        print("  migration committed")

    conn.close()
    return 0


def _export_skills(
    conn: sqlite3.Connection, tables: set[str], skills_dir: str, dry_run: bool
) -> None:
    if "skills" not in tables:
        return
    rows = conn.execute("SELECT * FROM skills").fetchall()
    for row in rows:
        skill = dict(row)
        name = skill["name"]
        content = ""
        old_path = skill.get("file_path", "")
        if old_path and os.path.isfile(old_path):
            try:
                with open(old_path) as f:
                    content = f.read()
            except OSError:
                pass

        skill_subdir = os.path.join(skills_dir, name)
        skill_path = os.path.join(skill_subdir, "SKILL.md")
        if dry_run:
            print(f"  [dry-run] would write {skill_path}")
            continue
        os.makedirs(skill_subdir, exist_ok=True)
        post = frontmatter.Post(
            content,
            name=name,
            description=skill.get("description", ""),
            version=skill.get("version", "1.0.0"),
            installed_at=skill.get("installed_at", ""),
        )
        with open(skill_path, "w") as f:
            f.write(frontmatter.dumps(post))
        print(f"  wrote {skill_path}")


def _drop_tables_in_tx(conn: sqlite3.Connection, tables: set[str]) -> None:
    for tbl in ("agents", "skills"):
        if tbl in tables:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            print(f"  dropped table '{tbl}'")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents_state (
            slug TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'idle',
            last_run_at TEXT,
            last_task_id TEXT
        )
    """)
    print("  created agents_state table")


def _drop_tables(conn: sqlite3.Connection, tables: set[str], dry_run: bool) -> None:
    """Used for the empty-agents early exit path (no mutations needed)."""
    for tbl in ("agents", "skills"):
        if tbl in tables:
            if dry_run:
                print(f"  [dry-run] would drop table '{tbl}'")
            else:
                conn.execute(f"DROP TABLE IF EXISTS {tbl}")
                print(f"  dropped table '{tbl}'")

    if dry_run:
        print("  [dry-run] would create agents_state table")
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents_state (
                slug TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'idle',
                last_run_at TEXT,
                last_task_id TEXT
            )
        """)
        conn.commit()
        print("  created agents_state table")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2]))
