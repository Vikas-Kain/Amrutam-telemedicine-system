"""Doctor availability slots lifecycle, validation, and persistence services."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import User
from app.schemas.availability import SlotCreateRequest, SlotUpdateRequest

logger = logging.getLogger(__name__)


async def get_doctor_by_user_id(session: AsyncSession, user_id: uuid.UUID) -> Doctor | None:
    """Retrieve the doctor profile associated with a user account."""
    stmt = select(Doctor).where(Doctor.user_id == user_id)
    return await session.scalar(stmt)


async def create_doctor_slots(
    session: AsyncSession,
    doctor: Doctor,
    slot_requests: list[SlotCreateRequest],
) -> list[AvailabilitySlot]:
    """Create one or more availability slots for a doctor in a single atomic transaction.

    Enforces:
    - Rejection of past intervals.
    - Rejection of internal overlaps within the batch.
    - Rejection of database overlaps for the same doctor.
    - PostgreSQL EXCLUDE constraint handling.
    """
    now = datetime.now(UTC)

    # 1. Reject past intervals
    for item in slot_requests:
        if item.start_at < now:
            raise BadRequestError(
                message="Cannot create availability slots in the past.",
                code="PAST_SLOT_NOT_ALLOWED",
            )

    # 2. Reject internal overlaps within the request batch
    sorted_items = sorted(slot_requests, key=lambda s: s.start_at)
    for i in range(len(sorted_items) - 1):
        if sorted_items[i].end_at > sorted_items[i + 1].start_at:
            raise ConflictError(
                message="Incoming slot list contains overlapping intervals.",
                code="SLOT_OVERLAP",
            )

    # 3. Check for database overlaps with existing slots for this doctor
    overlap_conditions = [
        and_(
            AvailabilitySlot.start_at < item.end_at,
            AvailabilitySlot.end_at > item.start_at,
        )
        for item in slot_requests
    ]
    overlap_query = (
        select(AvailabilitySlot.id)
        .where(
            AvailabilitySlot.doctor_id == doctor.id,
            or_(*overlap_conditions),
        )
        .limit(1)
    )
    existing_overlap = await session.scalar(overlap_query)
    if existing_overlap is not None:
        raise ConflictError(
            message="Slot interval overlaps with an existing slot for this doctor.",
            code="SLOT_OVERLAP",
        )

    # 4. Insert slots in a database transaction
    created_slots = [
        AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doctor.id,
            start_at=item.start_at,
            end_at=item.end_at,
            status="available",
            created_at=now,
            updated_at=now,
        )
        for item in sorted_items
    ]
    session.add_all(created_slots)

    try:
        await session.flush()
        if session.in_transaction():
            await session.commit()
    except IntegrityError as exc:
        if session.in_transaction():
            await session.rollback()
        logger.info("Slot creation aborted due to constraint violation: %s", type(exc).__name__)
        raise ConflictError(
            message="Slot interval overlaps with an existing slot or violates constraints.",
            code="SLOT_OVERLAP",
        ) from exc

    for slot in created_slots:
        await session.refresh(slot)

    logger.info(
        "Created %d availability slots for doctor %s",
        len(created_slots),
        doctor.id,
        extra={"doctor_id": str(doctor.id), "count": len(created_slots)},
    )
    return created_slots


async def list_doctor_slots(
    session: AsyncSession,
    doctor_id: uuid.UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_filter: str | None = "available",
) -> list[AvailabilitySlot]:
    """Retrieve availability slots for a doctor with optional range and status filters."""
    # Ensure doctor exists
    doc = await session.scalar(select(Doctor.id).where(Doctor.id == doctor_id))
    if doc is None:
        raise NotFoundError("Doctor not found.", code="DOCTOR_NOT_FOUND")

    stmt = select(AvailabilitySlot).where(AvailabilitySlot.doctor_id == doctor_id)

    if status_filter:
        stmt = stmt.where(AvailabilitySlot.status == status_filter)

    if date_from:
        stmt = stmt.where(AvailabilitySlot.end_at >= date_from)

    if date_to:
        stmt = stmt.where(AvailabilitySlot.start_at <= date_to)

    stmt = stmt.order_by(AvailabilitySlot.start_at.asc(), AvailabilitySlot.id.asc())

    result = await session.scalars(stmt)
    return list(result.all())


async def update_doctor_slot(
    session: AsyncSession,
    slot_id: uuid.UUID,
    current_user: User,
    update_data: SlotUpdateRequest,
) -> AvailabilitySlot:
    """Update slot interval or mark blocked/available.

    Enforces:
    - Resource authorization (owning doctor or admin).
    - Rejection of edits on booked slots.
    - Valid interval rules (future start_at, duration bounds).
    - Overlap checks against existing doctor slots.
    """
    slot = await session.scalar(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id))
    if slot is None:
        raise NotFoundError("Availability slot not found.", code="SLOT_NOT_FOUND")

    # Enforce ownership: only owning doctor or admin
    if current_user.role != "admin":
        doctor = await get_doctor_by_user_id(session, current_user.id)
        if doctor is None or slot.doctor_id != doctor.id:
            raise ForbiddenError(
                message="You do not have permission to modify this availability slot.",
                code="FORBIDDEN",
            )

    # Booked slots cannot be casually modified
    if slot.status == "booked":
        raise ConflictError(
            message="Cannot edit an availability slot that has already been booked.",
            code="SLOT_ALREADY_BOOKED",
        )

    # If updating interval timestamps
    if update_data.start_at is not None or update_data.end_at is not None:
        new_start = update_data.start_at if update_data.start_at is not None else slot.start_at
        new_end = update_data.end_at if update_data.end_at is not None else slot.end_at

        if new_end <= new_start:
            raise BadRequestError(
                message="Slot end_at must be strictly after start_at.",
                code="INVALID_INTERVAL",
            )

        duration = (new_end - new_start).total_seconds()
        if duration < 600 or duration > 14400:
            raise BadRequestError(
                message="Slot duration must be between 10 minutes and 4 hours.",
                code="INVALID_INTERVAL",
            )

        if new_start < datetime.now(UTC):
            raise BadRequestError(
                message="Cannot update an availability slot into the past.",
                code="PAST_SLOT_NOT_ALLOWED",
            )

        # Check overlap against other slots for this doctor
        overlap_stmt = (
            select(AvailabilitySlot.id)
            .where(
                AvailabilitySlot.doctor_id == slot.doctor_id,
                AvailabilitySlot.id != slot.id,
                AvailabilitySlot.start_at < new_end,
                AvailabilitySlot.end_at > new_start,
            )
            .limit(1)
        )
        existing_overlap = await session.scalar(overlap_stmt)
        if existing_overlap is not None:
            raise ConflictError(
                message="Updated interval overlaps with an existing slot for this doctor.",
                code="SLOT_OVERLAP",
            )

        slot.start_at = new_start
        slot.end_at = new_end

    # If updating status
    if update_data.status is not None:
        slot.status = update_data.status

    try:
        await session.flush()
        if session.in_transaction():
            await session.commit()
    except IntegrityError as exc:
        if session.in_transaction():
            await session.rollback()
        raise ConflictError(
            message="Updated interval overlaps with an existing slot or violates constraints.",
            code="SLOT_OVERLAP",
        ) from exc

    await session.refresh(slot)
    return slot


async def delete_doctor_slot(
    session: AsyncSession,
    slot_id: uuid.UUID,
    current_user: User,
) -> None:
    """Delete an unbooked availability slot.

    Enforces:
    - Resource authorization (owning doctor or admin).
    - Booked slots cannot be deleted.
    """
    slot = await session.scalar(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id))
    if slot is None:
        raise NotFoundError("Availability slot not found.", code="SLOT_NOT_FOUND")

    # Enforce ownership: only owning doctor or admin
    if current_user.role != "admin":
        doctor = await get_doctor_by_user_id(session, current_user.id)
        if doctor is None or slot.doctor_id != doctor.id:
            raise ForbiddenError(
                message="You do not have permission to delete this availability slot.",
                code="FORBIDDEN",
            )

    # Booked slots cannot be casually deleted
    if slot.status == "booked":
        raise ConflictError(
            message="Cannot delete an availability slot that has already been booked.",
            code="SLOT_ALREADY_BOOKED",
        )

    await session.delete(slot)
    if session.in_transaction():
        await session.commit()
