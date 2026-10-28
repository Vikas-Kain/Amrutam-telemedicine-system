"""Prescription service managing atomic issuance, amendment versioning, and access control."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.outbox import OutboxEvent
from app.models.prescription import Prescription, PrescriptionItem
from app.models.user import User
from app.schemas.prescription import PrescriptionCreate, PrescriptionResponse
from app.services.audit_service import record_audit_event


async def _get_doctor_id_for_user(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(select(Doctor.id).where(Doctor.user_id == user_id))


def _authorize_prescription_read(
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    current_user: User,
    caller_doctor_id: uuid.UUID | None = None,
) -> None:
    """Enforce read access policy: patient owner, assigned doctor, or administrator."""
    if current_user.role == "admin":
        return
    if current_user.role == "patient" and patient_id == current_user.id:
        return
    if current_user.role == "doctor" and caller_doctor_id == doctor_id:
        return
    raise ForbiddenError(
        message="You do not have permission to access this prescription.",
        code="PRESCRIPTION_ACCESS_FORBIDDEN",
    )


async def issue_or_amend_prescription(
    session: AsyncSession,
    *,
    consultation_id: uuid.UUID,
    payload: PrescriptionCreate,
    current_user: User,
) -> PrescriptionResponse:
    """Issue a new prescription or amend an existing one atomically within a transaction.

    Only the assigned doctor may author or correct prescriptions. Eligible consultations
    must be in 'in_progress' or 'completed' status. Prescription contents (medication names,
    dosages) are never recorded in audit logs or outbox events.
    """
    if current_user.role != "doctor":
        raise ForbiddenError(
            message="Only doctors may issue or amend prescriptions.",
            code="INSUFFICIENT_PERMISSIONS",
        )

    # Lock consultation to verify eligibility and assigned doctor
    consultation = await session.scalar(
        select(Consultation).where(Consultation.id == consultation_id).with_for_update()
    )
    if consultation is None:
        raise NotFoundError(message="Consultation not found.", code="CONSULTATION_NOT_FOUND")

    caller_doctor_id = await _get_doctor_id_for_user(session, current_user.id)
    if caller_doctor_id != consultation.doctor_id:
        raise ForbiddenError(
            message=(
                "Only the assigned doctor may issue or amend a prescription for this consultation."
            ),
            code="PRESCRIPTION_NOT_ASSIGNED_DOCTOR",
        )

    # Validate consultation status eligibility
    if consultation.status not in ("in_progress", "completed"):
        raise ConflictError(
            message=(
                "Prescriptions can only be issued for in-progress or completed consultations "
                f"(current status: '{consultation.status}')."
            ),
            code="CONSULTATION_NOT_ELIGIBLE_FOR_PRESCRIPTION",
        )

    # Check for existing prescription
    existing = await session.scalar(
        select(Prescription)
        .where(Prescription.consultation_id == consultation_id)
        .options(selectinload(Prescription.items))
        .with_for_update()
    )

    if existing is None:
        # Create fresh prescription (Version 1)
        prescription = Prescription(
            id=uuid.uuid4(),
            consultation_id=consultation.id,
            patient_id=consultation.patient_id,
            doctor_id=consultation.doctor_id,
            notes=payload.notes,
            version=1,
            issued_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(prescription)

        for item_in in payload.items:
            session.add(
                PrescriptionItem(
                    id=uuid.uuid4(),
                    prescription_id=prescription.id,
                    medicine_name=item_in.medicine_name,
                    dosage=item_in.dosage,
                    route=item_in.route,
                    frequency=item_in.frequency,
                    duration=item_in.duration,
                    instructions=item_in.instructions,
                )
            )
        await session.flush()

        # Audit hook without sensitive medication details
        await record_audit_event(
            session,
            action="prescription.create",
            resource_type="prescription",
            resource_id=prescription.id,
            actor_user_id=current_user.id,
            metadata={
                "consultation_id": str(consultation.id),
                "patient_id": str(consultation.patient_id),
                "doctor_id": str(consultation.doctor_id),
                "version": 1,
                "item_count": len(payload.items),
            },
        )

        session.add(
            OutboxEvent(
                event_type="prescription.issued",
                aggregate_type="prescription",
                aggregate_id=prescription.id,
                payload={
                    "prescription_id": str(prescription.id),
                    "consultation_id": str(consultation.id),
                    "doctor_id": str(prescription.doctor_id),
                    "patient_id": str(prescription.patient_id),
                    "version": 1,
                },
            )
        )
        await session.flush()
        target_id = prescription.id

    else:
        # Amendment / correction flow: increment version and replace items atomically
        existing.notes = payload.notes
        existing.version += 1
        existing.updated_at = datetime.now(UTC)

        existing.items.clear()
        for item_in in payload.items:
            existing.items.append(
                PrescriptionItem(
                    id=uuid.uuid4(),
                    prescription_id=existing.id,
                    medicine_name=item_in.medicine_name,
                    dosage=item_in.dosage,
                    route=item_in.route,
                    frequency=item_in.frequency,
                    duration=item_in.duration,
                    instructions=item_in.instructions,
                )
            )
        await session.flush()

        # Audit hook for amendment
        await record_audit_event(
            session,
            action="prescription.amend",
            resource_type="prescription",
            resource_id=existing.id,
            actor_user_id=current_user.id,
            metadata={
                "consultation_id": str(consultation.id),
                "patient_id": str(consultation.patient_id),
                "doctor_id": str(consultation.doctor_id),
                "version": existing.version,
                "item_count": len(payload.items),
            },
        )

        session.add(
            OutboxEvent(
                event_type="prescription.amended",
                aggregate_type="prescription",
                aggregate_id=existing.id,
                payload={
                    "prescription_id": str(existing.id),
                    "consultation_id": str(consultation.id),
                    "doctor_id": str(existing.doctor_id),
                    "patient_id": str(existing.patient_id),
                    "version": existing.version,
                },
            )
        )
        await session.flush()
        target_id = existing.id

    # Reload with items eager-loaded
    loaded = await session.scalar(
        select(Prescription)
        .where(Prescription.id == target_id)
        .options(selectinload(Prescription.items))
    )
    return PrescriptionResponse.model_validate(loaded)


async def get_prescription_by_consultation(
    session: AsyncSession,
    *,
    consultation_id: uuid.UUID,
    current_user: User,
) -> PrescriptionResponse:
    """Retrieve the prescription associated with a consultation subject to authorization."""
    consultation = await session.scalar(
        select(Consultation).where(Consultation.id == consultation_id)
    )
    if consultation is None:
        raise NotFoundError(message="Consultation not found.", code="CONSULTATION_NOT_FOUND")

    caller_doctor_id = None
    if current_user.role == "doctor":
        caller_doctor_id = await _get_doctor_id_for_user(session, current_user.id)

    _authorize_prescription_read(
        patient_id=consultation.patient_id,
        doctor_id=consultation.doctor_id,
        current_user=current_user,
        caller_doctor_id=caller_doctor_id,
    )

    prescription = await session.scalar(
        select(Prescription)
        .where(Prescription.consultation_id == consultation_id)
        .options(selectinload(Prescription.items))
    )
    if prescription is None:
        raise NotFoundError(
            message="Prescription not found for this consultation.",
            code="PRESCRIPTION_NOT_FOUND",
        )

    return PrescriptionResponse.model_validate(prescription)


async def get_prescription_by_id(
    session: AsyncSession,
    *,
    prescription_id: uuid.UUID,
    current_user: User,
) -> PrescriptionResponse:
    """Retrieve a prescription directly by its ID subject to caller authorization."""
    prescription = await session.scalar(
        select(Prescription)
        .where(Prescription.id == prescription_id)
        .options(selectinload(Prescription.items))
    )
    if prescription is None:
        raise NotFoundError(message="Prescription not found.", code="PRESCRIPTION_NOT_FOUND")

    caller_doctor_id = None
    if current_user.role == "doctor":
        caller_doctor_id = await _get_doctor_id_for_user(session, current_user.id)

    _authorize_prescription_read(
        patient_id=prescription.patient_id,
        doctor_id=prescription.doctor_id,
        current_user=current_user,
        caller_doctor_id=caller_doctor_id,
    )

    return PrescriptionResponse.model_validate(prescription)
