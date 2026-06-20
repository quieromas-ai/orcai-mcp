import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import frontmatter

from src.config import settings

logger = logging.getLogger(__name__)

# Per-file mtime cache: {path: (mtime, agent_dict)}
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _agents_dir() -> str:
    return os.path.join(settings.claude_dir, "agents")


def _skills_dir() -> str:
    return os.path.join(settings.claude_dir, "skills")


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _mtime_str(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path), tz=UTC).isoformat()


def _ctime_str(path: str) -> str:
    return datetime.fromtimestamp(os.path.getctime(path), tz=UTC).isoformat()


def _parse_agent_file(path: str) -> dict[str, Any]:
    mtime = os.path.getmtime(path)
    if path in _cache and _cache[path][0] == mtime:
        return _cache[path][1]

    with open(path) as f:
        post = frontmatter.load(f)

    slug = os.path.splitext(os.path.basename(path))[0]
    fm = post.metadata
    runner = fm.get("runner", "api")
    memory_raw = fm.get("memory", None)
    memory: str | None = memory_raw if memory_raw in ("user", "project", "local") else None
    if memory_raw is not None and memory is None:
        logger.warning(
            "agent_invalid_memory_scope",
            extra={"path": path, "memory": memory_raw},
        )
    agent: dict[str, Any] = {
        "id": slug,
        "name": fm.get("name", slug),
        "description": fm.get("description", ""),
        "role": fm.get("role", ""),
        "status": "idle",
        "system_prompt": post.content,
        "model_preference": fm.get("model", "claude-sonnet-4-6"),
        "runner": runner,
        "skills": fm.get("skills", []),
        "memory": memory,
        "config": {"runner": runner},
        # Internal: discoverable by this instance only if frontmatter sets
        # `<mcp_name>: true` (literal boolean). Absent/false/non-bool => skipped.
        "_discoverable": fm.get(settings.mcp_name) is True,
        "created_at": _ctime_str(path),
        "updated_at": _mtime_str(path),
    }
    _cache[path] = (mtime, agent)
    return agent


def get_agent(slug: str) -> dict[str, Any]:
    """Load a single agent by slug, raising ValueError if not found.

    Direct fetch by slug stays permissive (ignores the discovery flag) so
    delegate-by-slug paths keep working regardless of ownership.
    """
    path = os.path.join(_agents_dir(), f"{slug}.md")
    if not os.path.isfile(path):
        raise ValueError(f"Agent '{slug}' not found")
    agent = dict(_parse_agent_file(path))
    agent.pop("_discoverable", None)
    return agent


def list_agents() -> list[dict[str, Any]]:
    """Return discoverable agents from .claude/agents/*.md, using mtime cache.

    An agent is discoverable only if its frontmatter sets `<mcp_name>: true`
    (settings.mcp_name). Untagged, false, or non-boolean values are skipped.
    """
    agents_dir = _agents_dir()
    if not os.path.isdir(agents_dir):
        return []
    agents = []
    for fname in sorted(os.listdir(agents_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(agents_dir, fname)
        try:
            parsed = dict(_parse_agent_file(path))
        except Exception as exc:
            logger.warning("agent_parse_failed", extra={"path": path, "error": str(exc)})
            continue
        if not parsed.pop("_discoverable", False):
            continue
        agents.append(parsed)
    return agents


def write_agent(
    slug: str,
    *,
    name: str = "",
    description: str = "",
    role: str = "",
    system_prompt: str = "",
    model: str = "claude-sonnet-4-6",
    runner: str = "api",
    skills: list[str] | None = None,
    memory: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write .claude/agents/<slug>.md and return the parsed agent dict.

    Auto-stamps `<mcp_name>: true` so agents created through this instance are
    discoverable by it without manual tagging.
    """
    agents_dir = _agents_dir()
    os.makedirs(agents_dir, exist_ok=True)
    path = os.path.join(agents_dir, f"{slug}.md")

    fm: dict[str, Any] = {
        "name": name or slug,
        "description": description,
        "model": model,
        "role": role,
        "runner": runner,
        "skills": skills or [],
        settings.mcp_name: True,
    }
    if memory is not None:
        fm["memory"] = memory
    if extra:
        fm.update(extra)

    post = frontmatter.Post(system_prompt, **fm)
    with open(path, "w") as f:
        f.write(frontmatter.dumps(post))

    _cache.pop(path, None)
    return get_agent(slug)


def update_agent(
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    role: str | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
    runner: str | None = None,
    skills: list[str] | None = None,
    memory: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch an existing agent .md file in place."""
    path = os.path.join(_agents_dir(), f"{slug}.md")
    if not os.path.isfile(path):
        raise ValueError(f"Agent '{slug}' not found")

    with open(path) as f:
        post = frontmatter.load(f)

    if name is not None:
        post.metadata["name"] = name
    if description is not None:
        post.metadata["description"] = description
    if role is not None:
        post.metadata["role"] = role
    if model is not None:
        post.metadata["model"] = model
    if skills is not None:
        post.metadata["skills"] = skills
    if memory is not None:
        post.metadata["memory"] = memory
    if runner is not None:
        post.metadata["runner"] = runner
    elif config and "runner" in config:
        post.metadata["runner"] = config["runner"]
    if system_prompt is not None:
        post.content = system_prompt

    with open(path, "w") as f:
        f.write(frontmatter.dumps(post))

    _cache.pop(path, None)
    return get_agent(slug)


def delete_agent(slug: str) -> None:
    path = os.path.join(_agents_dir(), f"{slug}.md")
    if not os.path.isfile(path):
        raise ValueError(f"Agent '{slug}' not found")
    os.remove(path)
    _cache.pop(path, None)


def list_skills() -> list[dict[str, Any]]:
    """Return all installed skills from .claude/skills/*/SKILL.md."""
    skills_dir = _skills_dir()
    if not os.path.isdir(skills_dir):
        return []
    skills = []
    for entry in sorted(os.listdir(skills_dir)):
        skill_path = os.path.join(skills_dir, entry, "SKILL.md")
        if not os.path.isfile(skill_path):
            continue
        try:
            with open(skill_path) as f:
                post = frontmatter.load(f)
            fm = post.metadata
            skills.append({
                "id": entry,
                "name": fm.get("name", entry),
                "description": fm.get("description", ""),
                "file_path": skill_path,
                "version": str(fm.get("version", "1.0.0")),
                "installed_at": _ctime_str(skill_path),
            })
        except Exception as exc:
            logger.warning("skill_parse_failed", extra={"path": skill_path, "error": str(exc)})
            continue
    return skills


def clear_cache() -> None:
    """Clear the mtime cache — used in tests."""
    _cache.clear()
