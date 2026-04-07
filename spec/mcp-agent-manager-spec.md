# MCP Sub-Agent Manager — Technical Specification

**Project:** `mcp-agent-manager`
**Type:** Open-source, standalone GitHub repository
**License:** MIT
**Author:** Personal project, reusable across any codebase
**Date:** April 7, 2026

---

## 1. Vision

A self-hostable, MCP-compliant server that lets Claude Code and Cursor manage a fleet of sub-agents per project. Each project gets its own Docker container running a single Python process with two co-located servers:

- **FastMCP** — the MCP-protocol layer (JSON-RPC 2.0 over Streamable HTTP) that exposes tools, resources, and prompts to any MCP client. This is the primary interface for IDE agents.
- **FastAPI** — a standard REST API that serves the React UI and provides non-MCP endpoints (health checks, dashboard stats, file uploads). FastMCP is mounted inside FastAPI via ASGI, so both share one process and one port.

Agents are user-defined via Markdown files, tasks are spawned on demand (with queue overflow), and artifacts land in the IDE's native config directory (`.claude/` or `.cursor/`).

> **Why both?** FastMCP speaks MCP protocol only — it cannot serve a web UI or standard REST endpoints. FastAPI handles the React UI's data needs. If you only use the CLI and never open the UI, FastMCP alone would suffice — but the ASGI mount costs nothing, so we include both by default.

---

## 2. Architecture Overview

The system has three distinct runtime environments, each with a specific role:

```
┌──────────────────────────────────────────────────────────────────┐
│  HOST MACHINE (dev workstation / VM)                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  IDE (Claude Code / Cursor)                             │     │
│  │  MCP Client ← discovers tools via JSON-RPC 2.0         │     │
│  └───────────────┬─────────────────────────────────────────┘     │
│                  │  Streamable HTTP transport                     │
│  ┌───────────────▼─────────────────────────────────────────┐     │
│  │  MCP SERVER CONTAINER (one per project)                 │     │
│  │                                                         │     │
│  │  FastAPI + FastMCP — single process, single port        │     │
│  │    /mcp      → MCP tools, resources, prompts            │     │
│  │    /api/v1   → REST endpoints for React UI              │     │
│  │    /ui       → React static build                       │     │
│  │    /health   → Health check                             │     │
│  │                                                         │     │
│  │  SQLite DB, Task Engine, Skills library                 │     │
│  └───────────────┬─────────────────────────────────────────┘     │
│                  │  spawns agents into ↓                         │
│  ┌───────────────▼─────────────────────────────────────────┐     │
│  │  AGENT EXECUTION ENVIRONMENT (Dev Container)            │     │
│  │                                                         │     │
│  │  Sub-agents run here — all development tooling present  │     │
│  │    • Claude Code CLI / Cursor                           │     │
│  │    • AZ CLI, GH CLI, Docker Compose                     │     │
│  │    • Language runtimes, linters, test runners           │     │
│  │    • /workspace → mounted project directory             │     │
│  │    • /var/run/docker.sock → host Docker daemon          │     │
│  └───────────────┬─────────────────────────────────────────┘     │
│                  │  code pushed to ADO/GitHub                     │
│                  │                                                │
│  ┌───────────────▼─────────────────────────────────────────┐     │
│  │  COWORK (host-level orchestrator)                       │     │
│  │                                                         │     │
│  │  Receives event (Slack / webhook) on dev completion     │     │
│  │  Runs local deployment scripts (docker compose, etc.)   │     │
│  │  Acts as bridge between agent world and host machine    │     │
│  └─────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
                  │  merge to main triggers ↓
┌─────────────────▼────────────────────────────────────────────────┐
│  ADO PIPELINE (staging / production deployments)                 │
│                                                                  │
│  build container → push to ACR → deploy to Azure                │
│  → notify Slack on success/failure                               │
└──────────────────────────────────────────────────────────────────┘
```

**Key principle:** There are three distinct actors in the system — the MCP server (orchestration), the Dev Container (agent execution and code development), and the deployment layer (Cowork for local/dev, ADO pipelines for staging/prod). These are intentionally separate so that tool access, credentials, and side effects are scoped to the right layer.

---

## 3. Ingress Layer

### Option A: Remote (nginx behind firewall)

```nginx
# /etc/nginx/sites-available/mcp-agent-manager
server {
    listen 443 ssl;
    server_name mcp.yourserver.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.yourserver.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.yourserver.com/privkey.pem;

    # Everything goes to the same upstream — FastAPI serves all routes
    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;   # long-running agent tasks
        proxy_buffering off;        # SSE/streaming support
    }

    # Rate limiting on MCP endpoint only
    limit_req_zone $binary_remote_addr zone=mcp:10m rate=30r/m;
    location /mcp {
        limit_req zone=mcp burst=10 nodelay;
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
```

Authentication: Bearer token passed via `Authorization` header, validated by FastAPI middleware. Token set as env var `MCP_AUTH_TOKEN` on the container.

### Option B: Local (same machine)

No nginx needed. Container exposes `localhost:8100` for MCP and `localhost:3000` for UI directly. Auth optional (can be disabled via `MCP_AUTH_DISABLED=true` env var).

---

## 4. Docker Container

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps for subprocess spawning
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY ui/build/ ./ui/build/

# Volumes
VOLUME /data          # SQLite + persistent state
VOLUME /workspace     # Agent working directories
VOLUME /skills        # Installed skills (md files)
VOLUME /project       # Mounted project directory (.claude/ or .cursor/)

# Single port — FastAPI serves everything:
#   /mcp     → FastMCP (ASGI-mounted MCP server)
#   /api/v1  → REST endpoints for React UI
#   /ui      → React static build
#   /health  → Health check
ENV PORT=8100
ENV MCP_AUTH_TOKEN=""
ENV MCP_AUTH_DISABLED=false
ENV IDE_TARGET=claude
ENV MAX_CONCURRENT_AGENTS=3
ENV TASK_QUEUE_SIZE=20

EXPOSE 8100

CMD ["python", "-m", "src.main"]
```

### requirements.txt

```
mcp>=1.27.0
fastapi>=0.115.0
uvicorn>=0.30.0
pydantic>=2.9.0
aiosqlite>=0.20.0
httpx>=0.27.0
python-multipart>=0.0.9
```

### docker-compose.yml (per-project)

```yaml
version: "3.9"
services:
  mcp-agent-manager:
    build: .
    container_name: mcp-agents-${PROJECT_NAME:-default}
    ports:
      - "${PORT:-8100}:8100"
    volumes:
      - ./data:/data
      - ./workspace:/workspace
      - ./skills:/skills
      - ${PROJECT_DIR:-.}:/project
    environment:
      - MCP_AUTH_TOKEN=${MCP_AUTH_TOKEN:-}
      - MCP_AUTH_DISABLED=${MCP_AUTH_DISABLED:-true}
      - IDE_TARGET=${IDE_TARGET:-claude}
      - MAX_CONCURRENT_AGENTS=${MAX_CONCURRENT_AGENTS:-3}
      - TASK_QUEUE_SIZE=${TASK_QUEUE_SIZE:-20}
    restart: unless-stopped
```

---

## 5. Agent Execution Environment (Dev Container)

Sub-agents require access to host-level CLI tools to carry out real development work — building, testing, pushing code, interacting with cloud infrastructure. This tool access is provided by running agents inside a **Dev Container** that has all required tooling pre-installed and reproducibly defined.

This is distinct from the MCP server container (Section 4), which only runs the orchestration layer. The Dev Container is where actual work happens.

### Why a Dev Container (not the MCP server container)

The MCP server container is minimal by design — Python, SQLite, the FastMCP server. Installing AZ CLI, GH CLI, Docker, language runtimes, etc. into it would bloat the image and couple infrastructure tooling to the orchestration layer. Instead, agents are spawned into a separate, purpose-built Dev Container that defines the full development environment.

This also means the Dev Container can be changed per project (different language runtimes, different CLI versions) without touching the MCP server image.

### Dev Container Definition

A `.devcontainer/devcontainer.json` and `Dockerfile` at the project root define the agent execution environment:

```json
// .devcontainer/devcontainer.json
{
  "name": "Agent Execution Environment",
  "build": { "dockerfile": "Dockerfile.devcontainer" },
  "mounts": [
    "source=/var/run/docker.sock,target=/var/run/docker.sock,type=bind"
  ],
  "remoteEnv": {
    "AZURE_CONFIG_DIR": "${localEnv:HOME}/.azure",
    "GITHUB_TOKEN": "${localEnv:GITHUB_TOKEN}",
    "ANTHROPIC_API_KEY": "${localEnv:ANTHROPIC_API_KEY}"
  },
  "postCreateCommand": "gh auth status && az account show"
}
```

```dockerfile
# Dockerfile.devcontainer
FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

# Azure CLI
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=...] \
    https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install gh -y

# Docker CLI (talks to host daemon via socket mount — no Docker daemon inside)
RUN apt-get install -y docker-ce-cli docker-compose-plugin

# Language runtimes, linters, test runners (project-specific)
RUN apt-get install -y nodejs npm python3 python3-pip

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code
```

### Docker Socket Mount

To run `docker compose` commands from inside the Dev Container, the host Docker socket is bind-mounted:

```
/var/run/docker.sock → host Docker daemon
```

This means the Dev Container's Docker CLI controls the *host* Docker daemon — no Docker-in-Docker nesting, no additional overhead. The tradeoff is that containers spawned from inside the Dev Container appear on the host, not nested inside it. This is the preferred approach for development workflows.

> **Security note:** Mounting the Docker socket grants the container effective root-equivalent access to the host Docker daemon. This is acceptable for trusted dev team environments. For shared or untrusted environments, consider Docker-in-Docker or a rootless Docker setup instead.

### Credentials

CLI tools inside the Dev Container authenticate via credentials from the host, passed as environment variables or mounted credential directories:

| Tool | Credential mechanism |
|------|---------------------|
| AZ CLI | `~/.azure/` mounted from host, or `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` env vars |
| GH CLI | `GITHUB_TOKEN` env var, or `~/.config/gh/` mounted |
| Anthropic API | `ANTHROPIC_API_KEY` env var |
| Docker | Host socket mount — uses host's Docker credentials |

Credentials are injected at Dev Container startup via `remoteEnv` in `devcontainer.json`. Agents never store credentials — they inherit them from the container environment.

### Task Engine Integration

When the MCP Task Engine spawns a sub-agent (see Section 9), it targets the Dev Container rather than the MCP server container directly. The subprocess call executes inside the Dev Container environment, giving the agent access to all installed tools:

```python
# Agent subprocess runs inside the Dev Container environment
proc = await asyncio.create_subprocess_exec(
    "claude", "--print", "--model", agent.model_preference,
    "--system-prompt", agent.system_prompt_path,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=f"/workspace/{agent.id}",
    env={**os.environ, "WORKSPACE": f"/workspace/{agent.id}"},
)
```

The MCP server container and the Dev Container share the `/workspace` volume, so artifacts written by agents are accessible to both.

---

## 6. Deployment Architecture

Development and deployment are intentionally separate phases with separate actors. Agents develop code and push it; they do not deploy it. This keeps side effects scoped, credentials minimal, and rollback straightforward.

### Phase 1: Development (agents in Dev Container)

Agents write code, run tests, push branches, create PRs, and merge to main — all from inside the Dev Container. They have access to GH CLI, AZ CLI, and Docker Compose for development-time operations (spinning up local services, running integration tests, etc.).

Agents do **not** run production deployments directly. Their job ends at a merged, tested PR.

### Phase 2a: Staging / Production Deployment (ADO Pipelines)

A merge to `main` triggers an ADO pipeline automatically. The pipeline is entirely independent of the agent system — it builds the container image, pushes to ACR, and deploys to Azure. No machine needs to be running; no agent is involved.

```yaml
# azure-pipelines.yml (example — lives in the project repo)
trigger:
  branches:
    include: [main]

stages:
  - stage: Build
    jobs:
      - job: BuildAndPush
        steps:
          - task: Docker@2
            inputs:
              command: buildAndPush
              repository: $(ACR_REPO)
              tags: $(Build.BuildId)

  - stage: Deploy
    jobs:
      - deployment: DeployToAzure
        environment: production
        steps:
          - task: AzureWebAppContainer@1
            inputs:
              appName: $(APP_NAME)
              imageName: $(ACR_REPO):$(Build.BuildId)

  - stage: Notify
    jobs:
      - job: SlackNotify
        steps:
          - script: |
              curl -X POST $SLACK_WEBHOOK \
                -d '{"text":"✅ Deployment $(Build.BuildId) complete"}'
```

On completion, the pipeline posts a Slack notification. Cowork can subscribe to this notification to confirm the deployment is live.

### Phase 2b: Local / Dev Environment Deployment (Cowork)

For spinning up local dev environments, restarting services after a code change, or deploying to a personal dev Azure slot, **Cowork acts as the host-level executor**. Cowork has machine access and credentials that the containerised agents do not.

The trigger flow:
1. Agent completes dev work → posts completion message to a designated Slack channel
2. Cowork monitors that channel (via a scheduled task or Slack MCP)
3. Cowork executes host-level deployment scripts: `docker compose build && docker compose up -d`, `az webapp deploy`, etc.
4. Cowork posts confirmation back to Slack

This makes Cowork the **bridge between the agent world and the host machine** — the only actor that has both event awareness and host-level execution capability. This role should be formalised as a reusable Cowork skill or scheduled task.

```
Agent → Slack: "Feature X complete, merged to main, PR #42"
Cowork (monitoring Slack) → runs: docker compose pull && docker compose up -d
Cowork → Slack: "Local env updated to latest main ✅"
```

### Deployment Actor Summary

| Environment | Trigger | Actor | Credentials |
|-------------|---------|-------|-------------|
| Local dev | Slack message from agent | Cowork (host) | Host machine credentials |
| Dev slot (Azure) | Slack message or manual | Cowork (host) | `~/.azure` on host |
| Staging | Merge to `main` | ADO Pipeline | Pipeline service principal |
| Production | Merge to `main` (gated) | ADO Pipeline | Pipeline service principal |

---

## 7. Data Model (SQLite)

### `agents` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID v4 |
| `name` | TEXT UNIQUE NOT NULL | Human-readable name |
| `role` | TEXT | e.g. "frontend", "backend", "tester" |
| `status` | TEXT | `idle`, `busy`, `disabled` |
| `system_prompt` | TEXT | Full system prompt content |
| `model_preference` | TEXT | e.g. "claude-sonnet-4-6", "gpt-4o" |
| `skills` | TEXT (JSON array) | List of installed skill IDs |
| `config` | TEXT (JSON) | Arbitrary config (temperature, max_tokens, etc.) |
| `created_at` | TEXT (ISO 8601) | |
| `updated_at` | TEXT (ISO 8601) | |

### `tasks` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID v4 |
| `agent_id` | TEXT FK | Assigned agent |
| `description` | TEXT NOT NULL | Task description |
| `status` | TEXT | `queued`, `running`, `completed`, `failed`, `cancelled` |
| `priority` | INTEGER | 1 (low) – 5 (critical) |
| `input_context` | TEXT (JSON) | Files, references, prior output passed in |
| `output` | TEXT (JSON) | Result payload |
| `error` | TEXT | Error message if failed |
| `created_at` | TEXT (ISO 8601) | |
| `started_at` | TEXT (ISO 8601) | |
| `completed_at` | TEXT (ISO 8601) | |

### `skills` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID v4 |
| `name` | TEXT UNIQUE NOT NULL | Skill name |
| `description` | TEXT | What the skill does |
| `file_path` | TEXT | Path to skill MD file in /skills/ |
| `version` | TEXT | Semver |
| `installed_at` | TEXT (ISO 8601) | |

---

## 8. MCP Server Implementation

The server uses the **official MCP Python SDK** (`FastMCP`) to expose all capabilities as MCP primitives. This means any MCP client (Claude Code, Cursor, Claude Desktop, OpenAI Agents SDK) can discover and use the tools natively.

### Transport

Primary: **Streamable HTTP** on `/mcp` endpoint (recommended by MCP spec for remote servers).
Fallback: **stdio** for local development and testing.

### Server Bootstrap

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP
from contextlib import asynccontextmanager

# --- MCP Server (tools, resources, prompts) ---
mcp = FastMCP(
    "Agent Manager",
    description="Manage sub-agents, delegate tasks, install skills",
)

# --- FastAPI App (REST for UI + static serving) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    await init_task_queue()
    yield
    await cleanup()

app = FastAPI(title="MCP Agent Manager", lifespan=lifespan)

# REST routes for React UI
app.include_router(api_router, prefix="/api/v1")

# Static React build
app.mount("/ui", StaticFiles(directory="ui/build", html=True), name="ui")

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "agents": await get_agent_count()}

# Mount FastMCP into FastAPI — single process, single port
# IDE connects to /mcp, UI connects to /api/v1
mcp.mount_to_fastapi(app, path="/mcp")
```

> **Key insight:** FastMCP handles the MCP protocol (JSON-RPC 2.0, tool discovery, Streamable HTTP). FastAPI handles everything else (REST, static files, health). Both share the same asyncio event loop, the same SQLite connection pool, and the same task engine — no IPC overhead. If you strip out the React UI, you can run `mcp.run(transport="streamable-http")` standalone.

### 6.1 MCP Tools (8 endpoints, all return JSON)

Each tool is registered via `@mcp.tool()` decorator.

#### `add_agent`
```python
@mcp.tool()
async def add_agent(
    name: str,
    role: str,
    system_prompt: str,
    model_preference: str = "claude-sonnet-4-6",
    config: dict | None = None,
) -> dict:
    """Register a new sub-agent with a name, role, and system prompt.
    The system_prompt can be inline text or a path to an .md file
    in the /skills/ directory."""
```
Returns: `{ "id": "...", "name": "...", "status": "idle", "created_at": "..." }`

#### `update_agent`
```python
@mcp.tool()
async def update_agent(
    agent_id: str,
    name: str | None = None,
    role: str | None = None,
    system_prompt: str | None = None,
    model_preference: str | None = None,
    status: str | None = None,
    config: dict | None = None,
) -> dict:
    """Update any field on an existing agent. Pass only the fields to change."""
```
Returns: Full updated agent object.

#### `get_agents`
```python
@mcp.tool()
async def get_agents(
    role: str | None = None,
    status: str | None = None,
) -> dict:
    """List all registered agents. Optionally filter by role or status."""
```
Returns: `{ "agents": [...], "total": N }`

#### `get_active_agents`
```python
@mcp.tool()
async def get_active_agents() -> dict:
    """List only agents currently executing a task (status=busy)."""
```
Returns: `{ "agents": [...], "active_count": N, "queue_depth": N }`

#### `delegate_task`
```python
@mcp.tool()
async def delegate_task(
    agent_id: str,
    description: str,
    input_context: dict | None = None,
    priority: int = 3,
) -> dict:
    """Assign a task to a specific agent. If the agent is busy or the
    concurrency limit is reached, the task is queued. Tasks are
    spawned as subprocess calls to the agent's configured model."""
```
Returns: `{ "task_id": "...", "status": "running"|"queued", "position": N }`

#### `check_task_status`
```python
@mcp.tool()
async def check_task_status(
    task_id: str,
) -> dict:
    """Check the current status of a delegated task."""
```
Returns: `{ "task_id": "...", "status": "...", "output": {...}|null, "error": "..."|null }`

#### `install_skill`
```python
@mcp.tool()
async def install_skill(
    name: str,
    description: str,
    content: str,
    version: str = "1.0.0",
    assign_to: list[str] | None = None,
) -> dict:
    """Install a skill (markdown file) into the skills library.
    Content is the full markdown text. Optionally assign to
    agent IDs immediately."""
```
Returns: `{ "skill_id": "...", "file_path": "...", "assigned_to": [...] }`

#### `prompt_agent`
```python
@mcp.tool()
async def prompt_agent(
    agent_id: str,
    message: str,
    context: dict | None = None,
    wait: bool = True,
) -> dict:
    """Send an ad-hoc prompt to an agent and optionally wait for response.
    This is for interactive/conversational use, not long-running tasks.
    If wait=False, returns a task_id to poll later."""
```
Returns (wait=True): `{ "agent_id": "...", "response": "...", "tokens_used": N }`
Returns (wait=False): `{ "task_id": "...", "status": "running" }`

### 6.2 MCP Resources

```python
@mcp.resource("agents://list")
async def list_agents_resource() -> str:
    """All registered agents as JSON (read-only context for LLM)."""

@mcp.resource("agents://{agent_id}")
async def get_agent_resource(agent_id: str) -> str:
    """Single agent details including skills and task history."""

@mcp.resource("tasks://active")
async def active_tasks_resource() -> str:
    """All running and queued tasks."""

@mcp.resource("skills://available")
async def available_skills_resource() -> str:
    """All installed skills with descriptions."""
```

### 6.3 MCP Prompts

```python
@mcp.prompt()
def delegate_task_prompt(task_description: str, preferred_role: str = "") -> str:
    """Generate a structured delegation prompt that helps the LLM
    pick the right agent and formulate the task."""

@mcp.prompt()
def agent_setup_prompt(role: str, project_context: str = "") -> str:
    """Generate a prompt for creating a well-configured agent
    with appropriate system prompt for the given role."""
```

---

## 9. Task Execution Engine

### Concurrency Model

- `MAX_CONCURRENT_AGENTS` (default: 3) — max simultaneous subprocess spawns
- `TASK_QUEUE_SIZE` (default: 20) — max queued tasks before rejecting
- Tasks run as **asyncio subprocess** calls
- Each agent gets its own working directory under `/workspace/{agent_id}/`
- Output artifacts are written to `/project/.claude/agents/` or `/project/.cursor/agents/`

### Execution Flow

```
delegate_task() called
    │
    ├── Agent idle + slots available?
    │   YES → spawn subprocess immediately
    │         → set agent.status = "busy"
    │         → set task.status = "running"
    │
    │   NO  → queue_depth < TASK_QUEUE_SIZE?
    │         YES → enqueue task (priority-ordered)
    │               → set task.status = "queued"
    │         NO  → reject with 429 / queue_full error
    │
    ▼
subprocess completes
    │
    ├── Success → task.status = "completed"
    │           → task.output = result JSON
    │           → write artifacts to project dir
    │           → agent.status = "idle"
    │           → dequeue next task for this agent (if any)
    │
    └── Failure → task.status = "failed"
              → task.error = error message
              → agent.status = "idle"
              → dequeue next
```

### Subprocess Execution

Agents execute via CLI subprocess calls depending on the configured model:

```python
# Claude-based agent
proc = await asyncio.create_subprocess_exec(
    "claude", "--print", "--model", agent.model_preference,
    "--system-prompt", agent.system_prompt_path,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=f"/workspace/{agent.id}",
)

# Or via Anthropic API (httpx) for containerized execution
response = await httpx_client.post(
    "https://api.anthropic.com/v1/messages",
    headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"]},
    json={
        "model": agent.model_preference,
        "system": agent.system_prompt,
        "messages": [{"role": "user", "content": task.description}],
        "max_tokens": agent.config.get("max_tokens", 4096),
    },
)
```

---

## 10. CLI

### Installation

```bash
pip install mcp-agent-manager
# or
pipx install mcp-agent-manager
```

### Commands

```bash
# Initialize a new project
mcp-agents init --ide claude        # creates .claude/agents/ structure
mcp-agents init --ide cursor        # creates .cursor/agents/ structure

# Start the server
mcp-agents up                       # docker-compose up -d
mcp-agents up --local               # run without docker (uvicorn directly)

# Stop
mcp-agents down

# Register the MCP server with your IDE
mcp-agents register                 # auto-detects IDE from init
mcp-agents register --ide claude    # explicit

# For Claude Code, this runs:
#   claude mcp add --transport http agent-manager \
#     --scope project http://localhost:8100/mcp

# For Cursor, this writes to .cursor/mcp.json:
#   { "mcpServers": { "agent-manager": {
#       "url": "http://localhost:8100/mcp" } } }

# Quick commands
mcp-agents list                     # list agents
mcp-agents add "Frontend Dev" \
  --role frontend \
  --prompt ./agents/frontend.md
mcp-agents delegate <agent-id> "Build the login form"
mcp-agents status <task-id>
mcp-agents logs <agent-id>          # tail agent subprocess logs
```

### IDE Config Auto-Generation

When `mcp-agents register` runs:

**Claude Code** → writes `.mcp.json` at project root:
```json
{
  "mcpServers": {
    "agent-manager": {
      "type": "http",
      "url": "http://localhost:8100/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_AUTH_TOKEN}"
      }
    }
  }
}
```

**Cursor** → writes `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "agent-manager": {
      "url": "http://localhost:8100/mcp",
      "headers": {
        "Authorization": "Bearer ${env:MCP_AUTH_TOKEN}"
      }
    }
  }
}
```

---

## 11. Artifact Storage

Based on IDE target, artifacts are stored in the project directory:

```
# Claude Code
.claude/
├── agents/
│   ├── configs/          # Agent definitions (exported JSON)
│   ├── outputs/          # Task output files
│   │   └── {task_id}/
│   │       ├── result.json
│   │       ├── artifacts/    # Generated code, docs, etc.
│   │       └── log.txt
│   └── skills/           # Locally cached skill .md files
└── settings.local.json   # May include MCP server ref

# Cursor
.cursor/
├── agents/
│   ├── configs/
│   ├── outputs/
│   │   └── {task_id}/
│   └── skills/
└── mcp.json              # MCP server config
```

---

## 12. React UI Editor

Served from the same Docker container on the same port as the MCP server (default `:8100`). FastAPI serves the React production build as static files on `/ui` and provides REST endpoints on `/api/v1`. No separate process or port needed.

### Route Map (single port)

```
:8100/mcp        → FastMCP (Streamable HTTP, JSON-RPC 2.0)  ← IDE connects here
:8100/api/v1/*   → FastAPI REST routes                      ← React UI connects here
:8100/ui/*       → React static build                       ← Browser opens here
:8100/health     → Health check                             ← Monitoring
```

### Pages

1. **Dashboard** — Overview of all agents, active tasks, queue depth, resource usage
2. **Agents** — CRUD agents, edit system prompts (Monaco editor for .md), toggle status
3. **Tasks** — View task history, live status, output preview, retry/cancel
4. **Skills** — Browse installed skills, upload new .md files, assign to agents
5. **Settings** — IDE target, auth token, concurrency limits, server URL

### Tech Stack

- React 18 + TypeScript
- Tailwind CSS
- Monaco Editor (for system prompt / skill editing)
- React Query (data fetching against FastAPI REST endpoints)
- The UI talks to the same FastAPI app via REST endpoints (separate from MCP transport)

### REST API (for UI only, not MCP)

The FastAPI app exposes a parallel REST API on `/api/v1/` for the React UI:

```
GET    /api/v1/agents
POST   /api/v1/agents
PATCH  /api/v1/agents/{id}
DELETE /api/v1/agents/{id}
GET    /api/v1/agents/active
POST   /api/v1/tasks/delegate
GET    /api/v1/tasks/{id}/status
GET    /api/v1/tasks
POST   /api/v1/skills/install
GET    /api/v1/skills
GET    /api/v1/dashboard/stats
POST   /api/v1/agents/{id}/prompt
```

These map 1:1 to the MCP tools but use standard REST conventions for the web UI.

---

## 13. Security

- **Auth**: Bearer token validation middleware on both MCP and REST endpoints. Token stored as env var, never in config files.
- **Network**: When remote, nginx handles TLS. MCP server only listens on 127.0.0.1 — nginx proxies from the public interface.
- **Container isolation**: Each project gets its own container. Agents run as subprocesses within the container, not as separate containers.
- **API key management**: Anthropic/OpenAI keys passed as env vars to the container, never stored in SQLite.
- **Input validation**: Pydantic models on all endpoints. System prompts sanitized for injection.
- **Rate limiting**: nginx layer (remote) or FastAPI middleware (local).

---

## 14. Repository Structure

```
mcp-agent-manager/
├── README.md
├── LICENSE                     # MIT
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # lint + test
│   │   └── release.yml         # PyPI + Docker Hub publish
│   └── ISSUE_TEMPLATE/
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entrypoint: FastAPI app + FastMCP ASGI mount
│   ├── mcp_server.py           # FastMCP tools, resources, prompts
│   ├── rest_api.py             # FastAPI REST routes for UI
│   ├── models.py               # Pydantic models
│   ├── database.py             # SQLite via aiosqlite
│   ├── task_engine.py          # Subprocess spawning + queue
│   ├── agent_runner.py         # Agent execution logic
│   ├── skill_manager.py        # Skill install/assign
│   ├── config.py               # Env var config
│   └── auth.py                 # Bearer token middleware
├── ui/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Agents.tsx
│   │   │   ├── Tasks.tsx
│   │   │   ├── Skills.tsx
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   └── api/                # React Query hooks
│   └── build/                  # Production build (served by FastAPI)
├── cli/
│   ├── __init__.py
│   └── main.py                 # Click-based CLI
├── tests/
│   ├── test_mcp_tools.py
│   ├── test_task_engine.py
│   ├── test_rest_api.py
│   └── test_cli.py
├── examples/
│   ├── agents/
│   │   ├── frontend-dev.md     # Example agent system prompt
│   │   ├── backend-dev.md
│   │   ├── code-reviewer.md
│   │   └── test-writer.md
│   ├── skills/
│   │   ├── react-component.md
│   │   ├── api-endpoint.md
│   │   └── unit-test.md
│   └── docker-compose.remote.yml
└── docs/
    ├── QUICKSTART.md
    ├── ARCHITECTURE.md
    ├── MCP_INTEGRATION.md
    └── NGINX_SETUP.md
```

---

## 15. Implementation Phases

### Phase 1 — Core (MVP)
- SQLite schema + database layer
- FastMCP server with all 8 tools
- Task engine with subprocess spawning + basic queue
- CLI: `init`, `up`, `down`, `register`, `list`
- Bearer token auth
- Dockerfile + docker-compose

### Phase 2 — UI + Polish
- React UI (Dashboard, Agents, Tasks pages)
- Monaco-based system prompt editor
- Skills management (install, assign, browse)
- CLI: `add`, `delegate`, `status`, `logs`
- MCP resources + prompts
- REST API for UI

### Phase 3 — Production Hardening
- nginx example configs + docs
- Graceful shutdown / task drain
- Task retry with exponential backoff
- Agent health checks
- Structured logging (JSON)
- GitHub Actions CI/CD
- PyPI + Docker Hub publishing
- README, quickstart, architecture docs

### Phase 4 — Deployment Integration
- Dev Container scaffolding: `mcp-agents init` generates `.devcontainer/devcontainer.json` + `Dockerfile.devcontainer` with configurable tool set (AZ CLI, GH CLI, Docker Compose, language runtimes)
- Docker socket mount wiring in generated `devcontainer.json`
- Credential injection helpers: env var templates for AZ CLI, GH CLI, Anthropic API
- ADO pipeline template generation: `mcp-agents pipeline init` scaffolds `azure-pipelines.yml` with build → push → deploy → Slack notify stages
- Cowork deployment skill: a reusable Cowork skill that listens for agent completion events on Slack and runs configurable host-level deployment scripts
- Webhook / Slack event support in task engine: emit structured completion events that Cowork and ADO pipelines can consume

### Phase 5 — Advanced
- Multi-model support (OpenAI, local models via Ollama)
- Agent-to-agent delegation (agent A can delegate sub-tasks to agent B)
- MCP Registry listing
- Plugin system for custom task runners
- Metrics endpoint (Prometheus-compatible)

---

## 16. IDE Integration Quick Reference

### Claude Code

```bash
# After mcp-agents init --ide claude && mcp-agents up:
claude mcp add --transport http agent-manager \
  --scope project http://localhost:8100/mcp

# Verify
claude mcp list
# In Claude Code:
/mcp   # should show agent-manager as connected
```

### Cursor

```bash
# After mcp-agents init --ide cursor && mcp-agents up:
# .cursor/mcp.json is auto-generated
# Restart Cursor
# Check: Settings → Tools & MCP → agent-manager should show connected
```

### Usage from either IDE

Once connected, the LLM can use the tools naturally:

```
User: "Create a frontend agent and have it build a login component"

IDE LLM → calls add_agent(name="Frontend Dev", role="frontend", ...)
IDE LLM → calls delegate_task(agent_id="...", description="Build login component...")
IDE LLM → calls check_task_status(task_id="...")
IDE LLM → reads output artifacts from .claude/agents/outputs/{task_id}/
```
