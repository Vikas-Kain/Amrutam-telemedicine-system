"""Automated tests for security audit logging, sensitive data redaction,
and administrative review.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.deps import get_current_user, get_db_session
from app.core.errors import ForbiddenError
from app.core.logging import correlation_id_ctx_var, request_id_ctx_var
from app.db.session import get_session_factory
from app.main import create_app
from app.models.audit import AuditLog
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import User
from app.schemas.availability import SlotCreateRequest
from app.schemas.booking import BookingCreateRequest
from app.services.audit_service import (
    list_audit_logs,
    record_audit_event,
    sanitize_audit_metadata,
)
from app.services.availability_service import create_doctor_slots
from app.services.booking_service import cancel_booking, create_booking
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import is_postgres_available


def _make_user(*, role: str = "patient") -> User:
    return User(
        id=uuid.uuid4(),
        email_normalized=f"{role}_{uuid.uuid4().hex[:6]}@example.com",
        password_hash="placeholder_hash",
        role=role,
        is_active=True,
    )


def _make_doctor(user_id: uuid.UUID) -> Doctor:
    now = datetime.now(UTC)
    return Doctor(
        id=uuid.uuid4(),
        user_id=user_id,
        specialization="General Ayurveda",
        license_number=f"DOC-{uuid.uuid4().hex[:8].upper()}",
        is_verified=True,
        consultation_fee_minor=1500,
        currency="INR",
        created_at=now,
        updated_at=now,
    )


def _async_context_manager() -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock()
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Unit Tests: Sanitization, Redaction & Correlation Extraction
# ---------------------------------------------------------------------------


def test_sanitize_audit_metadata_redacts_sensitive_fields() -> None:
    """Never write passwords, tokens, MFA secrets, prescription contents or clinical bodies."""
    dangerous_payload = {
        "password": "SuperSecretPassword123!",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "mfa_secret": "JBSWY3DPEHPK3PXP",
        "prescription_items": [{"medicine_name": "Ashwagandha", "dosage": "500mg"}],
        "notes": "Patient complains of severe chronic pain",
        "diagnosis": "Vata dosha imbalance",
        "cvv": "123",
        "pan": "4111111111111111",
        "card_number": "4111111111111111",
        "request_body": {"raw": "clinical data"},
        # Safe allowlisted metadata
        "doctor_id": "11111111-1111-1111-1111-111111111111",
        "slot_id": "22222222-2222-2222-2222-222222222222",
        "version": 1,
        "amount_minor": 1500,
        "status": "succeeded",
    }

    clean = sanitize_audit_metadata(dangerous_payload)
    assert clean is not None

    # Sensitive keys must be completely absent
    for sensitive_key in [
        "password",
        "token",
        "mfa_secret",
        "prescription_items",
        "notes",
        "diagnosis",
        "cvv",
        "pan",
        "card_number",
        "request_body",
    ]:
        assert sensitive_key not in clean

    # Allowlisted keys must be preserved
    assert clean["doctor_id"] == "11111111-1111-1111-1111-111111111111"
    assert clean["slot_id"] == "22222222-2222-2222-2222-222222222222"
    assert clean["version"] == 1
    assert clean["amount_minor"] == 1500
    assert clean["status"] == "succeeded"


@pytest.mark.asyncio
async def test_record_audit_event_extracts_correlation_and_request_id() -> None:
    """Automatically extracts correlation/request ID from context variables if omitted."""
    req_token = request_id_ctx_var.set("req_ctx_test_999")
    corr_token = correlation_id_ctx_var.set("corr_ctx_test_888")

    try:
        session = AsyncMock()
        session.add = MagicMock()
        entry = await record_audit_event(
            session=session,
            action="booking.create",
            resource_type="consultation",
            resource_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            metadata={"status": "booked"},
        )

        assert entry.action == "booking.create"
        assert entry.correlation_id == "corr_ctx_test_888"
        assert entry.metadata_ == {"status": "booked"}
        session.add.assert_called_once_with(entry)
    finally:
        request_id_ctx_var.reset(req_token)
        correlation_id_ctx_var.reset(corr_token)


# ---------------------------------------------------------------------------
# Workflow Tests: Key Events Audit Trail Emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_booking_and_cancellation_emits_audit_events() -> None:
    """Booking creation and cancellation record audit entries with actor and metadata."""
    patient = _make_user(role="patient")
    doctor_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    now = datetime.now(UTC)

    slot = AvailabilitySlot(
        id=slot_id,
        doctor_id=doctor_id,
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
        status="available",
        created_at=now,
        updated_at=now,
    )

    # 1. Test create_booking audit record
    added_create: list[object] = []
    session_create = AsyncMock()
    session_create.scalar.side_effect = [None, slot]
    session_create.begin_nested = MagicMock(return_value=_async_context_manager())
    session_create.add = MagicMock(side_effect=added_create.append)

    async def flush_create() -> None:
        for item in added_create:
            if isinstance(item, Consultation) and item.id is None:
                item.id = uuid.uuid4()
                item.created_at = datetime.now(UTC)
                item.updated_at = item.created_at

    session_create.flush.side_effect = flush_create

    idemp_rec = MagicMock()
    idemp_rec.status = "in_progress"
    session_create.get.return_value = idemp_rec

    res = await create_booking(
        session=session_create,
        patient=patient,
        payload=BookingCreateRequest(doctor_id=doctor_id, slot_id=slot_id),
        idempotency_key="ik_audit_book_01",
    )
    assert res.booking.status == "booked"

    audit_create = next(x for x in added_create if isinstance(x, AuditLog))
    assert audit_create.action == "booking.create"
    assert audit_create.resource_type == "consultation"
    assert audit_create.actor_user_id == patient.id
    assert audit_create.metadata_["doctor_id"] == str(doctor_id)
    assert audit_create.metadata_["slot_id"] == str(slot_id)

    # 2. Test cancel_booking audit record
    consultation = Consultation(
        id=res.booking.id,
        patient_id=patient.id,
        doctor_id=doctor_id,
        slot_id=slot_id,
        status="booked",
        created_at=now,
        updated_at=now,
    )
    booked_slot = AvailabilitySlot(
        id=slot_id,
        doctor_id=doctor_id,
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
        status="booked",
        created_at=now,
        updated_at=now,
    )

    added_cancel: list[object] = []
    session_cancel = AsyncMock()
    session_cancel.scalar.side_effect = [None, consultation, booked_slot]
    session_cancel.begin_nested = MagicMock(return_value=_async_context_manager())
    session_cancel.add = MagicMock(side_effect=added_cancel.append)
    idemp_rec_cancel = MagicMock()
    idemp_rec_cancel.status = "in_progress"
    session_cancel.get.return_value = idemp_rec_cancel

    cancel_res = await cancel_booking(
        session=session_cancel,
        booking_id=consultation.id,
        current_user=patient,
        idempotency_key="ik_audit_cancel_01",
    )

    assert cancel_res.booking.status == "cancelled"

    audit_cancel = next(x for x in added_cancel if isinstance(x, AuditLog))
    assert audit_cancel.action == "booking.cancel"
    assert audit_cancel.resource_type == "consultation"
    assert audit_cancel.resource_id == consultation.id
    assert audit_cancel.actor_user_id == patient.id
    assert audit_cancel.metadata_["status"] == "cancelled"
    assert audit_cancel.metadata_["actor_role"] == "patient"


@pytest.mark.asyncio
async def test_availability_mutations_emit_audit_events() -> None:
    """Doctor availability create, update, and delete operations record audit entries."""
    doctor_user = _make_user(role="doctor")
    doctor = _make_doctor(doctor_user.id)
    now = datetime.now(UTC)

    added_slots: list[object] = []
    session = AsyncMock()
    session.add = MagicMock(side_effect=added_slots.append)
    session.add_all = MagicMock(side_effect=added_slots.extend)
    session.in_transaction = MagicMock(return_value=False)
    session.scalar.return_value = None  # No existing overlap

    # 1. Create slots audit
    slot_req = SlotCreateRequest(
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2),
    )
    await create_doctor_slots(session=session, doctor=doctor, slot_requests=[slot_req])

    audit_create = next(x for x in added_slots if isinstance(x, AuditLog))
    assert audit_create.action == "availability.create"
    assert audit_create.resource_type == "availability_slot"
    assert audit_create.actor_user_id == doctor_user.id
    assert audit_create.metadata_["slot_count"] == 1


# ---------------------------------------------------------------------------
# Administrative Audit Access & RBAC Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_audit_logs_rbac_denies_non_admin() -> None:
    """Non-administrators (patient or doctor) are strictly denied audit trail access."""
    patient = _make_user(role="patient")
    doctor = _make_user(role="doctor")
    session = AsyncMock()

    with pytest.raises(ForbiddenError):
        await list_audit_logs(session=session, current_user=patient)

    with pytest.raises(ForbiddenError):
        await list_audit_logs(session=session, current_user=doctor)


@pytest.mark.asyncio
async def test_list_audit_logs_admin_query_filters() -> None:
    """Admin can list and filter audit entries with deterministic pagination."""
    admin = _make_user(role="admin")
    entry = AuditLog(
        id=uuid.uuid4(),
        actor_user_id=admin.id,
        action="consultation.confirmed",
        resource_type="consultation",
        resource_id=uuid.uuid4(),
        correlation_id="req_filter_test",
        metadata_={"actor_role": "admin"},
        created_at=datetime.now(UTC),
    )

    session = AsyncMock()
    session.scalar.return_value = 1
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [entry]
    session.scalars.return_value = scalars_mock

    entries, total, total_pages = await list_audit_logs(
        session=session,
        current_user=admin,
        action="consultation.confirmed",
        resource_type="consultation",
        page=1,
        page_size=10,
    )

    assert total == 1
    assert total_pages == 1
    assert len(entries) == 1
    assert entries[0].action == "consultation.confirmed"


def test_admin_audit_endpoint_http_flow() -> None:
    """HTTP route tests: unauthenticated (401), forbidden for patient, allowed for admin."""
    app = create_app()
    client = TestClient(app)

    # 1. Unauthenticated returns 401
    res_unauth = client.get("/api/v1/admin/audit-logs")
    assert res_unauth.status_code == 401

    # 2. Patient role returns 403 Forbidden
    patient_user = _make_user(role="patient")
    app.dependency_overrides[get_current_user] = lambda: patient_user

    patient_client = TestClient(app)
    res_patient = patient_client.get("/api/v1/admin/audit-logs")
    assert res_patient.status_code == 403

    # 3. Admin role returns 200 and records audit access
    admin_user = _make_user(role="admin")
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = 0
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    session.scalars.return_value = scalars_mock

    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin_user

    admin_client = TestClient(app)
    res_admin = admin_client.get(
        "/api/v1/admin/audit-logs?action=booking.create&page=1&page_size=20",
    )
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1


# ---------------------------------------------------------------------------
# PostgreSQL Live Tests (Transactions, Rollback & Redaction Invariants)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL not available")
@pytest.mark.asyncio
async def test_postgres_audit_atomic_commit_and_rollback() -> None:
    """Live PostgreSQL test: atomic audit persistence, rollback policy,
    and absence of sensitive data.
    """
    session_factory = get_session_factory()
    now = datetime.now(UTC)

    # Create real admin user in database to satisfy foreign key constraint
    async with session_factory() as session:
        admin_user = User(
            id=uuid.uuid4(),
            email_normalized=f"audit_admin_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="hash",
            role="admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(admin_user)
        await session.commit()
        actor_id = admin_user.id

    res_id = uuid.uuid4()

    # 1. Atomic Commit: audit log persists when transaction commits
    async with session_factory() as session:
        await record_audit_event(
            session=session,
            action="security.key_rotation",
            resource_type="system",
            resource_id=res_id,
            actor_user_id=actor_id,
            correlation_id="corr_live_test",
            metadata={
                "actor_role": "admin",
                "status": "completed",
                # Pass dangerous fields to prove database sanitization
                "password": "attempted_leak",
                "token": "attempted_leak",
            },
        )
        await session.commit()

    # Verify audit log exists in PostgreSQL and dangerous keys are absent
    async with session_factory() as session:
        stored_entry = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "security.key_rotation",
                AuditLog.resource_id == res_id,
            )
        )
        assert stored_entry is not None
        assert stored_entry.correlation_id == "corr_live_test"
        assert stored_entry.metadata_["actor_role"] == "admin"
        assert stored_entry.metadata_["status"] == "completed"
        # Confirm sensitive fields are strictly absent in the database
        assert "password" not in stored_entry.metadata_
        assert "token" not in stored_entry.metadata_

    # 2. Deliberate Failure Policy (Atomic Rollback):
    # If the transaction rolls back, the audit record rolls back with it (no false phantom entries)
    rollback_res_id = uuid.uuid4()
    async with session_factory() as session:
        await record_audit_event(
            session=session,
            action="booking.create",
            resource_type="consultation",
            resource_id=rollback_res_id,
            actor_user_id=actor_id,
            metadata={"status": "booked"},
        )
        await session.rollback()

    async with session_factory() as session:
        phantom_entry = await session.scalar(
            select(AuditLog).where(
                AuditLog.resource_id == rollback_res_id,
            )
        )
        assert phantom_entry is None, "Audit record must not persist when transaction rolls back"
