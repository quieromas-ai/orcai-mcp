import asyncio
import itertools
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from src.agent_runner import get_runner
from src.config import settings

logger = logging.getLogger(__name__)

_task_counter = itertools.count()
DRAIN_TIMEOUT = 30.0  # seconds to wait for running tasks on shutdown


class QueueFullError(Exception):
    pass


class TaskEngine:
    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, str]] | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._running = False

    def start(self) -> None:
        # Bind queue and semaphore to the current running event loop
        self._queue = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_agents)
        self._active_tasks = set()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self, drain_timeout: float = DRAIN_TIMEOUT) -> None:
        """Stop accepting new tasks, drain in-flight tasks, then shut down."""
        self._running = False

        # Stop the queue-reader coroutine
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._worker_task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

        # Wait for all active task coroutines to finish (including retries spawned mid-drain)
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
                # asyncio.wait properly suspends the coroutine and allows other tasks to run;
                # re-check _active_tasks each iteration to pick up retries spawned mid-drain
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
                # Give cancelled coroutines a moment to clean up subprocesses
                await asyncio.gather(*list(self._active_tasks), return_exceptions=True)
            else:
                logger.info("All tasks drained cleanly")

    def queue_depth(self) -> int:
        return self._queue.qsize() if self._queue else 0

    def active_count(self) -> int:
        return len(self._active_tasks)

    async def submit(self, task_id: str, priority: int) -> None:
        """Enqueue a task by ID. Priority 5=critical, 1=low — invert for min-heap."""
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
        from src.database import get_db, parse_json_fields, row_to_dict

        async with self._semaphore:  # type: ignore[union-attr]
            db = await get_db()

            async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                logger.error("task_not_found", extra={"task_id": task_id})
                return

            task = parse_json_fields(row_to_dict(row), "input_context", "output")

            async with db.execute("SELECT * FROM agents WHERE id=?", (task["agent_id"],)) as cur:
                agent_row = await cur.fetchone()
            if not agent_row:
                await self._fail_task(db, task, "Agent not found")
                return

            agent = parse_json_fields(row_to_dict(agent_row), "config", "skills")

            now = datetime.now(UTC).isoformat()
            await db.execute(
                "UPDATE tasks SET status='running', started_at=? WHERE id=?",
                (now, task_id),
            )
            await db.execute(
                "UPDATE agents SET status='busy', updated_at=? WHERE id=?",
                (now, agent["id"]),
            )
            await db.commit()

            workspace_dir = os.path.join(settings.workspace_dir, agent["id"])
            os.makedirs(workspace_dir, exist_ok=True)

            try:
                runner = get_runner(agent)
                result, tokens = await runner.run(
                    agent=agent,
                    task_description=task["description"],
                    input_context=task.get("input_context") or {},
                    workspace_dir=workspace_dir,
                )
                await self._complete_task(db, task, agent, result, tokens)

            except asyncio.CancelledError:
                # Shutdown drain cancelled this coroutine — mark as failed + reset agent
                logger.warning("task_cancelled_on_shutdown", extra={"task_id": task_id})
                await self._fail_task(db, task, "Cancelled: server shutdown")
                await db.execute(
                    "UPDATE agents SET status='idle', updated_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), agent["id"]),
                )
                await db.commit()
                raise  # re-raise so asyncio.gather sees it

            except Exception as exc:
                retry_count: int = task.get("retry_count", 0)
                max_retries: int = task.get("max_retries", 0)
                if retry_count < max_retries:
                    await self._retry_task(db, task, str(exc))
                else:
                    await self._fail_task(db, task, str(exc))
                await db.execute(
                    "UPDATE agents SET status='idle', updated_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), agent["id"]),
                )
                await db.commit()

    async def _complete_task(
        self, db: Any, task: dict[str, Any], agent: dict[str, Any], result: str, tokens: int = 0
    ) -> None:
        now = datetime.now(UTC).isoformat()
        output = {"text": result, "tokens_used": tokens}

        await self._write_artifact(task["id"], result)

        await db.execute(
            "UPDATE tasks SET status='completed', output=?, completed_at=? WHERE id=?",
            (json.dumps(output), now, task["id"]),
        )
        await db.execute(
            "UPDATE agents SET status='idle', updated_at=? WHERE id=?",
            (now, agent["id"]),
        )
        await db.commit()
        logger.info(
            "task_completed",
            extra={"task_id": task["id"], "agent_id": agent["id"]},
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

    async def _retry_task(self, db: Any, task: dict[str, Any], error: str) -> None:
        retry_count: int = task.get("retry_count", 0) + 1
        delay = 2 ** retry_count  # exponential backoff in seconds
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
            "UPDATE agents SET status='idle', updated_at=? WHERE id=?",
            (now, task["agent_id"]),
        )
        await db.commit()

        # Schedule the retry as a tracked coroutine — NOT via the queue — so that
        # stop()/drain knows to wait for it even after the worker has been cancelled.
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
