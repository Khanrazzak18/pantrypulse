import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TextIO

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via `extra=` and is emitted.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Route uvicorn's own logs through the JSON handler; request lines come from our middleware.
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
