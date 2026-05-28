"""Tests for src/memory_manager.py"""

import os

from src.memory_manager import (
    _MEMORY_BYTES_LIMIT,
    _MEMORY_LINES_LIMIT,
    build_memory_prompt,
    load_memory_content,
    resolve_memory_dir,
)

# ---------------------------------------------------------------------------
# resolve_memory_dir
# ---------------------------------------------------------------------------


def test_resolve_user_scope(tmp_path):
    result = resolve_memory_dir("my-agent", "user", str(tmp_path))
    expected = os.path.expanduser("~/.claude/agent-memory/my-agent")
    assert result == expected


def test_resolve_project_scope(tmp_path):
    result = resolve_memory_dir("my-agent", "project", str(tmp_path))
    assert result == os.path.join(str(tmp_path), "agent-memory", "my-agent")


def test_resolve_local_scope(tmp_path):
    result = resolve_memory_dir("my-agent", "local", str(tmp_path))
    assert result == os.path.join(str(tmp_path), "agent-memory-local", "my-agent")


def test_resolve_agent_name_used_verbatim(tmp_path):
    result = resolve_memory_dir("team-leader", "project", str(tmp_path))
    assert result.endswith("team-leader")


# ---------------------------------------------------------------------------
# load_memory_content
# ---------------------------------------------------------------------------


def test_load_returns_empty_when_no_file(tmp_path):
    assert load_memory_content(str(tmp_path)) == ""


def test_load_reads_memory_md(tmp_path):
    (tmp_path / "MEMORY.md").write_text("# Notes\nSome content.")
    result = load_memory_content(str(tmp_path))
    assert "Some content." in result


def test_load_strips_whitespace(tmp_path):
    (tmp_path / "MEMORY.md").write_text("  content  \n")
    assert load_memory_content(str(tmp_path)) == "content"


def test_load_caps_at_line_limit(tmp_path):
    lines = [f"line {i}\n" for i in range(_MEMORY_LINES_LIMIT + 50)]
    (tmp_path / "MEMORY.md").write_text("".join(lines))
    result = load_memory_content(str(tmp_path))
    assert result.count("\n") <= _MEMORY_LINES_LIMIT


def test_load_caps_at_byte_limit(tmp_path):
    # Write content clearly over 25KB
    big = "x" * (_MEMORY_BYTES_LIMIT + 1000)
    (tmp_path / "MEMORY.md").write_text(big)
    result = load_memory_content(str(tmp_path))
    assert len(result.encode("utf-8")) <= _MEMORY_BYTES_LIMIT


def test_load_exact_line_limit_not_truncated(tmp_path):
    lines = [f"line {i}\n" for i in range(_MEMORY_LINES_LIMIT)]
    (tmp_path / "MEMORY.md").write_text("".join(lines))
    result = load_memory_content(str(tmp_path))
    # All 200 lines should be present
    assert "line 199" in result


# ---------------------------------------------------------------------------
# build_memory_prompt
# ---------------------------------------------------------------------------


def test_build_creates_memory_dir(tmp_path):
    build_memory_prompt("agent-x", "project", str(tmp_path))
    assert os.path.isdir(os.path.join(str(tmp_path), "agent-memory", "agent-x"))


def test_build_contains_memory_dir_path(tmp_path):
    prompt = build_memory_prompt("agent-x", "project", str(tmp_path))
    expected_dir = os.path.join(str(tmp_path), "agent-memory", "agent-x")
    assert expected_dir in prompt


def test_build_contains_instructions(tmp_path):
    prompt = build_memory_prompt("agent-x", "project", str(tmp_path))
    assert "MEMORY.md" in prompt
    assert "persistent memory" in prompt.lower()


def test_build_includes_existing_memory_content(tmp_path):
    memory_dir = os.path.join(str(tmp_path), "agent-memory", "agent-x")
    os.makedirs(memory_dir)
    (os.path.join(memory_dir, "MEMORY.md"))
    open(os.path.join(memory_dir, "MEMORY.md"), "w").close()
    with open(os.path.join(memory_dir, "MEMORY.md"), "w") as f:
        f.write("# Codebase patterns\nUses FastAPI.")
    prompt = build_memory_prompt("agent-x", "project", str(tmp_path))
    assert "Uses FastAPI." in prompt


def test_build_no_memory_section_when_file_empty(tmp_path):
    memory_dir = os.path.join(str(tmp_path), "agent-memory", "agent-x")
    os.makedirs(memory_dir)
    open(os.path.join(memory_dir, "MEMORY.md"), "w").close()
    prompt = build_memory_prompt("agent-x", "project", str(tmp_path))
    assert "Loaded from MEMORY.md" not in prompt


def test_build_local_scope_uses_agent_memory_local(tmp_path):
    prompt = build_memory_prompt("agent-y", "local", str(tmp_path))
    assert "agent-memory-local" in prompt
