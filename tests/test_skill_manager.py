import os

import pytest

from src.agent_registry import list_skills as get_skills
from src.mcp_server import add_agent
from src.skill_manager import install_skill


@pytest.mark.asyncio
async def test_install_skill_creates_file(db_path) -> None:
    result = install_skill(
        name="test-skill",
        description="A test skill",
        content="# Test Skill\n\nDo X when Y.",
        version="1.2.3",
    )
    file_path = result["file_path"]
    assert os.path.isfile(file_path), "SKILL.md should be written to disk"
    with open(file_path) as f:
        raw = f.read()
    assert "# Test Skill" in raw
    assert "version: 1.2.3" in raw


@pytest.mark.asyncio
async def test_install_skill_name_and_path(db_path) -> None:
    result = install_skill(name="db-skill", description="desc", content="content")
    assert result["skill_id"] == "db-skill"
    assert result["file_path"].endswith("SKILL.md")


@pytest.mark.asyncio
async def test_install_skill_lists_in_get_skills(db_path) -> None:
    install_skill(name="listed-skill", description="desc", content="content")
    skills = get_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "listed-skill"
    assert skills[0]["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_install_skill_assigns_to_agents(db_path) -> None:
    agent = await add_agent(name="SkillTarget", role="dev")
    result = install_skill(
        name="assigned-skill",
        description="",
        content="content",
        assign_to=[agent["id"]],
    )
    assert agent["id"] in result["assigned_to"]


@pytest.mark.asyncio
async def test_install_skill_upsert(db_path) -> None:
    """Re-installing a skill by the same name should overwrite it."""
    install_skill(name="upsert-skill", description="v1", content="v1 content")
    install_skill(
        name="upsert-skill", description="v2", content="v2 content", version="2.0.0"
    )

    skills = get_skills()
    named = [s for s in skills if s["name"] == "upsert-skill"]
    assert len(named) == 1
    assert named[0]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_get_skills_empty(db_path) -> None:
    skills = get_skills()
    assert skills == []
