"""Request and Correlation ID propagation middleware."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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
