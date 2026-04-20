import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import src.mcp_server as mcp_module
import src.task_engine as te_module
from src.database import get_db
from src.mcp_server import add_agent, delegate_task
from src.task_engine import TaskEngine


@pytest.mark.asyncio
async def test_task_retries_on_failure(db_path) -> None:
    """A task with max_retries=2 should be retried up to 2 times on failure."""
    attempt = 0

    async def flaky_run(*args, **kwargs) -> tuple[str, int]:
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise RuntimeError(f"Transient error (attempt {attempt})")
        return "success on attempt 3", 0

    # Patch sleep to avoid real delays in tests
    with patch("src.agent_runner.APIAgentRunner.run", side_effect=flaky_run), \
         patch("src.task_engine.asyncio.sleep", new_callable=AsyncMock):

        agent = await add_agent(name="FlakyBot", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()

            result = await delegate_task(
                agent=agent["id"], description="flaky work", max_retries=2
            )
            task_id = result["task_id"]

            # Give enough time for 3 attempts (with mocked sleep)
            await asyncio.sleep(0.6)
            await engine.stop(drain_timeout=3.0)

    db = await get_db()
    async with db.execute(
        "SELECT status, retry_count, output FROM tasks WHERE id=?", (task_id,)
    ) as cur:
        row = await cur.fetchone()

    assert row is not None
    assert row[0] == "completed", f"Expected completed, got {row[0]}"
    assert row[1] == 2, f"Expected retry_count=2, got {row[1]}"


@pytest.mark.asyncio
async def test_task_fails_after_exhausting_retries(db_path) -> None:
    """A task that always fails should be marked failed after max_retries exhausted."""
    with patch("src.agent_runner.APIAgentRunner.run", side_effect=RuntimeError("always fails")), \
         patch("src.task_engine.asyncio.sleep", new_callable=AsyncMock):

        agent = await add_agent(name="AlwaysFail", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            result = await delegate_task(
                agent=agent["id"], description="doomed task", max_retries=1
            )
            task_id = result["task_id"]

            await asyncio.sleep(0.4)
            await engine.stop(drain_timeout=3.0)

    db = await get_db()
    async with db.execute(
        "SELECT status, retry_count, error FROM tasks WHERE id=?", (task_id,)
    ) as cur:
        row = await cur.fetchone()

    assert row is not None
    assert row[0] == "failed"
    assert row[1] == 1  # one retry was made
    assert "always fails" in (row[2] or "")


@pytest.mark.asyncio
async def test_no_retry_when_max_retries_zero(db_path) -> None:
    """Default max_retries=0 means no retries — fail immediately."""
    call_count = 0

    async def fail_once(*args, **kwargs) -> tuple[str, int]:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("immediate fail")

    with patch("src.agent_runner.APIAgentRunner.run", side_effect=fail_once):
        agent = await add_agent(name="NoRetry", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            await delegate_task(agent=agent["id"], description="no-retry task")
            await asyncio.sleep(0.3)
            await engine.stop(drain_timeout=2.0)

    assert call_count == 1, "Runner should only be called once with max_retries=0"


@pytest.mark.asyncio
async def test_retry_increments_retry_count(db_path) -> None:
    """Each retry should increment retry_count in the DB."""
    attempt = 0

    async def fail_twice(*args, **kwargs) -> tuple[str, int]:
        nonlocal attempt
        attempt += 1
        if attempt <= 2:
            raise RuntimeError("fail")
        return "ok", 0

    with patch("src.agent_runner.APIAgentRunner.run", side_effect=fail_twice), \
         patch("src.task_engine.asyncio.sleep", new_callable=AsyncMock):
        agent = await add_agent(name="CountBot", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            result = await delegate_task(
                agent=agent["id"], description="count retries", max_retries=3
            )
            task_id = result["task_id"]

            await asyncio.sleep(0.6)
            await engine.stop(drain_timeout=3.0)

    db = await get_db()
    async with db.execute("SELECT status, retry_count FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()

    assert row[0] == "completed"
    assert row[1] == 2
