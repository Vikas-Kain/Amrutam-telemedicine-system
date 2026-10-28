"""Concurrency, row locking, and race condition test suite (Layer 5).

All tests in this suite run against live PostgreSQL using independent database sessions.
In-memory SQLite is strictly prohibited for these tests because it does not model PostgreSQL's
row-level locking (SELECT FOR UPDATE), transaction isolation levels, or partial unique indexes.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.errors import ConflictError
from app.db.session import get_session_factory
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.payment import Payment
from app.models.user import Profile, User
from app.schemas.booking import BookingCreateRequest
from app.schemas.consultation import ConsultationStatus
from app.schemas.payment import WebhookEventPayload
from app.services.booking_service import cancel_booking, create_booking
from app.services.consultation_service import transition_consultation
from app.services.payment_provider import MockPaymentProviderAdapter
from app.services.payment_service import process_provider_webhook
from sqlalchemy import select

from tests.conftest import is_postgres_available

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(
        not is_postgres_available(),
        reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
    ),
]


async def _setup_doctor_and_slot(
    session_factory, suffix: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper to provision a verified doctor and a single available slot in PostgreSQL."""
    doctor_user_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    now = datetime.now(UTC)

    async with session_factory() as session:
        user = User(
            id=doctor_user_id,
            email_normalized=f"concurr_doc_{suffix}@example.test",
            password_hash="placeholder_argon2id",
            role="doctor",
            is_active=True,
        )
        profile = Profile(
            user_id=doctor_user_id,
            full_name=f"Dr. Concurrency {suffix}",
        )
        doctor = Doctor(
            id=doctor_id,
            user_id=doctor_user_id,
            specialization="Kayachikitsa",
            license_number=f"LIC-CONC-{suffix}",
            is_verified=True,
            consultation_fee_minor=2000,
            currency="INR",
        )
        slot = AvailabilitySlot(
            id=slot_id,
            doctor_id=doctor_id,
            start_at=now + timedelta(days=2),
            end_at=now + timedelta(days=2, minutes=30),
            status="available",
        )
        session.add_all([user, profile, doctor, slot])
        await session.commit()

    return doctor_user_id, doctor_id, slot_id


async def _setup_patients(session_factory, count: int, suffix: str) -> list[uuid.UUID]:
    """Helper to provision N distinct patient accounts in PostgreSQL."""
    patient_ids = []
    async with session_factory() as session:
        for i in range(count):
            p_id = uuid.uuid4()
            patient_ids.append(p_id)
            user = User(
                id=p_id,
                email_normalized=f"concurr_pat_{i}_{suffix}@example.test",
                password_hash="placeholder_argon2id",
                role="patient",
                is_active=True,
            )
            profile = Profile(
                user_id=p_id,
                full_name=f"Patient {i} {suffix}",
            )
            session.add_all([user, profile])
        await session.commit()
    return patient_ids


# ==============================================================================
# 1. High-Contention Booking Race (5 Parallel Clients, Exactly 1 Winner)
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_competing_bookings_single_winner() -> None:
    """Verify 5 concurrent requests for the identical slot yield exactly 1 booking.

    Independent PostgreSQL sessions execute concurrently. Row-level locks (SELECT FOR UPDATE)
    and partial unique index (uq_consultations_active_slot) guarantee zero double-booking.
    4 requests fail with ConflictError; 1 succeeds with HTTP 201 Created.
    """
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:8]

    _, doctor_id, slot_id = await _setup_doctor_and_slot(factory, suffix)
    patient_ids = await _setup_patients(factory, count=5, suffix=suffix)

    async def attempt_booking(patient_id: uuid.UUID) -> str:
        async with factory() as session:
            patient = await session.get(User, patient_id)
            assert patient is not None
            try:
                result = await create_booking(
                    session=session,
                    patient=patient,
                    payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot_id),
                    idempotency_key=f"race-{patient_id}-{suffix}",
                )
                await session.commit()
                return "created" if not result.is_replayed else "replayed"
            except ConflictError:
                await session.rollback()
                return "conflict"

    # Launch all 5 booking attempts concurrently
    results = await asyncio.gather(*(attempt_booking(pid) for pid in patient_ids))

    # Assert exactly 1 winner and exactly 4 conflicts
    assert results.count("created") == 1
    assert results.count("conflict") == 4
    assert sorted(results) == ["conflict", "conflict", "conflict", "conflict", "created"]

    # Invariants verification in PostgreSQL
    async with factory() as session:
        consultations = (
            await session.scalars(select(Consultation).where(Consultation.slot_id == slot_id))
        ).all()
        slot = await session.get(AvailabilitySlot, slot_id)
        outbox_events = (
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "booking.created",
                    OutboxEvent.aggregate_id.in_([c.id for c in consultations]),
                )
            )
        ).all()

        assert len(consultations) == 1, "Must have exactly 1 consultation row"
        assert consultations[0].status == "booked"
        assert slot is not None and slot.status == "booked"
        assert len(outbox_events) == 1, "Must emit exactly 1 booking.created outbox event"


# ==============================================================================
# 2. Concurrent Booking vs Cancellation / Re-booking Race
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_booking_and_cancellation_race() -> None:
    """Verify concurrent cancellation and rebooking attempts maintain data integrity.

    Patient 1 cancels their existing booking while Patient 2 concurrently attempts
    to book the same slot. Either:
      - Cancellation completes first -> Patient 2 succeeds in booking ("created").
      - Booking attempts before cancellation commits -> Patient 2 receives "conflict".
    In neither case do two active bookings ever coexist in PostgreSQL.
    """
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:8]

    _, doctor_id, slot_id = await _setup_doctor_and_slot(factory, suffix)
    patients = await _setup_patients(factory, count=2, suffix=suffix)
    patient_1_id, patient_2_id = patients[0], patients[1]

    # Pre-book slot for Patient 1
    booking_id = uuid.uuid4()
    async with factory() as session:
        slot = await session.get(AvailabilitySlot, slot_id)
        assert slot is not None
        slot.status = "booked"
        consultation = Consultation(
            id=booking_id,
            patient_id=patient_1_id,
            doctor_id=doctor_id,
            slot_id=slot_id,
            status="booked",
        )
        session.add(consultation)
        await session.commit()

    async def do_cancellation() -> str:
        async with factory() as session:
            p1 = await session.get(User, patient_1_id)
            assert p1 is not None
            try:
                await cancel_booking(
                    session=session,
                    booking_id=booking_id,
                    current_user=p1,
                    idempotency_key=f"cancel-race-{suffix}",
                )
                await session.commit()
                return "cancelled"
            except Exception as exc:
                await session.rollback()
                return f"cancel_err_{type(exc).__name__}"

    async def do_competing_booking() -> str:
        async with factory() as session:
            p2 = await session.get(User, patient_2_id)
            assert p2 is not None
            try:
                await create_booking(
                    session=session,
                    patient=p2,
                    payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot_id),
                    idempotency_key=f"rebook-race-{suffix}",
                )
                await session.commit()
                return "booked"
            except ConflictError:
                await session.rollback()
                return "conflict"

    cancellation_result, booking_result = await asyncio.gather(
        do_cancellation(),
        do_competing_booking(),
    )

    assert cancellation_result == "cancelled"
    assert booking_result in ("booked", "conflict")

    # Invariants verification in PostgreSQL
    async with factory() as session:
        active_consultations = (
            await session.scalars(
                select(Consultation).where(
                    Consultation.slot_id == slot_id,
                    Consultation.status == "booked",
                )
            )
        ).all()
        slot = await session.get(AvailabilitySlot, slot_id)
        assert slot is not None

        if booking_result == "booked":
            # Rebooking succeeded: exactly 1 active consultation (Patient 2)
            assert len(active_consultations) == 1
            assert active_consultations[0].patient_id == patient_2_id
            assert slot.status == "booked"
        else:
            # Rebooking failed due to conflict: slot is available or 0 active bookings
            assert len(active_consultations) == 0
            assert slot.status == "available"


# ==============================================================================
# 3. Concurrent Consultation State Machine Transitions
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_state_transitions_on_same_consultation() -> None:
    """Verify 2 concurrent requests to advance consultation state handle row locks safely.

    Consultation is in 'booked' state. Two independent tasks call transition_consultation
    to 'confirmed' concurrently. Exactly 1 successfully transitions; the other fails
    with ConflictError because the predecessor state is no longer 'booked'.
    """
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:8]

    doctor_user_id, doctor_id, slot_id = await _setup_doctor_and_slot(factory, suffix)
    patients = await _setup_patients(factory, count=1, suffix=suffix)
    patient_id = patients[0]

    consultation_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            Consultation(
                id=consultation_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                slot_id=slot_id,
                status="booked",
            )
        )
        await session.commit()

    async def advance_to_confirmed() -> str:
        async with factory() as session:
            doctor_user = await session.get(User, doctor_user_id)
            assert doctor_user is not None
            try:
                await transition_consultation(
                    session=session,
                    consultation_id=consultation_id,
                    target_status=ConsultationStatus.CONFIRMED,
                    current_user=doctor_user,
                )
                await session.commit()
                return "confirmed"
            except ConflictError:
                await session.rollback()
                return "conflict"

    results = await asyncio.gather(
        advance_to_confirmed(),
        advance_to_confirmed(),
    )

    assert results.count("confirmed") == 1
    assert results.count("conflict") == 1

    # Verify state in PostgreSQL
    async with factory() as session:
        db_consultation = await session.get(Consultation, consultation_id)
        assert db_consultation is not None
        assert db_consultation.status == "confirmed"

        outbox_events = (
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == consultation_id,
                    OutboxEvent.event_type == "consultation.confirmed",
                )
            )
        ).all()
        assert len(outbox_events) == 1, "Must emit exactly 1 outbox event for confirmed state"


# ==============================================================================
# 4. Concurrent Webhook Processing Race
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_payment_webhook_processing_race() -> None:
    """Verify simultaneous duplicate webhook arrivals execute transition exactly once.

    Two concurrent tasks dispatch identical provider webhook events for the same payment.
    Row-level locking serializes execution: one processes the transition, while the other
    detects status already updated and acknowledges idempotently.
    """
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:8]

    _, doctor_id, slot_id = await _setup_doctor_and_slot(factory, suffix)
    patients = await _setup_patients(factory, count=1, suffix=suffix)
    patient_id = patients[0]

    consultation_id = uuid.uuid4()
    payment_id = uuid.uuid4()
    provider_ref = f"pay_conc_{suffix}"

    async with factory() as session:
        consultation = Consultation(
            id=consultation_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            slot_id=slot_id,
            status="confirmed",
        )
        payment = Payment(
            id=payment_id,
            consultation_id=consultation_id,
            amount_minor=2000,
            currency="INR",
            status="pending",
            provider="mock_provider",
            provider_reference=provider_ref,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add_all([consultation, payment])
        await session.commit()

    webhook_payload = WebhookEventPayload(
        event_id=f"evt_race_{suffix}",
        event_type="payment.succeeded",
        provider_reference=provider_ref,
    )
    raw_body = json.dumps(webhook_payload.model_dump(mode="json")).encode("utf-8")
    sig = MockPaymentProviderAdapter.generate_signature(
        raw_body, MockPaymentProviderAdapter.DEFAULT_SECRET
    )

    async def deliver_webhook() -> str:
        async with factory() as session:
            try:
                res = await process_provider_webhook(
                    session=session,
                    provider="mock_provider",
                    payload_bytes=raw_body,
                    signature_header=sig,
                    payload=webhook_payload,
                )
                await session.commit()
                return res.get("status", "unknown")
            except Exception as exc:
                await session.rollback()
                return f"error_{type(exc).__name__}"

    results = await asyncio.gather(deliver_webhook(), deliver_webhook())

    # One processes the transition, the other returns already_processed
    assert "processed" in results
    assert "already_processed" in results

    # Verify final payment state in PostgreSQL
    async with factory() as session:
        db_payment = await session.get(Payment, payment_id)
        assert db_payment is not None
        assert db_payment.status == "succeeded"

        events = (
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == payment_id,
                    OutboxEvent.event_type == "payment.succeeded",
                )
            )
        ).all()
        assert len(events) == 1, "Must emit payment.succeeded outbox event exactly once"
