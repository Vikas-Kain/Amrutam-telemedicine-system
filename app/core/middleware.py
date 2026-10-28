"""Request and Correlation ID propagation middleware."""

import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.logging import correlation_id_ctx_var, request_id_ctx_var

logger = logging.getLogger("app.middleware.request")


class RequestCorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware extracting or generating X-Request-ID and X-Correlation-ID headers.

    Propagates identifiers into async context variables for logging and ensures
    headers are attached to all outbound responses.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Extract existing header or generate a new unique identifier
        inbound_request_id = request.headers.get("X-Request-ID")
        request_id = inbound_request_id.strip() if inbound_request_id else f"req_{uuid.uuid4().hex}"

        inbound_correlation_id = request.headers.get("X-Correlation-ID")
        correlation_id = inbound_correlation_id.strip() if inbound_correlation_id else request_id

        # Attach to request state for handler access
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        # Bind to context variables for log formatting
        req_token = request_id_ctx_var.set(request_id)
        corr_token = correlation_id_ctx_var.set(correlation_id)

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Log safe request metrics without body or authorization data
            logger.info(
                "%s %s -> %d (%s ms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

            # Propagate identifiers in response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            # Clean up context variables to prevent cross-request pollution
            request_id_ctx_var.reset(req_token)
            correlation_id_ctx_var.reset(corr_token)


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing configurable maximum HTTP request payload limits.

    Rejects oversized payloads with HTTP 413 Payload Too Large and standardized
    error envelope, preventing memory exhaustion and denial-of-service vectors.
    """

    def __init__(self, app: Any, max_body_bytes: int | None = None) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only validate write methods that accept request bodies
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        settings = get_settings()
        limit = self.max_body_bytes or settings.max_request_body_bytes

        # Fast path: Check Content-Length header if present
        content_length_str = request.headers.get("content-length")
        if content_length_str:
            try:
                content_length = int(content_length_str)
                if content_length > limit:
                    inbound_id = request.headers.get("X-Request-ID")
                    request_id = (
                        getattr(request.state, "request_id", None)
                        or request_id_ctx_var.get()
                        or inbound_id
                        or f"req_{uuid.uuid4().hex}"
                    )
                    logger.warning(
                        "Request body exceeded limit via Content-Length [len=%d, max=%d, path=%s]",
                        content_length,
                        limit,
                        request.url.path,
                    )
                    return JSONResponse(
                        status_code=413,
                        headers={"X-Request-ID": request_id},
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": (
                                    f"Request body exceeds maximum allowed size of {limit} bytes."
                                ),
                                "request_id": request_id,
                                "details": {
                                    "max_bytes": limit,
                                    "content_length": content_length,
                                },
                            }
                        },
                    )
                # Content length is within limits, proceed without buffering
                return await call_next(request)
            except ValueError:
                pass

        # Slow path: Stream-read chunked or missing Content-Length bodies up to limit + 1
        body_chunks = []
        total_bytes = 0
        async for chunk in request.stream():
            total_bytes += len(chunk)
            if total_bytes > limit:
                inbound_id = request.headers.get("X-Request-ID")
                request_id = (
                    getattr(request.state, "request_id", None)
                    or request_id_ctx_var.get()
                    or inbound_id
                    or f"req_{uuid.uuid4().hex}"
                )
                logger.warning(
                    "Chunked request body exceeded limit [bytes_read=%d, limit=%d, path=%s]",
                    total_bytes,
                    limit,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=413,
                    headers={"X-Request-ID": request_id},
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": (
                                f"Request body exceeds maximum allowed size of {limit} bytes."
                            ),
                            "request_id": request_id,
                            "details": {
                                "max_bytes": limit,
                            },
                        }
                    },
                )
            body_chunks.append(chunk)

        # Re-attach body stream so downstream ASGI endpoints can read it
        full_body = b"".join(body_chunks)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": full_body, "more_body": False}

        request._receive = receive
        return await call_next(request)
