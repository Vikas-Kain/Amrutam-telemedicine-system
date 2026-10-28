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

    # Logging & Observability
    log_level: str = Field(default="INFO", description="Log level")
    log_format: Literal["console", "json"] = Field(
        default="console", description="Log output format (console for dev, json for prod/staging)"
    )
    metrics_enabled: bool = Field(default=True, description="Enable Prometheus metrics endpoint")
    metrics_auth_token: str | None = Field(
        default=None, description="Secret token required for /metrics access (restricted access)"
    )
    tracing_enabled: bool = Field(default=True, description="Enable OpenTelemetry tracing")

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

    # Rate Limiting & Resilience
    rate_limit_enabled: bool = Field(default=True, description="Enable API rate limiting")
    rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory", description="Rate limit backend storage ('memory' or 'redis')"
    )
    rate_limit_redis_url: str | None = Field(
        default=None, description="Redis URL for shared rate limiting (falls back to redis_url)"
    )
    rate_limit_auth_requests: int = Field(
        default=10, description="Allowed auth requests per window"
    )
    rate_limit_auth_window_seconds: int = Field(
        default=60, description="Auth rate limit window duration in seconds"
    )
    rate_limit_mfa_requests: int = Field(default=10, description="Allowed MFA requests per window")
    rate_limit_mfa_window_seconds: int = Field(
        default=60, description="MFA rate limit window duration in seconds"
    )
    rate_limit_write_requests: int = Field(
        default=30, description="Allowed sensitive write requests per window"
    )
    rate_limit_write_window_seconds: int = Field(
        default=60, description="Sensitive write rate limit window duration in seconds"
    )
    rate_limit_default_requests: int = Field(
        default=120, description="Allowed general read/list requests per window"
    )
    rate_limit_default_window_seconds: int = Field(
        default=60, description="General rate limit window duration in seconds"
    )

    # Request Body & Pagination Limits
    max_request_body_bytes: int = Field(
        default=1_048_576, description="Max allowed request payload size in bytes (1 MB)"
    )
    default_page_size: int = Field(default=20, description="Default pagination page size")
    max_page_size: int = Field(default=100, description="Maximum allowed pagination page size")

    # External HTTP Call Timeouts
    external_http_connect_timeout_seconds: float = Field(
        default=3.0, description="Timeout for external HTTP TCP connections"
    )
    external_http_read_timeout_seconds: float = Field(
        default=5.0, description="Timeout for external HTTP responses"
    )
    external_http_write_timeout_seconds: float = Field(
        default=5.0, description="Timeout for external HTTP request writes"
    )
    external_http_pool_timeout_seconds: float = Field(
        default=3.0, description="Timeout for acquiring connection from HTTP pool"
    )

    # Database Deadlock Retries
    db_deadlock_max_retries: int = Field(
        default=3, description="Maximum retry attempts on database deadlock conflict"
    )
    db_deadlock_base_delay: float = Field(
        default=0.05, description="Initial retry delay in seconds for deadlock resolution"
    )
    db_deadlock_max_delay: float = Field(
        default=0.5, description="Ceiling retry delay in seconds for deadlock resolution"
    )

    # Idempotency
    idempotency_default_ttl_seconds: int = Field(
        default=86400, description="Default TTL for idempotency records in seconds (24 hours)"
    )
    idempotency_in_progress_timeout_seconds: int = Field(
        default=120,
        description="Timeout threshold for orphaned in-progress idempotency keys in seconds",
    )

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
