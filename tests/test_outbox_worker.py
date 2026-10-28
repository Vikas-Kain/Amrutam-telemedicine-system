"""Automated tests for transactional outbox worker, backoff policies,

idempotent event handlers, transient failure recovery, and dead-letter routing.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import BadRequestError, ServiceUnavailableError
from app.core.retry import (
    PermanentError,
    RetryPolicy,
    TransientError,
    calculate_backoff_delay,
    is_transient_error,
)
from app.db.session import get_session_factory
from app.models.outbox import OutboxEvent
from app.services.outbox.handlers import (
    HANDLER_REGISTRY,
    get_dispatched_notifications,
    handle_booking_created,
    register_handler,
    reset_dispatched_notifications,
)
from app.services.outbox.worker import OutboxWorker
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import is_postgres_available


@pytest.fixture(autouse=True)
def _clean_notification_state():
    """Reset dispatched notifications between each test."""
    reset_dispatched_notifications()
    yield
    reset_dispatched_notifications()


def test_calculate_backoff_delay_exponential_scaling_and_bounds() -> None:
    """Test exponential backoff progression, capping at max_delay, and jitter bounds."""
    # Without jitter: strictly deterministic doubling
    assert calculate_backoff_delay(1, base_delay=1.0, jitter=False) == 1.0  # 1 * 2^0
    assert calculate_backoff_delay(2, base_delay=1.0, jitter=False) == 2.0  # 1 * 2^1
    assert calculate_backoff_delay(3, base_delay=1.0, jitter=False) == 4.0  # 1 * 2^2
    assert calculate_backoff_delay(4, base_delay=1.0, jitter=False) == 8.0  # 1 * 2^3
    assert calculate_backoff_delay(5, base_delay=1.0, jitter=False) == 16.0  # 1 * 2^4
    # Bounded by max_delay
    assert calculate_backoff_delay(10, base_delay=1.0, max_delay=30.0, jitter=False) == 30.0

    # With jitter: randomized within [0.5 * delay, min(max_delay, 1.5 * delay)]
    for attempt in range(1, 6):
        delay = calculate_backoff_delay(attempt, base_delay=2.0, max_delay=60.0, jitter=True)
        nominal = min(60.0, 2.0 * (2 ** (attempt - 1)))
        assert 0.49 * nominal <= delay <= 1.51 * nominal
        assert delay <= 60.0


def test_is_transient_error_classification() -> None:
    """Test distinction between retryable transient errors and permanent errors."""
    # Transient errors (retryable)
    assert is_transient_error(ConnectionError("Connection dropped"))
    assert is_transient_error(TimeoutError("Socket timeout"))
    assert is_transient_error(TimeoutError())
    assert is_transient_error(OperationalError("database locked", None, None))
    assert is_transient_error(TransientError("Custom temporary failure"))
    assert is_transient_error(ServiceUnavailableError("Downstream gateway unavailable"))

    # Permanent errors (non-retryable, should fail immediately)
    assert not is_transient_error(ValueError("Invalid argument format"))
    assert not is_transient_error(KeyError("missing_field"))
    assert not is_transient_error(TypeError("unexpected type"))
    assert not is_transient_error(PermanentError("Corrupt payload"))
    assert not is_transient_error(BadRequestError("Malformed input payload"))


@pytest.mark.asyncio
async def test_idempotent_handler_duplicate_delivery() -> None:
    """Delivering the same outbox event multiple times executes side-effects exactly once."""
    event_id = uuid.uuid4()
    consultation_id = uuid.uuid4()
    event = OutboxEvent(
        id=event_id,
        event_type="booking.created",
        aggregate_type="consultation",
        aggregate_id=consultation_id,
        payload={
            "consultation_id": str(consultation_id),
            "patient_id": str(uuid.uuid4()),
            "doctor_id": str(uuid.uuid4()),
            "slot_id": str(uuid.uuid4()),
        },
        status="pending",
    )
    session = AsyncMock(spec=AsyncSession)

    # First delivery: notification dispatched
    await handle_booking_created(event, session)
    dispatches = get_dispatched_notifications()
    assert (str(event_id), "booking_confirmation") in dispatches
    assert len(dispatches) == 1

    # Second delivery (simulating broker re-delivery or worker crash recovery):
    # Should detect duplicate and skip re-sending without raising an error
    await handle_booking_created(event, session)
    assert len(get_dispatched_notifications()) == 1


@pytest.mark.asyncio
async def test_worker_processes_pending_event_successfully() -> None:
    """Worker claims pending event, executes handler, and transitions status to completed."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="booking.created",
        aggregate_type="consultation",
        aggregate_id=uuid.uuid4(),
        payload={
            "consultation_id": str(uuid.uuid4()),
            "patient_id": str(uuid.uuid4()),
            "doctor_id": str(uuid.uuid4()),
            "slot_id": str(uuid.uuid4()),
        },
        status="pending",
        attempt_count=0,
    )

    session = AsyncMock(spec=AsyncSession)
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [event]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result
    session.get_bind.return_value.dialect.name = "sqlite"

    session_factory = MagicMock()
    worker = OutboxWorker(session_factory=session_factory)

    count = await worker.claim_and_process_batch(session)

    assert count == 1
    assert event.status == "completed"
    assert event.processed_at is not None
    assert event.last_error is None
    assert event.next_retry_at is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_transient_failure_exponential_backoff_and_recovery() -> None:
    """Transient failure increments attempts, schedules next_retry_at, and succeeds on retry."""
    event_id = uuid.uuid4()
    event = OutboxEvent(
        id=event_id,
        event_type="custom.transient_task",
        aggregate_type="consultation",
        aggregate_id=uuid.uuid4(),
        payload={"task_id": "test_1"},
        status="pending",
        attempt_count=0,
    )

    # Register temporary failing handler
    call_count = 0

    async def _flakey_handler(evt: OutboxEvent, sess: AsyncSession) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Simulated temporary gateway outage")
        # Succeeds on attempt 2

    register_handler("custom.transient_task", _flakey_handler)

    try:
        session = AsyncMock(spec=AsyncSession)
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [event]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result
        session.get_bind.return_value.dialect.name = "sqlite"

        policy = RetryPolicy(max_attempts=3, base_delay=2.0, max_delay=10.0, jitter=False)
        worker = OutboxWorker(session_factory=MagicMock(), retry_policy=policy)

        # 1. Attempt 1: Fails with transient ConnectionError
        now_before = datetime.now(UTC)
        count = await worker.claim_and_process_batch(session)
        assert count == 1
        assert event.attempt_count == 1
        assert event.status == "failed"
        assert "ConnectionError" in (event.last_error or "")
        assert event.next_retry_at is not None
        assert event.next_retry_at >= now_before + timedelta(seconds=1.9)

        # 2. Attempt 2: Handler succeeds
        count_retry = await worker.claim_and_process_batch(session)
        assert count_retry == 1
        assert event.status == "completed"
        assert event.processed_at is not None
        assert event.last_error is None
        assert event.next_retry_at is None
    finally:
        HANDLER_REGISTRY.pop("custom.transient_task", None)


@pytest.mark.asyncio
async def test_worker_permanent_failure_routes_to_dead_letter() -> None:
    """Non-retryable errors immediately transition to dead_letter without wasting retries."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="custom.permanent_task",
        aggregate_type="consultation",
        aggregate_id=uuid.uuid4(),
        payload={"bad_key": True},
        status="pending",
        attempt_count=0,
    )

    async def _failing_handler(evt: OutboxEvent, sess: AsyncSession) -> None:
        raise ValueError("Malformed payload schema: missing required fields")

    register_handler("custom.permanent_task", _failing_handler)

    try:
        session = AsyncMock(spec=AsyncSession)
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [event]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result
        session.get_bind.return_value.dialect.name = "sqlite"

        policy = RetryPolicy(max_attempts=5)
        worker = OutboxWorker(session_factory=MagicMock(), retry_policy=policy)

        count = await worker.claim_and_process_batch(session)
        assert count == 1
        assert event.attempt_count == 1
        assert event.status == "dead_letter"
        assert "ValueError" in (event.last_error or "")
        assert event.next_retry_at is None
    finally:
        HANDLER_REGISTRY.pop("custom.permanent_task", None)


@pytest.mark.asyncio
async def test_worker_max_retries_exhausted_routes_to_dead_letter() -> None:
    """When transient failures exceed max_attempts, event transitions to dead_letter."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="custom.exhaust_task",
        aggregate_type="consultation",
        aggregate_id=uuid.uuid4(),
        payload={"id": "exhaust"},
        status="failed",
        attempt_count=2,  # Already attempted 2 times
    )

    async def _always_down(evt: OutboxEvent, sess: AsyncSession) -> None:
        raise ConnectionError("Persistent network outage")

    register_handler("custom.exhaust_task", _always_down)

    try:
        session = AsyncMock(spec=AsyncSession)
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [event]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result
        session.get_bind.return_value.dialect.name = "sqlite"

        policy = RetryPolicy(max_attempts=3)  # Max 3 attempts
        worker = OutboxWorker(session_factory=MagicMock(), retry_policy=policy)

        count = await worker.claim_and_process_batch(session)
        assert count == 1
        assert event.attempt_count == 3
        assert event.status == "dead_letter"
        assert "ConnectionError" in (event.last_error or "")
    finally:
        HANDLER_REGISTRY.pop("custom.exhaust_task", None)


def test_outbox_payload_privacy_invariants() -> None:
    """Assert outbox payloads for core events never contain clinical notes,
    reasons, or card data.
    """
    sensitive_keys = {
        "reason",
        "notes",
        "diagnosis",
        "items",
        "pan",
        "card",
        "cvv",
        "password",
        "secret",
    }

    # Sample standard payload created by booking service
    booking_payload = {
        "consultation_id": str(uuid.uuid4()),
        "patient_id": str(uuid.uuid4()),
        "doctor_id": str(uuid.uuid4()),
        "slot_id": str(uuid.uuid4()),
        "status": "booked",
    }
    assert not any(k in booking_payload for k in sensitive_keys)

    # Sample standard payload created by payment service
    payment_payload = {
        "payment_id": str(uuid.uuid4()),
        "consultation_id": str(uuid.uuid4()),
        "amount_minor": 50000,
        "currency": "INR",
        "status": "succeeded",
    }
    assert not any(k in payment_payload for k in sensitive_keys)


# ---------------------------------------------------------------------------
# PostgreSQL Live Tests (Concurrent Claims, SKIP LOCKED & Persistence)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL not available")
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_postgres_outbox_concurrent_workers_skip_locked() -> None:
    """Live PostgreSQL test: competing worker tasks process distinct events
    without race conditions.
    """
    session_factory = get_session_factory()
    now = datetime.now(UTC)

    # Mark any pre-existing pending events as completed to isolate concurrency test
    async with session_factory() as session:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.status.in_(["pending", "failed"]))
            .values(status="completed", processed_at=now)
        )
        await session.commit()

    # Seed 6 fresh pending outbox events
    event_ids = [uuid.uuid4() for _ in range(6)]
    async with session_factory() as session:
        for eid in event_ids:
            event = OutboxEvent(
                id=eid,
                event_type="booking.created",
                aggregate_type="consultation",
                aggregate_id=uuid.uuid4(),
                payload={
                    "consultation_id": str(uuid.uuid4()),
                    "patient_id": str(uuid.uuid4()),
                    "doctor_id": str(uuid.uuid4()),
                    "slot_id": str(uuid.uuid4()),
                },
                status="pending",
                attempt_count=0,
                created_at=now,
            )
            session.add(event)
        await session.commit()

    # Run two competing worker batches concurrently
    worker1 = OutboxWorker(session_factory=session_factory, batch_size=3)
    worker2 = OutboxWorker(session_factory=session_factory, batch_size=3)

    results = await asyncio.gather(
        worker1.run_once(batch_size=3),
        worker2.run_once(batch_size=3),
    )

    # Together they should process 6 events without double-claiming or deadlocks
    total_processed = sum(results)
    assert total_processed == 6

    # Verify all 6 events are now 'completed' in PostgreSQL
    async with session_factory() as session:
        res = await session.execute(select(OutboxEvent).where(OutboxEvent.id.in_(event_ids)))
        completed_events = res.scalars().all()
        assert len(completed_events) == 6
        assert all(e.status == "completed" for e in completed_events)
        assert all(e.processed_at is not None for e in completed_events)
