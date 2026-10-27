"""Pytest fixtures for Amrutam API test suite."""

import socket
from collections.abc import Generator

import pytest
from app.core.config import get_settings
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url


def is_postgres_available(url_str: str | None = None) -> bool:
    """Check if the PostgreSQL test database is reachable via TCP socket."""
    if url_str is None:
        url_str = get_settings().test_database_url
    try:
        url = make_url(url_str)
        host = url.host or "localhost"
        port = url.port or 5432
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (OSError, TimeoutError):
        return False


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient fixture providing an isolated client for each test."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
async def cleanup_db():
    """Ensure database singletons and connection pools are cleaned up between test executions."""
    yield
    from app.db.session import close_database_connections, reset_database_state

    await close_database_connections()
    reset_database_state()
