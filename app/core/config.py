"""Central typed application settings using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # General
    app_name: str = Field(default="Amrutam Telemedicine API", description="Application name")
    app_env: Literal["development", "staging", "production", "test"] = Field(
        default="development", description="Deployment environment"
    )
    debug: bool = Field(default=False, description="Debug mode flag")
    api_v1_prefix: str = Field(default="/api/v1", description="Prefix for API v1 routes")
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server bind port")

    # Logging
    log_level: str = Field(default="INFO", description="Log level")
    log_format: Literal["console", "json"] = Field(
        default="console", description="Log output format (console for dev, json for prod/staging)"
    )

    # Security
    secret_key: str = Field(
        default="insecure-development-secret-key-replace-in-production-min-32-chars",
        description="JWT signing secret key",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        default=15, description="Access token expiration in minutes"
    )
    mfa_encryption_key: str = Field(
        default="insecure-dev-mfa-key-32-bytes-base64=",
        description="Base64-encoded key for encrypting MFA secrets at rest",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/amrutam_telemedicine",
        description="Primary PostgreSQL connection string",
    )
    test_database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/amrutam_telemedicine_test",
        description="Test PostgreSQL connection string",
    )
    db_pool_size: int = Field(default=10, description="Connection pool size")
    db_max_overflow: int = Field(default=20, description="Connection pool max overflow")
    db_pool_timeout: int = Field(
        default=30, description="Connection pool acquisition timeout (seconds)"
    )

    # Redis (Optional)
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origin URLs",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Validate log level string."""
        normalized = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            msg = f"Invalid log_level '{value}'. Allowed: {allowed}"
            raise ValueError(msg)
        return normalized

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key_length(cls, value: str) -> str:
        """Ensure secret key has minimum length."""
        if len(value) < 16:
            msg = "secret_key must be at least 16 characters long"
            raise ValueError(msg)
        return value


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton instance."""
    return Settings()
