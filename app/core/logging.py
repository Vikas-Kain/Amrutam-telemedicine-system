"""Safe structured logging with sensitive field redaction and context propagation."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variables for request-scoped correlation identifiers
request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_ctx_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Keys whose values must be masked in logs to avoid credential or PHI leakage
SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "secret_key",
    "mfa_secret",
    "authorization",
    "cookie",
    "card",
    "cvv",
    "prescription",
    "diagnosis",
}


def redact_sensitive_data(data: Any) -> Any:
    """Recursively mask sensitive keys in nested dictionaries and lists."""
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if isinstance(key, str) and any(s in key.lower() for s in SENSITIVE_KEYS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive_data(value)
        return redacted
    if isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    return data


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects with correlation IDs and redaction."""

    def __init__(self, service_name: str = "amrutam-api", environment: str = "development") -> None:
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Format a single log record into JSON."""
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "environment": self.environment,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx_var.get(),
            "correlation_id": correlation_id_ctx_var.get(),
        }

        # Correlate with active OpenTelemetry trace context if available
        try:
            from app.core.tracing import get_current_trace_and_span_ids

            trace_id, span_id = get_current_trace_and_span_ids()
            if trace_id:
                log_entry["trace_id"] = trace_id
            if span_id:
                log_entry["span_id"] = span_id
        except Exception:
            pass

        # Include exception information safely
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Include custom extra fields if provided
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            log_entry["extra"] = redact_sensitive_data(extra)

        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for local development console output."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        req_id = request_id_ctx_var.get() or "-"
        lvl = f"[{record.levelname:<8}]"
        return f"[{timestamp}] {lvl} [{req_id}] {record.name}: {record.getMessage()}"


def setup_logging(
    service_name: str = "amrutam-api",
    environment: str = "development",
    log_level: str = "INFO",
    log_format: str = "console",
) -> None:
    """Configure root logger with structured formatter and log level."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers to prevent duplicate lines
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        formatter = StructuredJsonFormatter(service_name=service_name, environment=environment)
        handler.setFormatter(formatter)
    else:
        handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(handler)

    # Ensure uvicorn loggers propagate to root
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uvicorn_logger_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
