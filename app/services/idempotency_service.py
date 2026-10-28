"""Idempotency service and lifecycle management for write operations.

## Architecture and Transaction Expectations

This module provides atomic, concurrency-safe idempotency persistence to prevent
duplicate side effects (e.g., duplicate appointments, double payments, replayed mutations).

### Transaction Lifecycle Patterns

1. **Atomic Single-Transaction Pattern (Recommended for Local DB Writes):**
   - The caller begins a single database transaction (`AsyncSession`).
   - `claim_or_replay(...)` is invoked. It reads any existing key with `SELECT ... FOR UPDATE`
     (so reclaiming an expired/failed/orphaned key is serialized by a row lock) and otherwise
     attempts an initial claim using a savepoint (`session.begin_nested()`).
   - If the operation was previously completed with matching payload, the saved response is replayed
     immediately and the outer transaction can exit cleanly without executing business logic.
   - If the claim is new, an `IdempotencyKey` record is staged with `status = "in_progress"`.
   - If a concurrent transaction races to claim the identical key, PostgreSQL's unique constraint
     (`uq_idempotency_user_key_operation`) causes the loser's savepoint to roll back without
     invalidating the outer transaction block, and the winner's committed or in-progress state is
     inspected cleanly.
   - The business logic executes (e.g., slot lock, booking insertion).
   - `record_success(...)` updates the idempotency record to `status = "completed"`.
   - The transaction commits atomically. If any error occurs prior to commit, the entire transaction
     rolls back, releasing the claimed key so the client can fix errors and retry safely.
     Consequence: error outcomes (e.g. 409 slot unavailable) are NOT cached; a retry with the
     same key re-evaluates the request against current state.
   - Because the in-progress row is uncommitted, a concurrent request with the same key blocks on
     the unique index until the first transaction finishes, then replays the committed outcome.

2. **Two-Phase Transaction Pattern (For External Third-Party APIs / Payments):**
   - Phase 1: Call `claim_or_replay(...)` and commit `in_progress` record in an initial transaction.
   - Phase 2: Perform the external provider network call (e.g., payment gateway intent).
   - Phase 3: Open a second transaction, perform local writes, and call `record_success(...)`.
   - Stale in-progress claims are automatically reclaimed after configured timeout.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Header
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError
from app.models.idempotency import IdempotencyKey
from app.schemas.idempotency import IdempotencyResult, IdempotencyStatus

logger = logging.getLogger(__name__)


def compute_request_hash(payload: Any) -> str:
    """Compute a deterministic, canonical SHA-256 hex digest for arbitrary request payloads.

    Handles None, empty payloads, Pydantic models, JSON strings, bytes, and nested
    dictionaries/lists with sorted keys and compact separators. UTF-8 bytes are decoded and
    treated exactly like the equivalent ``str`` so both representations hash identically.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = bytes(payload).decode("utf-8")
        except UnicodeDecodeError:
            return hashlib.sha256(bytes(payload)).hexdigest()

    if payload is None:
        normalized: Any = {}
    elif isinstance(payload, BaseModel):
        normalized = payload.model_dump(mode="json")
    elif isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            normalized = {}
        elif (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                normalized = json.loads(stripped)
            except json.JSONDecodeError:
                normalized = stripped
        else:
            normalized = stripped
    else:
        normalized = payload

    try:
        canonical_json = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        # Fallback for non-serializable objects
        return hashlib.sha256(str(normalized).encode("utf-8")).hexdigest()


def validate_idempotency_key(key: str | None) -> str:
    """Validate that an idempotency key is present, non-empty, and within length limits."""
    if key is None:
        raise BadRequestError(
            code="MISSING_IDEMPOTENCY_KEY",
            message="The 'Idempotency-Key' header is required for this operation.",
        )
    trimmed = key.strip()
    if not trimmed:
        raise BadRequestError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="The 'Idempotency-Key' header cannot be empty or blank.",
        )
    if len(trimmed) > 255:
        raise BadRequestError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="The 'Idempotency-Key' header must not exceed 255 characters.",
        )
    return trimmed


async def claim_or_replay(
    session: AsyncSession,
    user_id: uuid.UUID,
    key: str,
    operation: str,
    payload: Any = None,
    ttl_seconds: int | None = None,
    in_progress_timeout_seconds: int | None = None,
) -> IdempotencyResult:
    """Atomically claim an idempotency key or replay a previously completed response.

    Args:
        session: Active asynchronous SQLAlchemy database session.
        user_id: Authenticated actor UUID.
        key: Client-provided idempotency key string.
        operation: Operation identifier (e.g., 'create_booking', 'consultation_payment').
        payload: Inbound request payload to canonicalize and verify.
        ttl_seconds: Optional record expiry TTL (defaults to settings TTL).
        in_progress_timeout_seconds: Optional timeout threshold for orphaned in-progress keys.

    Returns:
        IdempotencyResult indicating whether this is a cached replay or a fresh claim.

    Raises:
        ConflictError: If payload mismatches (409) or concurrent request in progress (409).
        BadRequestError: If the key format is invalid.
    """
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.idempotency_default_ttl_seconds
    in_progress_timeout = (
        in_progress_timeout_seconds
        if in_progress_timeout_seconds is not None
        else settings.idempotency_in_progress_timeout_seconds
    )

    clean_key = validate_idempotency_key(key)
    request_hash = compute_request_hash(payload)
    now = datetime.now(UTC)

    # 1. Query for an existing record scoped to (user_id, key, operation).
    # FOR UPDATE serializes concurrent reclaims of expired/failed/orphaned records: without the
    # lock, two retries could both observe a reclaimable row and both execute side effects.
    stmt = (
        select(IdempotencyKey)
        .where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == clean_key,
            IdempotencyKey.operation == operation,
        )
        .with_for_update()
    )
    existing = await session.scalar(stmt)

    if existing is not None:
        # Check for record expiration
        if existing.expires_at <= now:
            # Never log the raw client-supplied key; the record id is sufficient for tracing.
            logger.info("Idempotency record %s expired; resetting for fresh claim.", existing.id)
            existing.status = IdempotencyStatus.IN_PROGRESS.value
            existing.request_hash = request_hash
            existing.response_code = None
            existing.response_body = None
            existing.resource_id = None
            existing.created_at = now
            existing.expires_at = now + timedelta(seconds=ttl)
            await session.flush()
            return IdempotencyResult(
                is_replayed=False,
                key=clean_key,
                operation=operation,
                status=IdempotencyStatus.IN_PROGRESS,
                idempotency_record_id=existing.id,
            )

        # Enforce payload fingerprint matching
        if existing.request_hash != request_hash:
            raise ConflictError(
                code="IDEMPOTENCY_PAYLOAD_MISMATCH",
                message="Idempotency key was previously used with a different request payload.",
            )

        # Handle completed record: replay original response
        if existing.status == IdempotencyStatus.COMPLETED.value:
            return IdempotencyResult(
                is_replayed=True,
                key=clean_key,
                operation=operation,
                status=IdempotencyStatus.COMPLETED,
                response_code=existing.response_code,
                response_body=existing.response_body,
                resource_id=existing.resource_id,
                idempotency_record_id=existing.id,
            )

        # Handle in-progress record: detect orphaned vs active concurrent execution
        if existing.status == IdempotencyStatus.IN_PROGRESS.value:
            elapsed = (now - existing.created_at).total_seconds()
            if elapsed > in_progress_timeout:
                logger.warning(
                    "Orphaned in-progress idempotency record %s (elapsed %.1fs). Reclaiming.",
                    existing.id,
                    elapsed,
                )
                existing.created_at = now
                existing.expires_at = now + timedelta(seconds=ttl)
                await session.flush()
                return IdempotencyResult(
                    is_replayed=False,
                    key=clean_key,
                    operation=operation,
                    status=IdempotencyStatus.IN_PROGRESS,
                    idempotency_record_id=existing.id,
                )

            raise ConflictError(
                code="IDEMPOTENCY_CONCURRENT_REQUEST",
                message=(
                    "A request with this idempotency key is currently in progress. "
                    "Please retry shortly."
                ),
            )

        # Handle failed record: allow immediate retry
        if existing.status == IdempotencyStatus.FAILED.value:
            existing.status = IdempotencyStatus.IN_PROGRESS.value
            existing.created_at = now
            existing.expires_at = now + timedelta(seconds=ttl)
            await session.flush()
            return IdempotencyResult(
                is_replayed=False,
                key=clean_key,
                operation=operation,
                status=IdempotencyStatus.IN_PROGRESS,
                idempotency_record_id=existing.id,
            )

    # 2. Key does not exist: attempt atomic claim wrapped in a nested savepoint
    new_record = IdempotencyKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key=clean_key,
        operation=operation,
        request_hash=request_hash,
        status=IdempotencyStatus.IN_PROGRESS.value,
        expires_at=now + timedelta(seconds=ttl),
        created_at=now,
    )

    try:
        async with session.begin_nested():
            session.add(new_record)
            await session.flush()

        return IdempotencyResult(
            is_replayed=False,
            key=clean_key,
            operation=operation,
            status=IdempotencyStatus.IN_PROGRESS,
            idempotency_record_id=new_record.id,
        )
    except IntegrityError as err:
        # Concurrent race condition: Another transaction committed or claimed the exact same key.
        # The savepoint was automatically rolled back, leaving the outer transaction valid.
        logger.info("Concurrent idempotency claim race on operation '%s'.", operation)
        winner_stmt = select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == clean_key,
            IdempotencyKey.operation == operation,
        )
        winner = await session.scalar(winner_stmt)

        if winner is None:
            # Racing transaction rolled back. Raise a clean conflict instructing retry.
            raise ConflictError(
                code="IDEMPOTENCY_CONCURRENT_REQUEST",
                message="Concurrent request conflict detected. Please retry.",
            ) from err

        # Validate fingerprint against the winner
        if winner.request_hash != request_hash:
            raise ConflictError(
                code="IDEMPOTENCY_PAYLOAD_MISMATCH",
                message="Idempotency key was previously used with a different request payload.",
            ) from err

        if winner.status == IdempotencyStatus.COMPLETED.value:
            return IdempotencyResult(
                is_replayed=True,
                key=clean_key,
                operation=operation,
                status=IdempotencyStatus.COMPLETED,
                response_code=winner.response_code,
                response_body=winner.response_body,
                resource_id=winner.resource_id,
                idempotency_record_id=winner.id,
            )

        raise ConflictError(
            code="IDEMPOTENCY_CONCURRENT_REQUEST",
            message=(
                "A request with this idempotency key is currently in progress. "
                "Please retry shortly."
            ),
        ) from err


async def record_success(
    session: AsyncSession,
    record_id: uuid.UUID,
    response_code: int,
    response_body: dict[str, Any] | None = None,
    resource_id: uuid.UUID | None = None,
) -> IdempotencyKey:
    """Transition an in-progress idempotency record to completed with its cached response.

    Only ``in_progress`` records may be completed; this prevents a stale caller from
    overwriting an outcome that has already been recorded.
    """
    record = await session.get(IdempotencyKey, record_id)
    if record is None:
        raise ConflictError(
            code="IDEMPOTENCY_RECORD_NOT_FOUND",
            message="The specified idempotency record could not be found to complete.",
        )
    if record.status != IdempotencyStatus.IN_PROGRESS.value:
        raise ConflictError(
            code="IDEMPOTENCY_INVALID_STATE",
            message="Only in-progress idempotency records can be completed.",
        )

    record.status = IdempotencyStatus.COMPLETED.value
    record.response_code = response_code
    record.response_body = response_body
    record.resource_id = resource_id
    await session.flush()
    return record


async def record_failure(session: AsyncSession, record_id: uuid.UUID) -> None:
    """Mark an in-progress record as failed so the client may retry (two-phase pattern only).

    Completed records are never downgraded; non in-progress records are left untouched.
    No error text is stored, so failures cannot leak sensitive request details.
    """
    record = await session.get(IdempotencyKey, record_id)
    if record is not None and record.status == IdempotencyStatus.IN_PROGRESS.value:
        record.status = IdempotencyStatus.FAILED.value
        await session.flush()


async def cleanup_expired_keys(
    session: AsyncSession,
    batch_size: int = 1000,
    now_utc: datetime | None = None,
) -> int:
    """Delete up to ``batch_size`` expired idempotency records (bounded per call)."""
    now = now_utc or datetime.now(UTC)
    expired_ids = select(IdempotencyKey.id).where(IdempotencyKey.expires_at < now).limit(batch_size)
    delete_stmt = (
        delete(IdempotencyKey)
        .where(IdempotencyKey.id.in_(expired_ids))
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(delete_stmt)
    await session.flush()
    return result.rowcount or 0


# ==============================================================================
# FastAPI Route Dependency Helpers
# ==============================================================================


def require_idempotency_key(
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
        description="Unique request key to guarantee at-most-once execution",
    ),
) -> str:
    """FastAPI dependency requiring a valid non-empty Idempotency-Key header on write endpoints."""
    return validate_idempotency_key(idempotency_key)


def optional_idempotency_key(
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
        description="Optional unique request key for idempotency tracking",
    ),
) -> str | None:
    """FastAPI dependency returning the Idempotency-Key header if provided, or None."""
    if idempotency_key is None:
        return None
    return validate_idempotency_key(idempotency_key)
