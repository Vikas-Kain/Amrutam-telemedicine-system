"""Tests for atomic, idempotent appointment booking."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.errors import ConflictError, ForbiddenError
from app.core.security import create_access_token
from app.db.session import get_db_session, get_session_factory
from app.main import create_app
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.user import Profile, User
from app.schemas.booking import BookingCreateRequest, BookingResponse
from app.schemas.idempotency import IdempotencyResult, IdempotencyStatus
from app.services.booking_service import (
    BookingOperationResult,
    cancel_booking,
    create_booking,
    get_booking,
)
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


def _make_booking(
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    slot_id: uuid.UUID,
    status: str = "booked",
) -> Consultation:
    now = datetime.now(UTC)
    return Consultation(
        id=uuid.uuid4(),
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot_id=slot_id,
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


def _cancellation_claim_result() -> IdempotencyResult:
    return IdempotencyResult(
        is_replayed=False,
        key="cancellation-key",
        operation="cancel_booking",
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


@pytest.mark.asyncio
async def test_get_booking_allows_owner_assigned_doctor_and_admin():
    """Retrieval grants access only to the patient, assigned doctor, or administrator."""
    patient = _make_patient()
    doctor_user = User(
        id=uuid.uuid4(),
        email_normalized="assigned-doctor@example.com",
        password_hash="placeholder",
        role="doctor",
    )
    doctor_id = uuid.uuid4()
    booking = _make_booking(
        patient_id=patient.id,
        doctor_id=doctor_id,
        slot_id=uuid.uuid4(),
    )

    owner_session = AsyncMock()
    owner_session.scalar.return_value = booking
    assert (
        await get_booking(session=owner_session, booking_id=booking.id, current_user=patient)
    ).id == booking.id

    doctor_session = AsyncMock()
    doctor_session.scalar.side_effect = [booking, doctor_id]
    assert (
        await get_booking(session=doctor_session, booking_id=booking.id, current_user=doctor_user)
    ).id == booking.id

    admin = User(
        id=uuid.uuid4(),
        email_normalized="admin@example.com",
        password_hash="placeholder",
        role="admin",
    )
    admin_session = AsyncMock()
    admin_session.scalar.return_value = booking
    assert (
        await get_booking(session=admin_session, booking_id=booking.id, current_user=admin)
    ).id == booking.id


@pytest.mark.asyncio
async def test_get_booking_rejects_unrelated_patient():
    """A patient cannot read another patient's booking."""
    owner = _make_patient()
    other = User(
        id=uuid.uuid4(),
        email_normalized="other-patient@example.com",
        password_hash="placeholder",
        role="patient",
    )
    booking = _make_booking(
        patient_id=owner.id,
        doctor_id=uuid.uuid4(),
        slot_id=uuid.uuid4(),
    )
    session = AsyncMock()
    session.scalar.return_value = booking

    with pytest.raises(ForbiddenError) as error:
        await get_booking(session=session, booking_id=booking.id, current_user=other)

    assert error.value.code == "BOOKING_ACCESS_FORBIDDEN"


@pytest.mark.asyncio
async def test_cancel_booking_atomically_releases_slot_and_emits_safe_event():
    """Cancellation preserves history while returning the future slot to availability."""
    patient = _make_patient()
    doctor_id = uuid.uuid4()
    slot = _make_slot(doctor_id=doctor_id, status="booked")
    booking = _make_booking(patient_id=patient.id, doctor_id=doctor_id, slot_id=slot.id)
    added: list[object] = []
    completed: dict[str, object] = {}
    session = AsyncMock()
    session.scalar.side_effect = [booking, slot]
    session.begin_nested = MagicMock(return_value=_async_context_manager())
    session.add = MagicMock(side_effect=added.append)

    async def complete(**kwargs: object) -> None:
        completed.update(kwargs)

    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_cancellation_claim_result()),
        ),
        patch("app.services.booking_service.record_success", new=AsyncMock(side_effect=complete)),
    ):
        result = await cancel_booking(
            session=session,
            booking_id=booking.id,
            current_user=patient,
            idempotency_key="cancellation-key",
        )

    assert result.booking.status == "cancelled"
    assert booking.status == "cancelled"
    assert slot.status == "available"
    assert completed["response_code"] == 200
    event = next(item for item in added if isinstance(item, OutboxEvent))
    assert event.event_type == "booking.cancelled"
    assert "reason" not in event.payload


@pytest.mark.asyncio
async def test_cancel_booking_is_idempotent_when_already_cancelled():
    """A fresh retry against historical cancelled state remains a successful no-op."""
    patient = _make_patient()
    booking = _make_booking(
        patient_id=patient.id,
        doctor_id=uuid.uuid4(),
        slot_id=uuid.uuid4(),
        status="cancelled",
    )
    session = AsyncMock()
    session.scalar.return_value = booking
    completed: dict[str, object] = {}

    async def complete(**kwargs: object) -> None:
        completed.update(kwargs)

    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_cancellation_claim_result()),
        ),
        patch("app.services.booking_service.record_success", new=AsyncMock(side_effect=complete)),
    ):
        result = await cancel_booking(
            session=session,
            booking_id=booking.id,
            current_user=patient,
            idempotency_key="new-cancellation-key",
        )

    assert result.booking.status == "cancelled"
    assert completed["response_code"] == 200
    session.begin_nested.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_booking_rejects_another_patient_and_ineligible_state():
    """Only the owner/admin may cancel, and only the booked lifecycle state is eligible."""
    owner = _make_patient()
    other = User(
        id=uuid.uuid4(),
        email_normalized="other-canceller@example.com",
        password_hash="placeholder",
        role="patient",
    )
    booking = _make_booking(
        patient_id=owner.id,
        doctor_id=uuid.uuid4(),
        slot_id=uuid.uuid4(),
    )
    ownership_session = AsyncMock()
    ownership_session.scalar.return_value = booking
    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_cancellation_claim_result()),
        ),
        pytest.raises(ForbiddenError),
    ):
        await cancel_booking(
            session=ownership_session,
            booking_id=booking.id,
            current_user=other,
            idempotency_key="cancellation-key",
        )

    booking.status = "confirmed"
    state_session = AsyncMock()
    state_session.scalar.return_value = booking
    with (
        patch(
            "app.services.booking_service.claim_or_replay",
            new=AsyncMock(return_value=_cancellation_claim_result()),
        ),
        pytest.raises(ConflictError) as error,
    ):
        await cancel_booking(
            session=state_session,
            booking_id=booking.id,
            current_user=owner,
            idempotency_key="cancellation-key",
        )
    assert error.value.code == "BOOKING_CANCELLATION_NOT_ALLOWED"


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

    client = TestClient(app)
    with patch(
        "app.api.v1.endpoints.bookings.create_booking",
        new=AsyncMock(return_value=BookingOperationResult(booking=booking, is_replayed=True)),
    ):
        response = client.post(
            "/api/v1/bookings",
            json={"doctor_id": str(doctor_id), "slot_id": str(slot_id)},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "booking-key"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(booking.id)


def test_booking_retrieval_endpoint_uses_authenticated_access_policy():
    """GET booking is registered and delegates to the scoped retrieval service."""
    patient = _make_patient()
    doctor_id = uuid.uuid4()
    booking = _make_booking(patient_id=patient.id, doctor_id=doctor_id, slot_id=uuid.uuid4())
    session = AsyncMock()
    session.scalar.side_effect = [patient, booking]
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    token = create_access_token(subject=patient.id, role="patient")

    client = TestClient(app)
    response = client.get(
        f"/api/v1/bookings/{booking.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(booking.id)


def test_booking_cancellation_endpoint_requires_key_and_returns_cancelled_booking():
    """POST cancellation enforces idempotency and exposes a successful cancelled result."""
    patient = _make_patient()
    booking = _make_booking(
        patient_id=patient.id,
        doctor_id=uuid.uuid4(),
        slot_id=uuid.uuid4(),
        status="cancelled",
    )
    response_model = BookingResponse.model_validate(booking)
    session = AsyncMock()
    session.scalar.return_value = patient
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    token = create_access_token(subject=patient.id, role="patient")
    client = TestClient(app)

    missing_key = client.post(
        f"/api/v1/bookings/{booking.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing_key.status_code == 400

    with patch(
        "app.api.v1.endpoints.bookings.cancel_booking",
        new=AsyncMock(
            return_value=BookingOperationResult(booking=response_model, is_replayed=False)
        ),
    ):
        response = client.post(
            f"/api/v1/bookings/{booking.id}/cancel",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "cancel-key"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.concurrency
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


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_cancellation_preserves_history_and_allows_rebooking():
    """Cancelling is atomic, repeat-safe, and frees the partial unique active-slot constraint."""
    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    doctor_user_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    rebooking_patient_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    original_booking_id = uuid.uuid4()
    cancellation_key = f"cancel-{suffix}"

    async with factory() as session:
        session.add_all(
            [
                User(
                    id=doctor_user_id,
                    email_normalized=f"cancel_doc_{suffix}@example.test",
                    password_hash="placeholder",
                    role="doctor",
                ),
                User(
                    id=owner_id,
                    email_normalized=f"cancel_owner_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
                User(
                    id=rebooking_patient_id,
                    email_normalized=f"cancel_rebook_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
            ]
        )
        session.add(Profile(user_id=doctor_user_id, full_name="Cancellation Doctor"))
        session.add(
            Doctor(
                id=doctor_id,
                user_id=doctor_user_id,
                specialization="General Medicine",
                license_number=f"CANCEL-{suffix}",
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
                status="booked",
            )
        )
        session.add(
            Consultation(
                id=original_booking_id,
                patient_id=owner_id,
                doctor_id=doctor_id,
                slot_id=slot_id,
                status="booked",
            )
        )
        await session.commit()

    async with factory() as session:
        owner = await session.get(User, owner_id)
        assert owner is not None
        cancelled = await cancel_booking(
            session=session,
            booking_id=original_booking_id,
            current_user=owner,
            idempotency_key=cancellation_key,
        )
        assert cancelled.booking.status == "cancelled"
        await session.commit()

    async with factory() as session:
        owner = await session.get(User, owner_id)
        assert owner is not None
        replay = await cancel_booking(
            session=session,
            booking_id=original_booking_id,
            current_user=owner,
            idempotency_key=cancellation_key,
        )
        assert replay.is_replayed is True
        assert replay.booking.status == "cancelled"
        await session.rollback()

    async with factory() as session:
        rebooking_patient = await session.get(User, rebooking_patient_id)
        assert rebooking_patient is not None
        replacement = await create_booking(
            session=session,
            patient=rebooking_patient,
            payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot_id),
            idempotency_key=f"rebook-{suffix}",
        )
        assert replacement.booking.status == "booked"
        await session.commit()

    async with factory() as session:
        consultations = (
            await session.scalars(
                select(Consultation)
                .where(Consultation.slot_id == slot_id)
                .order_by(Consultation.created_at)
            )
        ).all()
        slot = await session.get(AvailabilitySlot, slot_id)
        cancellation_events = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.aggregate_id == original_booking_id,
                OutboxEvent.event_type == "booking.cancelled",
            )
        )
        assert [consultation.status for consultation in consultations] == ["cancelled", "booked"]
        assert slot is not None and slot.status == "booked"
        assert cancellation_events == 1
