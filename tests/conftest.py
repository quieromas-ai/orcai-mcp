import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Use temp dirs for tests
os.environ["WORKSPACE_DIR"] = "/tmp/orcai_test_workspace"
os.environ["SKILLS_DIR"] = "/tmp/orcai_test_skills"
os.environ["PROJECT_DIR"] = "/tmp/orcai_test_project"
os.environ["MCP_AUTH_DISABLED"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"


@pytest_asyncio.fixture
async def db_path(tmp_path):
    """Initialise a fresh in-file SQLite DB per test."""
    import src.database as db_module
    db_module._db = None  # reset global connection

    path = str(tmp_path / "test.db")
    from src.database import close_database, init_database
    await init_database(db_path=path)
    yield path
    await close_database()


@pytest_asyncio.fixture
async def async_client(db_path) -> AsyncIterator[AsyncClient]:
    """Return an httpx AsyncClient with a fresh TaskEngine per test."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.task_engine import TaskEngine

    fresh_engine = TaskEngine()
    fresh_engine.start()

    with patch.object(te_module, "task_engine", fresh_engine), \
         patch.object(mcp_module, "task_engine", fresh_engine):
        from src.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    await fresh_engine.stop()


@pytest_asyncio.fixture
async def started_engine():
    """Fresh TaskEngine, started, patching both module references."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.task_engine import TaskEngine

    engine = TaskEngine()
    engine.start()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        yield engine
    await engine.stop()


@pytest.fixture
def mock_api_runner():
    """Patch APIAgentRunner.run to return a canned response."""
    with patch("src.agent_runner.APIAgentRunner.run", new_callable=AsyncMock) as mock:
        mock.return_value = ("Mock agent response", 0)
        yield mock


@pytest.fixture
def mock_cli_runner():
    """Patch CLIAgentRunner.run to return a canned response."""
    with patch("src.agent_runner.CLIAgentRunner.run", new_callable=AsyncMock) as mock:
        mock.return_value = ("Mock CLI response", 0)
        yield mock
