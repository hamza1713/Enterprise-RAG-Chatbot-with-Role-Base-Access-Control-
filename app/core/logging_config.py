"""
app/core/logging_config.py — Structured JSON logging & per-request ContextVar correlation.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
import json
import logging
import os
import sys
from typing import Any

_request_id_var: ContextVar[str | None] = ContextVar("finsight_request_id", default=None)
_username_var: ContextVar[str | None] = ContextVar("finsight_username", default=None)
_thread_id_var: ContextVar[str | None] = ContextVar("finsight_thread_id", default=None)


def get_request_context() -> dict[str, str | None]:
    """Return active request correlation fields bound via ContextVar."""
    return {
        "request_id": _request_id_var.get(),
        "username": _username_var.get(),
        "thread_id": _thread_id_var.get(),
    }


def bind_request_context(
    *,
    request_id: str | None = None,
    username: str | None = None,
    thread_id: str | None = None,
) -> tuple[Token | None, Token | None, Token | None]:
    """Bind request correlation metadata for the active async context."""
    t_req = _request_id_var.set(request_id) if request_id is not None else None
    t_user = _username_var.set(username) if username is not None else None
    t_thread = _thread_id_var.set(thread_id) if thread_id is not None else None
    return (t_req, t_user, t_thread)


def reset_request_context(tokens: tuple[Token | None, Token | None, Token | None]) -> None:
    """Restore previous ContextVar tokens cleanly at end of HTTP request."""
    t_req, t_user, t_thread = tokens
    if t_req is not None:
        _request_id_var.reset(t_req)
    if t_user is not None:
        _username_var.reset(t_user)
    if t_thread is not None:
        _thread_id_var.reset(t_thread)


def _active_trace_ids() -> tuple[str | None, str | None]:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        if ctx is not None and ctx.is_valid:
            return (f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}")
    except Exception:
        pass
    return (None, None)


class RequestContextFilter(logging.Filter):
    """Attach active request_id/username/thread_id attributes to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_request_context()
        record.request_id = getattr(record, "request_id", None) or ctx["request_id"] or "-"
        record.username = getattr(record, "username", None) or ctx["username"]
        record.thread_id = getattr(record, "thread_id", None) or ctx["thread_id"]
        return True


class JsonLogFormatter(logging.Formatter):
    """Emit structured single-line JSON log events suitable for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_request_context()
        trace_id, span_id = _active_trace_ids()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or ctx["request_id"],
            "username": getattr(record, "username", None) or ctx["username"],
            "thread_id": getattr(record, "thread_id", None) or ctx["thread_id"],
            "trace_id": trace_id,
            "span_id": span_id,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        clean = {k: v for k, v in payload.items() if v is not None}
        return json.dumps(clean, ensure_ascii=False)


def configure_logging(*, force: bool = False) -> None:
    """Configure root logging in either JSON (production default) or clean text format."""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    default_fmt = "json" if app_env == "production" else "text"
    log_format = os.getenv("LOG_FORMAT", default_fmt).strip().lower()
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if root.handlers and not force:
        # Ensure filter exists on active handlers without duplicating streams.
        for handler in root.handlers:
            if not any(isinstance(f, RequestContextFilter) for f in handler.filters):
                handler.addFilter(RequestContextFilter())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s [req=%(request_id)s]: %(message)s"
            )
        )

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google.generativeai").setLevel(logging.ERROR)
