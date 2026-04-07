import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from src.config import settings
from src.database import get_db, row_to_dict


async def install_skill(
    name: str,
    description: str,
    content: str,
    version: str = "1.0.0",
    assign_to: list[str] | None = None,
) -> dict[str, Any]:
    db = await get_db()
    skills_dir = settings.skills_dir
    os.makedirs(skills_dir, exist_ok=True)
    file_path = os.path.join(skills_dir, f"{name}.md")

    with open(file_path, "w") as f:
        f.write(content)

    skill_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    await db.execute(
        """
        INSERT INTO skills (id, name, description, file_path, version, installed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            description=excluded.description,
            file_path=excluded.file_path,
            version=excluded.version,
            installed_at=excluded.installed_at
        """,
        (skill_id, name, description, file_path, version, now),
    )

    assigned_to: list[str] = []
    if assign_to:
        for agent_id in assign_to:
            async with db.execute("SELECT skills FROM agents WHERE id=?", (agent_id,)) as cur:
                row = await cur.fetchone()
            if row:
                existing: list[str] = json.loads(row[0])
                if skill_id not in existing:
                    existing.append(skill_id)
                    await db.execute(
                        "UPDATE agents SET skills=?, updated_at=? WHERE id=?",
                        (json.dumps(existing), now, agent_id),
                    )
                    assigned_to.append(agent_id)

    await db.commit()
    return {"skill_id": skill_id, "file_path": file_path, "assigned_to": assigned_to}


async def get_skills() -> list[dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM skills ORDER BY installed_at DESC") as cur:
        rows = await cur.fetchall()
    return [row_to_dict(r) for r in rows]
