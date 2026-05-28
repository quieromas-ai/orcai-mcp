"""Tests for CLIAgentRunner and APIAgentRunner."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runner import BaseAgentRunner, CLIAgentRunner


@pytest.fixture
def scratch_dir(tmp_path):
    sd = str(tmp_path / "task-scratch")
    os.makedirs(sd, exist_ok=True)
    return sd


@pytest.fixture
def project_dir(tmp_path):
    pd = str(tmp_path / "shared-project")
    os.makedirs(pd, exist_ok=True)
    return pd


@pytest.fixture
def agent():
    return {
        "id": "test-agent",
        "system_prompt": "",
        "model_preference": "claude-haiku-4-5-20251001",
        "config": {},
        "runner": "cli",
    }


def _fake_process(stdout: bytes = b"result") -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


class TestCLIAgentRunner:
    @pytest.mark.asyncio
    async def test_project_dir_in_subprocess_env(self, scratch_dir, project_dir, agent):
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        env = mock_exec.call_args.kwargs["env"]
        assert env["PROJECT_DIR"] == project_dir

    @pytest.mark.asyncio
    async def test_cwd_set_to_project_dir(self, scratch_dir, project_dir, agent):
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        assert mock_exec.call_args.kwargs["cwd"] == project_dir

    @pytest.mark.asyncio
    async def test_system_prompt_written_to_scratch_dir(self, scratch_dir, project_dir, agent):
        agent["system_prompt"] = "You are helpful."
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        prompt_file = os.path.join(scratch_dir, ".system_prompt.md")
        assert os.path.isfile(prompt_file)
        with open(prompt_file) as f:
            assert "You are helpful." in f.read()

    @pytest.mark.asyncio
    async def test_no_system_prompt_file_when_empty(self, scratch_dir, project_dir, agent):
        agent["system_prompt"] = ""
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        prompt_file = os.path.join(scratch_dir, ".system_prompt.md")
        assert not os.path.isfile(prompt_file)

    @pytest.mark.asyncio
    async def test_mcp_config_written_to_scratch_dir(self, scratch_dir, project_dir, agent):
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", True):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        mcp_file = os.path.join(scratch_dir, ".mcp-delegate.json")
        assert os.path.isfile(mcp_file)

    @pytest.mark.asyncio
    async def test_memory_adds_dir_flag(self, scratch_dir, project_dir, agent, tmp_path):
        agent["memory"] = "project"
        mock_exec = AsyncMock(return_value=_fake_process())
        claude_dir = str(tmp_path / ".claude")
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.claude_dir", claude_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        cmd = list(mock_exec.call_args.args)
        assert "--add-dir" in cmd
        add_dir_idx = cmd.index("--add-dir")
        assert "agent-memory" in cmd[add_dir_idx + 1]

    @pytest.mark.asyncio
    async def test_no_memory_no_add_dir_flag(self, scratch_dir, project_dir, agent):
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        cmd = list(mock_exec.call_args.args)
        assert "--add-dir" not in cmd

    @pytest.mark.asyncio
    async def test_memory_injects_instructions_into_system_prompt(
        self, scratch_dir, project_dir, agent, tmp_path
    ):
        agent["system_prompt"] = "Base prompt."
        agent["memory"] = "project"
        mock_exec = AsyncMock(return_value=_fake_process())
        claude_dir = str(tmp_path / ".claude")
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.claude_dir", claude_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, scratch_dir)

        prompt_file = os.path.join(scratch_dir, ".system_prompt.md")
        with open(prompt_file) as f:
            contents = f.read()
        assert "Base prompt." in contents
        assert "MEMORY.md" in contents


class TestAugmentSystemPrompt:
    def test_no_memory_returns_base(self):
        agent = {"id": "a", "system_prompt": "Base.", "memory": None}
        with patch("src.agent_runner.settings.claude_dir", "/tmp"):
            result = BaseAgentRunner._augment_system_prompt(agent)
        assert result == "Base."

    def test_missing_memory_key_returns_base(self):
        agent = {"id": "a", "system_prompt": "Base."}
        with patch("src.agent_runner.settings.claude_dir", "/tmp"):
            result = BaseAgentRunner._augment_system_prompt(agent)
        assert result == "Base."

    def test_invalid_scope_returns_base(self):
        agent = {"id": "a", "system_prompt": "Base.", "memory": "global"}
        with patch("src.agent_runner.settings.claude_dir", "/tmp"):
            result = BaseAgentRunner._augment_system_prompt(agent)
        assert result == "Base."

    def test_valid_scope_appends_memory_block(self, tmp_path):
        agent = {"id": "my-agent", "system_prompt": "Base.", "memory": "project"}
        with patch("src.agent_runner.settings.claude_dir", str(tmp_path)):
            result = BaseAgentRunner._augment_system_prompt(agent)
        assert "Base." in result
        assert "MEMORY.md" in result
        assert "agent-memory" in result

    def test_empty_base_prompt_with_memory(self, tmp_path):
        agent = {"id": "my-agent", "system_prompt": "", "memory": "local"}
        with patch("src.agent_runner.settings.claude_dir", str(tmp_path)):
            result = BaseAgentRunner._augment_system_prompt(agent)
        assert "MEMORY.md" in result
