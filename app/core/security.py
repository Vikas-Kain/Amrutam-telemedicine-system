"""Cryptographic helpers, password hashing with Argon2id, and email normalization."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import UnauthorizedError

logger = logging.getLogger(__name__)

# Argon2id password hasher configured with RFC 9106 / OWASP recommended parameters
# time_cost: 3 iterations
# memory_cost: 65536 KiB (64 MiB)
# parallelism: 4 threads/lanes
# hash_len: 32 bytes
# salt_len: 16 bytes
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id with salted parameters.

    Never log or store the plaintext password.
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2id hash.

    Returns True if valid, False otherwise. Handles verification errors gracefully.
    """
    if not password or not hashed_password:
        return False
    try:
        return _password_hasher.verify(hashed_password, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError) as exc:
        logger.warning("Password verification failure due to invalid hash: %s", type(exc).__name__)
        return False


def normalize_email(email: str) -> str:
    """Normalize email address consistently by stripping whitespace and converting to lowercase."""
    if not email:
        return ""
    return email.strip().lower()


def create_access_token(
    subject: str | uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token with standard RFC 7519 claims.

    Claims:
    - sub: Subject identifier (User UUID string)
    - role: Assigned user role
    - iat: Issued at (UTC timestamp)
    - nbf: Not before (UTC timestamp)
    - exp: Expiration (UTC timestamp)
    - jti: Unique token identifier (UUID hex)

    Never logs raw tokens or secret keys.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )

    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and strictly validate a JWT access token.

    Validates signature, expiration, and ensures only the configured algorithm is accepted.
    Enforces required claims: sub, role, exp, iat.
    Never logs raw token contents.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "require": ["sub", "role", "exp", "iat"],
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError(
            message="Access token has expired.",
            code="TOKEN_EXPIRED",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError(
            message="Invalid access token.",
            code="INVALID_TOKEN",
        ) from exc
