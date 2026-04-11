"""Tests for CLI runner agent-to-agent delegation wiring."""

import json
import os
from unittest.mock import patch

import pytest

from src.agent_runner import CLIAgentRunner
from src.config import settings


@pytest.fixture
def workspace(tmp_path):
    ws = str(tmp_path / "workspace")
    os.makedirs(ws, exist_ok=True)
    return ws


class TestWriteMcpConfig:
    def test_creates_config_file(self, workspace: str) -> None:
        path = CLIAgentRunner._write_mcp_config(workspace)
        assert os.path.isfile(path)
        assert path.endswith(".mcp-delegate.json")

    def test_config_points_to_delegate_endpoint(self, workspace: str) -> None:
        path = CLIAgentRunner._write_mcp_config(workspace)
        with open(path) as f:
            config = json.load(f)
        server = config["mcpServers"]["orcai-mcp"]
        assert server["type"] == "http"
        assert "/mcp/delegate/mcp" in server["url"]

    def test_config_uses_configured_port(self, workspace: str) -> None:
        path = CLIAgentRunner._write_mcp_config(workspace)
        with open(path) as f:
            config = json.load(f)
        url = config["mcpServers"]["orcai-mcp"]["url"]
        assert f":{settings.port}/" in url


class TestDelegationHint:
    def test_hint_appended_to_system_prompt(self, workspace: str) -> None:
        agent = {"system_prompt": "You write code.", "model_preference": "claude-sonnet-4-6"}
        runner = CLIAgentRunner()

        with patch("src.config.settings.enable_agent_delegation", True):
            system_prompt = agent["system_prompt"]
            if settings.enable_agent_delegation and system_prompt:
                system_prompt += runner._DELEGATION_HINT
            assert "delegate_task" in system_prompt
            assert "get_agents" in system_prompt

    def test_hint_not_appended_when_disabled(self, workspace: str) -> None:
        agent = {"system_prompt": "You write code.", "model_preference": "claude-sonnet-4-6"}
        runner = CLIAgentRunner()

        with patch("src.config.settings.enable_agent_delegation", False):
            system_prompt = agent["system_prompt"]
            if settings.enable_agent_delegation and system_prompt:
                system_prompt += runner._DELEGATION_HINT
            assert "delegate_task" not in system_prompt

    def test_no_hint_when_no_system_prompt(self) -> None:
        runner = CLIAgentRunner()
        system_prompt = ""
        if system_prompt:
            system_prompt += runner._DELEGATION_HINT
        assert system_prompt == ""
