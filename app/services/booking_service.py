"""Atomic appointment-booking orchestration.

The caller must keep the supplied session's transaction open until this function returns.
``get_db_session`` does this for HTTP requests: it commits only after the handler completes and
rolls back on an exception.  The idempotency record, slot mutation, consultation, and outbox
event therefore commit (or roll back) together.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.schemas.booking import BookingCreateRequest, BookingResponse
from app.services.audit_service import record_audit_event
from app.services.idempotency_service import claim_or_replay, record_success

BOOKING_OPERATION = "create_booking"
CANCELLATION_OPERATION = "cancel_booking"


@dataclass(frozen=True)
class BookingOperationResult:
    """A booking response plus whether it was produced from a completed replay."""

    booking: BookingResponse
    is_replayed: bool


def _booking_payload(payload: BookingCreateRequest) -> dict[str, object]:
    """Return the complete canonical request body used by idempotency fingerprinting."""
    return payload.model_dump(mode="json")


def _is_active_booking_constraint(error: IntegrityError) -> bool:
    """Return whether an integrity error came from the active-slot unique index."""
    diagnostics = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostics, "constraint_name", None) == "uq_consultations_active_slot"


async def _authorize_booking_access(
    *,
    session: AsyncSession,
    booking: Consultation,
    current_user: User,
) -> None:
    """Enforce booking retrieval/cancellation policy without relying on route names alone."""
    if current_user.role == "admin":
        return
    if current_user.role == "patient" and booking.patient_id == current_user.id:
        return
    if current_user.role == "doctor":
        doctor_id = await session.scalar(select(Doctor.id).where(Doctor.user_id == current_user.id))
        if doctor_id == booking.doctor_id:
            return
    raise ForbiddenError(
        message="You do not have permission to access this booking.",
        code="BOOKING_ACCESS_FORBIDDEN",
    )


async def get_booking(
    *,
    session: AsyncSession,
    booking_id: uuid.UUID,
    current_user: User,
) -> BookingResponse:
    """Return a booking only to its patient, assigned doctor, or an administrator."""
    booking = await session.scalar(select(Consultation).where(Consultation.id == booking_id))
    if booking is None:
        raise NotFoundError(message="Booking not found.", code="BOOKING_NOT_FOUND")
    await _authorize_booking_access(session=session, booking=booking, current_user=current_user)
    return BookingResponse.model_validate(booking)


async def _replay_booking_result(idempotency_response: object) -> BookingOperationResult:
    """Convert a completed idempotency outcome to a typed booking response."""
    response_body = getattr(idempotency_response, "response_body", None)
    if response_body is None:
        raise ConflictError(
            code="IDEMPOTENCY_REPLAY_UNAVAILABLE",
            message="The original booking outcome cannot be replayed. Please contact support.",
        )
    return BookingOperationResult(
        booking=BookingResponse.model_validate(response_body),
        is_replayed=True,
    )


async def create_booking(
    *,
    session: AsyncSession,
    patient: User,
    payload: BookingCreateRequest,
    idempotency_key: str,
) -> BookingOperationResult:
    """Atomically reserve an available slot and persist its idempotent response.

    A row lock serializes contenders for a slot, while the partial unique index on
    ``consultations.slot_id`` protects the invariant independently at the database level.
    No remote work is performed in this transaction.
    """
    idempotency = await claim_or_replay(
        session=session,
        user_id=patient.id,
        key=idempotency_key,
        operation=BOOKING_OPERATION,
        payload=_booking_payload(payload),
    )

    if idempotency.is_replayed:
        return await _replay_booking_result(idempotency)

    # The idempotency claim is deliberately in the same transaction as the slot reservation.
    # This locks the specific row before observing its state, so two patients cannot both book it.
    slot = await session.scalar(
        select(AvailabilitySlot).where(AvailabilitySlot.id == payload.slot_id).with_for_update()
    )
    if slot is None:
        raise NotFoundError(message="Availability slot not found.", code="SLOT_NOT_FOUND")
    if slot.doctor_id != payload.doctor_id:
        raise ConflictError(
            message="The availability slot does not belong to the requested doctor.",
            code="SLOT_DOCTOR_MISMATCH",
        )
    if slot.status != "available" or slot.start_at <= datetime.now(UTC):
        raise ConflictError(
            message="The availability slot is no longer bookable.",
            code="SLOT_NOT_AVAILABLE",
        )

    consultation = Consultation(
        patient_id=patient.id,
        doctor_id=payload.doctor_id,
        slot_id=slot.id,
        status="booked",
        reason=payload.reason,
    )

    try:
        # A savepoint maps the expected unique-index race without invalidating the caller's
        # surrounding transaction.  Other integrity errors remain visible as operational faults.
        async with session.begin_nested():
            slot.status = "booked"
            session.add(consultation)
            await session.flush()

            response = BookingResponse.model_validate(consultation)
            await record_success(
                session=session,
                record_id=idempotency.idempotency_record_id,
                response_code=201,
                response_body=response.model_dump(mode="json"),
                resource_id=consultation.id,
            )
            # Keep the event deliberately free of the appointment reason or other clinical data.
            session.add(
                OutboxEvent(
                    event_type="booking.created",
                    aggregate_type="consultation",
                    aggregate_id=consultation.id,
                    payload={
                        "consultation_id": str(consultation.id),
                        "doctor_id": str(consultation.doctor_id),
                        "slot_id": str(consultation.slot_id),
                    },
                )
            )
            await record_audit_event(
                session,
                action="booking.create",
                resource_type="consultation",
                resource_id=consultation.id,
                actor_user_id=patient.id,
                metadata={
                    "doctor_id": str(payload.doctor_id),
                    "slot_id": str(slot.id),
                },
            )
            await session.flush()
    except IntegrityError as error:
        if _is_active_booking_constraint(error):
            raise ConflictError(
                message="The availability slot has already been booked.",
                code="SLOT_NOT_AVAILABLE",
            ) from error
        raise

    return BookingOperationResult(booking=response, is_replayed=False)


async def cancel_booking(
    *,
    session: AsyncSession,
    booking_id: uuid.UUID,
    current_user: User,
    idempotency_key: str,
) -> BookingOperationResult:
    """Cancel an eligible booking and release its slot in the same transaction.

    Patients may cancel only their own future, ``booked`` consultations; administrators may
    perform the same operational action. A previously cancelled consultation is preserved and
    returned as a successful idempotent result. Assigned doctors may read a booking but cannot
    cancel it in this milestone.
    """
    idempotency = await claim_or_replay(
        session=session,
        user_id=current_user.id,
        key=idempotency_key,
        operation=CANCELLATION_OPERATION,
        payload={"booking_id": str(booking_id)},
    )
    if idempotency.is_replayed:
        return await _replay_booking_result(idempotency)

    booking = await session.scalar(
        select(Consultation).where(Consultation.id == booking_id).with_for_update()
    )
    if booking is None:
        raise NotFoundError(message="Booking not found.", code="BOOKING_NOT_FOUND")
    await _authorize_booking_access(session=session, booking=booking, current_user=current_user)

    if booking.status == "cancelled":
        response = BookingResponse.model_validate(booking)
        await record_success(
            session=session,
            record_id=idempotency.idempotency_record_id,
            response_code=200,
            response_body=response.model_dump(mode="json"),
            resource_id=booking.id,
        )
        return BookingOperationResult(booking=response, is_replayed=False)
    if booking.status != "booked":
        raise ConflictError(
            message="Only bookings that have not progressed beyond booked can be cancelled.",
            code="BOOKING_CANCELLATION_NOT_ALLOWED",
        )

    slot = await session.scalar(
        select(AvailabilitySlot).where(AvailabilitySlot.id == booking.slot_id).with_for_update()
    )
    if slot is None or slot.doctor_id != booking.doctor_id or slot.status != "booked":
        raise ConflictError(
            message="The booking slot is not in a cancellable state.",
            code="BOOKING_SLOT_STATE_INCONSISTENT",
        )
    if slot.start_at <= datetime.now(UTC):
        raise ConflictError(
            message="A booking cannot be cancelled after its slot has started.",
            code="BOOKING_CANCELLATION_WINDOW_CLOSED",
        )

    async with session.begin_nested():
        booking.status = "cancelled"
        slot.status = "available"
        await session.flush()

        response = BookingResponse.model_validate(booking)
        await record_success(
            session=session,
            record_id=idempotency.idempotency_record_id,
            response_code=200,
            response_body=response.model_dump(mode="json"),
            resource_id=booking.id,
        )
        session.add(
            OutboxEvent(
                event_type="booking.cancelled",
                aggregate_type="consultation",
                aggregate_id=booking.id,
                payload={
                    "consultation_id": str(booking.id),
                    "doctor_id": str(booking.doctor_id),
                    "slot_id": str(booking.slot_id),
                },
            )
        )
        await record_audit_event(
            session,
            action="booking.cancel",
            resource_type="consultation",
            resource_id=booking.id,
            actor_user_id=current_user.id,
            metadata={
                "doctor_id": str(booking.doctor_id),
                "slot_id": str(booking.slot_id),
                "status": "cancelled",
                "actor_role": current_user.role,
            },
        )
        await session.flush()

    return BookingOperationResult(booking=response, is_replayed=False)
