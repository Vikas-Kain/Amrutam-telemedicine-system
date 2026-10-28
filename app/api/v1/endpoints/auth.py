"""Authentication API endpoints."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.rate_limit import rate_limit_auth
from app.core.security import create_access_token
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UserRegisterRequest,
    UserResponse,
)
from app.services.auth_service import authenticate_user, register_user

router = APIRouter()


@router.post(
    "/register",
    dependencies=[Depends(rate_limit_auth)],
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient account",
    description=(
        "Registers a new patient account and associated profile in a single atomic transaction. "
        "Enforces consistent email normalization and unique email constraints. "
        "Returns a sanitized profile response with password and secrets excluded."
    ),
    responses={
        201: {
            "description": "User account and profile successfully created.",
        },
        409: {
            "description": "Email address already registered.",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "EMAIL_ALREADY_EXISTS",
                            "message": "A user with this email address already exists.",
                            "request_id": "req_01j9a4k7...",
                        }
                    }
                }
            },
        },
        422: {
            "description": "Request validation failed.",
        },
    },
)
async def register_patient(
    payload: UserRegisterRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserResponse:
    """Register a new patient user and profile."""
    user = await register_user(session=session, payload=payload)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    dependencies=[Depends(rate_limit_auth)],
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and issue access token",
    description=(
        "Authenticates a user using normalized email and password. "
        "Upon successful verification, returns a signed JWT access token with short expiry. "
        "Never exposes password hash, raw tokens in logs, or specific error details "
        "that allow enumeration."
    ),
    responses={
        200: {
            "description": "User successfully authenticated; access token returned.",
        },
        401: {
            "description": "Invalid credentials provided.",
        },
        403: {
            "description": "User account is inactive.",
        },
        422: {
            "description": "Request payload validation failed.",
        },
    },
)
async def login_user(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    """Authenticate credentials and generate signed access token."""
    user = await authenticate_user(session=session, email=payload.email, password=payload.password)
    settings = get_settings()
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    token = create_access_token(
        subject=user.id,
        role=user.role,
        expires_delta=expires_delta,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve current authenticated user profile",
    description=(
        "Retrieves account and demographic profile information for the authenticated user. "
        "Requires a valid Bearer access token. Sensitive credentials and secrets are excluded."
    ),
    responses={
        200: {
            "description": "Current user profile information.",
        },
        401: {
            "description": "Authentication token missing, invalid, or expired.",
        },
        403: {
            "description": "User account is inactive.",
        },
    },
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return profile details for the currently authenticated user."""
    return UserResponse.model_validate(current_user)
