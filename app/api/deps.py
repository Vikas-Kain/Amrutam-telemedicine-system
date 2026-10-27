"""Reusable FastAPI dependencies for authentication, role authorization, and database access."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.user import User
from app.services.auth_service import get_user_by_id

# Security scheme configured with auto_error=False so that missing/invalid authorization headers
# raise standardized AppException envelopes (UnauthorizedError HTTP 401)
# rather than default FastAPI payloads.
oauth2_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Validate bearer token and resolve current authenticated user.

    Rejects missing or invalid tokens with HTTP 401 UnauthorizedError.
    Rejects inactive users with HTTP 403 ForbiddenError.
    Never logs raw tokens.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise UnauthorizedError(
            message="Authentication credentials were not provided.",
            code="AUTHENTICATION_REQUIRED",
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError(
            message="Invalid access token.",
            code="INVALID_TOKEN",
        )

    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError(
            message="Invalid access token subject.",
            code="INVALID_TOKEN",
        ) from exc

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise UnauthorizedError(
            message="User account not found.",
            code="USER_NOT_FOUND",
        )

    if not user.is_active:
        raise ForbiddenError(
            message="User account is inactive.",
            code="ACCOUNT_INACTIVE",
        )

    return user


def require_roles(*allowed_roles: str) -> Callable[..., Callable[..., User]]:
    """Factory creating an authorization dependency enforcing role membership.

    Ensures the caller has one of the specified roles; raises ForbiddenError (HTTP 403) otherwise.
    Note: Feature-level resource ownership must also be verified independently by domain services.
    """
    valid_roles = set(allowed_roles)

    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in valid_roles:
            raise ForbiddenError(
                message="You do not have permission to perform this action.",
                code="INSUFFICIENT_PERMISSIONS",
            )
        return current_user

    return role_checker


# Pre-configured role dependencies for route declarations
require_doctor = require_roles("doctor")
require_admin = require_roles("admin")
require_doctor_or_admin = require_roles("doctor", "admin")
require_patient = require_roles("patient")
