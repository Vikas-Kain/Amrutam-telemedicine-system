"""Main FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.v1.endpoints import health
from app.api.v1.router import api_v1_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Amrutam Telemedicine API",
        description="Backend services for the Amrutam Telemedicine platform.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Root-level health probe endpoint (/health/live)
    app.include_router(health.router)

    # Versioned API routes (/api/v1)
    app.include_router(api_v1_router, prefix="/api")

    return app


app = create_app()
