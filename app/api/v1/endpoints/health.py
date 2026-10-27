"""Health check and dependency readiness probe endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import ServiceUnavailableError
from app.db.session import check_database_connection

router = APIRouter()


class LivenessResponse(BaseModel):
    """Schema for liveness probe response."""

    status: str = Field(default="ok", description="Process liveness indicator")


class ReadinessResponse(BaseModel):
    """Schema for readiness probe response."""

    status: str = Field(default="ok", description="Service readiness indicator")
    database: str = Field(default="connected", description="PostgreSQL connectivity state")


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Process Liveness Check",
    description="Returns 200 when the application process is running and responding to requests.",
)
def liveness_probe() -> LivenessResponse:
    """Return process liveness confirmation without external dependency checks."""
    return LivenessResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Application Readiness Probe",
    description=(
        "Returns 200 when all core dependencies (PostgreSQL) are connected and accepting traffic."
    ),
    responses={
        503: {
            "description": "Database or dependency is unavailable",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": "Database service is unavailable.",
                            "request_id": "req_...",
                        }
                    }
                }
            },
        }
    },
)
async def readiness_probe() -> ReadinessResponse:
    """Verify core database readiness without leaking connection strings or credentials."""
    is_connected = await check_database_connection()
    if not is_connected:
        raise ServiceUnavailableError("Database service is unavailable.")
    return ReadinessResponse(status="ok", database="connected")
