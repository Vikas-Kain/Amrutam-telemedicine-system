"""Database seeder for initial demo accounts (Doctor, Patient, Admin) and availability slots."""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import Profile, User

logger = logging.getLogger("app.seed")

DEMO_ACCOUNTS = {
    "doctor": {
        "email": "doctor@amrutam.com",
        "password": "Doctor123!Secure",
        "role": "doctor",
        "full_name": "Dr. Vaidya Sharma",
        "phone": "+919876543210",
        "specialization": "Ayurveda",
        "license_number": "AYUR-REG-2026-001",
        "consultation_fee_minor": 150000,
        "currency": "INR",
        "bio": (
            "Senior Ayurvedic Practitioner specializing in Panchakarma, "
            "holistic wellness, and lifestyle consultation."
        ),
    },
    "patient": {
        "email": "patient@amrutam.com",
        "password": "Patient123!Secure",
        "role": "patient",
        "full_name": "Aarav Patel",
        "phone": "+919876543212",
        "date_of_birth": date(1995, 6, 15),
    },
    "admin": {
        "email": "admin@amrutam.com",
        "password": "Admin123!Secure",
        "role": "admin",
        "full_name": "System Administrator",
        "phone": "+919876543213",
    },
}


async def seed_demo_data(session: AsyncSession) -> dict[str, str]:
    """Idempotently seed standard demo accounts (Doctor, Patient, Admin) and availability slots.

    Safe to run repeatedly. Verifies associated profile and doctor records.
    Returns a dictionary mapping account role to email.
    """
    seeded: dict[str, str] = {}

    for role_name, data in DEMO_ACCOUNTS.items():
        email = data["email"]
        stmt = (
            select(User)
            .options(selectinload(User.profile), selectinload(User.doctor))
            .where(User.email_normalized == email)
        )
        existing_user = await session.scalar(stmt)

        if existing_user is None:
            user_id = uuid.uuid4()
            user = User(
                id=user_id,
                email_normalized=email,
                password_hash=hash_password(data["password"]),
                role=data["role"],
                is_active=True,
                mfa_enabled=False,
            )
            session.add(user)

            profile = Profile(
                user_id=user_id,
                full_name=data["full_name"],
                phone=data.get("phone"),
                date_of_birth=data.get("date_of_birth"),
            )
            session.add(profile)

            if data["role"] == "doctor":
                doctor_id = uuid.uuid4()
                doctor = Doctor(
                    id=doctor_id,
                    user_id=user_id,
                    specialization=data["specialization"],
                    license_number=data["license_number"],
                    is_verified=True,
                    consultation_fee_minor=data["consultation_fee_minor"],
                    currency=data["currency"],
                    bio=data.get("bio"),
                )
                session.add(doctor)

                # Seed initial future availability slots for demonstration
                await _seed_initial_doctor_slots(session, doctor_id)
        else:
            # User exists; ensure doctor record and slots exist if role is doctor
            if existing_user.role == "doctor":
                doctor_id = None
                if existing_user.doctor is not None:
                    doctor_id = existing_user.doctor.id
                else:
                    doc_check = await session.scalar(
                        select(Doctor).where(Doctor.user_id == existing_user.id)
                    )
                    if doc_check is not None:
                        doctor_id = doc_check.id
                    else:
                        doctor_id = uuid.uuid4()
                        doctor = Doctor(
                            id=doctor_id,
                            user_id=existing_user.id,
                            specialization=data["specialization"],
                            license_number=data["license_number"],
                            is_verified=True,
                            consultation_fee_minor=data["consultation_fee_minor"],
                            currency=data["currency"],
                            bio=data.get("bio"),
                        )
                        session.add(doctor)
                if doctor_id is not None:
                    await _seed_initial_doctor_slots(session, doctor_id)

        seeded[role_name] = email

    await session.commit()
    return seeded


async def _seed_initial_doctor_slots(session: AsyncSession, doctor_id: uuid.UUID) -> None:
    """Seed initial non-overlapping future availability slots if none exist."""
    existing_slots = await session.scalar(
        select(AvailabilitySlot.id).where(AvailabilitySlot.doctor_id == doctor_id).limit(1)
    )
    if existing_slots is not None:
        return

    # Create 3 future slots starting tomorrow
    base_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    slot_hours = [10, 11, 14]  # 10:00, 11:00, 14:00 UTC
    for h in slot_hours:
        slot_start = base_time.replace(hour=h)
        slot_end = slot_start + timedelta(minutes=30)
        slot = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doctor_id,
            start_at=slot_start,
            end_at=slot_end,
            status="available",
        )
        session.add(slot)


if __name__ == "__main__":
    import asyncio

    from app.db.session import close_database_connections, get_session_factory

    async def _main():
        factory = get_session_factory()
        async with factory() as session:
            result = await seed_demo_data(session)
            print("Successfully seeded demo accounts:", result)
        await close_database_connections()

    asyncio.run(_main())
