"""Tests for health probe and app lifecycle."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_health_live_endpoint(client: TestClient) -> None:
    """Verify GET /health/live returns HTTP 200 and status ok."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_v1_health_live_endpoint(client: TestClient) -> None:
    """Verify versioned router GET /api/v1/health/live returns HTTP 200 and status ok."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_endpoint_success(client: TestClient) -> None:
    """Verify GET /health/ready returns HTTP 200 when database connectivity is healthy."""
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}


def test_api_v1_health_ready_endpoint_success(client: TestClient) -> None:
    """Verify GET /api/v1/health/ready returns HTTP 200 when database is healthy."""
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}


def test_health_ready_endpoint_failure(client: TestClient) -> None:
    """Verify GET /health/ready returns HTTP 503 SERVICE_UNAVAILABLE when database is down."""
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        new_callable=AsyncMock,
        return_value=False,
    ):
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "database" in data["error"]["message"].lower()


def test_openapi_schema_generated(client: TestClient) -> None:
    """Verify that OpenAPI schema is properly configured and accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Amrutam Telemedicine API"
    assert "/health/live" in schema["paths"]
    assert "/health/ready" in schema["paths"]
