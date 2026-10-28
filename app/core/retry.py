"""Exponential backoff, jitter, error classification, and deadlock transaction retries.

Provides bounded exponential retry delay calculation with full jitter,
robust classification of transient vs permanent failures, and bounded
safe rerunning of database transactions exclusively on PostgreSQL deadlocks.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppException,
    ConflictError,
    DeadlockRetryExhaustedError,
    ForbiddenError,
    UnauthorizedError,
)

logger = logging.getLogger("app.core.retry")


class TransientError(Exception):
    """Explicitly marks an error as transient and safe for retry."""


class PermanentError(Exception):
    """Explicitly marks an error as permanent and non-retryable."""


class DeadlockError(TransientError):
    """Explicitly marks a database transaction deadlock conflict."""


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for bounded exponential backoff retries."""

    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    random_generator: Any | None = None,
) -> float:
    """Calculate bounded exponential backoff delay with jitter.

    Uses the formula:
        delay = min(max_delay, base_delay * 2^(attempt - 1))
    When jitter is enabled, applies decorrelated uniform randomization within
    [0.5 * delay, min(max_delay, 1.5 * delay)].

    Args:
        attempt: Attempt counter (1-indexed, attempt >= 1).
        base_delay: Initial retry backoff in seconds.
        max_delay: Ceiling backoff delay in seconds.
        jitter: Whether to apply randomization to avoid thundering herds.
        random_generator: Optional custom RNG for deterministic testing.

    Returns:
        Delay in seconds as a float.
    """
    exponent = max(0, attempt - 1)
    raw_delay = min(max_delay, base_delay * (2**exponent))

    if not jitter:
        return float(raw_delay)

    rng = random_generator or random
    min_bound = 0.5 * raw_delay
    max_bound = min(max_delay, 1.5 * raw_delay)
    if min_bound > max_bound:
        min_bound = max_bound * 0.5

    return round(float(rng.uniform(min_bound, max_bound)), 4)


def is_deadlock_error(exc: Exception) -> bool:
    """Determine whether an exception represents a PostgreSQL deadlock or serialization failure.

    Matches:
    - DeadlockError
    - PostgreSQL SQLSTATE '40P01' (deadlock_detected)
    - PostgreSQL SQLSTATE '40001' (serialization_failure)
    - DBAPIError/OperationalError containing deadlock diagnostic strings
    """
    if isinstance(exc, DeadlockError):
        return True

    # Check asyncpg / psycopg underlying error diagnostics
    orig = getattr(exc, "orig", None)

    # Check SQLSTATE error code
    sqlstate = (
        getattr(orig, "sqlstate", None)
        or getattr(exc, "pgcode", None)
        or getattr(orig, "pgcode", None)
    )
    if sqlstate in ("40P01", "40001"):
        return True

    # Check exception class names
    class_name = type(exc).__name__
    orig_class_name = type(orig).__name__ if orig else ""
    if "Deadlock" in class_name or "Deadlock" in orig_class_name:
        return True
    if "SerializationFailure" in class_name or "SerializationFailure" in orig_class_name:
        return True

    # Check error message strings
    msg = str(exc).lower()
    if "deadlock detected" in msg or "could not serialize access" in msg:
        return True

    return False


def is_slot_conflict_error(exc: Exception) -> bool:
    """Determine if an exception represents an appointment slot business conflict.

    Slot conflicts (slot already booked, slot belonging to another doctor,
    or partial unique index violation on active booking) MUST NOT be retried.
    """
    if isinstance(exc, ConflictError):
        if exc.code in ("SLOT_NOT_AVAILABLE", "SLOT_DOCTOR_MISMATCH", "SLOT_ALREADY_BOOKED"):
            return True

    # Check active booking partial unique index
    if isinstance(exc, IntegrityError):
        diag = getattr(getattr(exc, "orig", None), "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        if constraint == "uq_consultations_active_slot":
            return True
        if "uq_consultations_active_slot" in str(exc):
            return True

    return False


def is_permission_error(exc: Exception) -> bool:
    """Determine if an exception represents an authorization or authentication denial."""
    if isinstance(exc, (ForbiddenError, UnauthorizedError)):
        return True
    if isinstance(exc, AppException) and exc.status_code in (401, 403):
        return True
    return False


def is_validation_error(exc: Exception) -> bool:
    """Determine if an exception represents a schema, semantic, or request validation error."""
    # Fast path: application validation error
    if isinstance(exc, AppException) and exc.status_code in (400, 422):
        return True

    # Check for Pydantic / FastAPI validation errors
    try:
        from fastapi.exceptions import RequestValidationError
        from pydantic import ValidationError

        if isinstance(exc, (RequestValidationError, ValidationError)):
            return True
    except ImportError:
        pass

    # Builtin Python validation errors
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return True

    return False


def is_transient_error(exc: Exception) -> bool:
    """Classify whether an exception represents a transient, retryable failure.

    Transient failures include network drops, socket timeouts, temporary database
    connection outages, PostgreSQL deadlocks, and explicit TransientError.

    Permanent errors that MUST NOT be retried include:
    - Validation errors (HTTP 400, 422, ValueError, etc.)
    - Permission errors (HTTP 401, 403)
    - Slot conflicts (HTTP 409 slot already booked)
    - Logic / missing resource bugs (HTTP 404)
    """
    # 1. Explicit non-retryable categories
    if is_validation_error(exc):
        return False
    if is_permission_error(exc):
        return False
    if is_slot_conflict_error(exc):
        return False
    if isinstance(exc, PermanentError):
        return False

    # 2. Explicit transient categories
    if isinstance(exc, (TransientError, DeadlockError)):
        return True
    if is_deadlock_error(exc):
        return True

    # 3. Standard network and socket errors
    if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)):
        return True

    # 4. Database operational failures
    if isinstance(exc, (OperationalError, DBAPIError)):
        return True

    # 5. Application exceptions: only 503 is transient
    if isinstance(exc, AppException):
        return exc.status_code == 503

    return False


async def execute_transaction_with_deadlock_retry[T](
    session_or_factory: Any,
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 0.5,
    jitter: bool = True,
) -> T:
    """Safely rerun a database transaction a bounded number of times on PostgreSQL deadlock.

    Requirements enforced:
    1. Reruns the entire transaction from the start on deadlock / serialization conflict.
    2. Rolls back the session cleanly before each retry attempt.
    3. Never retries validation errors, permission errors, or slot conflicts.
    4. Applies jittered exponential backoff between attempts to de-synchronize contenders.
    5. Raises DeadlockRetryExhaustedError if all attempts fail without leaking internals.
    """
    for attempt in range(1, max_attempts + 1):
        # Determine whether session_or_factory is an async context manager / factory
        is_factory = callable(session_or_factory) and not isinstance(
            session_or_factory, AsyncSession
        )

        try:
            if is_factory:
                async with session_or_factory() as session:
                    result = await operation(session)
                    if session.in_transaction():
                        await session.commit()
                    return result
            else:
                session = session_or_factory
                result = await operation(session)
                if session.in_transaction():
                    await session.commit()
                return result

        except Exception as exc:
            # Ensure session is rolled back immediately
            if isinstance(session_or_factory, AsyncSession) and session_or_factory.in_transaction():
                await session_or_factory.rollback()

            # Bounded retry ONLY on database deadlock / serialization failure
            if is_deadlock_error(exc):
                if attempt < max_attempts:
                    delay = calculate_backoff_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        jitter=jitter,
                    )
                    logger.warning(
                        "Database deadlock detected on attempt %d/%d; retrying transaction in %s s",
                        attempt,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(
                    "Database deadlock retries exhausted after %d attempts",
                    max_attempts,
                )
                raise DeadlockRetryExhaustedError(
                    message=(
                        "Operation failed due to concurrent transaction deadlock. Please try again."
                    ),
                    code="TRANSACTION_DEADLOCK_EXHAUSTED",
                ) from exc

            # Do NOT retry validation errors, permission errors, slot conflicts, or other errors
            raise
