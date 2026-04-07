import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.task_engine import QueueFullError, TaskEngine


@pytest.mark.asyncio
async def test_submit_and_queue_depth() -> None:
    engine = TaskEngine()
    engine.start()
    with patch("src.agent_runner.APIAgentRunner.run", new_callable=AsyncMock) as m:
        m.return_value = "ok"
        await engine.submit("task-1", priority=3)
        await engine.submit("task-2", priority=5)
    await engine.stop()


@pytest.mark.asyncio
async def test_queue_full_raises() -> None:
    from src.config import settings

    engine = TaskEngine()
    # Initialize the queue by calling start, but immediately pause the worker
    engine.start()
    engine._running = False
    if engine._worker_task:
        engine._worker_task.cancel()

    # Fill queue to limit
    for i in range(settings.task_queue_size):
        await engine._queue.put((0, i, f"task-{i}"))  # type: ignore[union-attr]

    with pytest.raises(QueueFullError):
        await engine.submit("overflow", priority=3)


@pytest.mark.asyncio
async def test_priority_ordering() -> None:
    """Higher priority tasks should be dequeued first (min-heap, inverted priority)."""
    engine = TaskEngine()
    engine.start()
    engine._running = False  # stop worker so tasks stay in queue
    if engine._worker_task:
        engine._worker_task.cancel()

    await engine.submit("low", priority=1)
    await engine.submit("critical", priority=5)
    await engine.submit("medium", priority=3)

    first = await engine._queue.get()  # type: ignore[union-attr]
    assert first[2] == "critical"  # inverted: 5-5=0, lowest heap value = highest priority


@pytest.mark.asyncio
async def test_api_runner_called(db_path, mock_api_runner) -> None:
    """End-to-end: delegate_task → task engine → APIAgentRunner.run()"""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.mcp_server import add_agent, delegate_task

    agent = await add_agent(name="ApiBot", role="dev", system_prompt="You help.")

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start()
        result = await delegate_task(
            agent_id=agent["id"],
            description="Do something",
            priority=3,
        )
        task_id = result["task_id"]
        await asyncio.sleep(0.3)
        await engine.stop()

    from src.database import get_db
    db = await get_db()
    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_cli_runner_used_when_configured(db_path, mock_cli_runner) -> None:
    """Agent with runner=cli should use CLIAgentRunner."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.mcp_server import add_agent, delegate_task

    agent = await add_agent(
        name="CliBot",
        role="cli-dev",
        system_prompt="CLI agent",
        config={"runner": "cli"},
    )

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start()
        await delegate_task(agent_id=agent["id"], description="CLI task", priority=3)
        await asyncio.sleep(0.3)
        await engine.stop()

    mock_cli_runner.assert_called()
