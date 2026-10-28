"""API rate limiting engine and resilience backends.

Provides configurable sliding-window rate limiting supporting:
1. In-memory sliding window backend (default, thread-safe, local process storage).
2. Redis-backed sliding window backend (distributed shared counters via sorted sets).
3. FastAPI dependency integrating with endpoint routing.
4. Standard HTTP 429 response formatting with Retry-After and X-RateLimit-* headers.

Local-only limitation notice:
The InMemoryRateLimiter maintains counters in local process memory. In a multi-instance
deployment behind a load balancer without sticky sessions, each replica instance maintains
independent counters. For distributed environments where multiple instances must strictly
share limit quotas, configure Redis (`RATE_LIMIT_BACKEND=redis` and `REDIS_URL`).
"""

import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from fastapi import Request, Response

from app.core.config import Settings, get_settings
from app.core.errors import RateLimitExceededError
from app.core.security import decode_access_token

logger = logging.getLogger("app.core.rate_limit")


class RateLimiterBackend(ABC):
    """Abstract interface for rate limiting storage backends."""

    @abstractmethod
    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """Check if request is allowed under sliding window policy.

        Returns:
            tuple of (allowed: bool, retry_after: int, remaining: int)
        """
        ...

    @abstractmethod
    def is_allowed_sync(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """Synchronous variant for non-async contexts."""
        ...

    @abstractmethod
    async def areset(self) -> None:
        """Asynchronously reset all recorded rate limit state."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Synchronously reset all recorded rate limit state."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Dispose of underlying connections or resources."""
        ...


class InMemoryRateLimiter(RateLimiterBackend):
    """In-memory sliding window rate limiter using timestamps log.

    Thread-safe and async-safe using reentrant locks.
    Local-only limitation: State is not shared across multi-process workers.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, list[float]] = defaultdict(list)

    def _clean_and_check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        now: float,
    ) -> tuple[bool, int, int]:
        with self._lock:
            timestamps = self._records[key]
            cutoff = now - window_seconds
            # Purge expired timestamps
            valid_timestamps = [ts for ts in timestamps if ts > cutoff]

            if len(valid_timestamps) < max_requests:
                valid_timestamps.append(now)
                self._records[key] = valid_timestamps
                remaining = max(0, max_requests - len(valid_timestamps))
                return True, 0, remaining
            else:
                self._records[key] = valid_timestamps
                oldest_in_window = valid_timestamps[0]
                retry_after = max(1, int(oldest_in_window + window_seconds - now) + 1)
                return False, retry_after, 0

    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        now = time.time()
        return self._clean_and_check(key, max_requests, window_seconds, now)

    def is_allowed_sync(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        now = time.time()
        return self._clean_and_check(key, max_requests, window_seconds, now)

    async def areset(self) -> None:
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    async def close(self) -> None:
        self.reset()


class RedisRateLimiter(RateLimiterBackend):
    """Redis-backed distributed sliding window rate limiter.

    Uses Redis Sorted Sets (ZSET) with millisecond-precision timestamps:
    - ZREMRANGEBYSCORE: drops timestamps older than (now - window)
    - ZCARD: measures current request count
    - ZRANGE: reads oldest timestamp to compute accurate Retry-After
    - ZADD / EXPIRE: registers current attempt and refreshes key TTL

    Resilience guarantee: If Redis is unreachable or fails, logs a warning
    and falls back to an embedded in-memory limiter to avoid dropping client traffic.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Any | None = None
        self._fallback = InMemoryRateLimiter()

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis

                self._client = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to initialize Redis client (%s); using in-memory fallback", exc
                )
                return None
        return self._client

    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        client = self._get_client()
        if client is None:
            return await self._fallback.is_allowed(key, max_requests, window_seconds)

        now = time.time()
        cutoff = now - window_seconds
        redis_key = f"ratelimit:{key}"

        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zcard(redis_key)
            pipe.zrange(redis_key, 0, 0, withscores=True)
            results = await pipe.execute()

            current_count = results[1]
            oldest_entries = results[2]

            if current_count < max_requests:
                member_id = f"{now}:{uuid.uuid4().hex[:8]}"
                pipe = client.pipeline()
                pipe.zadd(redis_key, {member_id: now})
                pipe.expire(redis_key, window_seconds + 5)
                await pipe.execute()
                remaining = max(0, max_requests - current_count - 1)
                return True, 0, remaining
            else:
                if oldest_entries:
                    oldest_score = float(oldest_entries[0][1])
                    retry_after = max(1, int(oldest_score + window_seconds - now) + 1)
                else:
                    retry_after = window_seconds
                return False, retry_after, 0
        except Exception as exc:
            logger.warning("Redis rate limit operation failed (%s); failing open to in-memory", exc)
            return await self._fallback.is_allowed(key, max_requests, window_seconds)

    def is_allowed_sync(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        # Synchronous calls fallback to memory limiter
        return self._fallback.is_allowed_sync(key, max_requests, window_seconds)

    async def areset(self) -> None:
        self._fallback.reset()
        client = self._get_client()
        if client is not None:
            try:
                keys = await client.keys("ratelimit:*")
                if keys:
                    await client.delete(*keys)
            except Exception as exc:
                logger.warning("Failed to reset Redis rate limit keys: %s", exc)

    def reset(self) -> None:
        self._fallback.reset()

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        await self._fallback.close()


# Backend Singleton
_backend_instance: RateLimiterBackend | None = None
_backend_lock = threading.Lock()


def get_rate_limiter_backend(settings: Settings | None = None) -> RateLimiterBackend:
    """Return configured rate limiter backend singleton."""
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    with _backend_lock:
        if _backend_instance is not None:
            return _backend_instance

        cfg = settings or get_settings()
        if cfg.rate_limit_backend == "redis":
            redis_url = cfg.rate_limit_redis_url or cfg.redis_url
            _backend_instance = RedisRateLimiter(redis_url=redis_url)
        else:
            _backend_instance = InMemoryRateLimiter()

        return _backend_instance


def set_rate_limiter_backend(backend: RateLimiterBackend | None) -> None:
    """Explicitly override rate limiter backend (primarily for test fixture injection)."""
    global _backend_instance
    with _backend_lock:
        _backend_instance = backend


async def reset_rate_limiters() -> None:
    """Reset all active rate limit storage state across memory and Redis backends."""
    global _backend_instance
    if _backend_instance is not None:
        await _backend_instance.areset()


def reset_rate_limiters_sync() -> None:
    """Synchronous reset helper for test cleanup fixtures."""
    global _backend_instance
    if _backend_instance is not None:
        _backend_instance.reset()


def resolve_client_identifier(request: Request) -> str:
    """Resolve stable, safe client identifier for rate limiting.

    Priority:
    1. Authenticated user ID (from request.state or JWT bearer token).
    2. Client IP address (X-Forwarded-For if behind trusted proxy, else client.host).
    Never logs or exposes tokens or internal network topologies.
    """
    # 1. State-bound user ID
    if hasattr(request.state, "user_id") and request.state.user_id:
        return f"user:{request.state.user_id}"

    # 2. Check Authorization header without full DB lookup
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = decode_access_token(token)
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass

    # 3. Client IP address
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif request.client and request.client.host:
        client_ip = request.client.host
    else:
        client_ip = "127.0.0.1"

    return f"ip:{client_ip}"


class RateLimiter:
    """FastAPI route dependency enforcing sliding-window rate limiting.

    Configurable with custom request quotas or defaults sourced from application Settings.
    Sets standard RFC rate limit headers and raises RateLimitExceededError (HTTP 429) on breach.
    """

    def __init__(
        self,
        bucket: str,
        requests: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        self.bucket = bucket
        self.requests = requests
        self.window_seconds = window_seconds

    def _resolve_limits(self, settings: Settings) -> tuple[int, int]:
        """Resolve maximum request limit and window duration."""
        if self.requests is not None and self.window_seconds is not None:
            return self.requests, self.window_seconds

        if self.bucket == "auth":
            limit = self.requests or settings.rate_limit_auth_requests
            window = self.window_seconds or settings.rate_limit_auth_window_seconds
        elif self.bucket == "mfa":
            limit = self.requests or settings.rate_limit_mfa_requests
            window = self.window_seconds or settings.rate_limit_mfa_window_seconds
        elif self.bucket == "write":
            limit = self.requests or settings.rate_limit_write_requests
            window = self.window_seconds or settings.rate_limit_write_window_seconds
        else:
            limit = self.requests or settings.rate_limit_default_requests
            window = self.window_seconds or settings.rate_limit_default_window_seconds

        return limit, window

    async def __call__(self, request: Request, response: Response) -> None:
        """Evaluate rate limit quota for inbound request."""
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return

        limit, window = self._resolve_limits(settings)
        client_id = resolve_client_identifier(request)
        key = f"{self.bucket}:{client_id}"

        backend = get_rate_limiter_backend(settings)
        allowed, retry_after, remaining = await backend.is_allowed(
            key=key,
            max_requests=limit,
            window_seconds=window,
        )

        # Attach standard rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(window)

        if not allowed:
            response.headers["Retry-After"] = str(retry_after)
            logger.warning(
                "Rate limit exceeded for %s [key=%s, limit=%d, window=%ds, retry_after=%ds]",
                self.bucket,
                key,
                limit,
                window,
                retry_after,
            )
            raise RateLimitExceededError(
                message=(
                    f"Rate limit exceeded for {self.bucket}. "
                    f"Please retry after {retry_after} seconds."
                ),
                retry_after=retry_after,
                details={
                    "bucket": self.bucket,
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after": retry_after,
                },
            )


# Pre-configured route dependency instances
rate_limit_auth = RateLimiter("auth")
rate_limit_mfa = RateLimiter("mfa")
rate_limit_write = RateLimiter("write")
rate_limit_default = RateLimiter("default")
