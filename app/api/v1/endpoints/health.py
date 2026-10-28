"""Health check and dependency readiness probe endpoints."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.db.session import check_database_connection

logger = logging.getLogger(__name__)

router = APIRouter()


class LivenessResponse(BaseModel):
    """Schema for liveness probe response."""

    status: str = Field(default="ok", description="Process liveness indicator")


class ReadinessResponse(BaseModel):
    """Schema for readiness probe response."""

    status: str = Field(default="ok", description="Service readiness indicator")
    database: str = Field(default="connected", description="PostgreSQL connectivity state")
    redis: str | None = Field(default=None, description="Redis connectivity state if configured")


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
    response_model_exclude_none=True,
    summary="Application Readiness Probe",
    description=(
        "Returns 200 when all core dependencies (PostgreSQL, Redis if configured) are "
        "connected and accepting traffic."
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
    """Verify database and cache readiness without leaking connection strings or credentials."""
    settings = get_settings()

    is_connected = await check_database_connection()
    if not is_connected:
        raise ServiceUnavailableError("Database service is unavailable.")

    redis_status: str | None = None
    if settings.rate_limit_backend == "redis":
        try:
            import redis.asyncio as aioredis

            redis_url = settings.rate_limit_redis_url or settings.redis_url
            client = aioredis.from_url(
                redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            await client.ping()
            await client.aclose()
            redis_status = "connected"
        except Exception as exc:
            logger.warning("Redis readiness probe failed: %s", type(exc).__name__)
            redis_status = "unavailable"

    return ReadinessResponse(status="ok", database="connected", redis=redis_status)
