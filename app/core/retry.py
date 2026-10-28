"""Exponential backoff, jitter, and error classification helpers.

Provides bounded exponential retry delay calculation with full jitter and
robust classification of transient vs permanent failures.
"""

import asyncio
import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.errors import AppException


class TransientError(Exception):
    """Explicitly marks an error as transient and safe for retry."""


class PermanentError(Exception):
    """Explicitly marks an error as permanent and non-retryable."""


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
    # Ensure min_bound does not exceed max_bound
    if min_bound > max_bound:
        min_bound = max_bound * 0.5

    return round(float(rng.uniform(min_bound, max_bound)), 4)


def is_transient_error(exc: Exception) -> bool:
    """Classify whether an exception represents a transient, retryable failure.

    Transient failures include network drops, socket timeouts, temporary database
    connection outages, serialization conflicts, and explicit TransientError.

    Permanent errors include schema/validation bugs, logic errors, missing records,
    and HTTP 4xx client errors, which should fail fast and avoid wasting retry budgets.
    """
    if isinstance(exc, TransientError):
        return True
    if isinstance(exc, PermanentError):
        return False

    # Standard python and async network/socket errors
    if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)):
        return True

    # Database operational failures (connectivity loss, deadlock/lock timeout)
    if isinstance(exc, (OperationalError, DBAPIError)):
        return True

    # Application business exceptions (4xx) are permanent
    if isinstance(exc, AppException):
        # 503 is service unavailable (transient), whereas 400, 401, 403, 404, 409 are permanent
        return exc.status_code == 503

    # Common programming bugs and schema errors are permanent
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError, IndexError)):
        return False

    return False
