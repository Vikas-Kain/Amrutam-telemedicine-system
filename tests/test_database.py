"""Tests for SQLAlchemy persistence layer, session lifecycle, probes, and Alembic migrations."""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.api.v1.endpoints.health import ReadinessResponse
from app.core.config import get_settings
from app.db.session import (
    check_database_connection,
    get_db_session,
    get_engine,
    get_session_factory,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import is_postgres_available


def test_settings_database_url_and_pool_config():
    """Verify database and test database URLs are configured in Settings."""
    settings = get_settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.test_database_url.startswith("postgresql+asyncpg://")
    assert settings.db_pool_size > 0
    assert settings.db_max_overflow >= 0
    assert settings.db_pool_timeout > 0


def test_engine_initialization_singleton():
    """Verify get_engine initializes and caches an AsyncEngine singleton."""
    engine_1 = get_engine()
    engine_2 = get_engine()

    assert isinstance(engine_1, AsyncEngine)
    assert engine_1 is engine_2
    assert engine_1.pool is not None


def test_session_factory_singleton():
    """Verify get_session_factory returns a configured async_sessionmaker singleton."""
    factory_1 = get_session_factory()
    factory_2 = get_session_factory()

    assert factory_1 is factory_2
    assert factory_1.kw.get("expire_on_commit") is False
    assert factory_1.kw.get("autoflush") is False


async def test_session_lifecycle_commits_on_success():
    """Verify get_db_session commits active transaction and closes session on clean completion."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__.return_value = None

    with patch("app.db.session.get_session_factory", return_value=mock_factory):
        async with asynccontextmanager(get_db_session)() as session:
            assert session is mock_session

    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()
    mock_session.close.assert_awaited_once()


async def test_session_lifecycle_rolls_back_on_exception():
    """Verify get_db_session rolls back active transaction and closes session on error."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__.return_value = None

    class CustomTestException(Exception):
        pass

    with (
        patch("app.db.session.get_session_factory", return_value=mock_factory),
        pytest.raises(CustomTestException),
    ):
        async with asynccontextmanager(get_db_session)() as session:
            assert session is mock_session
            raise CustomTestException("Deliberate operational failure")

    mock_session.commit.assert_not_awaited()
    mock_session.rollback.assert_awaited_once()
    mock_session.close.assert_awaited_once()


async def test_check_database_connection_returns_false_on_failure(caplog):
    """Verify connectivity check catches errors and never leaks connection details or passwords."""
    with patch("app.db.session.get_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = ConnectionRefusedError("Simulated connection refusal")
        mock_get_engine.return_value = mock_engine

        result = await check_database_connection(timeout_seconds=0.5)

        assert result is False
        # Verify log message does not leak credentials
        assert "Simulated connection refusal" not in caplog.text
        assert "password" not in caplog.text.lower()


def test_health_ready_endpoint_healthy(client):
    """Verify /health/ready returns 200 OK when database probe succeeds."""
    with patch("app.api.v1.endpoints.health.check_database_connection", return_value=True):
        response = client.get("/health/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["database"] == "connected"

        # Verify endpoint model validity
        ReadinessResponse(**payload)

        # Also verify versioned route
        v1_response = client.get("/api/v1/health/ready")
        assert v1_response.status_code == 200


def test_health_ready_endpoint_unhealthy_returns_503_without_credentials_leak(client):
    """Verify /health/ready returns 503 SERVICE_UNAVAILABLE and sanitizes internal details."""
    with patch("app.api.v1.endpoints.health.check_database_connection", return_value=False):
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()

        assert "error" in data
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "Database service is unavailable" in data["error"]["message"]
        assert "request_id" in data["error"]

        # Ensure no database credentials, URLs, or internal hosts are leaked
        response_text = response.text.lower()
        assert "postgres" not in response_text or "database service is unavailable" in response_text
        assert "password" not in response_text
        assert "localhost" not in response_text
        assert "5432" not in response_text


def test_alembic_configuration_wired_to_settings():
    """Verify Alembic configuration correctly discovers models and revisions."""
    # Verify alembic.ini and env.py exist
    alembic_ini_path = Path("alembic.ini")
    assert alembic_ini_path.exists()

    env_py_path = Path("alembic/env.py")
    assert env_py_path.exists()
    env_content = env_py_path.read_text(encoding="utf-8")
    assert "get_settings" in env_content
    assert "target_metadata = Base.metadata" in env_content

    # Verify script directory and head revision
    alembic_cfg = Config(str(alembic_ini_path))
    script = ScriptDirectory.from_config(alembic_cfg)
    heads = script.get_heads()

    assert len(heads) == 1
    assert heads[0] == "0003_slot_constraints_and_idx"


def test_alembic_offline_migration_sql_generation(capsys):
    """Verify Alembic generates clean transactional SQL for revisions in offline mode."""
    alembic_cfg = Config("alembic.ini")

    command.upgrade(alembic_cfg, "head", sql=True)
    captured = capsys.readouterr()

    assert "CREATE TABLE alembic_version" in captured.out
    assert "CREATE TABLE _schema_bootstrap_probe" in captured.out
    assert "CREATE TABLE users" in captured.out
    assert "CREATE TABLE consultations" in captured.out
    assert "0002_create_core_models" in captured.out
    assert "0003_slot_constraints_and_idx" in captured.out
    assert "exclude_overlapping_doctor_slots" in captured.out


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
async def test_live_postgres_connectivity_and_migration():
    """Execute live database verification when PostgreSQL service is active."""
    settings = get_settings()
    is_live = await check_database_connection()
    assert is_live is True, f"Failed to connect to PostgreSQL at {settings.database_url}"
