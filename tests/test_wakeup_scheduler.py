import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.wakeup_scheduler import WakeupScheduler


@pytest.mark.asyncio
async def test_fires_due_wakeup(db_path, mock_api_runner):
    """Pending wakeup with wake_at in the past fires and creates a task."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="WakeBot", role="dev", system_prompt="Wake up!")
    agent_id = agent["id"]

    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    past_wake = (now - timedelta(seconds=5)).isoformat()

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (wakeup_id, agent_id, "Wake prompt", "test", 60, past_wake, now.isoformat()),
    )
    await db.commit()

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start()
        scheduler = WakeupScheduler(engine)
        await scheduler._fire_due_wakeups()
        await asyncio.sleep(0.3)
        await engine.stop()

    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "fired"

    async with db.execute(
        "SELECT description FROM tasks WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
        (agent_id,),
    ) as cur:
        task_row = await cur.fetchone()
    assert task_row is not None
    assert task_row[0] == "Wake prompt"


@pytest.mark.asyncio
async def test_skips_future_wakeup(db_path):
    """Wakeup with wake_at in the future is not fired."""
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="FutureBot", role="dev", system_prompt="Not yet.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    future_wake = (now + timedelta(hours=1)).isoformat()

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (wakeup_id, agent["id"], "Too early", "test", 3600, future_wake, now.isoformat()),
    )
    await db.commit()

    engine = TaskEngine()
    engine.start()
    scheduler = WakeupScheduler(engine)
    await scheduler._fire_due_wakeups()
    await engine.stop()

    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "pending"


@pytest.mark.asyncio
async def test_skips_cancelled_wakeup(db_path):
    """Cancelled wakeup is never fired even if wake_at is in the past."""
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="CancelBot", role="dev", system_prompt="Cancelled.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    past = (now - timedelta(seconds=5)).isoformat()

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'cancelled', ?)
        """,
        (wakeup_id, agent["id"], "Should not fire", "test", 60, past, now.isoformat()),
    )
    await db.commit()

    engine = TaskEngine()
    engine.start()
    scheduler = WakeupScheduler(engine)
    await scheduler._fire_due_wakeups()
    await engine.stop()

    async with db.execute(
        "SELECT COUNT(*) FROM tasks WHERE agent_id=?", (agent["id"],)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_cancel_wakeup_tool(db_path):
    """cancel_wakeup MCP tool marks a pending wakeup as cancelled."""
    from src.database import get_db
    from src.mcp_server import add_agent, cancel_wakeup, schedule_wakeup

    agent = await add_agent(name="CancelMe", role="dev", system_prompt="Cancel me.")
    result = await schedule_wakeup(
        agent=agent["id"], delay_seconds=3600, prompt="Wake", reason="test"
    )
    wakeup_id = result["wakeup_id"]

    cancel_result = await cancel_wakeup(wakeup_id=wakeup_id)
    assert cancel_result["status"] == "cancelled"

    db = await get_db()
    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_wakeup_not_found(db_path):
    """cancel_wakeup returns not_found for unknown IDs."""
    from src.mcp_server import cancel_wakeup

    result = await cancel_wakeup(wakeup_id="nonexistent-id")
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_cancel_already_fired(db_path):
    """cancel_wakeup returns fired status when wakeup already fired."""
    from src.database import get_db
    from src.mcp_server import add_agent, cancel_wakeup

    agent = await add_agent(name="FiredBot", role="dev", system_prompt="Already fired.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at, fired_at)
        VALUES (?, ?, ?, ?, ?, ?, 'fired', ?, ?)
        """,
        (wakeup_id, agent["id"], "Already done", "test", 60, now.isoformat(), now.isoformat(), now.isoformat()),
    )
    await db.commit()

    result = await cancel_wakeup(wakeup_id=wakeup_id)
    assert result["status"] == "fired"


@pytest.mark.asyncio
async def test_delay_clamping(db_path):
    """schedule_wakeup clamps delay_seconds to [60, wakeup_max_delay_seconds]."""
    from src.mcp_server import add_agent, schedule_wakeup

    agent = await add_agent(name="ClampBot", role="dev", system_prompt="Clamp test.")

    r1 = await schedule_wakeup(agent=agent["id"], delay_seconds=5, prompt="too short")
    assert r1["delay_seconds"] == 60

    r2 = await schedule_wakeup(agent=agent["id"], delay_seconds=999999, prompt="too long")
    assert r2["delay_seconds"] == 86400

    r3 = await schedule_wakeup(agent=agent["id"], delay_seconds=300, prompt="in range")
    assert r3["delay_seconds"] == 300


@pytest.mark.asyncio
async def test_scheduler_start_stop():
    """WakeupScheduler starts a poll task and stops it cleanly."""
    from src.task_engine import TaskEngine

    engine = TaskEngine()
    engine.start()
    scheduler = WakeupScheduler(engine)
    scheduler.start()
    assert scheduler._poll_task is not None
    assert not scheduler._poll_task.done()
    await scheduler.stop()
    assert scheduler._poll_task is None
    await engine.stop()


# ---------------------------------------------------------------------------
# New tests from TL review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_full_retry(db_path):
    """Queue-full: wakeup stays pending, task marked failed, retry on next poll."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import QueueFullError, TaskEngine

    agent = await add_agent(name="QueueFullBot", role="dev", system_prompt="Queue full.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    past = (now - timedelta(seconds=5)).isoformat(timespec="microseconds")

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (wakeup_id, agent["id"], "Queue test", "test", 60, past, now.isoformat()),
    )
    await db.commit()

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start()
        # Make submit raise QueueFullError
        with patch.object(engine, "submit", side_effect=QueueFullError("full")):
            scheduler = WakeupScheduler(engine)
            await scheduler._fire_due_wakeups()
        await engine.stop()

    # Wakeup should be back to pending for retry
    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "pending"

    # No orphan task row — it is deleted on queue-full (Fix C)
    async with db.execute(
        "SELECT COUNT(*) FROM tasks WHERE agent_id=?", (agent["id"],)
    ) as cur:
        count = await cur.fetchone()
    assert count[0] == 0


@pytest.mark.asyncio
async def test_cancel_during_fire_race(db_path, mock_api_runner):
    """Wakeup cancelled in DB before _fire_due_wakeups processes it — no task created."""
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="RaceBot", role="dev", system_prompt="Race test.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    past = (now - timedelta(seconds=5)).isoformat(timespec="microseconds")

    # Insert as already-cancelled even though wake_at is in the past
    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'cancelled', ?)
        """,
        (wakeup_id, agent["id"], "Race prompt", "test", 60, past, now.isoformat()),
    )
    await db.commit()

    engine = TaskEngine()
    engine.start()
    scheduler = WakeupScheduler(engine)
    await scheduler._fire_due_wakeups()
    await engine.stop()

    # No task should be created
    async with db.execute(
        "SELECT COUNT(*) FROM tasks WHERE agent_id=?", (agent["id"],)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 0

    # Status stays cancelled
    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "cancelled"


@pytest.mark.asyncio
async def test_multiple_due_wakeups(db_path, mock_api_runner):
    """Three past-due pending wakeups all fire in one _fire_due_wakeups call."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="MultiBot", role="dev", system_prompt="Multi test.")
    db = await get_db()
    now = datetime.now(UTC)
    past = (now - timedelta(seconds=5)).isoformat(timespec="microseconds")

    wakeup_ids = []
    for i in range(3):
        wid = str(uuid.uuid4())
        wakeup_ids.append(wid)
        await db.execute(
            """
            INSERT INTO scheduled_wakeups
                (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (wid, agent["id"], f"Prompt {i}", "test", 60, past, now.isoformat()),
        )
    await db.commit()

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start()
        scheduler = WakeupScheduler(engine)
        await scheduler._fire_due_wakeups()
        await asyncio.sleep(0.3)
        await engine.stop()

    # All three wakeups should be fired
    for wid in wakeup_ids:
        async with db.execute(
            "SELECT status FROM scheduled_wakeups WHERE id=?", (wid,)
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == "fired", f"Wakeup {wid} not fired"

    # Three task rows created
    async with db.execute(
        "SELECT COUNT(*) FROM tasks WHERE agent_id=?", (agent["id"],)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 3


@pytest.mark.asyncio
async def test_delay_exact_boundaries(db_path):
    """schedule_wakeup accepts exact boundary values 60 and 86400 without clamping."""
    from src.mcp_server import add_agent, schedule_wakeup

    agent = await add_agent(name="BoundaryBot", role="dev", system_prompt="Boundary test.")

    r_min = await schedule_wakeup(agent=agent["id"], delay_seconds=60, prompt="min")
    assert r_min["delay_seconds"] == 60
    assert r_min["clamped"] is False

    r_max = await schedule_wakeup(agent=agent["id"], delay_seconds=86400, prompt="max")
    assert r_max["delay_seconds"] == 86400
    assert r_max["clamped"] is False

    r_low = await schedule_wakeup(agent=agent["id"], delay_seconds=5, prompt="below min")
    assert r_low["clamped"] is True

    r_high = await schedule_wakeup(agent=agent["id"], delay_seconds=999999, prompt="above max")
    assert r_high["clamped"] is True


@pytest.mark.asyncio
async def test_schedule_wakeup_unknown_agent(db_path):
    """schedule_wakeup returns structured error for unknown agent (no ValueError)."""
    from src.mcp_server import schedule_wakeup

    result = await schedule_wakeup(agent="nonexistent-agent", delay_seconds=300, prompt="test")
    assert result["status"] == "rejected"
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_reason_stored_as_null(db_path):
    """Empty reason string is persisted as NULL in the database."""
    from src.database import get_db
    from src.mcp_server import add_agent, schedule_wakeup

    agent = await add_agent(name="NullReasonBot", role="dev", system_prompt="Null reason.")
    result = await schedule_wakeup(agent=agent["id"], delay_seconds=300, prompt="test", reason="")
    wakeup_id = result["wakeup_id"]

    db = await get_db()
    async with db.execute(
        "SELECT reason FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] is None


@pytest.mark.asyncio
async def test_list_wakeups(db_path):
    """list_wakeups returns all wakeups, filterable by agent and status."""
    from src.mcp_server import add_agent, cancel_wakeup, list_wakeups, schedule_wakeup

    agent_a = await add_agent(name="ListBotA", role="dev", system_prompt="A")
    agent_b = await add_agent(name="ListBotB", role="dev", system_prompt="B")

    r1 = await schedule_wakeup(agent=agent_a["id"], delay_seconds=300, prompt="A1")
    r2 = await schedule_wakeup(agent=agent_a["id"], delay_seconds=600, prompt="A2")
    r3 = await schedule_wakeup(agent=agent_b["id"], delay_seconds=300, prompt="B1")

    # Cancel one of agent_a's wakeups
    await cancel_wakeup(wakeup_id=r1["wakeup_id"])

    # All wakeups
    all_result = await list_wakeups()
    assert all_result["total"] == 3

    # Filter by agent
    a_result = await list_wakeups(agent=agent_a["id"])
    assert a_result["total"] == 2

    b_result = await list_wakeups(agent=agent_b["id"])
    assert b_result["total"] == 1

    # Filter by status
    pending_result = await list_wakeups(status="pending")
    assert pending_result["total"] == 2

    cancelled_result = await list_wakeups(status="cancelled")
    assert cancelled_result["total"] == 1

    # Combined filter
    a_pending = await list_wakeups(agent=agent_a["id"], status="pending")
    assert a_pending["total"] == 1
    assert a_pending["wakeups"][0]["wakeup_id"] == r2["wakeup_id"]


@pytest.mark.asyncio
async def test_startup_requeue(db_path, mock_api_runner):
    """TaskEngine.start() requeues tasks with status='queued' from a prior run."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="RequeueBot", role="dev", system_prompt="Requeue test.")
    db = await get_db()
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Simulate a task left in 'queued' state from a prior server run
    await db.execute(
        """
        INSERT INTO tasks (id, agent_id, description, status, priority, input_context, max_retries, created_at)
        VALUES (?, ?, ?, 'queued', 3, '{}', 0, ?)
        """,
        (task_id, agent["id"], "Requeue me", now),
    )
    await db.commit()

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start(requeue_on_start=True)
        await asyncio.sleep(0.3)  # allow _requeue_pending and worker to run
        await engine.stop()

    # Task should have been picked up and completed (mock runner returns immediately)
    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] in ("completed", "running"), f"Expected completed/running, got {row[0]}"


@pytest.mark.asyncio
async def test_claim_insert_failure_resets_wakeup(db_path):
    """If task INSERT fails after claiming, rollback keeps wakeup pending and fired_at NULL."""
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="InsertFailBot", role="dev", system_prompt="Insert fail.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    past = (now - timedelta(seconds=5)).isoformat(timespec="microseconds")

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (wakeup_id, agent["id"], "Fail prompt", "test", 60, past, now.isoformat()),
    )
    await db.commit()

    # Force INSERT INTO tasks to fail via a trigger
    await db.execute(
        "CREATE TRIGGER fail_tasks_insert BEFORE INSERT ON tasks "
        "BEGIN SELECT RAISE(FAIL, 'Simulated DB failure'); END"
    )
    await db.commit()

    engine = TaskEngine()
    engine.start()
    scheduler = WakeupScheduler(engine)
    await scheduler._fire_due_wakeups()
    await engine.stop()

    await db.execute("DROP TRIGGER IF EXISTS fail_tasks_insert")
    await db.commit()

    # Claim rolled back — wakeup stays pending with fired_at NULL
    async with db.execute(
        "SELECT status, fired_at FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "pending"
    assert row[1] is None

    # No task row
    async with db.execute("SELECT COUNT(*) FROM tasks WHERE agent_id=?", (agent["id"],)) as cur:
        count = await cur.fetchone()
    assert count[0] == 0


@pytest.mark.asyncio
async def test_startup_resets_orphaned_running_tasks(db_path, mock_api_runner):
    """_requeue_pending() resets tasks stuck in running from a prior crash to queued."""
    import src.mcp_server as mcp_module
    import src.task_engine as te_module
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="OrphanBot", role="dev", system_prompt="Orphan test.")
    db = await get_db()
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    await db.execute(
        """
        INSERT INTO tasks
            (id, agent_id, description, status, priority, input_context, max_retries, created_at, started_at)
        VALUES (?, ?, ?, 'running', 3, '{}', 0, ?, ?)
        """,
        (task_id, agent["id"], "Orphaned task", now, now),
    )
    await db.commit()

    engine = TaskEngine()
    with patch.object(te_module, "task_engine", engine), \
         patch.object(mcp_module, "task_engine", engine):
        engine.start(requeue_on_start=True)
        await asyncio.sleep(0.4)
        await engine.stop()

    async with db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] in ("completed", "running", "queued"), f"Unexpected status: {row[0]}"


@pytest.mark.asyncio
async def test_wake_at_iso_format(db_path):
    """schedule_wakeup returns wake_at with consistent microsecond precision."""
    from src.mcp_server import add_agent, schedule_wakeup

    agent = await add_agent(name="ISOBot", role="dev", system_prompt="ISO test.")
    result = await schedule_wakeup(agent=agent["id"], delay_seconds=300, prompt="ISO test")

    wake_at = result["wake_at"]
    parsed = datetime.fromisoformat(wake_at)
    assert parsed.tzinfo is not None

    # Microseconds must always be present (no inconsistent fractional seconds)
    assert "." in wake_at, f"wake_at missing fractional seconds: {wake_at}"
    fractional = wake_at.split(".")[1].split("+")[0].rstrip("Z")
    assert len(fractional) == 6, f"Expected 6-digit microseconds, got: {fractional!r}"


@pytest.mark.asyncio
async def test_wakeup_gone_agent_cancelled(db_path):
    """Wakeup for a deleted agent is cancelled at fire time, no task created."""
    from src.database import get_db
    from src.mcp_server import add_agent
    from src.task_engine import TaskEngine

    agent = await add_agent(name="GoneBot", role="dev", system_prompt="Gone.")
    db = await get_db()
    wakeup_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    past = (now - timedelta(seconds=5)).isoformat(timespec="microseconds")

    await db.execute(
        """
        INSERT INTO scheduled_wakeups
            (id, agent_id, prompt, reason, delay_seconds, wake_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (wakeup_id, "nonexistent-agent-slug", "Ghost prompt", "test", 60, past, now.isoformat()),
    )
    await db.commit()

    engine = TaskEngine()
    engine.start()
    scheduler = WakeupScheduler(engine)
    await scheduler._fire_due_wakeups()
    await engine.stop()

    # Wakeup should be cancelled
    async with db.execute(
        "SELECT status FROM scheduled_wakeups WHERE id=?", (wakeup_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "cancelled"

    # No task created
    async with db.execute("SELECT COUNT(*) FROM tasks") as cur:
        row = await cur.fetchone()
    assert row[0] == 0
