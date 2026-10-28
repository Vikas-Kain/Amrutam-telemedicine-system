"""Prometheus metrics endpoint with optional network/token restriction."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status

from app.core.config import get_settings
from app.core.errors import NotFoundError, UnauthorizedError
from app.core.metrics import generate_prometheus_metrics

router = APIRouter()


async def verify_metrics_access(
    authorization: Annotated[str | None, Header()] = None,
    x_metrics_key: Annotated[str | None, Header(alias="X-Metrics-Key")] = None,
) -> None:
    """Verify metrics access credentials when metrics_auth_token is configured."""
    settings = get_settings()

    if not settings.metrics_enabled:
        raise NotFoundError(message="Metrics collection is disabled.", code="METRICS_DISABLED")

    # If an access token is configured, enforce Bearer token or X-Metrics-Key header
    if settings.metrics_auth_token:
        provided_token = None
        if authorization and authorization.lower().startswith("bearer "):
            provided_token = authorization[7:].strip()
        elif x_metrics_key:
            provided_token = x_metrics_key.strip()

        if not provided_token or provided_token != settings.metrics_auth_token:
            raise UnauthorizedError(
                message="Invalid or missing metrics access token.",
                code="INVALID_METRICS_TOKEN",
            )


@router.get(
    "/metrics",
    dependencies=[Depends(verify_metrics_access)],
    status_code=status.HTTP_200_OK,
    summary="Prometheus text metrics exposition",
    description=(
        "Exposes application, HTTP, database connection pool, and business metrics in standard "
        "Prometheus text format (version=0.0.4). Labels are strictly low-cardinality."
    ),
    responses={
        200: {
            "description": "Prometheus metric exposition data.",
            "content": {"text/plain": {}},
        },
        401: {"description": "Metrics access token required or invalid."},
        404: {"description": "Metrics endpoint is disabled."},
    },
)
def get_prometheus_metrics() -> Response:
    """Return formatted Prometheus exposition text."""
    content = generate_prometheus_metrics()
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
