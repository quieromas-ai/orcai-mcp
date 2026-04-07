import os

import pytest

from src.mcp_server import add_agent
from src.skill_manager import get_skills, install_skill


@pytest.mark.asyncio
async def test_install_skill_creates_file(db_path, tmp_path) -> None:
    import src.config as cfg_module
    original = cfg_module.settings.skills_dir
    cfg_module.settings.skills_dir = str(tmp_path / "skills")

    result = await install_skill(
        name="test-skill",
        description="A test skill",
        content="# Test Skill\n\nDo X when Y.",
        version="1.2.3",
    )

    file_path = result["file_path"]
    assert os.path.isfile(file_path), "Skill .md file should be written to disk"
    with open(file_path) as f:
        content = f.read()
    assert "# Test Skill" in content

    cfg_module.settings.skills_dir = original


@pytest.mark.asyncio
async def test_install_skill_persists_to_db(db_path, tmp_path) -> None:
    import src.config as cfg_module
    cfg_module.settings.skills_dir = str(tmp_path / "skills")

    await install_skill(name="db-skill", description="desc", content="content")
    skills = await get_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "db-skill"
    assert skills[0]["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_install_skill_assigns_to_agents(db_path, tmp_path) -> None:
    import src.config as cfg_module
    cfg_module.settings.skills_dir = str(tmp_path / "skills")

    agent = await add_agent(name="SkillTarget", role="dev")
    result = await install_skill(
        name="assigned-skill",
        description="",
        content="content",
        assign_to=[agent["id"]],
    )
    assert agent["id"] in result["assigned_to"]


@pytest.mark.asyncio
async def test_install_skill_upsert(db_path, tmp_path) -> None:
    """Re-installing a skill by the same name should update it (upsert)."""
    import src.config as cfg_module
    cfg_module.settings.skills_dir = str(tmp_path / "skills")

    await install_skill(name="upsert-skill", description="v1", content="v1")
    await install_skill(name="upsert-skill", description="v2", content="v2", version="2.0.0")

    skills = await get_skills()
    named = [s for s in skills if s["name"] == "upsert-skill"]
    assert len(named) == 1
    assert named[0]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_get_skills_empty(db_path) -> None:
    skills = await get_skills()
    assert skills == []
