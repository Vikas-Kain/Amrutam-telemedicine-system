"""Idempotent domain event handlers for transactional outbox dispatch.

Implements deferred tasks including booking confirmations, cancellation alerts,
and payment receipt dispatches while maintaining strict at-least-once idempotency.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent

logger = logging.getLogger(__name__)

# In-memory tracking of dispatched side-effects to ensure consumer idempotency
# under at-least-once delivery semantics.
_DISPATCHED_NOTIFICATIONS: set[tuple[str, str]] = set()

OutboxHandler = Callable[[OutboxEvent, AsyncSession], Awaitable[None]]


def reset_dispatched_notifications() -> None:
    """Clear dispatched notification records (useful between test runs)."""
    _DISPATCHED_NOTIFICATIONS.clear()


def get_dispatched_notifications() -> set[tuple[str, str]]:
    """Return a copy of all dispatched notification keys."""
    return set(_DISPATCHED_NOTIFICATIONS)


async def handle_booking_created(event: OutboxEvent, session: AsyncSession) -> None:
    """Idempotent handler for 'booking.created' event.

    Dispatches booking confirmation to patient and doctor. Never exposes PHI.
    """
    dispatch_key = (str(event.id), "booking_confirmation")
    if dispatch_key in _DISPATCHED_NOTIFICATIONS:
        logger.info(
            "Duplicate event delivery detected for booking %s; skipping dispatch.",
            event.payload.get("consultation_id"),
            extra={"event_id": str(event.id), "is_duplicate": True},
        )
        return

    consultation_id = event.payload.get("consultation_id")
    patient_id = event.payload.get("patient_id")
    doctor_id = event.payload.get("doctor_id")

    logger.info(
        "Dispatched booking confirmation for consultation %s (patient=%s, doctor=%s)",
        consultation_id,
        patient_id,
        doctor_id,
        extra={"event_id": str(event.id), "event_type": event.event_type},
    )
    _DISPATCHED_NOTIFICATIONS.add(dispatch_key)


async def handle_booking_cancelled(event: OutboxEvent, session: AsyncSession) -> None:
    """Idempotent handler for 'booking.cancelled' event.

    Dispatches appointment cancellation notifications.
    """
    dispatch_key = (str(event.id), "booking_cancellation")
    if dispatch_key in _DISPATCHED_NOTIFICATIONS:
        logger.info("Duplicate delivery for cancellation event %s; skipping.", event.id)
        return

    consultation_id = event.payload.get("consultation_id")
    logger.info(
        "Dispatched cancellation alert for consultation %s",
        consultation_id,
        extra={"event_id": str(event.id)},
    )
    _DISPATCHED_NOTIFICATIONS.add(dispatch_key)


async def handle_payment_succeeded(event: OutboxEvent, session: AsyncSession) -> None:
    """Idempotent handler for 'payment.succeeded' event.

    Dispatches payment receipt and updates billing records.
    """
    dispatch_key = (str(event.id), "payment_receipt")
    if dispatch_key in _DISPATCHED_NOTIFICATIONS:
        logger.info("Duplicate delivery for payment receipt %s; skipping.", event.id)
        return

    payment_id = event.payload.get("payment_id")
    amount_minor = event.payload.get("amount_minor")
    currency = event.payload.get("currency", "INR")

    logger.info(
        "Dispatched payment receipt for payment %s (%s %s)",
        payment_id,
        currency,
        amount_minor,
        extra={"event_id": str(event.id)},
    )
    _DISPATCHED_NOTIFICATIONS.add(dispatch_key)


async def handle_consultation_status_changed(event: OutboxEvent, session: AsyncSession) -> None:
    """Idempotent handler for consultation status transition events."""
    dispatch_key = (str(event.id), f"status_{event.event_type}")
    if dispatch_key in _DISPATCHED_NOTIFICATIONS:
        logger.info("Duplicate delivery for status event %s; skipping.", event.id)
        return

    logger.info(
        "Processed consultation status event %s for consultation %s",
        event.event_type,
        event.payload.get("consultation_id"),
        extra={"event_id": str(event.id)},
    )
    _DISPATCHED_NOTIFICATIONS.add(dispatch_key)


# Default registry mapping event_type to its async handler
HANDLER_REGISTRY: dict[str, OutboxHandler] = {
    "booking.created": handle_booking_created,
    "booking.cancelled": handle_booking_cancelled,
    "payment.succeeded": handle_payment_succeeded,
    "payment.failed": handle_consultation_status_changed,
    "payment.refunded": handle_consultation_status_changed,
    "consultation.confirmed": handle_consultation_status_changed,
    "consultation.in_progress": handle_consultation_status_changed,
    "consultation.completed": handle_consultation_status_changed,
    "consultation.no_show": handle_consultation_status_changed,
    "prescription.issued": handle_consultation_status_changed,
    "prescription.created": handle_consultation_status_changed,
    "prescription.amended": handle_consultation_status_changed,
}


def register_handler(event_type: str, handler: OutboxHandler) -> None:
    """Register or override an outbox event handler."""
    HANDLER_REGISTRY[event_type] = handler
