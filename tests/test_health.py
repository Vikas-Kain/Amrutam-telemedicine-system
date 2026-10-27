"""Tests for health probe and app lifecycle."""

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


def test_openapi_schema_generated(client: TestClient) -> None:
    """Verify that OpenAPI schema is properly configured and accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Amrutam Telemedicine API"
    assert "/health/live" in schema["paths"]
    assert "/health/ready" in schema["paths"]
