"""Application exception hierarchy and standardized error schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Standardized error payload structure according to API contract."""

    code: str = Field(..., description="Machine-readable error classification code")
    message: str = Field(..., description="Human-readable safe error message")
    request_id: str | None = Field(default=None, description="Correlation / request identifier")
    details: Any = Field(default=None, description="Optional supplementary error metadata")


class ErrorResponse(BaseModel):
    """Top-level error response envelope."""

    error: ErrorDetail


class AppException(Exception):
    """Base application exception with HTTP status code and standardized error code."""

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = 500,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        self.headers = headers or {}


class BadRequestError(AppException):
    """Raised for malformed or semantically invalid requests (HTTP 400)."""

    def __init__(
        self,
        message: str = "Bad request.",
        code: str = "BAD_REQUEST",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=400, details=details)


class UnauthorizedError(AppException):
    """Raised when authentication is required and either missing or invalid (HTTP 401)."""

    def __init__(
        self,
        message: str = "Authentication required.",
        code: str = "UNAUTHORIZED",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=401, details=details)


class ForbiddenError(AppException):
    """Raised when caller lacks required role or resource ownership (HTTP 403)."""

    def __init__(
        self,
        message: str = "Access forbidden.",
        code: str = "FORBIDDEN",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=403, details=details)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist (HTTP 404)."""

    def __init__(
        self,
        message: str = "Resource not found.",
        code: str = "NOT_FOUND",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=404, details=details)


class ConflictError(AppException):
    """Raised on state conflicts, duplicate records, or double-booking attempts (HTTP 409)."""

    def __init__(
        self,
        message: str = "Resource state conflict.",
        code: str = "CONFLICT",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=409, details=details)


class ValidationException(AppException):
    """Raised on request validation errors (HTTP 422)."""

    def __init__(
        self,
        message: str = "Validation failed.",
        code: str = "VALIDATION_ERROR",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class ServiceUnavailableError(AppException):
    """Raised when an external or database dependency is temporarily unavailable (HTTP 503)."""

    def __init__(
        self,
        message: str = "Service temporarily unavailable.",
        code: str = "SERVICE_UNAVAILABLE",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=503, details=details)


class RateLimitExceededError(AppException):
    """Raised when rate limits are exceeded (HTTP 429)."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please try again later.",
        code: str = "RATE_LIMIT_EXCEEDED",
        retry_after: int = 60,
        details: Any = None,
    ) -> None:
        headers = {"Retry-After": str(retry_after)}
        super().__init__(
            message=message,
            code=code,
            status_code=429,
            details=details,
            headers=headers,
        )
        self.retry_after = retry_after


class PayloadTooLargeError(AppException):
    """Raised when request payload exceeds configured limits (HTTP 413)."""

    def __init__(
        self,
        message: str = "Request payload exceeds maximum allowed size.",
        code: str = "PAYLOAD_TOO_LARGE",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=413, details=details)


class DeadlockRetryExhaustedError(AppException):
    """Raised when database transaction deadlock retries are exhausted (HTTP 503)."""

    def __init__(
        self,
        message: str = "Concurrent transaction conflict; retries exhausted. Please try again.",
        code: str = "TRANSACTION_DEADLOCK_EXHAUSTED",
        details: Any = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=503, details=details)
