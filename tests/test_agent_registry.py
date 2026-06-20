from pathlib import Path
from unittest.mock import patch

import frontmatter
import pytest

import src.agent_registry as registry_module
from src.agent_registry import (
    _slugify,
    delete_agent,
    get_agent,
    list_agents,
    list_skills,
    update_agent,
    write_agent,
)

# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert _slugify("Backend Dev") == "backend-dev"


def test_slugify_collapses_whitespace():
    assert _slugify("  Frontend  Agent  ") == "frontend-agent"


def test_slugify_strips_punctuation():
    assert _slugify("My Agent! (v2)") == "my-agent-v2"


def test_slugify_non_ascii():
    assert _slugify("Агент один") == ""


def test_slugify_numbers_preserved():
    assert _slugify("Agent 42") == "agent-42"


def test_slugify_strips_leading_trailing_hyphens():
    assert _slugify("!Hello!") == "hello"


# ---------------------------------------------------------------------------
# write_agent / get_agent round-trip
# ---------------------------------------------------------------------------


def test_write_get_roundtrip(claude_dir_path):
    agent = write_agent(
        "myagent",
        name="My Agent",
        description="Test agent",
        role="tester",
        system_prompt="You test things.",
        model="claude-haiku-4-5-20251001",
        runner="api",
        skills=["skill-a"],
    )
    assert agent["id"] == "myagent"
    assert agent["name"] == "My Agent"
    assert agent["role"] == "tester"
    assert agent["system_prompt"] == "You test things."
    assert agent["model_preference"] == "claude-haiku-4-5-20251001"
    assert agent["runner"] == "api"
    assert agent["skills"] == ["skill-a"]
    assert agent["config"] == {"runner": "api"}

    fetched = get_agent("myagent")
    assert fetched == agent


def test_write_creates_md_file(claude_dir_path):
    write_agent("testslug", name="Test Slug")
    path = Path(claude_dir_path) / "agents" / "testslug.md"
    assert path.exists()
    with open(path) as f:
        post = frontmatter.load(f)
    assert post.metadata["name"] == "Test Slug"


def test_get_agent_not_found_raises(claude_dir_path):
    with pytest.raises(ValueError, match="not found"):
        get_agent("does-not-exist")


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


def test_update_merges_frontmatter_preserves_body(claude_dir_path):
    write_agent("u1", name="Update Me", system_prompt="Original body.", role="old")
    updated = update_agent("u1", role="new")
    assert updated["role"] == "new"
    assert updated["system_prompt"] == "Original body."


def test_update_body_preserves_frontmatter(claude_dir_path):
    write_agent("u2", name="Update Body", role="worker", system_prompt="Old body.")
    updated = update_agent("u2", system_prompt="New body.")
    assert updated["system_prompt"] == "New body."
    assert updated["role"] == "worker"


def test_update_agent_not_found_raises(claude_dir_path):
    with pytest.raises(ValueError, match="not found"):
        update_agent("ghost", name="Ghost")


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------


def test_delete_removes_file(claude_dir_path):
    write_agent("del1", name="Delete Me")
    path = Path(claude_dir_path) / "agents" / "del1.md"
    assert path.exists()
    delete_agent("del1")
    assert not path.exists()


def test_delete_not_found_raises(claude_dir_path):
    with pytest.raises(ValueError, match="not found"):
        delete_agent("ghost-agent")


def test_delete_evicts_cache(claude_dir_path):
    write_agent("cached", name="Cached Agent")
    get_agent("cached")  # populate cache
    delete_agent("cached")
    with pytest.raises(ValueError):
        get_agent("cached")


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


def test_list_agents_returns_all(claude_dir_path):
    write_agent("a1", name="Alpha")
    write_agent("a2", name="Beta")
    agents = list_agents()
    slugs = [a["id"] for a in agents]
    assert "a1" in slugs
    assert "a2" in slugs


def test_list_agents_skips_malformed(claude_dir_path, caplog):
    write_agent("good", name="Good Agent")
    bad_path = Path(claude_dir_path) / "agents" / "bad.md"
    bad_path.write_bytes(b"\x80\x81 not valid utf-8")  # causes UnicodeDecodeError on open
    with caplog.at_level("WARNING", logger="src.agent_registry"):
        agents = list_agents()
    slugs = [a["id"] for a in agents]
    assert "good" in slugs
    assert "bad" not in slugs
    assert any("agent_parse_failed" in r.message for r in caplog.records)


def test_list_agents_empty_dir(claude_dir_path):
    assert list_agents() == []


# ---------------------------------------------------------------------------
# discovery scoping: <mcp_name>: true frontmatter flag
# ---------------------------------------------------------------------------


def _write_raw_agent(claude_dir_path, slug, **metadata):
    """Write an agent .md with exact frontmatter (bypasses write_agent auto-stamp)."""
    path = Path(claude_dir_path) / "agents" / f"{slug}.md"
    post = frontmatter.Post("body", name=slug, **metadata)
    path.write_text(frontmatter.dumps(post))
    registry_module.clear_cache()
    return path


def test_list_agents_returns_tagged_true(claude_dir_path):
    _write_raw_agent(claude_dir_path, "owned", **{"orcai-mcp": True})
    assert [a["id"] for a in list_agents()] == ["owned"]


def test_list_agents_excludes_untagged(claude_dir_path):
    _write_raw_agent(claude_dir_path, "foreign")  # no flag (e.g. a Slack-only agent)
    assert list_agents() == []


def test_list_agents_excludes_tagged_false(claude_dir_path):
    _write_raw_agent(claude_dir_path, "disabled", **{"orcai-mcp": False})
    assert list_agents() == []


def test_list_agents_excludes_nonbool_flag(claude_dir_path):
    # Only the literal boolean True counts — "true"/1 must NOT pass.
    _write_raw_agent(claude_dir_path, "stringy", **{"orcai-mcp": "true"})
    _write_raw_agent(claude_dir_path, "numeric", **{"orcai-mcp": 1})
    assert list_agents() == []


def test_list_agents_mixed_returns_only_tagged_and_hides_internal_key(claude_dir_path):
    _write_raw_agent(claude_dir_path, "mine", **{"orcai-mcp": True})
    _write_raw_agent(claude_dir_path, "theirs")  # untagged
    agents = list_agents()
    assert [a["id"] for a in agents] == ["mine"]
    assert all("_discoverable" not in a for a in agents)


def test_write_agent_autostamps_discovery_flag(claude_dir_path):
    write_agent("stamped", name="Stamped")
    # on-disk frontmatter carries the flag
    path = Path(claude_dir_path) / "agents" / "stamped.md"
    with open(path) as f:
        post = frontmatter.load(f)
    assert post.metadata["orcai-mcp"] is True
    # and the agent is consequently discoverable
    assert "stamped" in [a["id"] for a in list_agents()]


def test_update_agent_preserves_ownership_flag(claude_dir_path):
    write_agent("keep", name="Keep")  # auto-stamped
    update_agent("keep", description="changed")
    assert "keep" in [a["id"] for a in list_agents()]


def test_mcp_name_override_keys_discovery_per_instance(claude_dir_path, monkeypatch):
    import src.config as cfg_module

    _write_raw_agent(claude_dir_path, "orcai-agent", **{"orcai-mcp": True})
    _write_raw_agent(claude_dir_path, "trading-agent", **{"trading-mcp": True})

    monkeypatch.setattr(cfg_module.settings, "mcp_name", "trading-mcp")
    registry_module.clear_cache()

    assert [a["id"] for a in list_agents()] == ["trading-agent"]


def test_get_agent_permissive_for_untagged(claude_dir_path):
    # Direct fetch by slug ignores the discovery flag (delegate-by-slug path).
    _write_raw_agent(claude_dir_path, "direct")  # untagged
    fetched = get_agent("direct")
    assert fetched["id"] == "direct"
    assert "_discoverable" not in fetched


# ---------------------------------------------------------------------------
# mtime cache
# ---------------------------------------------------------------------------


def test_cache_hit_avoids_reparse(claude_dir_path):
    write_agent("cached2", name="Cache Test")
    registry_module.clear_cache()  # evict so first get_agent call parses fresh
    with patch.object(frontmatter, "load", wraps=frontmatter.load) as mock_load:
        get_agent("cached2")
        get_agent("cached2")
    assert mock_load.call_count == 1


def test_cache_invalidated_on_file_change(claude_dir_path, tmp_path):
    write_agent("changing", name="Original")
    get_agent("changing")  # cache it

    import time
    time.sleep(0.01)  # ensure mtime changes
    update_agent("changing", name="Modified")

    result = get_agent("changing")
    assert result["name"] == "Modified"


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------


def test_list_skills_finds_skill_md(claude_dir_path):
    skills_dir = Path(claude_dir_path) / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    post = frontmatter.Post(
        "Skill content", name="my-skill", description="A skill", version="2.0.0"
    )
    (skills_dir / "SKILL.md").write_text(frontmatter.dumps(post))

    skills = list_skills()
    assert len(skills) == 1
    assert skills[0]["id"] == "my-skill"
    assert skills[0]["version"] == "2.0.0"


def test_list_skills_ignores_dirs_without_skill_md(claude_dir_path):
    no_md_dir = Path(claude_dir_path) / "skills" / "no-skill"
    no_md_dir.mkdir(parents=True)
    (no_md_dir / "README.md").write_text("not a skill")

    assert list_skills() == []


def test_list_skills_empty(claude_dir_path):
    assert list_skills() == []


def test_list_skills_skips_malformed(claude_dir_path, caplog):
    bad_dir = Path(claude_dir_path) / "skills" / "broken"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SKILL.md").write_bytes(b"\x80\x81 not utf-8")

    with caplog.at_level("WARNING", logger="src.agent_registry"):
        skills = list_skills()
    assert skills == []
    assert any("skill_parse_failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# memory frontmatter field
# ---------------------------------------------------------------------------


def test_write_agent_with_memory_project(claude_dir_path):
    agent = write_agent("mem-agent", name="Mem Agent", memory="project")
    assert agent["memory"] == "project"


def test_write_agent_with_memory_user(claude_dir_path):
    agent = write_agent("mem-user", name="Mem User", memory="user")
    assert agent["memory"] == "user"


def test_write_agent_with_memory_local(claude_dir_path):
    agent = write_agent("mem-local", name="Mem Local", memory="local")
    assert agent["memory"] == "local"


def test_write_agent_no_memory_defaults_none(claude_dir_path):
    agent = write_agent("no-mem", name="No Mem")
    assert agent["memory"] is None


def test_memory_persisted_in_frontmatter(claude_dir_path):
    write_agent("persisted", name="Persisted", memory="project")
    path = Path(claude_dir_path) / "agents" / "persisted.md"
    with open(path) as f:
        post = frontmatter.load(f)
    assert post.metadata["memory"] == "project"


def test_update_agent_sets_memory(claude_dir_path):
    write_agent("upd-mem", name="Upd Mem")
    updated = update_agent("upd-mem", memory="local")
    assert updated["memory"] == "local"


def test_invalid_memory_scope_returns_none(claude_dir_path, caplog):
    path = Path(claude_dir_path) / "agents" / "bad-mem.md"
    post = frontmatter.Post("content", name="bad-mem", memory="global")
    path.write_text(frontmatter.dumps(post))
    with caplog.at_level("WARNING", logger="src.agent_registry"):
        agent = get_agent("bad-mem")
    assert agent["memory"] is None
    assert any("agent_invalid_memory_scope" in r.message for r in caplog.records)


def test_get_agent_roundtrip_includes_memory(claude_dir_path):
    write_agent("rt-mem", name="RT Mem", memory="user")
    fetched = get_agent("rt-mem")
    assert fetched["memory"] == "user"
