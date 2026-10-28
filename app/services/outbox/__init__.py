"""Outbox service package."""

from app.services.outbox.handlers import (
    HANDLER_REGISTRY,
    handle_booking_cancelled,
    handle_booking_created,
    handle_consultation_status_changed,
    handle_payment_succeeded,
    register_handler,
    reset_dispatched_notifications,
)
from app.services.outbox.worker import OutboxWorker

__all__ = [
    "HANDLER_REGISTRY",
    "OutboxWorker",
    "handle_booking_cancelled",
    "handle_booking_created",
    "handle_consultation_status_changed",
    "handle_payment_succeeded",
    "register_handler",
    "reset_dispatched_notifications",
]
