import asyncio
import itertools
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from typing import Any

from src.agent_runner import get_runner
from src.config import settings
from src.database import fetch_agent, get_db, parse_json_fields, row_to_dict

logger = logging.getLogger(__name__)

_task_counter = itertools.count()
DRAIN_TIMEOUT = 30.0


class QueueFullError(Exception):
    pass


class TaskEngine:
    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, str]] | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._running = False

    def start(self, requeue_on_start: bool = False) -> None:
        self._queue = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_agents)
        self._active_tasks = set()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        if requeue_on_start:
            asyncio.create_task(self._requeue_pending())

    async def _requeue_pending(self) -> None:
        """Restore tasks from a prior run: reset orphaned running tasks and requeue pending."""
        db = await get_db()
        # Tasks stuck in 'running' from a mid-run crash will never complete — reset them.
        await db.execute("UPDATE tasks SET status='queued' WHERE status='running'")
        await db.commit()
        async with db.execute(
            "SELECT id, priority FROM tasks WHERE status='queued' ORDER BY created_at"
        ) as cur:
            rows = list(await cur.fetchall())
        cap = settings.task_queue_size
        for task_id, priority in rows[:cap]:
            counter = next(_task_counter)
            await self._queue.put((5 - priority, counter, task_id))  # type: ignore[union-attr]
        if len(rows) > cap:
            logger.warning(
                "task_engine_requeue_capped: %d task(s) dropped (queue_size=%d)",
                len(rows) - cap,
                cap,
            )
        if rows:
            logger.info("task_engine_requeued %d task(s) on startup", min(len(rows), cap))

    async def stop(self, drain_timeout: float = DRAIN_TIMEOUT) -> None:
        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._worker_task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

        if self._active_tasks:
            n = len(self._active_tasks)
            logger.info(
                "Draining %d in-flight task(s) (timeout: %ds)", n, int(drain_timeout)
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + drain_timeout
            while self._active_tasks:
                remaining_time = deadline - loop.time()
                if remaining_time <= 0:
                    break
                await asyncio.wait(
                    list(self._active_tasks),
                    timeout=min(0.1, remaining_time),
                )

            if self._active_tasks:
                remaining = len(self._active_tasks)
                logger.warning(
                    "Drain timeout exceeded — cancelling %d remaining task(s)", remaining
                )
                for t in list(self._active_tasks):
                    t.cancel()
                await asyncio.gather(*list(self._active_tasks), return_exceptions=True)
            else:
                logger.info("All tasks drained cleanly")

    def queue_depth(self) -> int:
        return self._queue.qsize() if self._queue else 0

    def active_count(self) -> int:
        return len(self._active_tasks)

    async def submit(self, task_id: str, priority: int) -> None:
        if self._queue is None:
            raise RuntimeError("TaskEngine not started — call start() first")
        if self._queue.qsize() >= settings.task_queue_size:
            raise QueueFullError(f"Task queue is full ({settings.task_queue_size} max)")
        counter = next(_task_counter)
        await self._queue.put((5 - priority, counter, task_id))

    async def _worker(self) -> None:
        while self._running:
            try:
                _priority, _counter, task_id = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0  # type: ignore[union-attr]
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t: asyncio.Task[None] = asyncio.create_task(self._run_task(task_id))
            self._active_tasks.add(t)
            t.add_done_callback(self._active_tasks.discard)

    async def _run_task(self, task_id: str) -> None:
        async with self._semaphore:  # type: ignore[union-attr]
            db = await get_db()

            async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                logger.error("task_not_found", extra={"task_id": task_id})
                return

            task = parse_json_fields(row_to_dict(row), "input_context", "output")
            agent_slug: str = task["agent_id"]

            try:
                agent = await fetch_agent(agent_slug)
            except ValueError:
                await self._fail_task(db, task, f"Agent '{agent_slug}' not found")
                return

            now = datetime.now(UTC).isoformat()
            await db.execute(
                "UPDATE tasks SET status='running', started_at=? WHERE id=?",
                (now, task_id),
            )
            await db.execute(
                """
                INSERT INTO agents_state (slug, status, last_run_at, last_task_id)
                VALUES (?, 'busy', ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    status='busy', last_run_at=excluded.last_run_at,
                    last_task_id=excluded.last_task_id
                """,
                (agent_slug, now, task_id),
            )
            await db.commit()

            task_scratch_dir = os.path.abspath(
                os.path.join(settings.data_dir, "task-scratch", task_id)
            )
            os.makedirs(task_scratch_dir, exist_ok=True)

            try:
                runner = get_runner(agent)
                result, tokens = await runner.run(
                    agent=agent,
                    task_description=task["description"],
                    input_context=task.get("input_context") or {},
                    task_scratch_dir=task_scratch_dir,
                )
                await self._complete_task(db, task, agent_slug, result, tokens)

            except asyncio.CancelledError:
                logger.warning("task_cancelled_on_shutdown", extra={"task_id": task_id})
                await self._fail_task(db, task, "Cancelled: server shutdown")
                await self._set_agent_idle(db, agent_slug)
                raise

            except Exception as exc:
                retry_count: int = task.get("retry_count", 0)
                max_retries: int = task.get("max_retries", 0)
                if retry_count < max_retries:
                    await self._retry_task(db, task, agent_slug, str(exc))
                else:
                    await self._fail_task(db, task, str(exc))
                await self._set_agent_idle(db, agent_slug)

            finally:
                shutil.rmtree(task_scratch_dir, ignore_errors=True)

    async def _set_agent_idle(self, db: Any, slug: str) -> None:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE agents_state SET status='idle', last_run_at=? WHERE slug=?",
            (now, slug),
        )
        await db.commit()

    async def _complete_task(
        self, db: Any, task: dict[str, Any], agent_slug: str, result: str, tokens: int = 0
    ) -> None:
        now = datetime.now(UTC).isoformat()
        output = {"text": result, "tokens_used": tokens}

        await self._write_artifact(task["id"], result)

        await db.execute(
            "UPDATE tasks SET status='completed', output=?, completed_at=? WHERE id=?",
            (json.dumps(output), now, task["id"]),
        )
        await db.commit()
        await self._set_agent_idle(db, agent_slug)
        logger.info(
            "task_completed",
            extra={"task_id": task["id"], "agent_slug": agent_slug},
        )

    async def _fail_task(self, db: Any, task: dict[str, Any], error: str) -> None:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE tasks SET status='failed', error=?, completed_at=? WHERE id=?",
            (error, now, task["id"]),
        )
        await db.commit()
        logger.error(
            "task_failed",
            extra={"task_id": task["id"], "error": error},
        )

    async def _retry_task(
        self, db: Any, task: dict[str, Any], agent_slug: str, error: str
    ) -> None:
        retry_count: int = task.get("retry_count", 0) + 1
        delay = 2 ** retry_count
        logger.warning(
            "task_retrying",
            extra={"task_id": task["id"], "attempt": retry_count, "delay_s": delay, "error": error},
        )
        now = datetime.now(UTC).isoformat()
        await db.execute(
            "UPDATE tasks SET status='queued', retry_count=? WHERE id=?",
            (retry_count, task["id"]),
        )
        await db.execute(
            "UPDATE agents_state SET status='idle', last_run_at=? WHERE slug=?",
            (now, agent_slug),
        )
        await db.commit()

        task_id = task["id"]

        async def _delayed_retry() -> None:
            await asyncio.sleep(delay)
            await self._run_task(task_id)

        t: asyncio.Task[None] = asyncio.create_task(_delayed_retry())
        self._active_tasks.add(t)
        t.add_done_callback(self._active_tasks.discard)

    async def _write_artifact(self, task_id: str, result: str) -> None:
        ide = settings.ide_target
        base = settings.project_dir
        output_dir = os.path.join(base, f".{ide}", "agents", "outputs", task_id)
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "result.json"), "w") as f:
            json.dump({"task_id": task_id, "result": result}, f, indent=2)


task_engine = TaskEngine()
