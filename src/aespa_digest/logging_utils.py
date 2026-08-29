"""JSON logging with an allowlist of non-sensitive operational fields."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import TextIO

_SAFE_FIELDS = frozenset(
    {
        "run_id",
        "feed_count",
        "successful_feeds",
        "failed_feeds",
        "fetched_articles",
        "qualified_articles",
        "new_articles",
        "summary_failures",
        "sent_count",
        "state_updated",
        "dry_run",
        "feed_name",
        "error_type",
    }
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event_name", "log"),
        }
        payload.update(getattr(record, "safe_fields", {}))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(stream: TextIO | None = None) -> logging.Logger:
    logger = logging.getLogger("aespa_digest")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    safe_fields = {
        key: value
        for key, value in fields.items()
        if key in _SAFE_FIELDS and isinstance(value, (bool, float, int, str))
    }
    logger.log(
        level,
        "",
        extra={"event_name": event, "safe_fields": safe_fields},
    )
