"""Structured logging with correlation across API, queue and worker.

JSON in production so logs are queryable; human-readable in development so
they are legible. Either way the *fields* are the same, which is what makes a
request traceable from an HTTP call through an enqueued job into the worker.

Correlation travels in a `ContextVar`, so any log call inside a request or a
job automatically carries the ids without every call site passing them.

Redaction is belt and braces: values are scrubbed through `redact_secrets`,
and a field whose *name* looks credential-bearing is dropped entirely. A log
line is the easiest place to leak a token by accident.
"""

import json
import logging
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

#: Correlation carried implicitly through a request or job.
_context: ContextVar[dict] = ContextVar("agentforge_log_context", default={})

#: Fields promoted onto every record when present.
CORRELATION_FIELDS = (
    "request_id",
    "job_id",
    "user_id",
    "project_id",
    "task_id",
    "run_id",
    "stage",
    "provider",
    "model",
    "duration_ms",
    "error_code",
)

#: Dropped by name, whatever the value.
_SENSITIVE_NAMES = frozenset(
    {
        "token",
        "access_token",
        "installation_token",
        "authorization",
        "secret",
        "client_secret",
        "webhook_secret",
        "password",
        "private_key",
        "api_key",
        "credentials",
        "prompt",
        "messages",
        "diff",
        "content",
        "env",
        "environ",
        "command",
        "argv",
    }
)

# Attributes LogRecord always has; anything else is a caller-supplied extra.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def current_context() -> dict:
    return dict(_context.get())


def bind(**fields: Any) -> None:
    """Add correlation to the current context (request or job)."""
    merged = {**_context.get(), **{k: v for k, v in fields.items() if v is not None}}
    _context.set(merged)


@contextmanager
def log_context(**fields: Any):
    """Scope correlation to a block, restoring the previous context after."""
    token = _context.set(
        {**_context.get(), **{k: v for k, v in fields.items() if v is not None}}
    )
    try:
        yield
    finally:
        _context.reset(token)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def _safe(value: Any) -> Any:
    """Redact token-shaped strings; leave other primitives alone."""
    from app.services.github_app_api import redact_secrets

    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_secrets(str(value))


class CorrelationFilter(logging.Filter):
    """Attach the ambient correlation to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JSONFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": _safe(record.getMessage()),
        }
        for field in CORRELATION_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = _safe(value)
        # Caller-supplied extras, minus anything credential-shaped.
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key in payload:
                continue
            if key.lower() in _SENSITIVE_NAMES:
                continue
            payload[key] = _safe(value)
        if record.exc_info:
            # Type only. A full traceback can carry paths and arguments, and
            # belongs in the exception log, not in a structured field.
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


class DevFormatter(logging.Formatter):
    """Readable single line with correlation appended."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname:<7} {record.name} — {_safe(record.getMessage())}"
        )
        extras = [
            f"{field}={getattr(record, field)}"
            for field in CORRELATION_FIELDS
            if getattr(record, field, None) is not None
        ]
        return base + (f"  [{' '.join(extras)}]" if extras else "")


def configure_logging(force_json: bool | None = None) -> None:
    """Install the formatter for this environment. Safe to call twice."""
    use_json = (
        force_json
        if force_json is not None
        else settings.app_env.strip().lower() == "production"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter() if use_json else DevFormatter())
    handler.addFilter(CorrelationFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Access logs duplicate what the correlation-aware records already say.
    logging.getLogger("uvicorn.access").propagate = False
