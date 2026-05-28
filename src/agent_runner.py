import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

from src.config import settings
from src.memory_manager import build_memory_prompt, resolve_memory_dir


class BaseAgentRunner(ABC):
    @staticmethod
    def _build_prompt(task_description: str, input_context: dict[str, Any]) -> str:
        if input_context:
            return f"{task_description}\n\nContext:\n{json.dumps(input_context, indent=2)}"
        return task_description

    @staticmethod
    def _augment_system_prompt(agent: dict[str, Any]) -> str:
        """Return system prompt with memory block appended when agent has memory scope."""
        base: str = agent.get("system_prompt") or ""
        scope: str | None = agent.get("memory")
        if not scope or scope not in ("user", "project", "local"):
            return base
        memory_block = build_memory_prompt(
            agent_name=agent["id"],
            scope=scope,  # type: ignore[arg-type]
            claude_dir=settings.claude_dir,
        )
        return f"{base}{memory_block}" if base else memory_block

    @abstractmethod
    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        task_scratch_dir: str,
    ) -> tuple[str, int]:
        """Execute task and return (result_text, tokens_used)."""


class APIAgentRunner(BaseAgentRunner):
    """Calls the Anthropic Messages API directly via httpx."""

    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        task_scratch_dir: str,
    ) -> tuple[str, int]:
        api_key = settings.anthropic_api_key
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        prompt = self._build_prompt(task_description, input_context)

        config: dict[str, Any] = agent.get("config") or {}
        max_tokens: int = int(config.get("max_tokens", 4096))
        system_prompt = self._augment_system_prompt(agent)

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
                    "system": system_prompt,
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
    def _write_mcp_config(scratch_dir: str) -> str:
        mcp_config = {
            "mcpServers": {
                "orcai-mcp": {
                    "type": "http",
                    "url": f"http://localhost:{settings.port}/mcp/delegate/mcp",
                }
            }
        }
        path = os.path.join(scratch_dir, ".mcp-delegate.json")
        with open(path, "w") as f:
            json.dump(mcp_config, f)
        return path

    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        task_scratch_dir: str,
    ) -> tuple[str, int]:
        prompt = self._build_prompt(task_description, input_context)

        delegation_enabled = settings.enable_agent_delegation
        system_prompt = self._augment_system_prompt(agent)
        if delegation_enabled and system_prompt:
            system_prompt += self._DELEGATION_HINT

        system_prompt_path: str | None = None
        if system_prompt:
            system_prompt_path = os.path.join(task_scratch_dir, ".system_prompt.md")
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
            mcp_config_path = self._write_mcp_config(task_scratch_dir)
            cmd += ["--mcp-config", mcp_config_path]

        memory_scope: str | None = agent.get("memory")
        if memory_scope and memory_scope in ("user", "project", "local"):
            memory_dir = resolve_memory_dir(
                agent_name=agent["id"],
                scope=memory_scope,  # type: ignore[arg-type]
                claude_dir=settings.claude_dir,
            )
            cmd += ["--add-dir", memory_dir]

        env = {**os.environ, "PROJECT_DIR": settings.project_dir}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.project_dir,
            env=env,
        )
        try:
            stdout, stderr = await proc.communicate(input=prompt.encode())
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
            raise

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI exited {proc.returncode}: {stderr.decode()}")
        return stdout.decode(), 0


def get_runner(agent: dict[str, Any]) -> BaseAgentRunner:
    runner_type: str = agent.get("runner", "api")
    if runner_type == "cli":
        return CLIAgentRunner()
    return APIAgentRunner()
