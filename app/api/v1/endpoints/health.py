"""Health check endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class LivenessResponse(BaseModel):
    """Schema for liveness probe response."""

    status: str = Field(default="ok", description="Process liveness indicator")


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Process Liveness Check",
    description="Returns 200 when the application process is running and responding to requests.",
)
def liveness_probe() -> LivenessResponse:
    """Return process liveness confirmation without external dependency checks."""
    return LivenessResponse(status="ok")
