import json
import logging
import time
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line with standard + contextual fields."""

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
        ts_full = f"{ts}.{int(record.msecs):03d}Z"

        entry: dict[str, Any] = {
            "timestamp": ts_full,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Contextual fields passed via extra={...}
        for key in ("task_id", "agent_id", "error", "attempt", "delay_s"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any default handlers added by basicConfig
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
