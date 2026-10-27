"""Tests for doctor availability slot creation, update, deletion, and overlap rules."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import BadRequestError, ConflictError, ForbiddenError
from app.core.security import create_access_token
from app.db.session import get_db_session
from app.main import create_app
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import Profile, User
from app.schemas.availability import (
    SlotCreateRequest,
    SlotUpdateRequest,
)
from app.services.availability_service import (
    create_doctor_slots,
    delete_doctor_slot,
    update_doctor_slot,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from tests.conftest import is_postgres_available

# ==============================================================================
# Helper Factories
# ==============================================================================


def _create_mock_doctor_user(
    role: str = "doctor",
    doctor_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    email: str = "doctor.test@amrutam.co.in",
    full_name: str = "Dr. Test Doctor",
) -> tuple[User, Doctor]:
    """Helper to instantiate mock User and Doctor instances."""
    u_id = user_id or uuid.uuid4()
    d_id = doctor_id or uuid.uuid4()

    user = User(
        id=u_id,
        email_normalized=email,
        password_hash="argon2_hashed_placeholder",
        role=role,
        is_active=True,
    )
    user.profile = Profile(
        id=uuid.uuid4(),
        user_id=u_id,
        full_name=full_name,
    )
    doctor = Doctor(
        id=d_id,
        user_id=u_id,
        specialization="Ayurveda",
        license_number=f"LIC-{uuid.uuid4().hex[:6].upper()}",
        is_verified=True,
        consultation_fee_minor=50000,
        currency="INR",
    )
    doctor.user = user
    user.doctor = doctor
    return user, doctor


def _create_mock_slot(
    doctor_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    status: str = "available",
    slot_id: uuid.UUID | None = None,
) -> AvailabilitySlot:
    """Helper to instantiate mock AvailabilitySlot."""
    return AvailabilitySlot(
        id=slot_id or uuid.uuid4(),
        doctor_id=doctor_id,
        start_at=start_at,
        end_at=end_at,
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _build_mock_session() -> AsyncMock:
    """Create a configured AsyncMock session with synchronous methods properly stubbed."""
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.in_transaction = MagicMock(return_value=True)
    return session


# ==============================================================================
# 1. Pydantic Schema Validation Tests
# ==============================================================================


def test_slot_create_schema_valid():
    """Verify valid timestamps pass SlotCreateRequest validation."""
    now = datetime.now(UTC) + timedelta(days=1)
    slot = SlotCreateRequest(
        start_at=now,
        end_at=now + timedelta(minutes=30),
    )
    assert slot.start_at == now
    assert slot.end_at == now + timedelta(minutes=30)


def test_slot_create_schema_rejects_inverted_interval():
    """Verify end_at <= start_at is rejected with ValidationError."""
    now = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(ValidationError):
        SlotCreateRequest(
            start_at=now,
            end_at=now - timedelta(minutes=10),
        )


def test_slot_create_schema_duration_limits():
    """Verify durations under 10 minutes or over 4 hours are rejected."""
    now = datetime.now(UTC) + timedelta(days=1)

    # Under 10 minutes
    with pytest.raises(ValidationError):
        SlotCreateRequest(start_at=now, end_at=now + timedelta(minutes=5))

    # Over 4 hours
    with pytest.raises(ValidationError):
        SlotCreateRequest(start_at=now, end_at=now + timedelta(hours=5))


def test_slot_update_schema_status_validation():
    """Verify slot update accepts 'available' and 'blocked', rejecting others."""
    update_ok = SlotUpdateRequest(status="blocked")
    assert update_ok.status == "blocked"

    with pytest.raises(ValidationError):
        SlotUpdateRequest(status="invalid_status")  # type: ignore[arg-type]


# ==============================================================================
# 2. Availability Service Unit Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_create_slots_rejects_past_interval():
    """Verify create_doctor_slots rejects intervals with start_at in the past."""
    _, doctor = _create_mock_doctor_user()
    past_time = datetime.now(UTC) - timedelta(hours=1)
    req = SlotCreateRequest(
        start_at=past_time,
        end_at=past_time + timedelta(minutes=30),
    )

    mock_session = AsyncMock()

    with pytest.raises(BadRequestError) as exc_info:
        await create_doctor_slots(mock_session, doctor, [req])
    assert exc_info.value.code == "PAST_SLOT_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_create_slots_rejects_internal_batch_overlap():
    """Verify create_doctor_slots rejects overlapping slots within the same batch."""
    _, doctor = _create_mock_doctor_user()
    start = datetime.now(UTC) + timedelta(days=2)
    s1 = SlotCreateRequest(start_at=start, end_at=start + timedelta(minutes=45))
    s2 = SlotCreateRequest(
        start_at=start + timedelta(minutes=30),
        end_at=start + timedelta(hours=1),
    )

    mock_session = AsyncMock()

    with pytest.raises(ConflictError) as exc_info:
        await create_doctor_slots(mock_session, doctor, [s1, s2])
    assert exc_info.value.code == "SLOT_OVERLAP"


@pytest.mark.asyncio
async def test_create_slots_rejects_database_overlap():
    """Verify create_doctor_slots rejects slots that overlap with existing DB records."""
    _, doctor = _create_mock_doctor_user()
    start = datetime.now(UTC) + timedelta(days=2)
    s1 = SlotCreateRequest(start_at=start, end_at=start + timedelta(minutes=30))

    mock_session = AsyncMock()
    # Mock overlap query returning an existing slot ID
    mock_session.scalar.return_value = uuid.uuid4()

    with pytest.raises(ConflictError) as exc_info:
        await create_doctor_slots(mock_session, doctor, [s1])
    assert exc_info.value.code == "SLOT_OVERLAP"


@pytest.mark.asyncio
async def test_update_slot_cannot_modify_booked_slot():
    """Verify update_doctor_slot rejects modification of booked slots with HTTP 409."""
    user, doctor = _create_mock_doctor_user()
    start = datetime.now(UTC) + timedelta(days=1)
    booked_slot = _create_mock_slot(
        doctor.id, start, start + timedelta(minutes=30), status="booked"
    )

    mock_session = _build_mock_session()
    mock_session.scalar.side_effect = [booked_slot, doctor]

    with pytest.raises(ConflictError) as exc_info:
        await update_doctor_slot(
            session=mock_session,
            slot_id=booked_slot.id,
            current_user=user,
            update_data=SlotUpdateRequest(status="blocked"),
        )
    assert exc_info.value.code == "SLOT_ALREADY_BOOKED"


@pytest.mark.asyncio
async def test_update_slot_enforces_doctor_ownership():
    """Verify a doctor cannot modify another doctor's availability slot."""
    user_a, doctor_a = _create_mock_doctor_user(full_name="Dr. Alice")
    _, doctor_b = _create_mock_doctor_user(full_name="Dr. Bob")

    start = datetime.now(UTC) + timedelta(days=1)
    slot_b = _create_mock_slot(doctor_b.id, start, start + timedelta(minutes=30))

    mock_session = _build_mock_session()
    # First call returns slot_b, second call returns doctor_a
    mock_session.scalar.side_effect = [slot_b, doctor_a]

    with pytest.raises(ForbiddenError) as exc_info:
        await update_doctor_slot(
            session=mock_session,
            slot_id=slot_b.id,
            current_user=user_a,
            update_data=SlotUpdateRequest(status="blocked"),
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_slot_cannot_delete_booked_slot():
    """Verify delete_doctor_slot rejects deletion of a booked slot with HTTP 409."""
    user, doctor = _create_mock_doctor_user()
    start = datetime.now(UTC) + timedelta(days=1)
    booked_slot = _create_mock_slot(
        doctor.id, start, start + timedelta(minutes=30), status="booked"
    )

    mock_session = _build_mock_session()
    mock_session.scalar.side_effect = [booked_slot, doctor]

    with pytest.raises(ConflictError) as exc_info:
        await delete_doctor_slot(
            session=mock_session,
            slot_id=booked_slot.id,
            current_user=user,
        )
    assert exc_info.value.code == "SLOT_ALREADY_BOOKED"


@pytest.mark.asyncio
async def test_delete_slot_enforces_doctor_ownership():
    """Verify a doctor cannot delete another doctor's availability slot."""
    user_a, doctor_a = _create_mock_doctor_user(full_name="Dr. Alice")
    _, doctor_b = _create_mock_doctor_user(full_name="Dr. Bob")

    start = datetime.now(UTC) + timedelta(days=1)
    slot_b = _create_mock_slot(doctor_b.id, start, start + timedelta(minutes=30))

    mock_session = AsyncMock()
    mock_session.scalar.side_effect = [slot_b, doctor_a]

    with pytest.raises(ForbiddenError) as exc_info:
        await delete_doctor_slot(
            session=mock_session,
            slot_id=slot_b.id,
            current_user=user_a,
        )
    assert exc_info.value.status_code == 403


# ==============================================================================
# 3. API Endpoint Tests
# ==============================================================================


def test_api_create_doctor_slots_single_success():
    """Verify POST /api/v1/doctors/me/slots creates a single slot successfully."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)
    start_str = (now).isoformat()
    end_str = (now + timedelta(minutes=30)).isoformat()

    mock_session = _build_mock_session()
    # 1. get_current_user -> user
    # 2. get_doctor_by_user_id -> doctor
    # 3. overlap check -> None (no overlap)
    mock_session.scalar.side_effect = [user, doctor, None]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/doctors/me/slots",
        json={"start_at": start_str, "end_at": end_str},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["doctor_id"] == str(doctor.id)
    assert data[0]["status"] == "available"


def test_api_create_doctor_slots_batch_success():
    """Verify POST /api/v1/doctors/me/slots supports batch slot creation."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    base = datetime.now(UTC) + timedelta(days=2)
    s1_start = base.isoformat()
    s1_end = (base + timedelta(minutes=30)).isoformat()
    s2_start = (base + timedelta(minutes=45)).isoformat()
    s2_end = (base + timedelta(minutes=75)).isoformat()

    mock_session = _build_mock_session()
    mock_session.scalar.side_effect = [user, doctor, None]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/doctors/me/slots",
        json={
            "slots": [
                {"start_at": s1_start, "end_at": s1_end},
                {"start_at": s2_start, "end_at": s2_end},
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data) == 2


def test_api_create_doctor_slots_patient_role_forbidden():
    """Verify a patient cannot create doctor availability slots (HTTP 403)."""
    user = User(
        id=uuid.uuid4(),
        email_normalized="patient@amrutam.co.in",
        password_hash="dummy",
        role="patient",
        is_active=True,
    )
    token = create_access_token(subject=user.id, role="patient")

    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    now = datetime.now(UTC) + timedelta(days=1)
    response = client.post(
        "/api/v1/doctors/me/slots",
        json={"start_at": now.isoformat(), "end_at": (now + timedelta(minutes=30)).isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_api_create_doctor_slots_past_interval_rejected():
    """Verify creating a slot in the past returns HTTP 400 PAST_SLOT_NOT_ALLOWED."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    past = datetime.now(UTC) - timedelta(hours=2)

    mock_session = AsyncMock()
    mock_session.scalar.side_effect = [user, doctor]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/doctors/me/slots",
        json={"start_at": past.isoformat(), "end_at": (past + timedelta(minutes=30)).isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PAST_SLOT_NOT_ALLOWED"


def test_api_create_doctor_slots_overlap_rejected():
    """Verify overlapping slot creation returns HTTP 409 SLOT_OVERLAP."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)

    mock_session = AsyncMock()
    # 1. get_current_user -> user
    # 2. get_doctor_by_user_id -> doctor
    # 3. overlap check -> returns an existing slot ID (collision!)
    mock_session.scalar.side_effect = [user, doctor, uuid.uuid4()]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/doctors/me/slots",
        json={"start_at": now.isoformat(), "end_at": (now + timedelta(minutes=30)).isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLOT_OVERLAP"


def test_api_update_doctor_slot_success():
    """Verify PATCH /api/v1/doctors/me/slots/{slot_id} updates status to blocked."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)
    slot = _create_mock_slot(doctor.id, now, now + timedelta(minutes=30), status="available")

    mock_session = _build_mock_session()
    # 1. get_current_user -> user
    # 2. fetch slot -> slot
    # 3. get_doctor_by_user_id -> doctor
    mock_session.scalar.side_effect = [user, slot, doctor]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/doctors/me/slots/{slot.id}",
        json={"status": "blocked"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"


def test_api_update_doctor_slot_booked_rejected():
    """Verify PATCH on booked slot returns HTTP 409 SLOT_ALREADY_BOOKED."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)
    slot = _create_mock_slot(doctor.id, now, now + timedelta(minutes=30), status="booked")

    mock_session = _build_mock_session()
    mock_session.scalar.side_effect = [user, slot, doctor]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/doctors/me/slots/{slot.id}",
        json={"status": "available"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLOT_ALREADY_BOOKED"


def test_api_update_doctor_slot_wrong_doctor_forbidden():
    """Verify doctor B cannot update doctor A's slot (HTTP 403 FORBIDDEN)."""
    user_a, doctor_a = _create_mock_doctor_user(email="alice@amrutam.co.in")
    user_b, _ = _create_mock_doctor_user(email="bob@amrutam.co.in")
    token_b = create_access_token(subject=user_b.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)
    slot_a = _create_mock_slot(doctor_a.id, now, now + timedelta(minutes=30))

    mock_session = _build_mock_session()
    # 1. get_current_user -> user_b
    # 2. fetch slot -> slot_a
    # 3. get_doctor_by_user_id for user_b -> None or different doctor
    mock_session.scalar.side_effect = [user_b, slot_a, None]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/doctors/me/slots/{slot_a.id}",
        json={"status": "blocked"},
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_api_delete_doctor_slot_success():
    """Verify DELETE /api/v1/doctors/me/slots/{slot_id} removes unbooked slot."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)
    slot = _create_mock_slot(doctor.id, now, now + timedelta(minutes=30))

    mock_session = _build_mock_session()
    mock_session.scalar.side_effect = [user, slot, doctor]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.delete(
        f"/api/v1/doctors/me/slots/{slot.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204


def test_api_delete_doctor_slot_booked_rejected():
    """Verify DELETE on booked slot returns HTTP 409 SLOT_ALREADY_BOOKED."""
    user, doctor = _create_mock_doctor_user()
    token = create_access_token(subject=user.id, role="doctor")

    now = datetime.now(UTC) + timedelta(days=1)
    slot = _create_mock_slot(doctor.id, now, now + timedelta(minutes=30), status="booked")

    mock_session = AsyncMock()
    mock_session.scalar.side_effect = [user, slot, doctor]

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.delete(
        f"/api/v1/doctors/me/slots/{slot.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLOT_ALREADY_BOOKED"


def test_api_list_doctor_slots_public():
    """Verify GET /api/v1/doctors/{doctor_id}/slots returns available slots list."""
    _, doctor = _create_mock_doctor_user()
    now = datetime.now(UTC) + timedelta(days=1)
    s1 = _create_mock_slot(doctor.id, now, now + timedelta(minutes=30))
    s2 = _create_mock_slot(doctor.id, now + timedelta(minutes=45), now + timedelta(minutes=75))

    mock_session = _build_mock_session()
    mock_session.scalar.return_value = doctor.id
    mock_result = MagicMock()
    mock_result.all.return_value = [s1, s2]
    mock_session.scalars.return_value = mock_result

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.get(f"/api/v1/doctors/{doctor.id}/slots")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["status"] == "available"


# ==============================================================================
# 4. Live PostgreSQL Integration Tests
# ==============================================================================


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_slot_exclusion_constraint_and_overlap_enforcement():
    """Verify PostgreSQL exclusion constraint prevents overlapping intervals on live database."""
    unique_suffix = uuid.uuid4().hex[:6]
    async for session in get_db_session():
        # 1. Create User, Profile, and Doctor with explicit UUIDs
        u_id = uuid.uuid4()
        u = User(
            id=u_id,
            email_normalized=f"doc_{unique_suffix}@amrutam.co.in",
            password_hash="argon2_hashed_placeholder",
            role="doctor",
        )
        session.add(u)

        prof = Profile(user_id=u_id, full_name=f"Dr. Live {unique_suffix}")
        session.add(prof)

        doc_id = uuid.uuid4()
        doc = Doctor(
            id=doc_id,
            user_id=u_id,
            specialization="Ayurveda",
            license_number=f"LIC-{unique_suffix.upper()}",
            is_verified=True,
            consultation_fee_minor=60000,
        )
        session.add(doc)
        await session.commit()

        # 2. Insert first availability slot
        now = datetime.now(UTC) + timedelta(days=5)
        slot1 = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc_id,
            start_at=now,
            end_at=now + timedelta(minutes=30),
            status="available",
        )
        session.add(slot1)
        await session.commit()

        # 3. Attempt inserting overlapping slot directly at SQL/PostgreSQL level
        slot_overlap = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc_id,
            start_at=now + timedelta(minutes=15),  # Overlaps with slot1!
            end_at=now + timedelta(minutes=45),
            status="available",
        )
        session.add(slot_overlap)

        with pytest.raises(IntegrityError):
            await session.commit()

        await session.rollback()

        # 4. Non-overlapping slot succeeds
        slot2 = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc_id,
            start_at=now + timedelta(minutes=45),
            end_at=now + timedelta(minutes=75),
            status="available",
        )
        session.add(slot2)
        await session.commit()
        assert slot2.id is not None
        break
