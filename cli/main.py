import json
import os
import subprocess
import sys

import click
import httpx


def _server_url(ctx: click.Context) -> str:
    return str(ctx.obj.get("url", "http://localhost:8100"))


@click.group()
@click.option("--url", default="http://localhost:8100", envvar="ORCAI_URL", help="Server base URL")
@click.pass_context
def cli(ctx: click.Context, url: str) -> None:
    """orcai-mcp — MCP sub-agent manager CLI"""
    ctx.ensure_object(dict)
    ctx.obj["url"] = url


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


_DEVCONTAINER_JSON = {
    "name": "orcai-mcp dev",
    "image": "python:3.12-slim",
    "features": {
        "ghcr.io/devcontainers/features/node:1": {"version": "20"},
        "ghcr.io/devcontainers/features/git:1": {},
    },
    "forwardPorts": [8100],
    "postCreateCommand": "pip install -e '.[dev]'",
    "remoteEnv": {
        "PORT": "8100",
        "MCP_AUTH_DISABLED": "true",
        "IDE_TARGET": "claude",
        "MAX_CONCURRENT_AGENTS": "3",
        "TASK_QUEUE_SIZE": "20",
        "DATA_DIR": "./data",
        "WORKSPACE_DIR": "./workspace",
        "SKILLS_DIR": "./skills",
        "PROJECT_DIR": ".",
    },
    "customizations": {
        "vscode": {
            "extensions": [
                "ms-python.python",
                "ms-python.vscode-pylance",
                "charliermarsh.ruff",
                "ms-python.mypy-type-checker",
            ],
            "settings": {
                "python.defaultInterpreterPath": "/usr/local/bin/python",
                "[python]": {
                    "editor.formatOnSave": True,
                    "editor.defaultFormatter": "charliermarsh.ruff",
                },
            },
        }
    },
}


@cli.command()
@click.option("--ide", type=click.Choice(["claude", "cursor"]), default="claude", show_default=True)
@click.option("--devcontainer", is_flag=True, default=False, help="Scaffold .devcontainer/ for VS Code / Cursor dev containers")
def init(ide: str, devcontainer: bool) -> None:
    """Initialise project artifact directories for Claude Code or Cursor."""
    base = f".{ide}"
    dirs = [
        os.path.join(base, "agents", "configs"),
        os.path.join(base, "agents", "outputs"),
        os.path.join(base, "agents", "skills"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        click.echo(f"  created {d}/")
    click.echo(f"\nInitialised {ide.upper()} artifact directories in {base}/")

    if devcontainer:
        dc_dir = ".devcontainer"
        os.makedirs(dc_dir, exist_ok=True)
        dc_path = os.path.join(dc_dir, "devcontainer.json")
        with open(dc_path, "w") as f:
            json.dump(_DEVCONTAINER_JSON, f, indent=2)
            f.write("\n")
        click.echo(f"  created {dc_path}")
        click.echo("\nDev container ready. Open this folder in VS Code or Cursor and")
        click.echo("select 'Reopen in Container' to start a fully configured dev environment.")

    click.echo("Next: run 'orcai-mcp up' then 'orcai-mcp register'")


# ---------------------------------------------------------------------------
# up / down
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--local", is_flag=True, help="Run without Docker (uvicorn directly)")
def up(local: bool) -> None:
    """Start the orcai-mcp server."""
    if local:
        click.echo("Starting server locally (uvicorn)…")
        os.execvp(sys.executable, [sys.executable, "-m", "src.main"])
    else:
        click.echo("Starting via docker compose…")
        subprocess.run(["docker", "compose", "up", "-d"], check=True)
        click.echo("Server started. Check logs: docker compose logs -f")


@cli.command()
def down() -> None:
    """Stop the orcai-mcp server."""
    click.echo("Stopping via docker compose…")
    subprocess.run(["docker", "compose", "down"], check=True)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--ide", type=click.Choice(["claude", "cursor"]), default=None)
@click.option("--url", default="http://localhost:8100", show_default=True)
@click.option("--token", default="", envvar="MCP_AUTH_TOKEN")
@click.pass_context
def register(ctx: click.Context, ide: str | None, url: str, token: str) -> None:
    """Register this MCP server with your IDE."""
    if ide is None:
        # Auto-detect from init
        if os.path.isdir(".claude"):
            ide = "claude"
        elif os.path.isdir(".cursor"):
            ide = "cursor"
        else:
            ide = "claude"
            click.echo("Could not detect IDE, defaulting to claude. Use --ide to override.")

    mcp_url = f"{url}/mcp"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        click.echo("Warning: token written to file in plaintext.")

    if ide == "claude":
        config = {
            "mcpServers": {
                "orcai-mcp": {
                    "type": "http",
                    "url": mcp_url,
                    **({"headers": headers} if headers else {}),
                }
            }
        }
        path = ".mcp.json"
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        click.echo(f"Written {path}")
        click.echo(f"Or run: claude mcp add --transport http orcai-mcp {mcp_url}")
    else:
        os.makedirs(".cursor", exist_ok=True)
        config = {
            "mcpServers": {
                "orcai-mcp": {
                    "url": mcp_url,
                    **({"headers": headers} if headers else {}),
                }
            }
        }
        path = ".cursor/mcp.json"
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        click.echo(f"Written {path}")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@cli.command(name="list")
@click.pass_context
def list_agents(ctx: click.Context) -> None:
    """List all registered agents."""
    url = _server_url(ctx)
    try:
        r = httpx.get(f"{url}/api/v1/agents", timeout=10.0)
        r.raise_for_status()
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    data = r.json()
    agents = data.get("agents", [])
    if not agents:
        click.echo("No agents registered.")
        return

    fmt = "{:<36}  {:<20}  {:<12}  {:<12}  {:<6}"
    click.echo(fmt.format("ID", "NAME", "ROLE", "STATUS", "RUNNER"))
    click.echo("-" * 95)
    for a in agents:
        cfg = a.get("config") or {}
        runner = cfg.get("runner", "api")
        click.echo(fmt.format(a["id"], a["name"][:20], a["role"][:12], a["status"], runner))


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("name")
@click.option("--role", default="", help="Agent role (e.g. frontend, backend)")
@click.option("--prompt", "prompt_path", default=None, help="Path to system prompt .md file")
@click.option("--model", default="claude-sonnet-4-6", show_default=True)
@click.option("--runner", type=click.Choice(["api", "cli"]), default="api", show_default=True)
@click.pass_context
def add(
    ctx: click.Context, name: str, role: str, prompt_path: str | None, model: str, runner: str
) -> None:
    """Register a new agent."""
    system_prompt = ""
    if prompt_path:
        with open(prompt_path) as f:
            system_prompt = f.read()

    url = _server_url(ctx)
    payload = {
        "name": name,
        "role": role,
        "system_prompt": system_prompt,
        "model_preference": model,
        "config": {"runner": runner},
    }
    try:
        r = httpx.post(f"{url}/api/v1/agents", json=payload, timeout=10.0)
        r.raise_for_status()
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    data = r.json()
    click.echo(f"Agent created: {data['id']} ({name})")


# ---------------------------------------------------------------------------
# delegate
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("agent_id")
@click.argument("description")
@click.option("--priority", default=3, type=click.IntRange(1, 5), show_default=True)
@click.pass_context
def delegate(ctx: click.Context, agent_id: str, description: str, priority: int) -> None:
    """Delegate a task to an agent."""
    url = _server_url(ctx)
    payload = {"agent_id": agent_id, "description": description, "priority": priority}
    try:
        r = httpx.post(f"{url}/api/v1/tasks/delegate", json=payload, timeout=10.0)
        r.raise_for_status()
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    data = r.json()
    click.echo(f"Task queued: {data.get('task_id')} (status: {data.get('status')})")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("task_id")
@click.pass_context
def status(ctx: click.Context, task_id: str) -> None:
    """Check status of a task."""
    url = _server_url(ctx)
    try:
        r = httpx.get(f"{url}/api/v1/tasks/{task_id}/status", timeout=10.0)
        r.raise_for_status()
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    data = r.json()
    click.echo(f"Status:  {data['status']}")
    if data.get("output"):
        click.echo(f"Output:  {json.dumps(data['output'], indent=2)}")
    if data.get("error"):
        click.echo(f"Error:   {data['error']}")


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("agent_id")
def logs(agent_id: str) -> None:
    """Show Docker logs filtered to lines mentioning agent_id.

    Note: filters by string match against container stdout — not a dedicated per-agent stream.
    """
    result = subprocess.run(
        ["docker", "compose", "logs", "--tail=200"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if agent_id in line:
            click.echo(line)
