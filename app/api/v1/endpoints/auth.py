"""Authentication API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.auth import UserRegisterRequest, UserResponse
from app.services.auth_service import register_user

router = APIRouter()


@router.post(
    "/register",
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
