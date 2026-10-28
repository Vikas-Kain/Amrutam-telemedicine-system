"""Atomic appointment-booking orchestration.

The caller must keep the supplied session's transaction open until this function returns.
``get_db_session`` does this for HTTP requests: it commits only after the handler completes and
rolls back on an exception.  The idempotency record, slot mutation, consultation, and outbox
event therefore commit (or roll back) together.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.schemas.booking import BookingCreateRequest, BookingResponse
from app.services.idempotency_service import claim_or_replay, record_success

BOOKING_OPERATION = "create_booking"


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
        if idempotency.response_body is None:
            # A completed record without an outcome is corrupt and must not cause a duplicate.
            raise ConflictError(
                code="IDEMPOTENCY_REPLAY_UNAVAILABLE",
                message="The original booking outcome cannot be replayed. Please contact support.",
            )
        return BookingOperationResult(
            booking=BookingResponse.model_validate(idempotency.response_body),
            is_replayed=True,
        )

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
            await session.flush()
    except IntegrityError as error:
        if _is_active_booking_constraint(error):
            raise ConflictError(
                message="The availability slot has already been booked.",
                code="SLOT_NOT_AVAILABLE",
            ) from error
        raise

    return BookingOperationResult(booking=response, is_replayed=False)
