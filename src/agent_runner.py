import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

from src.config import settings


class BaseAgentRunner(ABC):
    @staticmethod
    def _build_prompt(task_description: str, input_context: dict[str, Any]) -> str:
        if input_context:
            return f"{task_description}\n\nContext:\n{json.dumps(input_context, indent=2)}"
        return task_description

    @abstractmethod
    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        workspace_dir: str,
    ) -> tuple[str, int]:
        """Execute task and return (result_text, tokens_used)."""


class APIAgentRunner(BaseAgentRunner):
    """Calls the Anthropic Messages API directly via httpx."""

    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        workspace_dir: str,
    ) -> tuple[str, int]:
        api_key = settings.anthropic_api_key
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        prompt = self._build_prompt(task_description, input_context)

        config: dict[str, Any] = agent.get("config") or {}
        max_tokens: int = int(config.get("max_tokens", 4096))

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": agent.get("model_preference", "claude-sonnet-4-6"),
                    "system": agent.get("system_prompt", ""),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            text = "\n".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
            usage = data.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            return text, tokens


class CLIAgentRunner(BaseAgentRunner):
    """Spawns the Claude Code CLI as a subprocess."""

    _DELEGATION_HINT = (
        "\n\n---\n"
        "You have access to sibling agents via the orcai-mcp MCP server. "
        "Use `get_agents` to discover them and `delegate_task` to assign work. "
        "Poll with `check_task_status` until the task completes."
    )

    @staticmethod
    def _write_mcp_config(workspace_dir: str) -> str:
        """Write an MCP config file that connects back to the delegate endpoint."""
        mcp_config = {
            "mcpServers": {
                "orcai-mcp": {
                    "type": "http",
                    "url": f"http://localhost:{settings.port}/mcp/delegate/mcp",
                }
            }
        }
        path = os.path.join(workspace_dir, ".mcp-delegate.json")
        with open(path, "w") as f:
            json.dump(mcp_config, f)
        return path

    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        workspace_dir: str,
    ) -> tuple[str, int]:
        prompt = self._build_prompt(task_description, input_context)

        delegation_enabled = settings.enable_agent_delegation
        system_prompt = agent.get("system_prompt", "")
        if delegation_enabled and system_prompt:
            system_prompt += self._DELEGATION_HINT

        system_prompt_path: str | None = None
        if system_prompt:
            system_prompt_path = os.path.join(workspace_dir, ".system_prompt.md")
            with open(system_prompt_path, "w") as f:
                f.write(system_prompt)

        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--model", agent.get("model_preference", "claude-sonnet-4-6"),
        ]
        if system_prompt_path:
            cmd += ["--system-prompt-file", system_prompt_path]

        if delegation_enabled:
            mcp_config_path = self._write_mcp_config(workspace_dir)
            cmd += ["--mcp-config", mcp_config_path]

        env = {**os.environ, "WORKSPACE": workspace_dir, "PROJECT_DIR": settings.project_dir}

        # Create a 'project' symlink in the workspace so agents can reference the
        # shared project directory via a relative path (./project/) in addition to $PROJECT_DIR.
        shared_dir = settings.project_dir
        symlink_path = os.path.join(workspace_dir, "project")
        if os.path.isdir(shared_dir) and not os.path.lexists(symlink_path):
            os.symlink(shared_dir, symlink_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_dir,
            env=env,
        )
        try:
            stdout, stderr = await proc.communicate(input=prompt.encode())
        except asyncio.CancelledError:
            # Server is shutting down — terminate subprocess gracefully
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
            raise

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI exited {proc.returncode}: {stderr.decode()}")
        return stdout.decode(), 0  # CLI runner does not expose token counts


def get_runner(agent: dict[str, Any]) -> BaseAgentRunner:
    runner_type: str = agent.get("runner", "api")
    if runner_type == "cli":
        return CLIAgentRunner()
    return APIAgentRunner()
