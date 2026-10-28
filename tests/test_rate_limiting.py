from unittest.mock import patch

import pytest
from app.core.config import get_settings
from app.core.pagination import PaginationParams, validate_pagination_bounds
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
    reset_rate_limiters_sync,
    set_rate_limiter_backend,
)
from app.main import create_app
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_limiter_state():
    """Ensure rate limiter storage is fresh before and after each test."""
    reset_rate_limiters_sync()
    yield
    reset_rate_limiters_sync()
    set_rate_limiter_backend(None)


# ==============================================================================
# 1. Rate Limiting Response & Headers Tests
# ==============================================================================


def test_rate_limit_response_headers_on_success(client: TestClient):
    """Verify that allowed requests include X-RateLimit-* headers."""
    import uuid

    unique_email = f"ratelimit_header_{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email,
            "password": "ValidPassword123!",
            "full_name": "Header Test User",
            "date_of_birth": "1990-01-01",
        },
    )
    assert response.status_code == 201
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "X-RateLimit-Reset" in response.headers
    assert int(response.headers["X-RateLimit-Remaining"]) >= 0


def test_rate_limit_exceeded_returns_429_with_retry_after(client: TestClient):
    """Verify that exceeding rate limit returns HTTP 429 with Retry-After header."""
    app = create_app()
    test_router = APIRouter()
    # Rate limiter configured with limit of 2 requests per 60 seconds
    test_limiter = RateLimiter("test_strict", requests=2, window_seconds=60)

    @test_router.get("/test-rate-limit", dependencies=[Depends(test_limiter)])
    def limited_endpoint():
        return {"status": "ok"}

    app.include_router(test_router)

    with TestClient(app) as test_client:
        # Request 1: OK
        res1 = test_client.get("/test-rate-limit")
        assert res1.status_code == 200
        assert res1.headers["X-RateLimit-Remaining"] == "1"

        # Request 2: OK
        res2 = test_client.get("/test-rate-limit")
        assert res2.status_code == 200
        assert res2.headers["X-RateLimit-Remaining"] == "0"

        # Request 3: Exceeded -> HTTP 429
        res3 = test_client.get("/test-rate-limit")
        assert res3.status_code == 429
        assert "Retry-After" in res3.headers
        assert int(res3.headers["Retry-After"]) > 0

        # Verify standardized error envelope
        data = res3.json()
        assert "error" in data
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Rate limit exceeded" in data["error"]["message"]
        assert "request_id" in data["error"]
        assert data["error"]["details"]["bucket"] == "test_strict"
        assert data["error"]["details"]["limit"] == 2


def test_rate_limit_error_response_zero_secret_leak(client: TestClient):
    """Verify rate limit error payloads contain zero sensitive server internals."""
    app = create_app()
    test_router = APIRouter()
    strict_limiter = RateLimiter("test_leak_check", requests=1, window_seconds=30)

    @test_router.get("/test-leak", dependencies=[Depends(strict_limiter)])
    def leak_endpoint():
        return {"status": "ok"}

    app.include_router(test_router)

    with TestClient(app) as test_client:
        test_client.get("/test-leak")
        res = test_client.get("/test-leak")
        assert res.status_code == 429
        raw_text = res.text.lower()

        # Invariant checks: zero internal credentials or stack traces leaked
        assert "password" not in raw_text
        assert "secret" not in raw_text
        assert "postgres" not in raw_text
        assert "traceback" not in raw_text
        assert "redis://" not in raw_text
        assert "file" not in raw_text


# ==============================================================================
# 2. Configuration & Scoping Tests
# ==============================================================================


def test_rate_limit_disabled_configuration_bypasses_limits():
    """Verify rate limiting is completely bypassed when rate_limit_enabled=False."""
    settings = get_settings()
    with patch.object(settings, "rate_limit_enabled", False):
        app = create_app()
        test_router = APIRouter()
        strict_limiter = RateLimiter("bypass_test", requests=1, window_seconds=60)

        @test_router.get("/bypass-route", dependencies=[Depends(strict_limiter)])
        def bypass_route():
            return {"status": "ok"}

        app.include_router(test_router)

        with TestClient(app) as test_client:
            # Should allow 5 consecutive requests without 429
            for _ in range(5):
                res = test_client.get("/bypass-route")
                assert res.status_code == 200


def test_rate_limit_scoping_by_user_id_vs_ip():
    """Verify authenticated requests are partitioned by user ID rather than sharing IP bucket."""
    app = create_app()
    test_router = APIRouter()
    user_limiter = RateLimiter("user_scoping_test", requests=1, window_seconds=60)

    @test_router.get("/user-scoped", dependencies=[Depends(user_limiter)])
    def user_scoped_endpoint():
        return {"status": "ok"}

    app.include_router(test_router)

    from app.core.security import create_access_token

    token_user_1 = create_access_token(
        subject="00000000-0000-0000-0000-000000000001", role="patient"
    )
    token_user_2 = create_access_token(
        subject="00000000-0000-0000-0000-000000000002", role="patient"
    )

    with TestClient(app) as test_client:
        # User 1 request 1 -> OK
        res1 = test_client.get("/user-scoped", headers={"Authorization": f"Bearer {token_user_1}"})
        assert res1.status_code == 200

        # User 1 request 2 -> 429 (quota exhausted)
        res2 = test_client.get("/user-scoped", headers={"Authorization": f"Bearer {token_user_1}"})
        assert res2.status_code == 429

        # User 2 request 1 -> OK (separate quota despite identical client IP)
        res3 = test_client.get("/user-scoped", headers={"Authorization": f"Bearer {token_user_2}"})
        assert res3.status_code == 200


# ==============================================================================
# 3. In-Memory & Redis Backend Unit Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_in_memory_rate_limiter_sliding_window():
    """Test InMemoryRateLimiter sliding window tracking and reset."""
    limiter = InMemoryRateLimiter()

    # Allowed: 2 requests
    allowed1, retry1, rem1 = await limiter.is_allowed("test_key", max_requests=2, window_seconds=60)
    assert allowed1 is True
    assert rem1 == 1

    allowed2, retry2, rem2 = await limiter.is_allowed("test_key", max_requests=2, window_seconds=60)
    assert allowed2 is True
    assert rem2 == 0

    # Rejected on 3rd attempt
    allowed3, retry3, rem3 = await limiter.is_allowed("test_key", max_requests=2, window_seconds=60)
    assert allowed3 is False
    assert retry3 > 0
    assert rem3 == 0

    # Reset cleans storage
    await limiter.areset()
    allowed_after_reset, _, _ = await limiter.is_allowed(
        "test_key", max_requests=2, window_seconds=60
    )
    assert allowed_after_reset is True


@pytest.mark.asyncio
async def test_redis_rate_limiter_resilience_fallback():
    """Verify RedisRateLimiter falls back cleanly to in-memory on Redis outage."""
    # Provide unreachable Redis URL
    redis_limiter = RedisRateLimiter(redis_url="redis://nonexistent-host:6379/9")

    # Should gracefully fail open to in-memory fallback without throwing exceptions
    allowed, retry_after, remaining = await redis_limiter.is_allowed(
        key="fallback_test",
        max_requests=2,
        window_seconds=60,
    )
    assert allowed is True
    assert remaining == 1

    # Second request
    allowed2, _, remaining2 = await redis_limiter.is_allowed(
        key="fallback_test",
        max_requests=2,
        window_seconds=60,
    )
    assert allowed2 is True
    assert remaining2 == 0

    # Third request blocked by in-memory fallback
    allowed3, retry3, _ = await redis_limiter.is_allowed(
        key="fallback_test",
        max_requests=2,
        window_seconds=60,
    )
    assert allowed3 is False
    assert retry3 > 0


# ==============================================================================
# 4. Request Body Limit Middleware Tests (HTTP 413)
# ==============================================================================


def test_request_body_size_limit_via_content_length():
    """Verify requests with Content-Length exceeding limit are rejected with HTTP 413."""
    from app.core.middleware import RequestBodyLimitMiddleware

    custom_app = create_app()
    custom_app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=500)

    with TestClient(custom_app) as custom_client:
        # Oversized payload: 600 bytes
        oversized_data = {"text": "A" * 600}
        response = custom_client.post("/api/v1/auth/login", json=oversized_data)

        assert response.status_code == 413
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
        assert "maximum allowed size" in data["error"]["message"]
        assert "request_id" in data["error"]
        assert "X-Request-ID" in response.headers


def test_request_body_size_within_limit_passes(client: TestClient):
    """Verify requests within payload size limit proceed to handler."""
    # Under default 1 MB limit
    normal_data = {
        "email": "normal_size_user@example.com",
        "password": "ValidPassword123!",
    }
    response = client.post("/api/v1/auth/login", json=normal_data)
    # Reaches authentication handler (401 invalid credentials, NOT 413)
    assert response.status_code == 401


# ==============================================================================
# 5. Pagination Limits & Bounds Validation Tests
# ==============================================================================


def test_pagination_bounds_validation():
    """Verify pagination validation helpers reject invalid or oversized limits."""
    # Valid parameters
    validate_pagination_bounds(page=1, page_size=20, max_page_size=100)
    validate_pagination_bounds(page=5, page_size=100, max_page_size=100)

    # Invalid page < 1
    with pytest.raises(Exception) as exc_page:
        validate_pagination_bounds(page=0, page_size=20)
    assert "page must be greater than or equal to 1" in str(exc_page.value)

    # Invalid page_size < 1
    with pytest.raises(Exception) as exc_size_low:
        validate_pagination_bounds(page=1, page_size=0)
    assert "page_size must be between 1 and" in str(exc_size_low.value)

    # Oversized page_size > 100
    with pytest.raises(Exception) as exc_size_high:
        validate_pagination_bounds(page=1, page_size=101, max_page_size=100)
    assert "page_size must be between 1 and 100" in str(exc_size_high.value)


def test_pagination_params_offset_and_limit_calculation():
    """Verify PaginationParams computes SQL offset and limit accurately."""
    p1 = PaginationParams(page=1, page_size=20)
    assert p1.offset == 0
    assert p1.limit == 20

    p2 = PaginationParams(page=3, page_size=25)
    assert p2.offset == 50
    assert p2.limit == 25


def test_api_endpoint_rejects_oversized_pagination(client: TestClient):
    """Verify API pagination endpoints reject page_size > 100 with HTTP 422."""
    response = client.get("/api/v1/doctors?page=1&page_size=101")
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
