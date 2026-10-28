"""Synthetic test data seeder and cleanup routines for performance benchmarks.

Provides reproducible, non-sensitive synthetic doctors, availability slots, patients,
and consultation records for load testing, with guaranteed isolated cleanup.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.security import create_access_token, hash_password
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import Profile, User
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

PERF_EMAIL_PREFIX = "perf_test_"
SPECIALIZATIONS = ["Ayurveda", "Panchakarma", "Yoga", "Unani", "Homeopathy", "Naturopathy"]


@dataclass
class PerformanceDataset:
    """Container holding seeded entity IDs and access tokens for benchmark execution."""

    doctor_ids: list[str] = field(default_factory=list)
    slot_ids: list[str] = field(default_factory=list)
    consultation_ids: list[str] = field(default_factory=list)
    patient_tokens: list[str] = field(default_factory=list)
    doctor_tokens: list[str] = field(default_factory=list)
    patient_ids: list[str] = field(default_factory=list)


async def seed_performance_dataset(
    session: AsyncSession,
    doctor_count: int = 15,
    slots_per_doctor: int = 10,
    patient_count: int = 10,
) -> PerformanceDataset:
    """Seed synthetic doctors, slots, patients, and initial consultations for benchmarks."""
    dataset = PerformanceDataset()
    password_hash = hash_password("PerfTest123!Secure")
    now = datetime.now(UTC)

    # 1. Seed synthetic patients
    for i in range(patient_count):
        patient_id = uuid.uuid4()
        patient_email = f"{PERF_EMAIL_PREFIX}patient_{i}_{patient_id.hex[:6]}@example.com"
        patient_user = User(
            id=patient_id,
            email_normalized=patient_email.lower(),
            password_hash=password_hash,
            role="patient",
            is_active=True,
        )
        profile = Profile(
            user_id=patient_id,
            full_name=f"Synthetic Patient {i}",
            phone=f"+9198000{i:05d}",
        )
        patient_user.profile = profile
        session.add(patient_user)

        dataset.patient_ids.append(str(patient_id))
        token = create_access_token(subject=str(patient_id), role="patient")
        dataset.patient_tokens.append(token)

    # 2. Seed synthetic doctors with availability slots
    for d_idx in range(doctor_count):
        doc_user_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        doc_email = f"{PERF_EMAIL_PREFIX}doctor_{d_idx}_{doc_user_id.hex[:6]}@example.com"
        doc_user = User(
            id=doc_user_id,
            email_normalized=doc_email.lower(),
            password_hash=password_hash,
            role="doctor",
            is_active=True,
        )
        doc_profile = Profile(
            user_id=doc_user_id,
            full_name=f"Dr. Synthetic {d_idx}",
            phone=f"+9199000{d_idx:05d}",
        )
        doc_user.profile = doc_profile
        session.add(doc_user)

        spec = SPECIALIZATIONS[d_idx % len(SPECIALIZATIONS)]
        doctor = Doctor(
            id=doc_id,
            user_id=doc_user_id,
            specialization=spec,
            license_number=f"PERF-LIC-{d_idx}-{doc_id.hex[:6].upper()}",
            is_verified=True,
            consultation_fee_minor=1000 + (d_idx * 100),
            currency="INR",
            bio=f"Synthetic practitioner specializing in {spec} for load testing.",
        )
        session.add(doctor)
        dataset.doctor_ids.append(str(doc_id))

        doc_token = create_access_token(subject=str(doc_user_id), role="doctor")
        dataset.doctor_tokens.append(doc_token)

        # Seed future availability slots for each doctor
        for s_idx in range(slots_per_doctor):
            slot_id = uuid.uuid4()
            start_at = now + timedelta(days=1 + s_idx, hours=9 + (s_idx % 8))
            end_at = start_at + timedelta(minutes=30)
            slot = AvailabilitySlot(
                id=slot_id,
                doctor_id=doc_id,
                start_at=start_at,
                end_at=end_at,
                status="available",
            )
            session.add(slot)
            dataset.slot_ids.append(str(slot_id))

    await session.flush()

    # 3. Seed sample booked consultations for consultation read benchmarks
    if dataset.patient_ids and dataset.doctor_ids and len(dataset.slot_ids) >= 2:
        for c_idx in range(min(2, len(dataset.slot_ids))):
            consult_id = uuid.uuid4()
            booked_slot_id = uuid.UUID(dataset.slot_ids[-(c_idx + 1)])
            patient_uuid = uuid.UUID(dataset.patient_ids[c_idx % len(dataset.patient_ids)])

            # Mark slot booked
            slot_obj = await session.get(AvailabilitySlot, booked_slot_id)
            if slot_obj:
                slot_obj.status = "booked"
                consultation = Consultation(
                    id=consult_id,
                    patient_id=patient_uuid,
                    doctor_id=slot_obj.doctor_id,
                    slot_id=booked_slot_id,
                    status="booked",
                    reason="Synthetic routine checkup for load test.",
                )
                session.add(consultation)
                dataset.consultation_ids.append(str(consult_id))

    await session.commit()
    return dataset


async def cleanup_performance_dataset(
    session: AsyncSession,
    dataset: PerformanceDataset | None = None,
) -> int:
    """Explicitly delete all synthetic performance test records from database."""
    # Find all synthetic users matching PERF_EMAIL_PREFIX
    perf_users = (
        await session.scalars(
            select(User.id).where(User.email_normalized.like(f"{PERF_EMAIL_PREFIX.lower()}%"))
        )
    ).all()

    if not perf_users:
        return 0

    user_ids = list(perf_users)

    # 1. Delete consultations involving synthetic patients or doctors
    await session.execute(
        delete(Consultation).where(
            Consultation.patient_id.in_(user_ids)
            | Consultation.doctor_id.in_(select(Doctor.id).where(Doctor.user_id.in_(user_ids)))
        )
    )

    # 2. Delete availability slots of synthetic doctors
    await session.execute(
        delete(AvailabilitySlot).where(
            AvailabilitySlot.doctor_id.in_(select(Doctor.id).where(Doctor.user_id.in_(user_ids)))
        )
    )

    # 3. Delete synthetic doctors
    await session.execute(delete(Doctor).where(Doctor.user_id.in_(user_ids)))

    # 4. Delete synthetic user profiles
    await session.execute(delete(Profile).where(Profile.user_id.in_(user_ids)))

    # 5. Delete synthetic users
    delete_result = await session.execute(delete(User).where(User.id.in_(user_ids)))

    await session.commit()
    return delete_result.rowcount or 0
