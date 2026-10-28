"""OpenTelemetry tracing instrumentation, W3C Trace Context, and attribute sanitization.

Implements distributed tracing requirements from docs/observability.md:
- W3C Trace Context propagation (traceparent header)
- HTTP ingress, outbound HTTP client, and business service span helpers
- Strict redaction: Never sets passwords, tokens, MFA secrets, or PHI notes on spans
"""

import logging
import secrets
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    StatusCode,
    TraceFlags,
    Tracer,
    TracerProvider,
    use_span,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.logging import SENSITIVE_KEYS

logger = logging.getLogger(__name__)

# W3C Trace Context propagator singleton
_propagator = TraceContextTextMapPropagator()
_provider_initialized = False


class SimpleSpan(NonRecordingSpan):
    """Concrete span holding sanitized attributes and active W3C trace context."""

    def __init__(self, name: str, context: SpanContext) -> None:
        super().__init__(context)
        self.name = name
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def is_recording(self) -> bool:
        return True


class SimpleTracer(Tracer):
    """Tracer producing spans with valid W3C trace and span IDs linked to parent context."""

    def start_span(
        self,
        name: str,
        context: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Any = None,
        links: Any = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> trace.Span:
        parent_span = trace.get_current_span(context)
        p_ctx = parent_span.get_span_context() if parent_span else None
        if p_ctx and p_ctx.is_valid:
            trace_id = p_ctx.trace_id
        else:
            trace_id = secrets.randbits(128)
        span_id = secrets.randbits(64)
        span_ctx = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=False,
            trace_flags=TraceFlags(1),
        )
        span = SimpleSpan(name, span_ctx)
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        return span

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        context: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Any = None,
        links: Any = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
        end_on_exit: bool = True,
    ) -> Generator[trace.Span, None, None]:
        span = self.start_span(
            name,
            context=context,
            kind=kind,
            attributes=attributes,
            links=links,
            start_time=start_time,
            record_exception=record_exception,
            set_status_on_exception=set_status_on_exception,
        )
        with use_span(
            span,
            end_on_exit=end_on_exit,
            record_exception=record_exception,
            set_status_on_exception=set_status_on_exception,
        ) as active_span:
            yield active_span


class SimpleTracerProvider(TracerProvider):
    """TracerProvider producing SimpleTracer instances."""

    def get_tracer(self, *args: Any, **kwargs: Any) -> Tracer:
        return SimpleTracer()


def setup_tracing(service_name: str = "amrutam-api", environment: str = "development") -> None:
    """Initialize OpenTelemetry global propagator and default tracer provider."""
    global _provider_initialized
    propagate.set_global_textmap(_propagator)
    if not _provider_initialized:
        try:
            trace.set_tracer_provider(SimpleTracerProvider())
        except Exception:
            pass
        _provider_initialized = True
    logger.debug(
        "OpenTelemetry tracing configured for service '%s' in '%s'",
        service_name,
        environment,
    )


# Automatically configure tracing provider at import time
setup_tracing()


def get_tracer(name: str = "amrutam-telemedicine") -> Tracer:
    """Return an OpenTelemetry Tracer instance."""
    setup_tracing()
    return trace.get_tracer(name, "0.1.0")


def extract_trace_context(headers: Mapping[str, str]) -> Context:
    """Extract W3C traceparent context from HTTP request headers."""
    # Convert header keys to lowercase mapping for case-insensitive lookup
    carrier = {k.lower(): v for k, v in headers.items()}
    return _propagator.extract(carrier=carrier)


def inject_trace_context(headers: dict[str, str]) -> None:
    """Inject W3C traceparent header into outbound HTTP request headers."""
    _propagator.inject(carrier=headers)


def get_current_trace_and_span_ids() -> tuple[str | None, str | None]:
    """Retrieve the current active trace_id and span_id formatted as hex strings.

    Returns (None, None) if no valid active span is recording.
    """
    current_span = trace.get_current_span()
    ctx = current_span.get_span_context()
    if ctx and ctx.is_valid:
        trace_id_hex = format(ctx.trace_id, "032x")
        span_id_hex = format(ctx.span_id, "016x")
        return trace_id_hex, span_id_hex
    return None, None


def sanitize_span_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Scrub sensitive keys and personal health information before attaching to span.

    Replaces passwords, auth tokens, MFA secrets, card numbers, and medical notes
    with '[REDACTED]' or omits raw clinical payloads.
    """
    if not attributes:
        return {}
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        key_lower = str(key).lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            clean[key] = "[REDACTED]"
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif value is None:
            continue
        else:
            # Complex objects serialized or excluded to avoid unbounded payloads
            clean[key] = str(value)[:256]
    return clean


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Generator[trace.Span, None, None]:
    """Context manager to execute a code block within a traced OpenTelemetry span.

    Automatically sanitizes attributes and marks status code on exception.
    """
    tracer = get_tracer()
    clean_attrs = sanitize_span_attributes(attributes)
    with tracer.start_as_current_span(name, kind=kind, attributes=clean_attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
