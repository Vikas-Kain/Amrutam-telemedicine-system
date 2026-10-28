"""Automated tests for consultation lifecycle state machine and access control."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import create_access_token
from app.db.session import get_db_session, get_session_factory
from app.main import create_app
from app.models.audit import AuditLog
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.user import Profile, User
from app.schemas.booking import BookingResponse
from app.schemas.consultation import ConsultationStatus
from app.services.booking_service import BookingOperationResult
from app.services.consultation_service import (
    get_consultation,
    list_consultations,
    transition_consultation,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.conftest import is_postgres_available


def _make_user(*, role: str = "patient", is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email_normalized=f"{role}_{uuid.uuid4().hex[:6]}@example.com",
        password_hash="placeholder_hash",
        role=role,
        is_active=is_active,
    )


def _make_consultation(
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    slot_id: uuid.UUID | None = None,
    status: str = "booked",
) -> Consultation:
    now = datetime.now(UTC)
    return Consultation(
        id=uuid.uuid4(),
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot_id=slot_id or uuid.uuid4(),
        status=status,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_consultations_patient_scope():
    """A patient only receives their own consultations."""
    patient = _make_user(role="patient")
    other_patient = _make_user(role="patient")
    doctor_id = uuid.uuid4()

    c1 = _make_consultation(patient_id=patient.id, doctor_id=doctor_id)
    _make_consultation(patient_id=other_patient.id, doctor_id=doctor_id)

    session = AsyncMock()
    session.scalar.return_value = 1
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [c1]
    session.scalars.return_value = scalars_mock

    response = await list_consultations(session=session, current_user=patient)
    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].id == c1.id


@pytest.mark.asyncio
async def test_list_consultations_doctor_scope():
    """A doctor only receives consultations assigned to their clinical profile."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    c = _make_consultation(patient_id=patient_id, doctor_id=doctor_id)

    session = AsyncMock()
    # First scalar call resolves get_doctor_id_for_user, second call counts total
    session.scalar.side_effect = [doctor_id, 1]
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [c]
    session.scalars.return_value = scalars_mock

    response = await list_consultations(session=session, current_user=doctor_user)
    assert response.total == 1
    assert response.items[0].doctor_id == doctor_id


@pytest.mark.asyncio
async def test_list_consultations_admin_can_view_all_and_filter():
    """Administrators can list all consultations with optional filters."""
    admin_user = _make_user(role="admin")
    c = _make_consultation(patient_id=uuid.uuid4(), doctor_id=uuid.uuid4(), status="confirmed")

    session = AsyncMock()
    session.scalar.return_value = 1
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [c]
    session.scalars.return_value = scalars_mock

    response = await list_consultations(
        session=session,
        current_user=admin_user,
        status="confirmed",
    )
    assert response.total == 1
    assert response.items[0].status == "confirmed"


@pytest.mark.asyncio
async def test_list_consultations_rejects_invalid_status():
    """Supplying an unknown status filter returns HTTP 400 BadRequestError."""
    patient = _make_user(role="patient")
    session = AsyncMock()

    with pytest.raises(BadRequestError) as exc_info:
        await list_consultations(
            session=session,
            current_user=patient,
            status="non_existent_status",
        )
    assert exc_info.value.code == "INVALID_STATUS_FILTER"


@pytest.mark.asyncio
async def test_get_consultation_authorization():
    """Retrieval is authorized for patient owner, assigned doctor, and admin only."""
    patient = _make_user(role="patient")
    other_patient = _make_user(role="patient")
    doctor_user = _make_user(role="doctor")
    other_doctor_user = _make_user(role="doctor")
    admin = _make_user(role="admin")

    doctor_id = uuid.uuid4()
    other_doctor_id = uuid.uuid4()
    consultation = _make_consultation(patient_id=patient.id, doctor_id=doctor_id)

    session = AsyncMock()
    session.scalar.return_value = consultation

    # 1. Patient owner succeeds
    res_patient = await get_consultation(
        session=session, consultation_id=consultation.id, current_user=patient
    )
    assert res_patient.id == consultation.id

    # 2. Other patient is forbidden
    with pytest.raises(ForbiddenError) as exc_patient:
        await get_consultation(
            session=session, consultation_id=consultation.id, current_user=other_patient
        )
    assert exc_patient.value.code == "CONSULTATION_ACCESS_FORBIDDEN"

    # 3. Assigned doctor succeeds
    session.scalar.side_effect = [consultation, doctor_id]
    res_doctor = await get_consultation(
        session=session, consultation_id=consultation.id, current_user=doctor_user
    )
    assert res_doctor.id == consultation.id

    # 4. Other doctor is forbidden
    session.scalar.side_effect = [consultation, other_doctor_id]
    with pytest.raises(ForbiddenError) as exc_doc:
        await get_consultation(
            session=session, consultation_id=consultation.id, current_user=other_doctor_user
        )
    assert exc_doc.value.code == "CONSULTATION_ACCESS_FORBIDDEN"

    # 5. Admin succeeds
    session.scalar.side_effect = [consultation]
    res_admin = await get_consultation(
        session=session, consultation_id=consultation.id, current_user=admin
    )
    assert res_admin.id == consultation.id

    # 6. Not found returns 404
    session.scalar.side_effect = [None]
    with pytest.raises(NotFoundError) as exc_nf:
        await get_consultation(session=session, consultation_id=uuid.uuid4(), current_user=patient)
    assert exc_nf.value.code == "CONSULTATION_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_status", "target_status", "actor_role", "is_admin"),
    [
        ("booked", ConsultationStatus.CONFIRMED, "doctor", False),
        ("booked", ConsultationStatus.CONFIRMED, "admin", True),
        ("confirmed", ConsultationStatus.IN_PROGRESS, "doctor", False),
        ("in_progress", ConsultationStatus.COMPLETED, "doctor", False),
        ("confirmed", ConsultationStatus.NO_SHOW, "doctor", False),
        ("confirmed", ConsultationStatus.NO_SHOW, "admin", True),
    ],
)
async def test_allowed_lifecycle_transitions(start_status, target_status, actor_role, is_admin):
    """Every allowed state transition succeeds and records audit/outbox events."""
    actor = _make_user(role=actor_role)
    doctor_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=uuid.uuid4(), doctor_id=doctor_id, status=start_status
    )

    added_items: list[object] = []
    session = AsyncMock()
    # First scalar: select consultation with_for_update, second scalar: doctor_id if doctor
    if is_admin:
        session.scalar.side_effect = [consultation]
    else:
        session.scalar.side_effect = [consultation, doctor_id]
    session.add = MagicMock(side_effect=added_items.append)

    res = await transition_consultation(
        session=session,
        consultation_id=consultation.id,
        target_status=target_status,
        current_user=actor,
    )

    assert res.status == target_status.value
    assert consultation.status == target_status.value

    # Verify AuditLog and OutboxEvent were enqueued
    audit_events = [x for x in added_items if isinstance(x, AuditLog)]
    outbox_events = [x for x in added_items if isinstance(x, OutboxEvent)]
    assert len(audit_events) == 1
    assert len(outbox_events) == 1
    assert audit_events[0].metadata_["to_status"] == target_status.value
    assert outbox_events[0].payload["to_status"] == target_status.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_status", "invalid_target"),
    [
        ("booked", ConsultationStatus.IN_PROGRESS),
        ("booked", ConsultationStatus.COMPLETED),
        ("booked", ConsultationStatus.NO_SHOW),
        ("confirmed", ConsultationStatus.COMPLETED),
        ("in_progress", ConsultationStatus.CONFIRMED),
        ("in_progress", ConsultationStatus.NO_SHOW),
        ("completed", ConsultationStatus.IN_PROGRESS),
        ("completed", ConsultationStatus.CONFIRMED),
        ("cancelled", ConsultationStatus.CONFIRMED),
        ("no_show", ConsultationStatus.CONFIRMED),
    ],
)
async def test_disallowed_lifecycle_transitions_raise_conflict(current_status, invalid_target):
    """Illegal transitions raise 409 ConflictError without mutating state."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=uuid.uuid4(), doctor_id=doctor_id, status=current_status
    )

    session = AsyncMock()
    session.scalar.side_effect = [consultation, doctor_id]

    with pytest.raises(ConflictError) as exc_info:
        await transition_consultation(
            session=session,
            consultation_id=consultation.id,
            target_status=invalid_target,
            current_user=doctor_user,
        )
    assert exc_info.value.code == "CONSULTATION_INVALID_TRANSITION"
    assert consultation.status == current_status


@pytest.mark.asyncio
async def test_unassigned_doctor_cannot_transition_consultation():
    """A doctor who is not assigned to the consultation cannot transition its status."""
    doctor_user = _make_user(role="doctor")
    assigned_doctor_id = uuid.uuid4()
    calling_doctor_id = uuid.uuid4()

    consultation = _make_consultation(
        patient_id=uuid.uuid4(), doctor_id=assigned_doctor_id, status="booked"
    )

    session = AsyncMock()
    session.scalar.side_effect = [consultation, calling_doctor_id]

    with pytest.raises(ForbiddenError) as exc_info:
        await transition_consultation(
            session=session,
            consultation_id=consultation.id,
            target_status=ConsultationStatus.CONFIRMED,
            current_user=doctor_user,
        )
    assert exc_info.value.code == "CONSULTATION_NOT_ASSIGNED_DOCTOR"


@pytest.mark.asyncio
async def test_patient_cannot_execute_doctor_status_transitions():
    """A patient caller is forbidden from invoking clinical status transitions."""
    patient = _make_user(role="patient")
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=uuid.uuid4(), status="booked"
    )

    session = AsyncMock()
    session.scalar.return_value = consultation

    with pytest.raises(ForbiddenError) as exc_info:
        await transition_consultation(
            session=session,
            consultation_id=consultation.id,
            target_status=ConsultationStatus.CONFIRMED,
            current_user=patient,
        )
    assert exc_info.value.code == "CONSULTATION_TRANSITION_FORBIDDEN"


def test_consultation_endpoints_via_test_client():
    """FastAPI TestClient endpoints correctly route status transitions and authorization."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    consultation = _make_consultation(patient_id=patient_id, doctor_id=doctor_id, status="booked")

    token = create_access_token(subject=doctor_user.id, role="doctor")
    session = AsyncMock()
    session.add = MagicMock()
    # 1. get_current_user resolves doctor_user
    # 2. confirm endpoint: with_for_update select consultation, then doctor_id lookup
    session.scalar.side_effect = [doctor_user, consultation, doctor_id]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    client = TestClient(app)

    response = client.post(
        f"/api/v1/consultations/{consultation.id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_consultation_cancel_endpoint_calls_cancellation():
    """POST /consultations/{id}/cancel provides a convenient alias for booking cancellation."""
    patient = _make_user(role="patient")
    consultation_id = uuid.uuid4()
    now = datetime.now(UTC)
    booking_response = BookingResponse(
        id=consultation_id,
        patient_id=patient.id,
        doctor_id=uuid.uuid4(),
        slot_id=uuid.uuid4(),
        status="cancelled",
        created_at=now,
        updated_at=now,
    )

    token = create_access_token(subject=patient.id, role="patient")
    session = AsyncMock()
    session.scalar.return_value = patient

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    client = TestClient(app)

    from unittest.mock import patch

    with patch(
        "app.api.v1.endpoints.consultations.cancel_booking",
        new=AsyncMock(
            return_value=BookingOperationResult(booking=booking_response, is_replayed=False)
        ),
    ):
        response = client.post(
            f"/api/v1/consultations/{consultation_id}/cancel",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "cancel-key"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_competing_transitions_prevent_silent_overwrites():
    """Concurrent transitions against the same consultation cannot silently overwrite each other.

    Row locking (SELECT ... FOR UPDATE) serializes transitions; the first completes
    (e.g. confirmed -> in_progress), causing the competing transition (e.g. confirmed -> no_show)
    to observe the updated state and be rejected with a 409 Conflict.
    """
    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    doctor_user_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    consultation_id = uuid.uuid4()

    async with factory() as session:
        session.add_all(
            [
                User(
                    id=doctor_user_id,
                    email_normalized=f"doc_race_{suffix}@example.test",
                    password_hash="placeholder",
                    role="doctor",
                ),
                User(
                    id=patient_id,
                    email_normalized=f"patient_race_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
            ]
        )
        session.add(Profile(user_id=doctor_user_id, full_name="Racing Doctor"))
        session.add(
            Doctor(
                id=doctor_id,
                user_id=doctor_user_id,
                specialization="General Medicine",
                license_number=f"RACE-{suffix}",
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
                id=consultation_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                slot_id=slot_id,
                status="confirmed",
            )
        )
        await session.commit()

    async def attempt_start() -> str:
        async with factory() as session:
            doctor = await session.get(User, doctor_user_id)
            assert doctor is not None
            try:
                await transition_consultation(
                    session=session,
                    consultation_id=consultation_id,
                    target_status=ConsultationStatus.IN_PROGRESS,
                    current_user=doctor,
                )
                await asyncio.sleep(0.05)
                await session.commit()
                return "in_progress"
            except ConflictError:
                await session.rollback()
                return "conflict"

    async def attempt_no_show() -> str:
        async with factory() as session:
            doctor = await session.get(User, doctor_user_id)
            assert doctor is not None
            try:
                await transition_consultation(
                    session=session,
                    consultation_id=consultation_id,
                    target_status=ConsultationStatus.NO_SHOW,
                    current_user=doctor,
                )
                await asyncio.sleep(0.05)
                await session.commit()
                return "no_show"
            except ConflictError:
                await session.rollback()
                return "conflict"

    outcomes = await asyncio.gather(attempt_start(), attempt_no_show())
    assert sorted(outcomes) in [
        ["conflict", "in_progress"],
        ["conflict", "no_show"],
    ]

    async with factory() as session:
        final_consultation = await session.get(Consultation, consultation_id)
        assert final_consultation is not None
        assert final_consultation.status in ("in_progress", "no_show")

        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.resource_id == consultation_id)
        )
        assert audit_count == 1


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_status_check_constraint():
    """PostgreSQL rejects illegal consultation status values via chk_consultations_status."""
    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    doctor_user_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    slot_id = uuid.uuid4()

    async with factory() as session:
        session.add_all(
            [
                User(
                    id=doctor_user_id,
                    email_normalized=f"doc_chk_{suffix}@example.test",
                    password_hash="placeholder",
                    role="doctor",
                ),
                User(
                    id=patient_id,
                    email_normalized=f"patient_chk_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
            ]
        )
        session.add(Profile(user_id=doctor_user_id, full_name="Constraint Doctor"))
        session.add(
            Doctor(
                id=doctor_id,
                user_id=doctor_user_id,
                specialization="General Medicine",
                license_number=f"CHK-{suffix}",
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

    async with factory() as session:
        invalid_consultation = Consultation(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            slot_id=slot_id,
            status="illegal_status_value",
        )
        session.add(invalid_consultation)
        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()

        assert "chk_consultations_status" in str(exc_info.value)
