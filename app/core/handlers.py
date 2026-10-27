"""Global exception handlers ensuring consistent error envelope and zero secret/trace leaks."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppException
from app.core.logging import request_id_ctx_var

logger = logging.getLogger("app.core.handlers")


def _get_request_id(request: Request) -> str | None:
    """Retrieve request ID from request state or async contextvar."""
    return getattr(request.state, "request_id", None) or request_id_ctx_var.get()


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle all domain-level AppException subclasses."""
    request_id = _get_request_id(request)
    payload: dict[str, Any] = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id,
        }
    }
    if exc.details is not None:
        payload["error"]["details"] = exc.details

    return JSONResponse(status_code=exc.status_code, content=payload)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic request validation errors cleanly without raw bodies."""
    request_id = _get_request_id(request)

    # Format errors cleanly into field-level messages
    sanitized_errors = []
    for err in exc.errors():
        field_loc = " -> ".join(str(loc) for loc in err.get("loc", []))
        sanitized_errors.append(
            {
                "field": field_loc,
                "message": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            }
        )

    payload = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "request_id": request_id,
            "details": sanitized_errors,
        }
    }
    return JSONResponse(status_code=422, content=payload)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard Starlette / FastAPI HTTPExceptions."""
    request_id = _get_request_id(request)

    # Map status code to standard error code
    status_code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    code = status_code_map.get(exc.status_code, f"HTTP_{exc.status_code}")

    payload = {
        "error": {
            "code": code,
            "message": str(exc.detail),
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=exc.status_code, content=payload)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Logs full traceback internally with request ID for debugging, but returns
    a sanitized 500 error to the client with ZERO leaked internals or stack traces.
    """
    request_id = _get_request_id(request)

    logger.exception(
        "Unhandled internal server exception [request_id=%s]: %s",
        request_id,
        str(exc),
        exc_info=exc,
    )

    payload = {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected internal server error occurred.",
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=500, content=payload)


def register_exception_handlers(app: FastAPI) -> None:
    """Register all centralized exception handlers on the application."""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
