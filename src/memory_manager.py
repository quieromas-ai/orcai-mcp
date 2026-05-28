import os
from typing import Literal

MemoryScope = Literal["user", "project", "local"]

_MEMORY_LINES_LIMIT = 200
_MEMORY_BYTES_LIMIT = 25 * 1024  # 25 KB

_MEMORY_INSTRUCTIONS = """\

## Agent Memory

Your persistent memory directory is at: {memory_dir}

Use it to retain knowledge across conversations:
- Read `MEMORY.md` for accumulated context (codebase patterns, decisions, recurring issues)
- Write or update `MEMORY.md` with new insights as you work
- Keep `MEMORY.md` concise — summarise rather than append; curate it if it exceeds 200 lines
- You may create additional files in the directory for structured notes
"""

_MEMORY_CONTENT_SECTION = """\

### Loaded from MEMORY.md:

{content}
"""


def resolve_memory_dir(agent_name: str, scope: MemoryScope, claude_dir: str) -> str:
    """Return the absolute path to the agent's memory directory for the given scope."""
    if scope == "user":
        return os.path.expanduser(f"~/.claude/agent-memory/{agent_name}")
    if scope == "project":
        return os.path.join(claude_dir, "agent-memory", agent_name)
    # local
    return os.path.join(claude_dir, "agent-memory-local", agent_name)


def load_memory_content(memory_dir: str) -> str:
    """Read MEMORY.md from memory_dir, capped at 200 lines or 25 KB (whichever first)."""
    memory_file = os.path.join(memory_dir, "MEMORY.md")
    if not os.path.isfile(memory_file):
        return ""

    with open(memory_file, encoding="utf-8") as f:
        raw = f.read()

    # Apply byte cap first
    encoded = raw.encode("utf-8")
    if len(encoded) > _MEMORY_BYTES_LIMIT:
        raw = encoded[:_MEMORY_BYTES_LIMIT].decode("utf-8", errors="ignore")

    # Apply line cap
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MEMORY_LINES_LIMIT:
        raw = "".join(lines[:_MEMORY_LINES_LIMIT])

    return raw.strip()


def build_memory_prompt(agent_name: str, scope: MemoryScope, claude_dir: str) -> str:
    """Return the memory block to append to an agent's system prompt.

    Creates the memory directory if it does not yet exist.
    """
    memory_dir = resolve_memory_dir(agent_name, scope, claude_dir)
    os.makedirs(memory_dir, exist_ok=True)

    block = _MEMORY_INSTRUCTIONS.format(memory_dir=memory_dir)

    content = load_memory_content(memory_dir)
    if content:
        block += _MEMORY_CONTENT_SECTION.format(content=content)

    return block
