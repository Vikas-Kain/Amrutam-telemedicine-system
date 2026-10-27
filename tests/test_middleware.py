"""Tests for Request & Correlation ID middleware."""

from app.core.logging import correlation_id_ctx_var, request_id_ctx_var
from fastapi.testclient import TestClient


def test_generated_request_id_in_response(client: TestClient) -> None:
    """Verify that a unique request ID is generated when no header is supplied."""
    response = client.get("/health/live")
    assert response.status_code == 200
    req_id = response.headers.get("X-Request-ID")
    assert req_id is not None
    assert req_id.startswith("req_")
    corr_id = response.headers.get("X-Correlation-ID")
    assert corr_id == req_id


def test_inbound_request_id_preserved(client: TestClient) -> None:
    """Verify that an incoming X-Request-ID is preserved and propagated."""
    custom_id = "req_custom_trace_12345"
    response = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id
    assert response.headers.get("X-Correlation-ID") == custom_id


def test_inbound_correlation_id_preserved(client: TestClient) -> None:
    """Verify incoming X-Correlation-ID is preserved even when X-Request-ID is distinct."""
    custom_req_id = "req_1111"
    custom_corr_id = "corr_2222"
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": custom_req_id, "X-Correlation-ID": custom_corr_id},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_req_id
    assert response.headers.get("X-Correlation-ID") == custom_corr_id


def test_context_variables_cleared_after_request(client: TestClient) -> None:
    """Verify that async contextvars do not leak between requests."""
    assert request_id_ctx_var.get() is None
    assert correlation_id_ctx_var.get() is None

    client.get("/health/live", headers={"X-Request-ID": "req_isolation_test"})

    # Context variables must be reset outside of the request lifecycle
    assert request_id_ctx_var.get() is None
    assert correlation_id_ctx_var.get() is None
