"""Cryptographic helpers, password hashing with Argon2id, and email normalization."""

import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

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
