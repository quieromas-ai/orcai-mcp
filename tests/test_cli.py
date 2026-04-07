import json
import os

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_init_claude(runner, tmp_path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["init", "--ide", "claude"])
        assert result.exit_code == 0
        assert os.path.isdir(".claude/agents/configs")
        assert os.path.isdir(".claude/agents/outputs")
        assert os.path.isdir(".claude/agents/skills")


def test_init_cursor(runner, tmp_path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["init", "--ide", "cursor"])
        assert result.exit_code == 0
        assert os.path.isdir(".cursor/agents/configs")


def test_register_claude(runner, tmp_path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.makedirs(".claude")
        result = runner.invoke(cli, ["register", "--ide", "claude"])
        assert result.exit_code == 0
        assert os.path.isfile(".mcp.json")
        config = json.loads(open(".mcp.json").read())
        assert "orcai-mcp" in config["mcpServers"]
        assert "/mcp" in config["mcpServers"]["orcai-mcp"]["url"]


def test_register_cursor(runner, tmp_path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["register", "--ide", "cursor"])
        assert result.exit_code == 0
        assert os.path.isfile(".cursor/mcp.json")
        config = json.loads(open(".cursor/mcp.json").read())
        assert "orcai-mcp" in config["mcpServers"]


def test_cli_help(runner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "orcai-mcp" in result.output
