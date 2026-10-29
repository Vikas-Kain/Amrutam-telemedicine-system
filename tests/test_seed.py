"""Tests for initial demo accounts and availability slot seeding service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.security import verify_password
from app.db.session import get_db_session
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import User
from app.services.seed_service import DEMO_ACCOUNTS, seed_demo_data
from sqlalchemy import select

from tests.conftest import is_postgres_available


@pytest.mark.asyncio
async def test_seed_demo_data_mocked_session():
    """Verify seed_demo_data creates User, Profile, Doctor, and Slots when no users exist."""
    session = AsyncMock()
    session.add = MagicMock()
    # Mock scalar to return None (users and slots don't exist yet)
    session.scalar.return_value = None

    seeded = await seed_demo_data(session)

    assert "doctor" in seeded
    assert "patient" in seeded
    assert "admin" in seeded
    assert seeded["doctor"] == DEMO_ACCOUNTS["doctor"]["email"]
    assert seeded["patient"] == DEMO_ACCOUNTS["patient"]["email"]
    assert seeded["admin"] == DEMO_ACCOUNTS["admin"]["email"]

    # Verify session.add was called multiple times (users, profiles, doctor, slots)
    added_items = [call.args[0] for call in session.add.call_args_list]
    types_added = [type(item) for item in added_items]

    assert User in types_added
    assert Doctor in types_added
    assert AvailabilitySlot in types_added
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_demo_data_idempotent_when_users_already_exist():
    """Verify seed_demo_data does not re-add existing users when called repeatedly."""
    session = AsyncMock()
    session.add = MagicMock()

    # Simulate existing doctor user with linked doctor profile
    mock_doctor_user = MagicMock(spec=User)
    mock_doctor_user.role = "doctor"
    mock_doctor_user.id = uuid.uuid4()
    mock_doctor_user.doctor = MagicMock(spec=Doctor)
    mock_doctor_user.doctor.id = uuid.uuid4()

    mock_patient_user = MagicMock(spec=User)
    mock_patient_user.role = "patient"
    mock_patient_user.id = uuid.uuid4()

    mock_admin_user = MagicMock(spec=User)
    mock_admin_user.role = "admin"
    mock_admin_user.id = uuid.uuid4()

    # scalar returns existing users in order, and slot check returns an existing slot ID
    session.scalar.side_effect = [
        mock_doctor_user,  # query for doctor
        uuid.uuid4(),  # query for slots
        mock_patient_user,  # query for patient
        mock_admin_user,  # query for admin
    ]

    seeded = await seed_demo_data(session)

    assert seeded["doctor"] == DEMO_ACCOUNTS["doctor"]["email"]
    assert seeded["patient"] == DEMO_ACCOUNTS["patient"]["email"]
    assert seeded["admin"] == DEMO_ACCOUNTS["admin"]["email"]

    # session.add should NOT have been called because all records already exist
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_seed_demo_data_flow():
    """Live PostgreSQL test: verify accounts, doctor profile, slots, and password authentication."""
    async for session in get_db_session():
        seeded = await seed_demo_data(session)
        assert len(seeded) == 3

        # Verify doctor account
        doc_email = DEMO_ACCOUNTS["doctor"]["email"]
        doctor_user = await session.scalar(select(User).where(User.email_normalized == doc_email))
        assert doctor_user is not None
        assert doctor_user.role == "doctor"
        assert verify_password(DEMO_ACCOUNTS["doctor"]["password"], doctor_user.password_hash)

        # Verify doctor profile
        doctor_profile = await session.scalar(
            select(Doctor).where(Doctor.user_id == doctor_user.id)
        )
        assert doctor_profile is not None
        assert doctor_profile.specialization == "Ayurveda"
        assert doctor_profile.is_verified is True

        # Verify doctor slots
        slots = (
            await session.scalars(
                select(AvailabilitySlot).where(AvailabilitySlot.doctor_id == doctor_profile.id)
            )
        ).all()
        assert len(slots) >= 3

        # Test idempotency on live DB (running again must not fail or duplicate)
        seeded_again = await seed_demo_data(session)
        assert seeded_again == seeded
