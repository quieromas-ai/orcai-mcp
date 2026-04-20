import os
from datetime import UTC, datetime
from typing import Any

import frontmatter

from src.agent_registry import get_agent, update_agent
from src.config import settings


def _skill_dir(name: str) -> str:
    return os.path.join(settings.claude_dir, "skills", name)


def _skill_path(name: str) -> str:
    return os.path.join(_skill_dir(name), "SKILL.md")


def install_skill(
    name: str,
    description: str,
    content: str,
    version: str = "1.0.0",
    assign_to: list[str] | None = None,
) -> dict[str, Any]:
    skill_dir = _skill_dir(name)
    os.makedirs(skill_dir, exist_ok=True)
    file_path = _skill_path(name)

    now = datetime.now(UTC).isoformat()
    post = frontmatter.Post(
        content,
        name=name,
        description=description,
        version=version,
        installed_at=now,
    )
    with open(file_path, "w") as f:
        f.write(frontmatter.dumps(post))

    assigned_to: list[str] = []
    if assign_to:
        for slug in assign_to:
            try:
                agent = get_agent(slug)
                existing: list[str] = list(agent["skills"])
                if name not in existing:
                    existing.append(name)
                    update_agent(slug, skills=existing)
                    assigned_to.append(slug)
            except ValueError:
                continue

    return {"skill_id": name, "file_path": file_path, "assigned_to": assigned_to}
