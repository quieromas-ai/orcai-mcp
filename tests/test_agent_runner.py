"""Tests for CLIAgentRunner shared workspace (PROJECT_DIR env var + symlink)."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runner import CLIAgentRunner


@pytest.fixture
def workspace(tmp_path):
    ws = str(tmp_path / "agent-workspace")
    os.makedirs(ws, exist_ok=True)
    return ws


@pytest.fixture
def project_dir(tmp_path):
    pd = str(tmp_path / "shared-project")
    os.makedirs(pd, exist_ok=True)
    return pd


@pytest.fixture
def agent():
    return {
        "id": "test-agent-id",
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


class TestSharedWorkspace:
    @pytest.mark.asyncio
    async def test_project_dir_in_subprocess_env(self, workspace, project_dir, agent):
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, workspace)

        env = mock_exec.call_args.kwargs["env"]
        assert env["PROJECT_DIR"] == project_dir

    @pytest.mark.asyncio
    async def test_workspace_env_still_injected(self, workspace, project_dir, agent):
        mock_exec = AsyncMock(return_value=_fake_process())
        with patch("asyncio.create_subprocess_exec", mock_exec), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, workspace)

        env = mock_exec.call_args.kwargs["env"]
        assert env["WORKSPACE"] == workspace

    @pytest.mark.asyncio
    async def test_project_symlink_created(self, workspace, project_dir, agent):
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_fake_process())), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, workspace)

        symlink = os.path.join(workspace, "project")
        assert os.path.islink(symlink)
        assert os.readlink(symlink) == project_dir

    @pytest.mark.asyncio
    async def test_project_symlink_idempotent(self, workspace, project_dir, agent):
        runner = CLIAgentRunner()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_fake_process())), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await runner.run(agent, "first", {}, workspace)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_fake_process())), \
             patch("src.agent_runner.settings.project_dir", project_dir), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await runner.run(agent, "second", {}, workspace)  # must not raise

        assert os.path.islink(os.path.join(workspace, "project"))

    @pytest.mark.asyncio
    async def test_no_symlink_when_project_dir_missing(self, workspace, agent):
        nonexistent = "/tmp/__orcai_no_such_project_dir_xyz__"
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_fake_process())), \
             patch("src.agent_runner.settings.project_dir", nonexistent), \
             patch("src.agent_runner.settings.enable_agent_delegation", False):
            await CLIAgentRunner().run(agent, "task", {}, workspace)

        assert not os.path.lexists(os.path.join(workspace, "project"))
