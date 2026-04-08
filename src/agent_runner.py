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

    async def run(
        self,
        agent: dict[str, Any],
        task_description: str,
        input_context: dict[str, Any],
        workspace_dir: str,
    ) -> tuple[str, int]:
        prompt = self._build_prompt(task_description, input_context)

        system_prompt_path: str | None = None
        system_prompt = agent.get("system_prompt", "")
        if system_prompt:
            system_prompt_path = os.path.join(workspace_dir, ".system_prompt.md")
            with open(system_prompt_path, "w") as f:
                f.write(system_prompt)

        cmd = [
            "claude",
            "--print",
            "--model", agent.get("model_preference", "claude-sonnet-4-6"),
        ]
        if system_prompt_path:
            cmd += ["--system", system_prompt_path]

        env = {**os.environ, "WORKSPACE": workspace_dir}

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
    config: dict[str, Any] = agent.get("config") or {}
    runner_type: str = config.get("runner", "api")
    if runner_type == "cli":
        return CLIAgentRunner()
    return APIAgentRunner()
