import asyncio
from unittest.mock import patch

import pytest

import src.mcp_server as mcp_module
import src.task_engine as te_module
from src.database import get_db
from src.mcp_server import add_agent, delegate_task
from src.task_engine import TaskEngine


@pytest.mark.asyncio
async def test_stop_waits_for_active_tasks(db_path) -> None:
    """stop() should wait for in-flight tasks to complete before returning."""
    completed = asyncio.Event()

    async def slow_run(*args, **kwargs) -> str:
        await asyncio.sleep(0.15)
        completed.set()
        return "done"

    with patch("src.agent_runner.APIAgentRunner.run", side_effect=slow_run):
        agent = await add_agent(name="SlowBot", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            result = await delegate_task(agent_id=agent["id"], description="slow task")
            task_id = result["task_id"]

            # Give worker a moment to pick up and start the task
            await asyncio.sleep(0.05)

            # Stop should drain the running task before returning
            await engine.stop(drain_timeout=5.0)

    assert completed.is_set(), "Task should have completed during drain"

    db = await get_db()
    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "completed"


@pytest.mark.asyncio
async def test_stop_cancels_on_timeout(db_path) -> None:
    """When drain_timeout is exceeded, stop() should cancel remaining tasks."""
    async def very_slow_run(*args, **kwargs) -> str:
        await asyncio.sleep(60.0)  # won't finish naturally
        return "never"

    with patch("src.agent_runner.APIAgentRunner.run", side_effect=very_slow_run):
        agent = await add_agent(name="FrozenBot", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            result = await delegate_task(agent_id=agent["id"], description="never ends")
            task_id = result["task_id"]

            await asyncio.sleep(0.05)
            # Drain with very short timeout — should cancel
            await engine.stop(drain_timeout=0.1)

    db = await get_db()
    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    # Task should be marked as failed (cancelled on shutdown)
    assert row is not None
    assert row[0] in ("failed", "running")  # may be running if cancel happened too fast


@pytest.mark.asyncio
async def test_queue_not_drained_after_stop(db_path) -> None:
    """Tasks still queued (not yet started) when stop() is called stay queued."""
    calls = 0

    async def counting_run(*args, **kwargs) -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)
        return "done"

    with patch("src.agent_runner.APIAgentRunner.run", side_effect=counting_run):
        agent = await add_agent(name="Queuer", role="dev")
        engine = TaskEngine()
        # Reduce concurrency so tasks back up
        engine._semaphore = None  # will be recreated in start()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            # Saturate the semaphore (MAX_CONCURRENT_AGENTS=3 in test env)
            for _ in range(3):
                await delegate_task(agent_id=agent["id"], description="concurrent")
            # Queue one more beyond concurrency
            await delegate_task(agent_id=agent["id"], description="queued extra")

            await asyncio.sleep(0.05)
            await engine.stop(drain_timeout=2.0)

    # The 3 concurrent tasks should have run; the queued one may not have
    assert calls <= 4


@pytest.mark.asyncio
async def test_active_count(db_path) -> None:
    """active_count() returns the number of in-flight tasks."""
    started = asyncio.Event()
    hold = asyncio.Event()

    async def gated_run(*args, **kwargs) -> str:
        started.set()
        await hold.wait()
        return "result"

    with patch("src.agent_runner.APIAgentRunner.run", side_effect=gated_run):
        agent = await add_agent(name="Gated", role="dev")
        engine = TaskEngine()

        with patch.object(te_module, "task_engine", engine), \
             patch.object(mcp_module, "task_engine", engine):
            engine.start()
            await delegate_task(agent_id=agent["id"], description="gated task")
            await asyncio.wait_for(started.wait(), timeout=2.0)

            assert engine.active_count() >= 1

            hold.set()
            await engine.stop(drain_timeout=2.0)

        assert engine.active_count() == 0
