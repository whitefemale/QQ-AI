"""结构化日志与全链路脱敏。"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import current_correlation_id, current_request_id
from app.core.security import redact_text

_CONFIGURED = False


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
        except Exception:  # pragma: no cover - 防御性兜底
            record.msg = "[日志脱敏失败]"
            record.args = ()
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        for key in ("message", "detail", "error", "token", "key"):
            if hasattr(record, key):
                value = getattr(record, key)
                if isinstance(value, str):
                    setattr(record, key, redact_text(value))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", current_request_id()),
            "correlation_id": getattr(record, "correlation_id", current_correlation_id()),
        }
        for key in ("event", "error_code", "account_id", "group_id", "message_id", "provider_id", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", current_request_id())
        timestamp = datetime.now(UTC).strftime("%H:%M:%S")
        base = f"{timestamp} {record.levelname:<8} [{rid}] {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + redact_text(self.formatException(record.exc_info))
        return base


def setup_logging(level: str = "INFO", *, json_logs: bool | None = None, log_file=None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:  # pragma: no cover
            pass

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()

    if json_logs is None:
        json_logs = level.upper() != "DEBUG"
    formatter: logging.Formatter = JsonFormatter() if json_logs else HumanFormatter()
    redaction = RedactionFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(redaction)
    root.addHandler(console)

    if log_file is not None:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)

    for noisy in ("httpx", "httpcore", "websockets", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(numeric_level)
