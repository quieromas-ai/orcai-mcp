# orcai-mcp

**A self-hostable MCP server that lets Claude Code and Cursor manage a fleet of sub-agents per project.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

---

## What it does

orcai-mcp exposes an MCP server that your IDE agent (Claude Code, Cursor, or any MCP-compatible client) can connect to. Once connected, the agent can register sub-agents with different roles and system prompts, delegate tasks to them, queue work, and collect results — all through standard MCP tool calls.

Each project gets one Docker container running a single Python process. That process serves the MCP protocol on `/mcp` and a management REST API + React UI on the same port.

```
IDE (Claude Code / Cursor)
    │  MCP tool calls (Streamable HTTP)
    ▼
orcai-mcp container  :8100
    ├── /mcp        ← MCP protocol (FastMCP)
    ├── /api/v1/*   ← REST API for the web UI
    ├── /ui         ← React dashboard
    └── /health     ← Health check
          │
          │  spawns agents via
          ▼
Anthropic API  /  Claude Code CLI subprocess
```

---

## Features

- **8 MCP tools** — add, update, list, and prompt agents; delegate tasks with priority and retry; install skills
- **Task queue** — configurable concurrency limit and queue depth; priority ordering (1–5); exponential-backoff retries
- **Two execution modes** — call the Anthropic API directly (`runner: api`) or spawn the Claude Code CLI as a subprocess (`runner: cli`)
- **React UI** — dashboard, agent editor with system-prompt editing, task history, skills library
- **CLI** — `orcai-mcp init / up / down / register / add / delegate / status / logs`
- **IDE auto-registration** — writes `.mcp.json` (Claude Code) or `.cursor/mcp.json` (Cursor) for you
- **Graceful shutdown** — in-flight tasks drain before the process exits
- **Structured JSON logging** — all task lifecycle events emitted as JSON

---

## Requirements

- Docker and Docker Compose **or** Python 3.12+
- An [Anthropic API key](https://console.anthropic.com/) (for `runner: api` mode)
- Claude Code CLI installed (for `runner: cli` mode)

---

## Quick start (Docker)

The fastest path from zero to a running server.

**1. Clone and enter the repo**

```bash
git clone https://github.com/quieromas-ai/orcai-mcp.git
cd orcai-mcp
```

**2. Copy the example env file**

```bash
cp .env.example .env
```

Open `.env` and set your Anthropic API key:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

Authentication is disabled by default for local use (`MCP_AUTH_DISABLED=true`). To enable it, set `MCP_AUTH_TOKEN` to a secret string and set `MCP_AUTH_DISABLED=false`.

**3. Start the server**

```bash
docker compose up -d
```

The server starts on `http://localhost:8100`. Check it is healthy:

```bash
curl http://localhost:8100/health
# {"status":"ok","agents":0,"queue_depth":0}
```

Open the dashboard at **http://localhost:8100/ui**.

**4. Register with your IDE**

From your project directory:

```bash
pip install orcai-mcp       # or: pipx install orcai-mcp
orcai-mcp init --ide claude  # creates .claude/agents/ structure
orcai-mcp register           # writes .mcp.json
```

For Cursor:

```bash
orcai-mcp init --ide cursor
orcai-mcp register --ide cursor  # writes .cursor/mcp.json
```

**5. Verify the connection**

In Claude Code:

```bash
claude mcp list
# agent-manager  http://localhost:8100/mcp  connected
```

In Cursor: **Settings → Tools & MCP** — `orcai-mcp` should show as connected.

---

## Quick start (local, no Docker)

If you prefer to run without Docker:

```bash
git clone https://github.com/quieromas-ai/orcai-mcp.git
cd orcai-mcp

pip install -e ".[dev]"      # or: uv pip install -e ".[dev]"
cp .env.example .env         # set ANTHROPIC_API_KEY

orcai-mcp up --local         # starts uvicorn directly
```

Data is stored in `/data` by default. Override with `DATA_DIR=./data` in `.env`.

---

## Usage

### From Claude Code / Cursor

Once connected, your IDE agent can use the tools naturally. Example conversation:

```
You: Create a backend agent and have it write a health check endpoint

Claude Code:
  → add_agent(name="Backend Dev", role="backend",
               system_prompt="You write Python FastAPI code...")
  → delegate_task(agent_id="...", description="Write a /health endpoint
                   that returns {status: ok, version: ...}")
  → check_task_status(task_id="...")
  → [reads output from .claude/agents/outputs/{task_id}/result.json]
```

### CLI

```bash
# List registered agents
orcai-mcp list

# Add an agent from a system prompt file
orcai-mcp add "Frontend Dev" --role frontend --prompt ./agents/frontend.md

# Delegate a task
orcai-mcp delegate <agent-id> "Build a login form component" --priority 4

# Check task status
orcai-mcp status <task-id>

# Show recent logs for an agent
orcai-mcp logs <agent-id>
```

### MCP tools reference

| Tool | Description |
|---|---|
| `add_agent` | Register a new sub-agent with name, role, system prompt, and model |
| `update_agent` | Update any field on an existing agent |
| `get_agents` | List agents, optionally filtered by role or status |
| `get_active_agents` | List agents currently executing a task |
| `delegate_task` | Assign a task to an agent; queued if agent is busy |
| `check_task_status` | Poll the status and output of a delegated task |
| `install_skill` | Install a Markdown skill file and optionally assign to agents |
| `prompt_agent` | Send an ad-hoc message to an agent and wait for a response |

Full parameter documentation is available via MCP resource discovery or at `/api/v1/docs`.

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` to get started.

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8100` | Port the server listens on |
| `MCP_AUTH_TOKEN` | _(empty)_ | Bearer token required on all requests |
| `MCP_AUTH_DISABLED` | `true` | Set to `false` to enforce auth |
| `IDE_TARGET` | `claude` | `claude` or `cursor` — controls artifact output paths |
| `MAX_CONCURRENT_AGENTS` | `3` | Max simultaneous agent tasks |
| `TASK_QUEUE_SIZE` | `20` | Max queued tasks before rejecting |
| `ANTHROPIC_API_KEY` | _(required for api runner)_ | Anthropic API key |
| `DATA_DIR` | `/data` | SQLite database location |
| `WORKSPACE_DIR` | `/workspace` | Agent working directories |
| `SKILLS_DIR` | `/skills` | Installed skill Markdown files |
| `PROJECT_DIR` | `.` | Project root (artifacts written here) |

---

## Agent execution modes

orcai-mcp supports two ways to run agents. Set `runner` in the agent's `config` when calling `add_agent`.

**`api` (default)** — calls the Anthropic Messages API directly via httpx. Works anywhere, no local tooling required. Requires `ANTHROPIC_API_KEY`.

```python
add_agent(name="API Agent", role="...", config={"runner": "api"})
```

**`cli`** — spawns Claude Code as a subprocess. Gives the agent full access to the filesystem, terminal, and any tools Claude Code supports. Requires the `claude` CLI to be installed and authenticated in the execution environment.

```python
add_agent(name="CLI Agent", role="...", config={"runner": "cli"})
```

---

## Artifact output

Task outputs are written to the project directory under the IDE target path:

```
# Claude Code
.claude/agents/outputs/{task_id}/result.json

# Cursor
.cursor/agents/outputs/{task_id}/result.json
```

Override the base directory with the `PROJECT_DIR` environment variable.

---

## Example agent system prompts

The `examples/agents/` directory contains ready-to-use system prompts:

- `frontend-dev.md` — React/TypeScript component development
- `backend-dev.md` — Python FastAPI endpoint development

Use them with:

```bash
orcai-mcp add "Frontend Dev" --role frontend --prompt examples/agents/frontend-dev.md
orcai-mcp add "Backend Dev"  --role backend  --prompt examples/agents/backend-dev.md
```

---

## Remote deployment (nginx + TLS)

For a server accessible over the network, put nginx in front of the container. Example config is in `examples/nginx/remote.conf`. Key settings required:

```nginx
proxy_read_timeout 300s;   # long-running agent tasks
proxy_buffering off;        # SSE / streaming support
```

Set `MCP_AUTH_TOKEN` and `MCP_AUTH_DISABLED=false` when running remotely. Then register with your IDE using the public URL:

```bash
orcai-mcp register --url https://mcp.yourserver.com --token <your-token>
```

---

## Development

```bash
git clone https://github.com/quieromas-ai/orcai-mcp.git
cd orcai-mcp

# Install with dev dependencies
pip install -e ".[dev]"

# Run quality checks
ruff check src/ cli/
mypy src/ cli/
pytest

# Start locally
cp .env.example .env   # set ANTHROPIC_API_KEY
orcai-mcp up --local
```

The test suite covers MCP tools, task engine concurrency, graceful shutdown, retry logic, REST API, skill manager, and CLI. Tests use an in-memory SQLite database and mock the agent runner by default. The end-to-end CLI test (`test_cli_runner_end_to_end_with_system_prompt`) is automatically skipped if `claude` is not installed.

---

## Contributing

Contributions are welcome. Please:

1. Open an issue before starting significant work so we can discuss the approach.
2. Follow the existing code style — `ruff` and `mypy` must pass with no new errors.
3. Add or update tests for any changed behaviour.
4. Keep PRs focused — one concern per PR.

Bug reports and feature requests via [GitHub Issues](https://github.com/quieromas-ai/orcai-mcp/issues).

---

## Roadmap

- [ ] Dev container scaffolding (`orcai-mcp init` generates `.devcontainer/`)
- [ ] Agent-to-agent delegation
- [ ] Multi-model support (OpenAI, Ollama)
- [ ] Webhook / Slack completion events
- [ ] MCP Registry listing
- [ ] Prometheus metrics endpoint

---

## License

MIT — see [LICENSE](LICENSE).
