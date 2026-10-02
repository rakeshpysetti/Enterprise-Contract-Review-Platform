"""Structured application logging with conservative redaction."""

import json
import logging
import re
import sys
from collections.abc import Mapping
from typing import TextIO

LOGGER_NAME = "contract_review"
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "database_url",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "body",
    "content",
    "contract_content",
    "contract_text",
    "prompt",
    "query",
    "question",
    "source_text",
}
_URI_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.I
)
_BEARER_TOKEN = re.compile(r"\bBearer\s+[^\s]+", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"\b(password|secret|token|api[_-]?key)\s*([=:])\s*[^\s,;]+", re.I
)
_STANDARD_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__)


def redact_text(value: str) -> str:
    redacted = _URI_CREDENTIALS.sub(r"\g<scheme>***:***@", value)
    redacted = _BEARER_TOKEN.sub("Bearer ***", redacted)
    return _SECRET_ASSIGNMENT.sub(r"\1\2***", redacted)


def redact(value: object, *, key: str | None = None) -> object:
    if key is not None and _is_sensitive_key(key):
        return "***"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("api_key", "password", "secret", "token")
    )


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": redact_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                payload[key] = redact(value, key=key)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(*, stream: TextIO | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
