"""Tests for resilience policies, error classification, deadlock retries, and HTTP timeouts."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.core.config import get_settings
from app.core.errors import (
    BadRequestError,
    ConflictError,
    DeadlockRetryExhaustedError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationException,
)
from app.core.http_client import (
    create_resilient_http_client,
    execute_http_request_with_retry,
    get_http_timeouts,
    is_transient_http_error,
)
from app.core.retry import (
    DeadlockError,
    PermanentError,
    TransientError,
    execute_transaction_with_deadlock_retry,
    is_deadlock_error,
    is_permission_error,
    is_slot_conflict_error,
    is_transient_error,
    is_validation_error,
)
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

# ==============================================================================
# 1. Error Classification Unit Tests
# ==============================================================================


def test_deadlock_error_classification():
    """Verify deadlock errors are classified as transient and retryable."""
    # Explicit DeadlockError
    assert is_deadlock_error(DeadlockError("Deadlock detected")) is True
    assert is_transient_error(DeadlockError("Deadlock detected")) is True

    # SQLSTATE 40P01 (PostgreSQL deadlock_detected)
    pg_deadlock = DBAPIError("SELECT FOR UPDATE", None, None)
    pg_deadlock.pgcode = "40P01"
    assert is_deadlock_error(pg_deadlock) is True
    assert is_transient_error(pg_deadlock) is True

    # SQLSTATE 40001 (PostgreSQL serialization_failure)
    pg_serialization = OperationalError("Transaction conflict", None, None)
    pg_serialization.pgcode = "40001"
    assert is_deadlock_error(pg_serialization) is True
    assert is_transient_error(pg_serialization) is True

    # Generic string match
    generic_deadlock = Exception("deadlock detected between transactions")
    assert is_deadlock_error(generic_deadlock) is True
    assert is_transient_error(generic_deadlock) is True


def test_slot_conflict_classification_not_retryable():
    """Verify booking slot conflicts are strictly classified as non-retryable."""
    # Slot not available conflict
    slot_conflict = ConflictError(
        message="The slot is no longer available.",
        code="SLOT_NOT_AVAILABLE",
    )
    assert is_slot_conflict_error(slot_conflict) is True
    assert is_deadlock_error(slot_conflict) is False
    assert is_transient_error(slot_conflict) is False

    # Doctor mismatch conflict
    doctor_mismatch = ConflictError(
        message="Slot doctor mismatch.",
        code="SLOT_DOCTOR_MISMATCH",
    )
    assert is_slot_conflict_error(doctor_mismatch) is True
    assert is_transient_error(doctor_mismatch) is False

    # Partial unique index violation on consultations.slot_id
    orig_mock = MagicMock()
    orig_mock.diag.constraint_name = "uq_consultations_active_slot"
    integrity_error = IntegrityError("statement", {}, orig_mock)
    assert is_slot_conflict_error(integrity_error) is True
    assert is_transient_error(integrity_error) is False


def test_validation_error_classification_not_retryable():
    """Verify validation and schema errors are classified as non-retryable."""
    # Application BadRequestError
    bad_req = BadRequestError("Invalid parameter format.", code="BAD_REQUEST")
    assert is_validation_error(bad_req) is True
    assert is_transient_error(bad_req) is False

    # Application ValidationException
    val_exc = ValidationException("Missing required line item.", code="VALIDATION_ERROR")
    assert is_validation_error(val_exc) is True
    assert is_transient_error(val_exc) is False

    # Standard python ValueError / KeyError / TypeError
    assert is_validation_error(ValueError("Invalid integer")) is True
    assert is_transient_error(ValueError("Invalid integer")) is False

    assert is_validation_error(KeyError("missing_field")) is True
    assert is_transient_error(KeyError("missing_field")) is False

    # Pydantic ValidationError
    class SampleModel(BaseModel):
        num: int = Field(gt=0)

    try:
        SampleModel(num=-1)
    except Exception as exc:
        assert is_validation_error(exc) is True
        assert is_transient_error(exc) is False


def test_permission_error_classification_not_retryable():
    """Verify authorization and authentication errors are non-retryable."""
    forbidden = ForbiddenError("Access forbidden.", code="FORBIDDEN")
    assert is_permission_error(forbidden) is True
    assert is_transient_error(forbidden) is False

    unauthorized = UnauthorizedError("Missing token.", code="UNAUTHORIZED")
    assert is_permission_error(unauthorized) is True
    assert is_transient_error(unauthorized) is False


def test_other_errors_classification():
    """Verify resource not found, permanent error, and network transient errors."""
    # NotFound is permanent
    not_found = NotFoundError("Resource not found")
    assert is_transient_error(not_found) is False

    # Explicit PermanentError
    perm = PermanentError("Corrupt payload")
    assert is_transient_error(perm) is False

    # Explicit TransientError
    trans = TransientError("Network reset")
    assert is_transient_error(trans) is True

    # Connection and Timeout errors
    assert is_transient_error(ConnectionResetError("Socket reset")) is True
    assert is_transient_error(TimeoutError("Read timeout")) is True


# ==============================================================================
# 2. Database Transaction Deadlock Bounded Retry Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_deadlock_retry_reruns_full_transaction_and_succeeds():
    """Verify transaction reruns from beginning after deadlock and succeeds."""
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    attempts = 0

    async def transactional_operation(sess: AsyncSession) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # First attempt fails with PostgreSQL deadlock
            raise DeadlockError("deadlock detected")
        # Second attempt succeeds
        return {"status": "booked", "attempts": str(attempts)}

    result = await execute_transaction_with_deadlock_retry(
        session_or_factory=session,
        operation=transactional_operation,
        max_attempts=3,
        base_delay=0.01,
        max_delay=0.02,
        jitter=False,
    )

    assert result["status"] == "booked"
    assert attempts == 2
    # Verify rollback was called between attempts
    assert session.rollback.await_count >= 1
    # Verify commit was called on success
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_deadlock_retries_exhausted_raises_sanitized_503():
    """Verify exhausting bounded deadlock attempts raises DeadlockRetryExhaustedError."""
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    attempts = 0

    async def failing_operation(sess: AsyncSession):
        nonlocal attempts
        attempts += 1
        raise DeadlockError(f"deadlock attempt {attempts}")

    with pytest.raises(DeadlockRetryExhaustedError) as exc_info:
        await execute_transaction_with_deadlock_retry(
            session_or_factory=session,
            operation=failing_operation,
            max_attempts=3,
            base_delay=0.01,
            max_delay=0.02,
            jitter=False,
        )

    assert attempts == 3
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "TRANSACTION_DEADLOCK_EXHAUSTED"

    # Invariant: verify message does not leak internal SQL or connection details
    msg = str(exc_info.value).lower()
    assert "postgresql://" not in msg
    assert "password" not in msg
    assert "select" not in msg


@pytest.mark.asyncio
async def test_deadlock_retry_does_not_retry_slot_conflicts():
    """Verify slot conflicts fail immediately on attempt 1 without retrying."""
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    attempts = 0

    async def slot_conflict_operation(sess: AsyncSession):
        nonlocal attempts
        attempts += 1
        raise ConflictError(
            message="The selected slot is already booked.",
            code="SLOT_NOT_AVAILABLE",
        )

    with pytest.raises(ConflictError) as exc_info:
        await execute_transaction_with_deadlock_retry(
            session_or_factory=session,
            operation=slot_conflict_operation,
            max_attempts=3,
        )

    assert attempts == 1  # Strictly called only once!
    assert exc_info.value.code == "SLOT_NOT_AVAILABLE"
    assert session.rollback.await_count == 1


@pytest.mark.asyncio
async def test_deadlock_retry_does_not_retry_validation_errors():
    """Verify validation errors fail immediately on attempt 1 without retrying."""
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    attempts = 0

    async def validation_error_operation(sess: AsyncSession):
        nonlocal attempts
        attempts += 1
        raise BadRequestError("Invalid consultation ID format.")

    with pytest.raises(BadRequestError):
        await execute_transaction_with_deadlock_retry(
            session_or_factory=session,
            operation=validation_error_operation,
            max_attempts=3,
        )

    assert attempts == 1  # Never retried


@pytest.mark.asyncio
async def test_deadlock_retry_does_not_retry_permission_errors():
    """Verify permission errors fail immediately on attempt 1 without retrying."""
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    attempts = 0

    async def forbidden_operation(sess: AsyncSession):
        nonlocal attempts
        attempts += 1
        raise ForbiddenError("You are not assigned to this consultation.")

    with pytest.raises(ForbiddenError):
        await execute_transaction_with_deadlock_retry(
            session_or_factory=session,
            operation=forbidden_operation,
            max_attempts=3,
        )

    assert attempts == 1  # Never retried


# ==============================================================================
# 3. External HTTP Client Timeouts & Bounded Retry Tests
# ==============================================================================


def test_external_http_client_timeouts_configuration():
    """Verify external HTTP client applies bounded timeout configuration."""
    settings = get_settings()
    timeout = get_http_timeouts(settings)

    assert timeout.connect == settings.external_http_connect_timeout_seconds
    assert timeout.read == settings.external_http_read_timeout_seconds
    assert timeout.write == settings.external_http_write_timeout_seconds
    assert timeout.pool == settings.external_http_pool_timeout_seconds

    # Create client factory
    client = create_resilient_http_client(settings)
    assert client.timeout.connect == settings.external_http_connect_timeout_seconds
    assert client.timeout.read == settings.external_http_read_timeout_seconds


def test_is_transient_http_error_classification():
    """Verify classification of transient network/5xx vs non-transient 4xx HTTP responses."""
    # Transient exceptions
    assert is_transient_http_error(exc=httpx.ConnectTimeout("Connect timeout")) is True
    assert is_transient_http_error(exc=httpx.ReadTimeout("Read timeout")) is True
    assert is_transient_http_error(exc=httpx.ConnectError("Connection refused")) is True

    # Transient 5xx status codes
    resp_502 = httpx.Response(502)
    resp_503 = httpx.Response(503)
    resp_504 = httpx.Response(504)
    assert is_transient_http_error(response=resp_502) is True
    assert is_transient_http_error(response=resp_503) is True
    assert is_transient_http_error(response=resp_504) is True

    # Non-transient 4xx status codes (MUST NOT RETRY)
    resp_400 = httpx.Response(400)
    resp_401 = httpx.Response(401)
    resp_403 = httpx.Response(403)
    resp_404 = httpx.Response(404)
    resp_409 = httpx.Response(409)
    resp_422 = httpx.Response(422)
    assert is_transient_http_error(response=resp_400) is False
    assert is_transient_http_error(response=resp_401) is False
    assert is_transient_http_error(response=resp_403) is False
    assert is_transient_http_error(response=resp_404) is False
    assert is_transient_http_error(response=resp_409) is False
    assert is_transient_http_error(response=resp_422) is False


@pytest.mark.asyncio
async def test_execute_http_request_retries_transient_503_and_recovers():
    """Verify external HTTP call retries transient 503 error and recovers."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    attempts = 0

    async def mock_request(method: str, url: str, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "upstream overloaded"})
        return httpx.Response(200, json={"status": "payment_processed"})

    mock_client.request.side_effect = mock_request

    response = await execute_http_request_with_retry(
        client=mock_client,
        method="POST",
        url="https://api.paymentprovider.mock/intents",
        max_retries=3,
        base_delay=0.01,
        max_delay=0.02,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "payment_processed"}
    assert attempts == 2


@pytest.mark.asyncio
async def test_execute_http_request_does_not_retry_400_bad_request():
    """Verify external HTTP call does NOT retry 400 Bad Request client errors."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    attempts = 0

    async def mock_request(method: str, url: str, **kwargs):
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": "invalid_currency"})

    mock_client.request.side_effect = mock_request

    response = await execute_http_request_with_retry(
        client=mock_client,
        method="POST",
        url="https://api.paymentprovider.mock/intents",
        max_retries=3,
    )

    assert response.status_code == 400
    assert attempts == 1  # Strictly called only once


@pytest.mark.asyncio
async def test_execute_http_request_exhaustion_raises_sanitized_error():
    """Verify exhausted HTTP retries raise sanitized ServiceUnavailableError."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request.side_effect = httpx.ConnectTimeout("Connection timed out")

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await execute_http_request_with_retry(
            client=mock_client,
            method="POST",
            url="https://api.paymentprovider.mock/secret-token-key=123",
            max_retries=3,
            base_delay=0.01,
            max_delay=0.02,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "EXTERNAL_SERVICE_UNAVAILABLE"
    # Invariant: verify secret tokens in URL are not leaked in exception message
    assert "secret-token-key" not in str(exc_info.value)
