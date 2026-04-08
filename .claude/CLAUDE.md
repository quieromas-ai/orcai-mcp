# CLAUDE.md
- Your context folder is in ~/Dropbox/Orcai\ MCP/
- Spec (authoritative): `spec/mcp-agent-manager-spec.md`

## Stack
Python 3.12 · FastAPI + FastMCP · SQLite (aiosqlite) · Click CLI · React/Vite UI · Docker

## After every implementation
Always run `/simplify` after completing any implementation task.

## Quality checks (run before every commit)
```
uv run ruff check src/ cli/
uv run mypy src/ cli/
uv run pytest
```
mypy scope is `src/ cli/` only — test files have pre-existing untyped fixtures, do not include `tests/`.

## Key invariants
- `BaseAgentRunner.run()` returns `tuple[str, int]` — (result_text, tokens_used). `CLIAgentRunner` always returns `0` for tokens.
- Test mocks for `APIAgentRunner.run` / `CLIAgentRunner.run` must return `tuple[str, int]`, e.g. `mock.return_value = ("response", 0)`.
- Task `max_retries` must be passed at delegation time (via `delegate_task(max_retries=N)`), not updated in DB afterwards — the worker reads it on first fetch.
