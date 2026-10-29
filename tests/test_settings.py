"""Tests for application settings and environment variable validation."""

import pytest
from app.core.config import Settings, get_settings
from pydantic import ValidationError


def test_default_settings_instantiation() -> None:
    """Verify that default settings load with expected attributes."""
    settings = Settings()
    assert settings.app_name == "Amrutam Telemedicine API"
    assert settings.app_env in {"development", "staging", "production", "test"}
    assert settings.log_level == "INFO"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_access_token_expire_minutes == 15
    assert len(settings.secret_key) >= 16


def test_get_settings_cached_singleton() -> None:
    """Verify get_settings returns a cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify environment variables correctly override default settings."""
    monkeypatch.setenv("APP_NAME", "Amrutam Test Suite")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings()
    assert settings.app_name == "Amrutam Test Suite"
    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.log_level == "DEBUG"
    assert settings.port == 9000


def test_invalid_app_env_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify invalid app_env value is rejected."""
    monkeypatch.setenv("APP_ENV", "invalid_environment")
    with pytest.raises(ValidationError):
        Settings()


def test_invalid_log_level_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify invalid log_level value is rejected."""
    monkeypatch.setenv("LOG_LEVEL", "INVALID_LEVEL")
    with pytest.raises(ValidationError):
        Settings()


def test_short_secret_key_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify secret_key shorter than 16 characters is rejected."""
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ValidationError):
        Settings()


def test_database_url_normalization_for_cloud_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that postgres:// and postgresql:// URLs are normalized to postgresql+asyncpg://."""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@render.com/db")
    s1 = Settings()
    assert s1.database_url == "postgresql+asyncpg://user:pass@render.com/db"

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@railway.app/db")
    s2 = Settings()
    assert s2.database_url == "postgresql+asyncpg://user:pass@railway.app/db"
