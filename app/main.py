"""Main FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.endpoints import health
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestCorrelationIdMiddleware
from app.db.session import close_database_connections


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application lifecycle events."""
    yield
    await close_database_connections()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    # Configure structured logging
    setup_logging(
        service_name=settings.app_name,
        environment=settings.app_env,
        log_level=settings.log_level,
        log_format=settings.log_format,
    )

    app = FastAPI(
        title=settings.app_name,
        description="Backend services for the Amrutam Telemedicine platform.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # Middleware: Request & Correlation ID propagation
    app.add_middleware(RequestCorrelationIdMiddleware)

    # Centralized exception handling
    register_exception_handlers(app)

    # Probes and API routing
    app.include_router(health.router)
    app.include_router(api_v1_router, prefix="/api")

    return app


app = create_app()
