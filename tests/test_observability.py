"""Automated test suite for observability metrics, distributed tracing, logs, and health checks.

Validates the requirements from docs/observability.md and Prompt 22:
- Liveness and readiness probes (/health/live, /health/ready)
- Prometheus metrics exposition (/metrics) and low-cardinality enforcement
- Metrics authentication token restriction and enable/disable toggle
- OpenTelemetry W3C trace context extraction, propagation, and attribute redaction
- Structured JSON log correlation with trace and span IDs
"""

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from app.core.config import get_settings
from app.core.metrics import (
    normalize_route_template,
    record_booking_metric,
    record_idempotency_metric,
    record_outbox_lag_metric,
    record_payment_metric,
    record_worker_metric,
    reset_metrics,
)
from app.core.tracing import (
    inject_trace_context,
    sanitize_span_attributes,
    trace_span,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_metrics_state():
    """Reset all Prometheus metric counters and gauges before and after each test."""
    reset_metrics()
    yield
    reset_metrics()


def test_health_live_probe(client: TestClient) -> None:
    """GET /health/live must return HTTP 200 with status 'ok' without calling dependencies."""
    response = client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_health_ready_probe_success(client: TestClient) -> None:
    """GET /health/ready must return HTTP 200 with database connectivity confirmation."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_health_ready_probe_with_redis(client: TestClient) -> None:
    """When rate_limit_backend is 'redis', /health/ready includes redis connectivity."""
    settings = get_settings()
    with patch.object(settings, "rate_limit_backend", "redis"):
        with patch("redis.asyncio.from_url") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.aclose = AsyncMock()
            mock_redis.return_value = mock_client

            response = client.get("/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "connected"
            assert data["redis"] == "connected"


def test_health_ready_probe_database_failure(client: TestClient) -> None:
    """GET /health/ready must return HTTP 503 when primary PostgreSQL is unreachable."""
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        return_value=False,
    ):
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_metrics_endpoint_exposition_format(client: TestClient) -> None:
    """GET /metrics must expose metrics in valid Prometheus 0.0.4 text exposition format."""
    # Trigger an HTTP request so middleware records request metrics
    client.get("/health/live")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "version=0.0.4" in response.headers["content-type"]

    body = response.text
    # Core HTTP metrics
    assert "# HELP http_requests_total" in body
    assert "# TYPE http_requests_total counter" in body
    assert 'http_requests_total{method="GET",route="/health/live",status_code="200"}' in body

    assert "# HELP http_request_duration_seconds" in body
    assert "# TYPE http_request_duration_seconds histogram" in body
    assert 'http_request_duration_seconds_count{method="GET",route="/health/live"}' in body

    assert "# HELP http_requests_in_flight" in body
    assert "# TYPE http_requests_in_flight gauge" in body

    # Database connection pool metrics
    assert "# HELP db_pool_size" in body
    assert "# HELP db_pool_checked_in" in body
    assert "# HELP db_pool_checked_out" in body
    assert "# HELP db_query_duration_seconds" in body


def test_low_cardinality_route_template_normalization(client: TestClient) -> None:
    """Ensure dynamic UUIDs and IDs are normalized to prevent metrics cardinality explosion."""
    # Test normalization helper directly
    uuid_path = "/api/v1/consultations/d3b07384-d113-40e1-a0c4-a55099e2a392"
    normalized = normalize_route_template(uuid_path)
    assert normalized == "/api/v1/consultations/{id}"

    numeric_path = "/api/v1/doctors/42/slots"
    normalized_numeric = normalize_route_template(numeric_path)
    assert normalized_numeric == "/api/v1/doctors/{id}/slots"

    # Make request to a route with an unauthenticated / nonexistent UUID
    raw_uuid = "a1b2c3d4-e5f6-4a1b-8c2d-9e0f1a2b3c4d"
    client.get(f"/api/v1/bookings/{raw_uuid}")

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text

    # The raw UUID must NEVER appear as a metric label value
    assert raw_uuid not in metrics_text
    # The normalized route template must be used instead
    assert (
        "/api/v1/bookings/{id}" in metrics_text or "/api/v1/bookings/{booking_id}" in metrics_text
    )


def test_metrics_token_authorization(client: TestClient) -> None:
    """When metrics_auth_token is configured, enforce Bearer token or X-Metrics-Key header."""
    settings = get_settings()
    with patch.object(settings, "metrics_auth_token", "amrutam-ops-secret-key-123"):
        # 1. Missing authentication credentials -> 401 Unauthorized
        unauth_resp = client.get("/metrics")
        assert unauth_resp.status_code == 401
        assert unauth_resp.json()["error"]["code"] == "INVALID_METRICS_TOKEN"

        # 2. Invalid Bearer token -> 401 Unauthorized
        invalid_bearer = client.get("/metrics", headers={"Authorization": "Bearer wrong-token-xyz"})
        assert invalid_bearer.status_code == 401

        # 3. Valid Bearer token -> 200 OK
        valid_bearer = client.get(
            "/metrics",
            headers={"Authorization": "Bearer amrutam-ops-secret-key-123"},
        )
        assert valid_bearer.status_code == 200
        assert "# HELP http_requests_total" in valid_bearer.text

        # 4. Valid X-Metrics-Key header -> 200 OK
        valid_header = client.get(
            "/metrics",
            headers={"X-Metrics-Key": "amrutam-ops-secret-key-123"},
        )
        assert valid_header.status_code == 200


def test_metrics_disabled_returns_404(client: TestClient) -> None:
    """When metrics_enabled is False, /metrics must return 404 NOT_FOUND."""
    settings = get_settings()
    with patch.object(settings, "metrics_enabled", False):
        response = client.get("/metrics")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "METRICS_DISABLED"


def test_w3c_traceparent_context_propagation(client: TestClient) -> None:
    """Incoming W3C traceparent header must be propagated and reflected in response headers."""
    # Standard W3C Traceparent: version-trace_id-parent_span_id-trace_flags
    inbound_traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    response = client.get(
        "/health/live",
        headers={"traceparent": inbound_traceparent},
    )
    assert response.status_code == 200
    assert "traceparent" in response.headers

    outbound_traceparent = response.headers["traceparent"]
    # The trace_id (4bf92f3577b34da6a3ce929d0e0e4736) must match the incoming trace
    assert "4bf92f3577b34da6a3ce929d0e0e4736" in outbound_traceparent
    assert outbound_traceparent.startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")


def test_outbound_trace_context_injection() -> None:
    """inject_trace_context must attach W3C traceparent header for distributed propagation."""
    headers: dict[str, str] = {}
    with trace_span("outbound_http_test") as span:
        inject_trace_context(headers)
        span_ctx = span.get_span_context()
        if span_ctx and span_ctx.is_valid:
            assert "traceparent" in headers
            trace_id_hex = format(span_ctx.trace_id, "032x")
            assert trace_id_hex in headers["traceparent"]


def test_span_attribute_sanitization_scrubs_secrets_and_phi() -> None:
    """Sensitive attributes (passwords, tokens, cards, clinical notes) must be redacted."""
    raw_attributes = {
        "user.email": "test@example.com",
        "user.password": "P@ssw0rd123!",
        "auth.token": "eyJh...sensitive_jwt",
        "mfa.secret": "JBSWY3DPEHPK3PXP",
        "billing.card_number": "4111222233334444",
        "medical.prescription": "Amoxicillin 500mg TDS",
        "clinical.diagnosis": "Acute sinusitis",
        "http.status_code": 200,
        "is_active": True,
    }

    clean = sanitize_span_attributes(raw_attributes)
    # Sensitive keys must be scrubbed to [REDACTED]
    assert clean["user.password"] == "[REDACTED]"
    assert clean["auth.token"] == "[REDACTED]"
    assert clean["mfa.secret"] == "[REDACTED]"
    assert clean["billing.card_number"] == "[REDACTED]"
    assert clean["medical.prescription"] == "[REDACTED]"
    assert clean["clinical.diagnosis"] == "[REDACTED]"

    # Non-sensitive keys must remain intact
    assert clean["user.email"] == "test@example.com"
    assert clean["http.status_code"] == 200
    assert clean["is_active"] is True


def test_structured_json_logging_trace_correlation() -> None:
    """JSON log entries must include trace_id and span_id when executing within a trace span."""
    from app.core.logging import StructuredJsonFormatter

    formatter = StructuredJsonFormatter(service_name="test-service", environment="test")

    with trace_span("logged_operation") as span:
        span_ctx = span.get_span_context()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Executing traced operation",
            args=(),
            exc_info=None,
        )
        formatted_json = formatter.format(record)
        entry = json.loads(formatted_json)

        assert entry["message"] == "Executing traced operation"
        assert entry["service"] == "test-service"
        assert "trace_id" in entry
        assert "span_id" in entry
        if span_ctx and span_ctx.is_valid:
            assert entry["trace_id"] == format(span_ctx.trace_id, "032x")
            assert entry["span_id"] == format(span_ctx.span_id, "016x")


def test_domain_metrics_recording(client: TestClient) -> None:
    """Domain metric helper functions must record data cleanly in Prometheus format."""
    record_booking_metric(outcome="success")
    record_booking_metric(outcome="conflict")
    record_idempotency_metric(outcome="replayed")
    record_idempotency_metric(outcome="payload_mismatch")
    record_payment_metric(provider="mock", status="succeeded")
    record_payment_metric(provider="mock", status="failed")
    record_worker_metric(job_type="booking.created", status="processed")
    record_worker_metric(job_type="booking.created", status="dead_letter")
    record_outbox_lag_metric(12.75)

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    body = metrics_resp.text

    assert 'booking_operations_total{outcome="success"} 1.0' in body
    assert 'booking_operations_total{outcome="conflict"} 1.0' in body
    assert 'idempotency_replays_total{outcome="replayed"} 1.0' in body
    assert 'idempotency_replays_total{outcome="payload_mismatch"} 1.0' in body
    assert 'payment_transactions_total{provider="mock",status="succeeded"} 1.0' in body
    assert 'payment_transactions_total{provider="mock",status="failed"} 1.0' in body
    assert 'worker_jobs_total{job_type="booking.created",status="processed"} 1.0' in body
    assert 'worker_jobs_total{job_type="booking.created",status="dead_letter"} 1.0' in body
    assert "outbox_events_lag_seconds 12.75" in body
