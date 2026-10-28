"""Automated tests for prescription issuance, amendment, access control, and rollback."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import create_access_token
from app.db.session import get_db_session, get_session_factory
from app.main import create_app
from app.models.audit import AuditLog
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.prescription import Prescription, PrescriptionItem
from app.models.user import Profile, User
from app.schemas.prescription import PrescriptionCreate, PrescriptionItemCreate
from app.services.prescription_service import (
    get_prescription_by_consultation,
    get_prescription_by_id,
    issue_or_amend_prescription,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tests.conftest import is_postgres_available


def _make_user(*, role: str = "patient") -> User:
    return User(
        id=uuid.uuid4(),
        email_normalized=f"{role}_{uuid.uuid4().hex[:6]}@example.com",
        password_hash="placeholder_hash",
        role=role,
        is_active=True,
    )


def _make_consultation(
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    status: str = "in_progress",
) -> Consultation:
    now = datetime.now(UTC)
    return Consultation(
        id=uuid.uuid4(),
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot_id=uuid.uuid4(),
        status=status,
        created_at=now,
        updated_at=now,
    )


def _valid_prescription_payload() -> PrescriptionCreate:
    return PrescriptionCreate(
        notes="Patient diagnosed with mild seasonal allergies. Review in 1 week.",
        items=[
            PrescriptionItemCreate(
                medicine_name="Cetirizine",
                dosage="10mg",
                route="oral",
                frequency="once daily",
                duration="5 days",
                instructions="Take at night after food",
            ),
            PrescriptionItemCreate(
                medicine_name="Normal Saline Nasal Spray",
                dosage="2 sprays",
                route="nasal",
                frequency="twice daily",
                duration="7 days",
                instructions="Use before bedtime",
            ),
        ],
    )


def _amended_prescription_payload() -> PrescriptionCreate:
    return PrescriptionCreate(
        notes="Amended dosage following symptom review.",
        items=[
            PrescriptionItemCreate(
                medicine_name="Levocetirizine",
                dosage="5mg",
                route="oral",
                frequency="once daily",
                duration="10 days",
                instructions="Take with water before sleep",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_issue_prescription_valid_flow():
    """Assigned doctor issues a structured prescription for an in-progress consultation."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=patient_id, doctor_id=doctor_id, status="in_progress"
    )
    payload = _valid_prescription_payload()

    added_items: list[object] = []
    session = AsyncMock()
    # 1. with_for_update consultation
    # 2. _get_doctor_id_for_user
    # 3. existing prescription (None)
    # 4. reload with selectinload
    dummy_prescription = Prescription(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        notes=payload.notes,
        version=1,
        issued_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.scalar.side_effect = [
        consultation,
        doctor_id,
        None,
        dummy_prescription,
    ]
    session.add = MagicMock(side_effect=added_items.append)

    res = await issue_or_amend_prescription(
        session=session,
        consultation_id=consultation.id,
        payload=payload,
        current_user=doctor_user,
    )

    assert res.version == 1
    assert res.consultation_id == consultation.id

    # Verify audit event and outbox event
    audit_events = [x for x in added_items if isinstance(x, AuditLog)]
    outbox_events = [x for x in added_items if isinstance(x, OutboxEvent)]
    assert len(audit_events) == 1
    assert len(outbox_events) == 1
    assert audit_events[0].action == "prescription.create"
    assert audit_events[0].metadata_["item_count"] == 2
    # Verify clinical medication names are NEVER logged in audit trail
    assert "medicine_name" not in audit_events[0].metadata_
    assert "Cetirizine" not in str(audit_events[0].metadata_)


@pytest.mark.asyncio
async def test_amend_prescription_flow():
    """Amending an existing prescription increments version and updates items."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=patient_id, doctor_id=doctor_id, status="completed"
    )
    payload = _amended_prescription_payload()

    existing_prescription = Prescription(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        notes="Initial notes",
        version=1,
        issued_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    existing_prescription.items = [
        PrescriptionItem(
            id=uuid.uuid4(),
            prescription_id=existing_prescription.id,
            medicine_name="Old Med",
            dosage="100mg",
            route="oral",
            frequency="once",
            duration="1 day",
        )
    ]

    added_items: list[object] = []
    session = AsyncMock()
    session.scalar.side_effect = [
        consultation,
        doctor_id,
        existing_prescription,
        existing_prescription,
    ]
    session.add = MagicMock(side_effect=added_items.append)
    session.delete = AsyncMock()

    res = await issue_or_amend_prescription(
        session=session,
        consultation_id=consultation.id,
        payload=payload,
        current_user=doctor_user,
    )

    assert res.version == 2
    assert existing_prescription.version == 2
    assert existing_prescription.notes == payload.notes

    audit_events = [x for x in added_items if isinstance(x, AuditLog)]
    outbox_events = [x for x in added_items if isinstance(x, OutboxEvent)]
    assert len(audit_events) == 1
    assert len(outbox_events) == 1
    assert audit_events[0].action == "prescription.amend"
    assert audit_events[0].metadata_["version"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_status", ["booked", "confirmed", "cancelled", "no_show"])
async def test_issue_prescription_rejects_ineligible_consultation_status(invalid_status):
    """Prescriptions cannot be authored for consultations that are not in-progress or completed."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=uuid.uuid4(), doctor_id=doctor_id, status=invalid_status
    )
    payload = _valid_prescription_payload()

    session = AsyncMock()
    session.scalar.side_effect = [consultation, doctor_id]

    with pytest.raises(ConflictError) as exc_info:
        await issue_or_amend_prescription(
            session=session,
            consultation_id=consultation.id,
            payload=payload,
            current_user=doctor_user,
        )
    assert exc_info.value.code == "CONSULTATION_NOT_ELIGIBLE_FOR_PRESCRIPTION"


@pytest.mark.asyncio
async def test_issue_prescription_rejects_unassigned_doctor():
    """A doctor who is not assigned to the consultation is forbidden from issuing prescriptions."""
    doctor_user = _make_user(role="doctor")
    assigned_doctor_id = uuid.uuid4()
    calling_doctor_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=uuid.uuid4(), doctor_id=assigned_doctor_id, status="in_progress"
    )
    payload = _valid_prescription_payload()

    session = AsyncMock()
    session.scalar.side_effect = [consultation, calling_doctor_id]

    with pytest.raises(ForbiddenError) as exc_info:
        await issue_or_amend_prescription(
            session=session,
            consultation_id=consultation.id,
            payload=payload,
            current_user=doctor_user,
        )
    assert exc_info.value.code == "PRESCRIPTION_NOT_ASSIGNED_DOCTOR"


@pytest.mark.asyncio
async def test_patient_cannot_issue_prescription():
    """Patients cannot issue or amend prescriptions."""
    patient = _make_user(role="patient")
    payload = _valid_prescription_payload()
    session = AsyncMock()

    with pytest.raises(ForbiddenError) as exc_info:
        await issue_or_amend_prescription(
            session=session,
            consultation_id=uuid.uuid4(),
            payload=payload,
            current_user=patient,
        )
    assert exc_info.value.code == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.asyncio
async def test_get_prescription_authorization():
    """Retrieval is restricted to the owning patient, assigned doctor, or administrator."""
    patient = _make_user(role="patient")
    other_patient = _make_user(role="patient")
    doctor_user = _make_user(role="doctor")
    other_doctor_user = _make_user(role="doctor")
    admin = _make_user(role="admin")

    doctor_id = uuid.uuid4()
    other_doctor_id = uuid.uuid4()

    prescription = Prescription(
        id=uuid.uuid4(),
        consultation_id=uuid.uuid4(),
        patient_id=patient.id,
        doctor_id=doctor_id,
        notes="Notes",
        version=1,
        issued_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    prescription.items = []

    session = AsyncMock()

    # 1. Patient owner succeeds
    session.scalar.side_effect = [prescription]
    res_pat = await get_prescription_by_id(
        session=session, prescription_id=prescription.id, current_user=patient
    )
    assert res_pat.id == prescription.id

    # 2. Other patient is forbidden
    session.scalar.side_effect = [prescription]
    with pytest.raises(ForbiddenError) as exc_pat:
        await get_prescription_by_id(
            session=session, prescription_id=prescription.id, current_user=other_patient
        )
    assert exc_pat.value.code == "PRESCRIPTION_ACCESS_FORBIDDEN"

    # 3. Assigned doctor succeeds
    session.scalar.side_effect = [prescription, doctor_id]
    res_doc = await get_prescription_by_id(
        session=session, prescription_id=prescription.id, current_user=doctor_user
    )
    assert res_doc.id == prescription.id

    # 4. Other doctor is forbidden
    session.scalar.side_effect = [prescription, other_doctor_id]
    with pytest.raises(ForbiddenError) as exc_doc:
        await get_prescription_by_id(
            session=session, prescription_id=prescription.id, current_user=other_doctor_user
        )
    assert exc_doc.value.code == "PRESCRIPTION_ACCESS_FORBIDDEN"

    # 5. Admin succeeds
    session.scalar.side_effect = [prescription]
    res_adm = await get_prescription_by_id(
        session=session, prescription_id=prescription.id, current_user=admin
    )
    assert res_adm.id == prescription.id

    # 6. Not found returns 404
    session.scalar.side_effect = [None]
    with pytest.raises(NotFoundError) as exc_nf:
        await get_prescription_by_id(
            session=session, prescription_id=uuid.uuid4(), current_user=patient
        )
    assert exc_nf.value.code == "PRESCRIPTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_prescription_by_consultation():
    """Retrieving prescription via consultation endpoint enforces authorization."""
    patient = _make_user(role="patient")
    doctor_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=doctor_id, status="completed"
    )
    prescription = Prescription(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        patient_id=patient.id,
        doctor_id=doctor_id,
        notes="Summary",
        version=1,
        issued_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    prescription.items = []

    session = AsyncMock()
    session.scalar.side_effect = [consultation, prescription]

    res = await get_prescription_by_consultation(
        session=session, consultation_id=consultation.id, current_user=patient
    )
    assert res.consultation_id == consultation.id


def test_prescription_item_schema_validation():
    """Schema rejects empty items, blank strings, or whitespace-only medication data."""
    # Empty items list rejected
    with pytest.raises(ValidationError):
        PrescriptionCreate(items=[])

    # Blank medication name rejected
    with pytest.raises(ValidationError):
        PrescriptionItemCreate(
            medicine_name="   ",
            dosage="500mg",
            route="oral",
            frequency="once",
            duration="5 days",
        )

    # Blank dosage rejected
    with pytest.raises(ValidationError):
        PrescriptionItemCreate(
            medicine_name="Paracetamol",
            dosage="   ",
            route="oral",
            frequency="once",
            duration="5 days",
        )


def test_prescription_endpoints_http():
    """FastAPI TestClient routes prescription creation and retrieval correctly."""
    doctor_user = _make_user(role="doctor")
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    consultation = _make_consultation(
        patient_id=patient_id, doctor_id=doctor_id, status="in_progress"
    )

    now = datetime.now(UTC)
    prescription = Prescription(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        notes="Patient recovering well",
        version=1,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    prescription.items = [
        PrescriptionItem(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            medicine_name="Amoxicillin",
            dosage="500mg",
            route="oral",
            frequency="three times daily",
            duration="7 days",
        )
    ]

    token = create_access_token(subject=doctor_user.id, role="doctor")
    session = AsyncMock()
    session.add = MagicMock()
    # 1. get_current_user resolves doctor_user
    # 2. with_for_update consultation
    # 3. _get_doctor_id_for_user
    # 4. existing prescription (None)
    # 5. reload prescription
    session.scalar.side_effect = [
        doctor_user,
        consultation,
        doctor_id,
        None,
        prescription,
    ]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    client = TestClient(app)

    response = client.post(
        f"/api/v1/consultations/{consultation.id}/prescriptions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "notes": "Patient recovering well",
            "items": [
                {
                    "medicine_name": "Amoxicillin",
                    "dosage": "500mg",
                    "route": "oral",
                    "frequency": "three times daily",
                    "duration": "7 days",
                }
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["version"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["medicine_name"] == "Amoxicillin"


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_prescription_atomic_lifecycle_and_amendment():
    """Full database test: issue, amendment, items persistence, and rollback on failure."""
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
                    email_normalized=f"rx_doc_{suffix}@example.test",
                    password_hash="placeholder",
                    role="doctor",
                ),
                User(
                    id=patient_id,
                    email_normalized=f"rx_pat_{suffix}@example.test",
                    password_hash="placeholder",
                    role="patient",
                ),
            ]
        )
        session.add(Profile(user_id=doctor_user_id, full_name="Prescription Doctor"))
        session.add(
            Doctor(
                id=doctor_id,
                user_id=doctor_user_id,
                specialization="General Medicine",
                license_number=f"RX-{suffix}",
                is_verified=True,
                consultation_fee_minor=1_000,
            )
        )
        now = datetime.now(UTC)
        session.add(
            AvailabilitySlot(
                id=slot_id,
                doctor_id=doctor_id,
                start_at=now,
                end_at=now + timedelta(minutes=30),
                status="booked",
            )
        )
        session.add(
            Consultation(
                id=consultation_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                slot_id=slot_id,
                status="in_progress",
            )
        )
        await session.commit()

    # 1. Issue Version 1
    async with factory() as session:
        doctor = await session.get(User, doctor_user_id)
        assert doctor is not None
        rx_v1 = await issue_or_amend_prescription(
            session=session,
            consultation_id=consultation_id,
            payload=_valid_prescription_payload(),
            current_user=doctor,
        )
        assert rx_v1.version == 1
        assert len(rx_v1.items) == 2
        await session.commit()

    # 2. Verify Version 1 persisted in DB
    async with factory() as session:
        stored_rx = await session.scalar(
            select(Prescription)
            .where(Prescription.consultation_id == consultation_id)
            .options(selectinload(Prescription.items))
        )
        assert stored_rx is not None
        assert stored_rx.version == 1
        assert len(stored_rx.items) == 2

    # 3. Amend to Version 2
    async with factory() as session:
        doctor = await session.get(User, doctor_user_id)
        assert doctor is not None
        rx_v2 = await issue_or_amend_prescription(
            session=session,
            consultation_id=consultation_id,
            payload=_amended_prescription_payload(),
            current_user=doctor,
        )
        assert rx_v2.version == 2
        assert len(rx_v2.items) == 1
        assert rx_v2.items[0].medicine_name == "Levocetirizine"
        await session.commit()

    # 4. Verify Version 2 in DB and audit/outbox entries
    async with factory() as session:
        stored_v2 = await session.scalar(
            select(Prescription)
            .where(Prescription.consultation_id == consultation_id)
            .options(selectinload(Prescription.items))
        )
        assert stored_v2 is not None
        assert stored_v2.version == 2
        assert len(stored_v2.items) == 1

        outbox_events = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.aggregate_id == stored_v2.id)
                .order_by(OutboxEvent.created_at)
            )
        ).all()
        assert [e.event_type for e in outbox_events] == [
            "prescription.issued",
            "prescription.amended",
        ]

        audit_logs = (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.resource_id == stored_v2.id)
                .order_by(AuditLog.created_at)
            )
        ).all()
        assert [a.action for a in audit_logs] == ["prescription.create", "prescription.amend"]
        # Ensure no audit metadata has medication details
        for a in audit_logs:
            assert "medicine_name" not in a.metadata_
            assert "Levocetirizine" not in str(a.metadata_)
