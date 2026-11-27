"""
app/core/telemetry.py — OpenTelemetry GenAI spans & Prometheus metrics instrumentation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import logging
import os
import re
from typing import Any
import uuid

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.logging_config import bind_request_context, get_request_context, reset_request_context

logger = logging.getLogger("FinSight.telemetry")
_SAFE_REQ_ID_RE = re.compile(r"^[A-Za-z0-9._-]{4,64}$")

# ── Prometheus Metrics (registered once per process) ─────────────────────────

CHAT_REQUESTS_TOTAL = Counter(
    "finsight_chat_requests_total",
    "Total chat requests handled by FinSight.",
    ["mode", "outcome", "role"],
)

CHAT_LATENCY_SECONDS = Histogram(
    "finsight_chat_latency_seconds",
    "End-to-end chat execution latency in seconds.",
    ["mode"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

LLM_TOKENS_TOTAL = Counter(
    "finsight_llm_tokens_total",
    "Total Gemini input/output tokens observed across chat & evaluation.",
    ["model", "token_type"],
)

SQL_RETRIES_TOTAL = Counter(
    "finsight_sql_retries_total",
    "Governed DuckDB NL2SQL validation/execution attempts and outcomes.",
    ["outcome"],
)

GUARDRAIL_EVENTS_TOTAL = Counter(
    "finsight_guardrail_events_total",
    "OWASP LLM01/LLM02 guardrail trigger events.",
    ["category"],
)

CACHE_EVENTS_TOTAL = Counter(
    "finsight_cache_events_total",
    "Principal-scoped response cache hits and misses.",
    ["result"],
)

_telemetry_provider: TracerProvider | None = None
_telemetry_instrumented_apps: set[int] = set()


def _sanitize_attrs(attributes: dict[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if not attributes:
        return clean
    for key, val in attributes.items():
        if val is None:
            continue
        if isinstance(val, (str, bool, int, float)):
            clean[key] = val
        elif isinstance(val, (list, tuple)):
            clean[key] = [str(item) for item in val[:25]]
        else:
            clean[key] = str(val)
    return clean


def init_telemetry(app=None, *, span_exporter: SpanExporter | None = None) -> TracerProvider:
    """
    Configure OpenTelemetry TracerProvider & FastAPI instrumentation cleanly.
    When `OTEL_EXPORTER_OTLP_ENDPOINT` is empty and no custom exporter is passed,
    spans remain lightweight local in-process spans with zero network overhead.
    """
    global _telemetry_provider

    service_name = os.getenv("OTEL_SERVICE_NAME", "finsight-api").strip() or "finsight-api"
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")

    if _telemetry_provider is None or span_exporter is not None:
        resource = Resource.create(
            {
                "service.name": service_name,
                "deployment.environment": app_env,
            }
        )
        provider = TracerProvider(resource=resource)
        if span_exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        elif otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            traces_url = (
                otlp_endpoint
                if otlp_endpoint.endswith("/v1/traces")
                else f"{otlp_endpoint}/v1/traces"
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url))
            )
            logger.info("[Telemetry] Configured OTLP trace exporter -> %s", traces_url)
        try:
            trace.set_tracer_provider(provider)
        except Exception:
            # Test runs may replace global provider dynamically; attach processor if needed.
            current = trace.get_tracer_provider()
            if span_exporter is not None and hasattr(current, "add_span_processor"):
                current.add_span_processor(SimpleSpanProcessor(span_exporter))
                provider = current
        _telemetry_provider = provider

    if app is not None and id(app) not in _telemetry_instrumented_apps:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=_telemetry_provider,
                excluded_urls="/health,/ready,/metrics",
            )
            _telemetry_instrumented_apps.add(id(app))
        except Exception as exc:
            logger.debug("[Telemetry] FastAPI auto-instrumentation skipped: %s", exc)

    return _telemetry_provider


def _get_tracer():
    provider = _telemetry_provider
    if provider is not None:
        return provider.get_tracer("finsight.genai")
    return trace.get_tracer("finsight.genai")


@asynccontextmanager
async def trace_span(name: str, attributes: dict[str, Any] | None = None):
    """Async context manager wrapping a named OpenTelemetry span with GenAI metadata."""
    tracer = _get_tracer()
    ctx = get_request_context()
    merged = _sanitize_attrs(
        {
            "finsight.request_id": ctx.get("request_id"),
            "enduser.id": ctx.get("username"),
            "gen_ai.conversation.id": ctx.get("thread_id"),
            **(attributes or {}),
        }
    )
    with tracer.start_as_current_span(name, attributes=merged) as span:
        try:
            yield span
        except Exception as exc:
            try:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise


@contextmanager
def sync_trace_span(name: str, attributes: dict[str, Any] | None = None):
    """Synchronous OpenTelemetry span wrapper for worker/duckdb helpers."""
    tracer = _get_tracer()
    ctx = get_request_context()
    merged = _sanitize_attrs(
        {
            "finsight.request_id": ctx.get("request_id"),
            "enduser.id": ctx.get("username"),
            "gen_ai.conversation.id": ctx.get("thread_id"),
            **(attributes or {}),
        }
    )
    with tracer.start_as_current_span(name, attributes=merged) as span:
        try:
            yield span
        except Exception as exc:
            try:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise


def record_chat_metrics(
    *,
    mode: str,
    outcome: str,
    role: str,
    latency_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str = "gemini",
) -> None:
    """Safely record request counts, latency histogram, and LLM token metrics."""
    clean_mode = (mode or "unknown").lower()
    clean_outcome = (outcome or "allow").lower()
    clean_role = (role or "general").lower()
    clean_model = model or "gemini"
    try:
        CHAT_REQUESTS_TOTAL.labels(mode=clean_mode, outcome=clean_outcome, role=clean_role).inc()
        CHAT_LATENCY_SECONDS.labels(mode=clean_mode).observe(max(0.0, float(latency_seconds)))
        if input_tokens > 0:
            LLM_TOKENS_TOTAL.labels(model=clean_model, token_type="input").inc(int(input_tokens))
        if output_tokens > 0:
            LLM_TOKENS_TOTAL.labels(model=clean_model, token_type="output").inc(int(output_tokens))
    except Exception as exc:
        logger.debug("[Telemetry] Chat metric update skipped: %s", exc)


def record_sql_retry(outcome: str) -> None:
    try:
        SQL_RETRIES_TOTAL.labels(outcome=(outcome or "unknown").lower()).inc()
    except Exception:
        pass


def record_guardrail_event(category: str) -> None:
    try:
        GUARDRAIL_EVENTS_TOTAL.labels(category=(category or "unknown").lower()).inc()
    except Exception:
        pass


def record_cache_event(result: str) -> None:
    try:
        CACHE_EVENTS_TOTAL.labels(result=(result or "miss").lower()).inc()
    except Exception:
        pass


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Serialize Prometheus metrics for the `/metrics` endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST


class ObservabilityMiddleware:
    """
    Zero-buffering pure ASGI middleware propagating `X-Request-ID` headers
    and binding `ContextVar` logging metadata safely across async HTTP/streaming calls.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        incoming_id = ""
        for key, value in scope.get("headers") or ():
            if key.lower() == b"x-request-id":
                candidate = value.decode("ascii", errors="ignore").strip()
                if _SAFE_REQ_ID_RE.fullmatch(candidate):
                    incoming_id = candidate
                break

        request_id = incoming_id or uuid.uuid4().hex
        tokens = bind_request_context(request_id=request_id)

        async def send_with_request_id(message):
            if message.get("type") == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in (message.get("headers") or [])
                    if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            reset_request_context(tokens)
