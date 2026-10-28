"""Tests for atomic, idempotent appointment booking."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.errors import ConflictError
from app.core.security import create_access_token
from app.db.session import get_db_session, get_session_factory
from app.main import create_app
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.user import Profile, User
from app.schemas.booking import BookingCreateRequest, BookingResponse
from app.schemas.idempotency import IdempotencyResult, IdempotencyStatus
from app.services.booking_service import BookingOperationResult, create_booking
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.conftest import is_postgres_available


def _make_patient() -> User:
    return User(
        id=uuid.uuid4(),
        email_normalized="patient@example.com",
        password_hash="placeholder",
        role="patient",
        is_active=True,
    )


def _make_slot(*, doctor_id: uuid.UUID, status: str = "available") -> AvailabilitySlot:
    now = datetime.now(UTC)
    return AvailabilitySlot(
        id=uuid.uuid4(),
        doctor_id=doctor_id,
        start_at=now + timedelta(days=1),
        end_at=now + timedelta(days=1, minutes=30),
        status=status,
        created_at=now,
        updated_at=now,
    )


def _claim_result() -> IdempotencyResult:
    return IdempotencyResult(
        is_replayed=False,
        key="booking-key",
        operation="create_booking",
        status=IdempotencyStatus.IN_PROGRESS,
        idempotency_record_id=uuid.uuid4(),
    )


def _async_context_manager() -> MagicMock:
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock()
    context_manager.__aexit__ = AsyncMock(return_value=False)
    return context_manager


@pytest.mark.asyncio
async def test_create_booking_reserves_slot_persists_result_and_outbox_event():
    """A successful booking changes state and completes idempotency in one unit of work."""
    patient = _make_patient()
    doctor_id = uuid.uuid4()
    slot = _make_slot(doctor_id=doctor_id)
    request = BookingCreateRequest(doctor_id=doctor_id, slot_id=slot.id, reason="Follow-up")
    added: list[object] = []

    session = AsyncMock()
    session.scalar.return_value = slot
    session.begin_nested = MagicMock(return_value=_async_context_manager())
    session.add = MagicMock(side_effect=added.append)

    async def flush() -> None:
        for item in added:
            if isinstance(item, Consultation) and item.id is None:
                item.id = uuid.uuid4()
                item.created_at = datetime.now(UTC)
                item.updated_at = item.created_at

    session.flush.side_effect = flush
    completed: dict[str, object] = {}

    async def complete(**kwargs: object) -> None:
        completed.update(kwargs)

    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_claim_result()),
        ),
        patch("app.services.booking_service.record_success", new=AsyncMock(side_effect=complete)),
    ):
        result = await create_booking(
            session=session,
            patient=patient,
            payload=request,
            idempotency_key="booking-key",
        )

    assert result.is_replayed is False
    assert result.booking.status == "booked"
    assert result.booking.patient_id == patient.id
    assert slot.status == "booked"
    assert completed["response_code"] == 201
    assert completed["resource_id"] == result.booking.id
    outbox = next(item for item in added if isinstance(item, OutboxEvent))
    assert outbox.event_type == "booking.created"
    assert "reason" not in outbox.payload
    assert outbox.payload["consultation_id"] == str(result.booking.id)


@pytest.mark.asyncio
async def test_create_booking_replays_completed_response_without_locking_slot():
    """A matching completed key returns its recorded outcome rather than rebooking."""
    patient = _make_patient()
    booking_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    now = datetime.now(UTC)
    replay = IdempotencyResult(
        is_replayed=True,
        key="booking-key",
        operation="create_booking",
        status=IdempotencyStatus.COMPLETED,
        idempotency_record_id=uuid.uuid4(),
        resource_id=booking_id,
        response_code=201,
        response_body={
            "id": str(booking_id),
            "patient_id": str(patient.id),
            "doctor_id": str(doctor_id),
            "slot_id": str(slot_id),
            "status": "booked",
            "reason": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
    )
    session = AsyncMock()

    with patch("app.services.booking_service.claim_or_replay", new=AsyncMock(return_value=replay)):
        result = await create_booking(
            session=session,
            patient=patient,
            payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot_id),
            idempotency_key="booking-key",
        )

    assert result.is_replayed is True
    assert result.booking.id == booking_id
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_booking_rejects_slot_for_another_doctor():
    """The supplied doctor must own the requested slot before it can be booked."""
    patient = _make_patient()
    slot = _make_slot(doctor_id=uuid.uuid4())
    session = AsyncMock()
    session.scalar.return_value = slot

    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_claim_result()),
        ),
        pytest.raises(ConflictError) as error,
    ):
        await create_booking(
            session=session,
            patient=patient,
            payload=BookingCreateRequest(doctor_id=uuid.uuid4(), slot_id=slot.id),
            idempotency_key="booking-key",
        )

    assert error.value.code == "SLOT_DOCTOR_MISMATCH"


@pytest.mark.asyncio
async def test_create_booking_maps_active_slot_unique_violation_to_conflict():
    """The database-level double-booking defense returns a safe conflict response."""
    patient = _make_patient()
    doctor_id = uuid.uuid4()
    slot = _make_slot(doctor_id=doctor_id)
    session = AsyncMock()
    session.scalar.return_value = slot
    session.begin_nested = MagicMock(return_value=_async_context_manager())
    session.add = MagicMock()

    class DatabaseError(Exception):
        diag = type("Diagnostics", (), {"constraint_name": "uq_consultations_active_slot"})()

    session.flush.side_effect = IntegrityError("insert", {}, DatabaseError())

    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_claim_result()),
        ),
        pytest.raises(ConflictError) as error,
    ):
        await create_booking(
            session=session,
            patient=patient,
            payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot.id),
            idempotency_key="booking-key",
        )

    assert error.value.code == "SLOT_NOT_AVAILABLE"


def test_booking_schema_rejects_an_overlong_reason():
    """Patient-entered booking reasons are bounded before they reach persistence."""
    with pytest.raises(ValidationError):
        BookingCreateRequest(
            doctor_id=uuid.uuid4(),
            slot_id=uuid.uuid4(),
            reason="x" * 2_001,
        )


def test_booking_endpoint_requires_patient_and_idempotency_key():
    """The public endpoint denies non-patients and rejects a missing idempotency header."""
    doctor = User(
        id=uuid.uuid4(),
        email_normalized="doctor@example.com",
        password_hash="placeholder",
        role="doctor",
        is_active=True,
    )
    token = create_access_token(subject=doctor.id, role="doctor")
    session = AsyncMock()
    session.scalar.return_value = doctor
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    client = TestClient(app)

    response = client.post(
        "/api/v1/bookings",
        json={"doctor_id": str(uuid.uuid4()), "slot_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_booking_endpoint_rejects_a_patient_request_without_idempotency_key():
    """A patient must supply an idempotency key before a booking is evaluated."""
    patient = _make_patient()
    token = create_access_token(subject=patient.id, role="patient")
    session = AsyncMock()
    session.scalar.return_value = patient
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    client = TestClient(app)

    response = client.post(
        "/api/v1/bookings",
        json={"doctor_id": str(uuid.uuid4()), "slot_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"


def test_booking_endpoint_returns_200_for_a_replay():
    """A replay receives the original booking body with HTTP 200."""
    patient = _make_patient()
    doctor_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    now = datetime.now(UTC)
    booking = BookingResponse(
        id=uuid.uuid4(),
        patient_id=patient.id,
        doctor_id=doctor_id,
        slot_id=slot_id,
        status="booked",
        created_at=now,
        updated_at=now,
    )
    session = AsyncMock()
    session.scalar.return_value = patient
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    token = create_access_token(subject=patient.id, role="patient")

    with patch(
        "app.api.v1.endpoints.bookings.create_booking",
        new=AsyncMock(return_value=BookingOperationResult(booking=booking, is_replayed=True)),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/bookings",
            json={"doctor_id": str(doctor_id), "slot_id": str(slot_id)},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "booking-key"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(booking.id)


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_competing_patients_create_one_booking_and_one_outbox_event():
    """PostgreSQL locks and constraints allow only one of two competing bookings."""
    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    doctor_user_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    patient_a_id = uuid.uuid4()
    patient_b_id = uuid.uuid4()
    slot_id = uuid.uuid4()

    async with factory() as session:
        session.add_all(
            [
                User(
                    id=doctor_user_id,
                    email_normalized=f"booking_doc_{suffix}@example.test",
                    password_hash="placeholder",
                    role="doctor",
                ),
                User(
                    id=patient_a_id,
                    email_normalized=f"booking_patient_a_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
                User(
                    id=patient_b_id,
                    email_normalized=f"booking_patient_b_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
            ]
        )
        session.add(Profile(user_id=doctor_user_id, full_name="Booking Doctor"))
        session.add(
            Doctor(
                id=doctor_id,
                user_id=doctor_user_id,
                specialization="General Medicine",
                license_number=f"BOOK-{suffix}",
                is_verified=True,
                consultation_fee_minor=1_000,
            )
        )
        now = datetime.now(UTC)
        session.add(
            AvailabilitySlot(
                id=slot_id,
                doctor_id=doctor_id,
                start_at=now + timedelta(days=2),
                end_at=now + timedelta(days=2, minutes=30),
                status="available",
            )
        )
        await session.commit()

    async def attempt(patient_id: uuid.UUID, key: str) -> str:
        async with factory() as session:
            patient = await session.get(User, patient_id)
            assert patient is not None
            try:
                result = await create_booking(
                    session=session,
                    patient=patient,
                    payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot_id),
                    idempotency_key=key,
                )
                await asyncio.sleep(0.05)
                await session.commit()
                return "created" if not result.is_replayed else "replayed"
            except ConflictError:
                await session.rollback()
                return "conflict"

    outcomes = await asyncio.gather(
        attempt(patient_a_id, f"booking-a-{suffix}"),
        attempt(patient_b_id, f"booking-b-{suffix}"),
    )
    assert sorted(outcomes) == ["conflict", "created"]

    async with factory() as session:
        consultation_count = await session.scalar(
            select(func.count()).select_from(Consultation).where(Consultation.slot_id == slot_id)
        )
        event_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.aggregate_id.in_(
                    select(Consultation.id).where(Consultation.slot_id == slot_id)
                )
            )
        )
        slot = await session.get(AvailabilitySlot, slot_id)
        assert consultation_count == 1
        assert event_count == 1
        assert slot is not None and slot.status == "booked"
