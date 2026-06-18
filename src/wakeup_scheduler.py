import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.task_engine import TaskEngine

logger = logging.getLogger(__name__)


class WakeupScheduler:
    def __init__(self, task_engine: "TaskEngine") -> None:
        self._task_engine = task_engine
        self._poll_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        from src.config import settings
        self._poll_task = asyncio.create_task(
            self._poll_loop(settings.wakeup_poll_seconds)
        )
        logger.info("WakeupScheduler started (poll_interval=%ds)", settings.wakeup_poll_seconds)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._poll_task), timeout=5.0)
            except (asyncio.CancelledError, TimeoutError):
                pass
            self._poll_task = None
        logger.info("WakeupScheduler stopped")

    async def _poll_loop(self, interval: int) -> None:
        while True:
            try:
                await asyncio.sleep(interval)
                await self._fire_due_wakeups()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("wakeup_poll_error")

    async def _fire_due_wakeups(self) -> None:
        from src.agent_registry import get_agent
        from src.database import get_db
        from src.task_engine import QueueFullError

        db = await get_db()
        now = datetime.now(UTC).isoformat(timespec="microseconds")

        async with db.execute(
            "SELECT id, agent_id, prompt FROM scheduled_wakeups "
            "WHERE status='pending' AND wake_at <= ?",
            (now,),
        ) as cur:
            rows = await cur.fetchall()

        for row_id, agent_id, prompt in rows:
            # Claim-first: guarded UPDATE prevents cancel-during-fire race.
            try:
                claim_cursor = await db.execute(
                    "UPDATE scheduled_wakeups SET status='fired', fired_at=? "
                    "WHERE id=? AND status='pending'",
                    (now, row_id),
                )
            except Exception:
                logger.exception("wakeup_claim_error", extra={"wakeup_id": row_id})
                await db.rollback()
                continue

            if claim_cursor.rowcount == 0:
                # Already cancelled or fired — discard the no-op transaction.
                await db.rollback()
                continue

            # Re-check agent still exists before creating the task.
            try:
                get_agent(agent_id)
            except ValueError:
                logger.warning(
                    "wakeup_agent_gone — cancelling wakeup",
                    extra={"wakeup_id": row_id, "agent_id": agent_id},
                )
                # Override claim → cancelled in same transaction.
                await db.execute(
                    "UPDATE scheduled_wakeups SET status='cancelled', fired_at=NULL WHERE id=?",
                    (row_id,),
                )
                await db.commit()
                continue

            # Insert task in same transaction as claim → one atomic commit.
            task_id = str(uuid.uuid4())
            try:
                await db.execute(
                    """
                    INSERT INTO tasks
                        (id, agent_id, description, status, priority,
                         input_context, max_retries, created_at)
                    VALUES (?, ?, ?, 'queued', 3, '{}', 0, ?)
                    """,
                    (task_id, agent_id, prompt, now),
                )
                await db.commit()  # Atomically commits: status='fired' + task row.
            except Exception:
                logger.exception("wakeup_db_error", extra={"wakeup_id": row_id})
                # Rollback undoes the claim; wakeup stays pending for next poll.
                await db.rollback()
                continue

            try:
                await self._task_engine.submit(task_id, priority=3)
                logger.info(
                    "wakeup_fired",
                    extra={"wakeup_id": row_id, "agent_id": agent_id, "task_id": task_id},
                )
            except QueueFullError:
                # Claim committed — delete orphan task row and reset wakeup for next poll.
                await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                await db.execute(
                    "UPDATE scheduled_wakeups SET status='pending', fired_at=NULL WHERE id=?",
                    (row_id,),
                )
                await db.commit()
                logger.warning(
                    "wakeup_queue_full — will retry next poll",
                    extra={"wakeup_id": row_id, "agent_id": agent_id},
                )
