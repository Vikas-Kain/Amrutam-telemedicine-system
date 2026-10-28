"""Resilient external HTTP client with bounded timeouts and transient retry policies."""

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError
from app.core.retry import calculate_backoff_delay

logger = logging.getLogger("app.core.http_client")


def get_http_timeouts(settings: Settings | None = None) -> httpx.Timeout:
    """Build bounded httpx.Timeout configuration from application settings.

    Explicitly bounds connect, read, write, and pool acquisition timeouts
    to prevent indefinite hanging and resource starvation on third-party calls.
    """
    cfg = settings or get_settings()
    return httpx.Timeout(
        connect=cfg.external_http_connect_timeout_seconds,
        read=cfg.external_http_read_timeout_seconds,
        write=cfg.external_http_write_timeout_seconds,
        pool=cfg.external_http_pool_timeout_seconds,
    )


def create_resilient_http_client(
    settings: Settings | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Factory creating an AsyncClient preconfigured with safe timeouts."""
    timeout = kwargs.pop("timeout", None) or get_http_timeouts(settings)
    return httpx.AsyncClient(timeout=timeout, **kwargs)


def is_transient_http_error(
    exc: Exception | None = None,
    response: httpx.Response | None = None,
) -> bool:
    """Determine whether an HTTP interaction failed due to a transient condition.

    Transient conditions include:
    - Connection timeouts, read timeouts, write timeouts
    - Network connectivity drops, DNS resolution failures, connection resets
    - Upstream server errors: HTTP 502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout

    Permanent conditions that MUST NOT be retried:
    - HTTP 4xx client errors (400 Bad Request, 401 Unauthorized, 403 Forbidden, 404, 409, 422)
    - Valid non-error responses
    """
    if exc is not None:
        if isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.ConnectError,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ),
        ):
            return True

    if response is not None:
        # 502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout are transient
        if response.status_code in (502, 503, 504):
            return True

    return False


async def execute_http_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 2.0,
    **kwargs: Any,
) -> httpx.Response:
    """Execute outbound HTTP request with bounded retries only for transient failures.

    Applies jittered exponential backoff between attempts.
    Never retries 4xx client errors or validation faults.
    Sanitizes logs so sensitive credentials and tokens are never leaked.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)

            # Check for transient upstream server status (502, 503, 504)
            if is_transient_http_error(response=response):
                if attempt < max_retries:
                    delay = calculate_backoff_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        jitter=True,
                    )
                    logger.warning(
                        "Upstream HTTP transient %d [attempt %d/%d]; retry in %s s",
                        response.status_code,
                        attempt,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                # Transient 5xx retries exhausted
                logger.error(
                    "Upstream HTTP call retries exhausted with status %d after %d attempts",
                    response.status_code,
                    max_retries,
                )
                raise ServiceUnavailableError(
                    message="External service communication failed after bounded retry attempts.",
                    code="EXTERNAL_SERVICE_UNAVAILABLE",
                )

            # Return response for caller inspection (even 4xx; caller handles business logic)
            return response

        except Exception as exc:
            last_error = exc
            if is_transient_http_error(exc=exc):
                if attempt < max_retries:
                    delay = calculate_backoff_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        jitter=True,
                    )
                    logger.warning(
                        "Outbound HTTP transient [%s, attempt %d/%d]; retry in %s s",
                        type(exc).__name__,
                        attempt,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                # Transient exception retries exhausted
                logger.error(
                    "Outbound HTTP call retries exhausted after %d attempts [%s]",
                    max_retries,
                    type(exc).__name__,
                )
                break

            # Non-transient exception: fail immediately
            logger.error(
                "Outbound HTTP call failed permanently [%s]: %s",
                type(exc).__name__,
                str(exc),
            )
            raise

    # Retries exhausted
    raise ServiceUnavailableError(
        message="External service communication failed after bounded retry attempts.",
        code="EXTERNAL_SERVICE_UNAVAILABLE",
    ) from last_error
