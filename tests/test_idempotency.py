"""Unit, service, and live PostgreSQL integration tests for idempotency persistence."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import BadRequestError, ConflictError
from app.db.session import get_db_session
from app.models.idempotency import IdempotencyKey
from app.models.user import User
from app.schemas.idempotency import IdempotencyResult, IdempotencyStatus
from app.services.idempotency_service import (
    claim_or_replay,
    cleanup_expired_keys,
    compute_request_hash,
    optional_idempotency_key,
    record_failure,
    record_success,
    require_idempotency_key,
    validate_idempotency_key,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.conftest import is_postgres_available


class SamplePayload(BaseModel):
    doctor_id: uuid.UUID
    slot_id: uuid.UUID
    notes: str


# ==============================================================================
# 1. Canonical Fingerprint & Validation Tests
# ==============================================================================


def test_compute_request_hash_none_and_empty():
    """Verify None and empty structures produce deterministic hashes."""
    hash_none = compute_request_hash(None)
    hash_empty_dict = compute_request_hash({})
    assert len(hash_none) == 64
    assert hash_none == hash_empty_dict


def test_compute_request_hash_key_order_invariance():
    """Verify key order in dictionaries does not alter the canonical hash."""
    payload_a = {"b": 2, "a": 1, "c": [3, 2, 1]}
    payload_b = {"c": [3, 2, 1], "a": 1, "b": 2}
    assert compute_request_hash(payload_a) == compute_request_hash(payload_b)


def test_compute_request_hash_json_string_canonicalization():
    """Verify raw JSON strings are canonicalized equivalently to parsed dicts."""
    raw_json = '  {"status":   "active",   "amount": 5000} '
    parsed_dict = {"amount": 5000, "status": "active"}
    assert compute_request_hash(raw_json) == compute_request_hash(parsed_dict)


def test_compute_request_hash_pydantic_model_matches_dict():
    """Verify Pydantic models serialize identically to their equivalent dictionaries."""
    doc_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    model = SamplePayload(doctor_id=doc_id, slot_id=slot_id, notes="Follow-up consultation")
    dict_payload = {
        "doctor_id": str(doc_id),
        "slot_id": str(slot_id),
        "notes": "Follow-up consultation",
    }
    assert compute_request_hash(model) == compute_request_hash(dict_payload)


def test_compute_request_hash_detects_payload_mutation():
    """Verify any payload difference results in a distinct SHA-256 fingerprint."""
    base = {"slot_id": "123", "amount": 1000}
    mutated = {"slot_id": "123", "amount": 1001}
    assert compute_request_hash(base) != compute_request_hash(mutated)


def test_validate_idempotency_key_valid():
    """Verify valid idempotency keys are accepted and trimmed."""
    assert validate_idempotency_key("  valid-key-123  ") == "valid-key-123"


def test_validate_idempotency_key_missing_raises_bad_request():
    """Verify missing None key raises MISSING_IDEMPOTENCY_KEY."""
    with pytest.raises(BadRequestError) as exc:
        validate_idempotency_key(None)
    assert exc.value.code == "MISSING_IDEMPOTENCY_KEY"


def test_validate_idempotency_key_empty_or_whitespace_raises_bad_request():
    """Verify empty or whitespace-only keys raise INVALID_IDEMPOTENCY_KEY."""
    with pytest.raises(BadRequestError) as exc:
        validate_idempotency_key("   ")
    assert exc.value.code == "INVALID_IDEMPOTENCY_KEY"


def test_validate_idempotency_key_overly_long_raises_bad_request():
    """Verify keys exceeding 255 characters are rejected."""
    long_key = "a" * 256
    with pytest.raises(BadRequestError) as exc:
        validate_idempotency_key(long_key)
    assert exc.value.code == "INVALID_IDEMPOTENCY_KEY"


def test_require_idempotency_key_dependency():
    """Verify require_idempotency_key header dependency enforces presence."""
    assert require_idempotency_key("test-key") == "test-key"
    with pytest.raises(BadRequestError):
        require_idempotency_key(None)


def test_optional_idempotency_key_dependency():
    """Verify optional_idempotency_key allows None but validates when present."""
    assert optional_idempotency_key(None) is None
    assert optional_idempotency_key("test-key") == "test-key"
    with pytest.raises(BadRequestError):
        optional_idempotency_key("   ")


# ==============================================================================
# 2. Service Logic & Lifecycle Tests (Mocked AsyncSession)
# ==============================================================================


@pytest.mark.asyncio
async def test_claim_or_replay_new_claim_success():
    """Verify a fresh key is staged with status IN_PROGRESS and is_replayed=False."""
    user_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.scalar.return_value = None  # No existing key

    # Mock nested transaction savepoint (begin_nested is sync and returns an async context manager)
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock()
    nested_cm.__aexit__ = AsyncMock()
    mock_session.begin_nested = MagicMock(return_value=nested_cm)
    mock_session.add = MagicMock()

    result = await claim_or_replay(
        session=mock_session,
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        payload={"slot_id": "slot-1"},
    )

    assert isinstance(result, IdempotencyResult)
    assert result.is_replayed is False
    assert result.status == IdempotencyStatus.IN_PROGRESS
    assert result.key == "idemp-key-1"
    assert result.operation == "create_booking"
    assert mock_session.add.called
    assert mock_session.flush.called


@pytest.mark.asyncio
async def test_claim_or_replay_race_condition_savepoint_handling_unit():
    """Verify IntegrityError inside savepoint catches race and replays winner outcome."""
    user_id = uuid.uuid4()
    payload = {"slot_id": "slot-1"}
    req_hash = compute_request_hash(payload)
    winner_record = IdempotencyKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        request_hash=req_hash,
        status="completed",
        response_code=201,
        response_body={"booking_id": "b-123"},
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    # First scalar check: None (key not found yet)
    # Second scalar check (after race): winner_record
    mock_session.scalar.side_effect = [None, winner_record]

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock()
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin_nested = MagicMock(return_value=nested_cm)
    mock_session.add = MagicMock()
    mock_session.flush.side_effect = IntegrityError("duplicate key", params=None, orig=Exception())

    result = await claim_or_replay(
        session=mock_session,
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        payload=payload,
    )

    assert result.is_replayed is True
    assert result.status == IdempotencyStatus.COMPLETED
    assert result.response_code == 201
    assert result.response_body == {"booking_id": "b-123"}


@pytest.mark.asyncio
async def test_claim_or_replay_completed_key_replays_outcome():
    """Verify an existing completed key with identical payload returns cached outcome."""
    user_id = uuid.uuid4()
    payload = {"slot_id": "slot-1"}
    req_hash = compute_request_hash(payload)
    existing_id = uuid.uuid4()
    res_id = uuid.uuid4()

    existing_record = IdempotencyKey(
        id=existing_id,
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        request_hash=req_hash,
        status="completed",
        response_code=201,
        response_body={"id": str(res_id), "status": "booked"},
        resource_id=res_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = existing_record

    result = await claim_or_replay(
        session=mock_session,
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        payload=payload,
    )

    assert result.is_replayed is True
    assert result.status == IdempotencyStatus.COMPLETED
    assert result.response_code == 201
    assert result.response_body == {"id": str(res_id), "status": "booked"}
    assert result.resource_id == res_id
    assert not mock_session.add.called


@pytest.mark.asyncio
async def test_claim_or_replay_payload_mismatch_raises_conflict():
    """Verify re-using an active or completed key with different payload raises 409 Conflict."""
    user_id = uuid.uuid4()
    original_payload = {"slot_id": "slot-1"}
    original_hash = compute_request_hash(original_payload)

    existing_record = IdempotencyKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        request_hash=original_hash,
        status="completed",
        response_code=201,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = existing_record

    with pytest.raises(ConflictError) as exc:
        await claim_or_replay(
            session=mock_session,
            user_id=user_id,
            key="idemp-key-1",
            operation="create_booking",
            payload={"slot_id": "different-slot-2"},
        )

    assert exc.value.code == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_claim_or_replay_active_in_progress_raises_conflict():
    """Verify same-payload request during active execution raises IDEMPOTENCY_CONCURRENT_REQUEST."""
    user_id = uuid.uuid4()
    payload = {"slot_id": "slot-1"}
    req_hash = compute_request_hash(payload)

    existing_record = IdempotencyKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        request_hash=req_hash,
        status="in_progress",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC) - timedelta(seconds=10),  # Recent execution
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = existing_record

    with pytest.raises(ConflictError) as exc:
        await claim_or_replay(
            session=mock_session,
            user_id=user_id,
            key="idemp-key-1",
            operation="create_booking",
            payload=payload,
            in_progress_timeout_seconds=120,
        )

    assert exc.value.code == "IDEMPOTENCY_CONCURRENT_REQUEST"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_claim_or_replay_orphaned_in_progress_resets_and_claims():
    """Verify an abandoned in-progress key older than the timeout threshold is reclaimed."""
    user_id = uuid.uuid4()
    payload = {"slot_id": "slot-1"}
    req_hash = compute_request_hash(payload)

    existing_record = IdempotencyKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        request_hash=req_hash,
        status="in_progress",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC) - timedelta(seconds=300),  # Stale: 5 minutes old
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = existing_record

    result = await claim_or_replay(
        session=mock_session,
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        payload=payload,
        in_progress_timeout_seconds=120,
    )

    assert result.is_replayed is False
    assert result.status == IdempotencyStatus.IN_PROGRESS
    assert mock_session.flush.called


@pytest.mark.asyncio
async def test_claim_or_replay_expired_key_resets_and_claims():
    """Verify an expired key is reset for a new operation claim."""
    user_id = uuid.uuid4()
    payload = {"slot_id": "slot-1"}
    req_hash = compute_request_hash(payload)

    existing_record = IdempotencyKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        request_hash=req_hash,
        status="completed",
        response_code=201,
        expires_at=datetime.now(UTC) - timedelta(minutes=10),  # Expired
        created_at=datetime.now(UTC) - timedelta(days=2),
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = existing_record

    result = await claim_or_replay(
        session=mock_session,
        user_id=user_id,
        key="idemp-key-1",
        operation="create_booking",
        payload={"slot_id": "new-slot-after-expiry"},
    )

    assert result.is_replayed is False
    assert result.status == IdempotencyStatus.IN_PROGRESS
    assert mock_session.flush.called


@pytest.mark.asyncio
async def test_record_success_and_failure_transitions():
    """Verify record_success transitions record to COMPLETED and record_failure to FAILED."""
    record_id = uuid.uuid4()
    record = IdempotencyKey(
        id=record_id,
        user_id=uuid.uuid4(),
        key="key-1",
        operation="booking",
        request_hash="hash",
        status="in_progress",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = record

    # 1. Success transition
    res_id = uuid.uuid4()
    updated = await record_success(
        session=mock_session,
        record_id=record_id,
        response_code=201,
        response_body={"booking_id": str(res_id)},
        resource_id=res_id,
    )
    assert updated.status == "completed"
    assert updated.response_code == 201
    assert updated.resource_id == res_id

    # 2. Failure transition
    await record_failure(session=mock_session, record_id=record_id)
    assert record.status == "failed"


@pytest.mark.asyncio
async def test_cleanup_expired_keys_execution():
    """Verify cleanup_expired_keys executes delete query and returns row count."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_session.execute.return_value = mock_result

    deleted_count = await cleanup_expired_keys(session=mock_session)
    assert deleted_count == 5
    assert mock_session.execute.called
    assert mock_session.flush.called


# ==============================================================================
# 3. Live PostgreSQL Concurrency & Constraint Integration Tests
# ==============================================================================


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_idempotency_single_transaction_lifecycle():
    """Verify full idempotency lifecycle within a single database transaction on PostgreSQL."""
    suffix = uuid.uuid4().hex[:6]
    async for session in get_db_session():
        # 1. Setup authenticated user
        u = User(
            id=uuid.uuid4(),
            email_normalized=f"idemp_{suffix}@amrutam.co.in",
            password_hash="placeholder_hash",
            role="patient",
        )
        session.add(u)
        await session.commit()

        key = f"idemp-key-{suffix}"
        operation = "test_write_operation"
        payload = {"booking_reference": "REF-12345", "amount_minor": 50000}

        # 2. First claim: should succeed as fresh claim
        res1 = await claim_or_replay(
            session=session,
            user_id=u.id,
            key=key,
            operation=operation,
            payload=payload,
        )
        assert res1.is_replayed is False
        assert res1.status == IdempotencyStatus.IN_PROGRESS
        assert res1.idempotency_record_id is not None

        # 3. Complete the operation in the same transaction
        resource_id = uuid.uuid4()
        await record_success(
            session=session,
            record_id=res1.idempotency_record_id,
            response_code=201,
            response_body={"resource_id": str(resource_id), "status": "confirmed"},
            resource_id=resource_id,
        )
        await session.commit()

        # 4. Repeated request with identical key and payload: must replay outcome
        res2 = await claim_or_replay(
            session=session,
            user_id=u.id,
            key=key,
            operation=operation,
            payload=payload,
        )
        assert res2.is_replayed is True
        assert res2.status == IdempotencyStatus.COMPLETED
        assert res2.response_code == 201
        assert res2.resource_id == resource_id
        assert res2.response_body["status"] == "confirmed"

        # 5. Repeated request with same key but mutated payload: must conflict (HTTP 409)
        with pytest.raises(ConflictError) as exc:
            await claim_or_replay(
                session=session,
                user_id=u.id,
                key=key,
                operation=operation,
                payload={"booking_reference": "DIFFERENT-REF", "amount_minor": 50000},
            )
        assert exc.value.code == "IDEMPOTENCY_PAYLOAD_MISMATCH"
        break


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_idempotency_actor_and_operation_scoping():
    """Verify identical keys do not collide when scoped to different actors or operations."""
    suffix = uuid.uuid4().hex[:6]
    async for session in get_db_session():
        # Setup two distinct users
        u1 = User(
            id=uuid.uuid4(),
            email_normalized=f"actor1_{suffix}@amrutam.co.in",
            password_hash="placeholder_hash",
            role="patient",
        )
        u2 = User(
            id=uuid.uuid4(),
            email_normalized=f"actor2_{suffix}@amrutam.co.in",
            password_hash="placeholder_hash",
            role="patient",
        )
        session.add_all([u1, u2])
        await session.commit()

        shared_key = f"shared-key-{suffix}"
        payload = {"data": "test"}

        # Actor 1 claims key on operation A
        res_a1 = await claim_or_replay(session, u1.id, shared_key, "op_a", payload)
        await record_success(session, res_a1.idempotency_record_id, 200, {"actor": 1})
        await session.commit()

        # Actor 2 claims SAME key on operation A: must NOT collide
        res_a2 = await claim_or_replay(session, u2.id, shared_key, "op_a", payload)
        await record_success(session, res_a2.idempotency_record_id, 200, {"actor": 2})
        await session.commit()

        # Actor 1 claims SAME key on operation B: must NOT collide
        res_b1 = await claim_or_replay(session, u1.id, shared_key, "op_b", payload)
        await record_success(session, res_b1.idempotency_record_id, 200, {"actor": 1, "op": "b"})
        await session.commit()

        assert res_a1.idempotency_record_id != res_a2.idempotency_record_id
        assert res_a1.idempotency_record_id != res_b1.idempotency_record_id
        break


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_concurrent_same_key_race_handling():
    """Verify concurrent same-key requests against PostgreSQL do not crash with generic 500s.

    Spawns multiple simultaneous tasks attempting to claim the identical key and payload.
    Exactly one task should win the claim, while concurrent racers are safely handled via
    savepoints and unique constraints without generic errors or duplicate rows.
    """
    suffix = uuid.uuid4().hex[:6]
    user_id = uuid.uuid4()
    key = f"concurrent-race-{suffix}"
    operation = "concurrent_booking"
    payload = {"slot": "slot-999"}

    # 1. Create user
    async for session in get_db_session():
        u = User(
            id=user_id,
            email_normalized=f"concurrent_{suffix}@amrutam.co.in",
            password_hash="placeholder_hash",
            role="patient",
        )
        session.add(u)
        await session.commit()
        break

    # 2. Worker coroutine attempting claim and simulated write
    async def worker(task_idx: int) -> dict[str, str]:
        async for session in get_db_session():
            try:
                res = await claim_or_replay(
                    session=session,
                    user_id=user_id,
                    key=key,
                    operation=operation,
                    payload=payload,
                )
                if not res.is_replayed:
                    # Winner: simulate write and commit
                    await asyncio.sleep(0.05)  # Slight hold to force overlap
                    await record_success(
                        session=session,
                        record_id=res.idempotency_record_id,
                        response_code=201,
                        response_body={"winner": task_idx},
                    )
                    await session.commit()
                    return {"task": str(task_idx), "status": "won_claim"}
                else:
                    return {"task": str(task_idx), "status": "replayed"}
            except ConflictError as e:
                return {"task": str(task_idx), "status": f"conflict_{e.code}"}
            except Exception as e:
                return {"task": str(task_idx), "status": f"unexpected_{type(e).__name__}"}

    # 3. Run 6 simultaneous tasks racing to claim the identical key
    results = await asyncio.gather(*[worker(i) for i in range(6)])

    # 4. Verify outcomes:
    # - No unhandled or unexpected exceptions occurred
    statuses = [r["status"] for r in results]
    for s in statuses:
        assert not s.startswith("unexpected_"), f"Unexpected error occurred in worker: {s}"

    # - Exactly one task won the claim
    won_count = statuses.count("won_claim")
    assert won_count == 1, f"Expected exactly 1 claim winner, got {won_count}: {statuses}"

    # - All other tasks either received clean conflict or replayed
    for s in statuses:
        assert s in {"won_claim", "replayed", "conflict_IDEMPOTENCY_CONCURRENT_REQUEST"}

    # 5. Verify database invariant: exactly ONE row exists in idempotency_keys
    async for session in get_db_session():
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key,
            IdempotencyKey.operation == operation,
        )
        records = (await session.scalars(stmt)).all()
        assert len(records) == 1
        assert records[0].status == "completed"
        break
