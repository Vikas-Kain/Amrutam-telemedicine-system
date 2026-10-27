"""Authentication and user lifecycle business services."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.models.user import Profile, User
from app.schemas.auth import UserRegisterRequest

logger = logging.getLogger(__name__)


async def register_user(session: AsyncSession, payload: UserRegisterRequest) -> User:
    """Register a new patient account and associated profile in a single atomic transaction.

    Enforces email uniqueness with both pre-check and PostgreSQL unique constraint handling.
    Hashes the password with Argon2id before storage. Never logs credentials.
    Rolls back the entire transaction if profile creation fails.
    """
    # 1. Early check for existing user with normalized email
    stmt = select(User.id).where(User.email_normalized == payload.email)
    existing_user_id = await session.scalar(stmt)
    if existing_user_id is not None:
        raise ConflictError(
            message="A user with this email address already exists.",
            code="EMAIL_ALREADY_EXISTS",
        )

    # 2. Securely hash the password with Argon2id
    pwd_hash = hash_password(payload.password)

    # 3. Create User entity with default 'patient' role
    user = User(
        email_normalized=payload.email,
        password_hash=pwd_hash,
        role="patient",
        is_active=True,
        mfa_enabled=False,
    )
    session.add(user)

    try:
        # Flush to persist user and generate user.id
        await session.flush()

        # 4. Create Profile entity linked to user
        profile = Profile(
            user_id=user.id,
            full_name=payload.full_name,
            phone=payload.phone,
            date_of_birth=payload.date_of_birth,
        )
        session.add(profile)
        await session.flush()

        # Link profile relationship in-memory
        user.profile = profile

        # Commit active transaction atomically
        if session.in_transaction():
            await session.commit()

    except IntegrityError as exc:
        if session.in_transaction():
            await session.rollback()
        logger.info("Registration aborted: duplicate email constraint violation")
        raise ConflictError(
            message="A user with this email address already exists.",
            code="EMAIL_ALREADY_EXISTS",
        ) from exc
    except Exception as exc:
        if session.in_transaction():
            await session.rollback()
        logger.error("User registration transaction failed: %s", type(exc).__name__)
        raise

    logger.info(
        "Patient account registered successfully",
        extra={"user_id": str(user.id), "role": user.role},
    )
    return user
