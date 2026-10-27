"""Tests for standardized API error response handling and sensitive data redaction."""

from app.core.errors import ConflictError, NotFoundError
from app.core.handlers import register_exception_handlers
from app.core.middleware import RequestCorrelationIdMiddleware
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class SamplePayload(BaseModel):
    """Test schema for validation testing."""

    email: str = Field(..., min_length=5)
    age: int = Field(..., ge=18)


def create_error_test_app() -> FastAPI:
    """Create a minimal FastAPI app with registered error handlers and test routes."""
    app = FastAPI()
    app.add_middleware(RequestCorrelationIdMiddleware)
    register_exception_handlers(app)

    router = APIRouter()

    @router.get("/error/not-found")
    def trigger_not_found() -> None:
        raise NotFoundError("Doctor profile not found.", code="DOCTOR_NOT_FOUND")

    @router.get("/error/conflict")
    def trigger_conflict() -> None:
        raise ConflictError(
            "The slot has already been reserved.",
            code="SLOT_ALREADY_BOOKED",
            details={"slot_id": "slot_123"},
        )

    @router.post("/error/validation")
    def trigger_validation(payload: SamplePayload) -> dict[str, str]:
        return {"status": "success"}

    @router.get("/error/unhandled")
    def trigger_unhandled() -> None:
        # Simulate a crash containing internal SQL/credential information
        msg = "FATAL: connection to server at 'db.internal.amrutam' failed: password invalid"
        raise RuntimeError(msg)

    app.include_router(router)
    return app


def test_not_found_error_response_shape() -> None:
    """Verify custom NotFoundError produces standard error envelope."""
    app = create_error_test_app()
    with TestClient(app) as client:
        response = client.get("/error/not-found", headers={"X-Request-ID": "req_test_404"})
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "DOCTOR_NOT_FOUND"
        assert data["error"]["message"] == "Doctor profile not found."
        assert data["error"]["request_id"] == "req_test_404"


def test_conflict_error_response_with_details() -> None:
    """Verify ConflictError returns HTTP 409 with details preserved."""
    app = create_error_test_app()
    with TestClient(app) as client:
        response = client.get("/error/conflict")
        assert response.status_code == 409
        data = response.json()
        assert data["error"]["code"] == "SLOT_ALREADY_BOOKED"
        assert data["error"]["details"] == {"slot_id": "slot_123"}
        assert data["error"]["request_id"] is not None


def test_validation_error_response_shape() -> None:
    """Verify RequestValidationError produces HTTP 422 with sanitized field details."""
    app = create_error_test_app()
    with TestClient(app) as client:
        response = client.post("/error/validation", json={"email": "abc", "age": 16})
        assert response.status_code == 422
        data = response.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["message"] == "Request validation failed."
        assert isinstance(data["error"]["details"], list)
        assert len(data["error"]["details"]) == 2


def test_unhandled_exception_sanitization() -> None:
    """Verify unhandled exceptions return 500 and NEVER leak stack traces or internal messages."""
    app = create_error_test_app()
    # Note: raise_server_exceptions=False tells TestClient to let exception handlers catch it
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/error/unhandled", headers={"X-Request-ID": "req_crash_test"})
        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert data["error"]["request_id"] == "req_crash_test"
        # Ensure sensitive server details/credentials are completely absent from client response
        assert "db.internal.amrutam" not in response.text
        assert "password" not in response.text
        assert "FATAL" not in response.text
        assert "Traceback" not in response.text
