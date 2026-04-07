import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.auth import BearerTokenMiddleware
from src.config import settings
from src.database import close_database, get_db, init_database
from src.logging_config import configure_logging
from src.mcp_server import mcp
from src.rest_api import router as api_router
from src.task_engine import task_engine

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting orcai-mcp server")
    db_path = os.path.join(settings.data_dir, "orcai.db")
    await init_database(db_path)
    task_engine.start()
    logger.info("Database and task engine initialised")
    yield
    logger.info("Shutting down orcai-mcp server")
    await task_engine.stop()
    await close_database()
    logger.info("Shutdown complete")


app = FastAPI(
    title="orcai-mcp",
    description="MCP sub-agent manager for Claude Code and Cursor",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(BearerTokenMiddleware)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, Any]:
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM agents") as cur:
        row = await cur.fetchone()
    agent_count: int = row[0] if row else 0
    return {
        "status": "ok",
        "agents": agent_count,
        "queue_depth": task_engine.queue_depth(),
    }


# Mount React UI if build exists
_ui_build = os.path.join(os.path.dirname(__file__), "..", "ui", "build")
if os.path.isdir(_ui_build):
    app.mount("/ui", StaticFiles(directory=_ui_build, html=True), name="ui")

# Mount FastMCP Streamable HTTP on /mcp
app.mount("/mcp", mcp.streamable_http_app())


def main() -> None:
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
