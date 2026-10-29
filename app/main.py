"""Main FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.endpoints import health, metrics
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import (
    PrometheusMetricsMiddleware,
    RequestBodyLimitMiddleware,
    RequestCorrelationIdMiddleware,
    TracingMiddleware,
)
from app.core.tracing import setup_tracing
from app.db.session import close_database_connections


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application lifecycle events."""
    settings = get_settings()
    if settings.auto_migrate:
        import asyncio
        import logging

        from alembic import command
        from alembic.config import Config

        logger = logging.getLogger("app.migrations")
        logger.info("Executing automated database migrations (AUTO_MIGRATE=true)...")
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        try:
            await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
            logger.info("Automated database migrations completed successfully.")
        except Exception as err:
            logger.error("Automated database migrations failed: %s", err, exc_info=True)
            raise

    if settings.seed_demo_data:
        import logging

        from app.db.session import get_session_factory
        from app.services.seed_service import seed_demo_data

        seed_logger = logging.getLogger("app.seed")
        seed_logger.info("Executing automated demo data seeding (SEED_DEMO_DATA=true)...")
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                await seed_demo_data(session)
            seed_logger.info("Automated demo data seeding completed successfully.")
        except Exception as err:
            seed_logger.error("Automated demo data seeding failed: %s", err, exc_info=True)

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

    # Configure OpenTelemetry distributed tracing
    setup_tracing(
        service_name=settings.app_name,
        environment=settings.app_env,
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

    # Middleware execution pipeline (Starlette executes in reverse addition order)
    # 1. RequestCorrelationIdMiddleware (outermost: assigns request_id, sets headers)
    # 2. TracingMiddleware (extracts W3C traceparent, starts SERVER span)
    # 3. PrometheusMetricsMiddleware (records HTTP metrics, request counts, latencies)
    # 4. RequestBodyLimitMiddleware (rejects oversized bodies before handler execution)
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)
    app.add_middleware(TracingMiddleware)
    app.add_middleware(RequestCorrelationIdMiddleware)

    # Centralized exception handling
    register_exception_handlers(app)

    # Probes and API routing
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(api_v1_router, prefix="/api")

    return app


app = create_app()
