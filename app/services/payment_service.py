"""Payment domain service managing idempotent payment intent initiation, status retrieval,
and webhooks.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.outbox import OutboxEvent
from app.models.payment import Payment
from app.models.user import User
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentResponse,
    WebhookEventPayload,
)
from app.services.audit_service import record_audit_event
from app.services.idempotency_service import claim_or_replay, record_success
from app.services.payment_provider import (
    MockPaymentProviderAdapter,
    PaymentProviderAdapter,
)

PAYMENT_OPERATION = "initiate_payment"


async def initiate_consultation_payment(
    session: AsyncSession,
    *,
    consultation_id: uuid.UUID,
    payload: PaymentCreateRequest,
    current_user: User,
    idempotency_key: str,
    provider_adapter: PaymentProviderAdapter | None = None,
) -> PaymentResponse:
    """Initiate payment intent with simulated provider outside long database transactions."""
    # 1. Claim or replay idempotency
    idempotency = await claim_or_replay(
        session=session,
        user_id=current_user.id,
        key=idempotency_key,
        operation=PAYMENT_OPERATION,
        payload={"consultation_id": str(consultation_id), **payload.model_dump(mode="json")},
    )
    if idempotency.is_replayed:
        if idempotency.response_body is None:
            raise ConflictError(
                code="IDEMPOTENCY_REPLAY_UNAVAILABLE",
                message="The original payment outcome cannot be replayed. Please contact support.",
            )
        return PaymentResponse.model_validate(idempotency.response_body)

    # 2. Short read check for consultation and authorization
    consultation = await session.scalar(
        select(Consultation).where(Consultation.id == consultation_id)
    )
    if consultation is None:
        raise NotFoundError(message="Consultation not found.", code="CONSULTATION_NOT_FOUND")

    if current_user.role != "patient" or consultation.patient_id != current_user.id:
        raise ForbiddenError(
            message="Only the patient who booked this consultation can pay for it.",
            code="PAYMENT_FORBIDDEN",
        )

    if consultation.status in ("cancelled", "no_show"):
        raise ConflictError(
            message=f"Cannot pay for consultation in '{consultation.status}' state.",
            code="CONSULTATION_INELIGIBLE_FOR_PAYMENT",
        )

    # Check if payment already succeeded
    existing_succeeded = await session.scalar(
        select(Payment).where(
            Payment.consultation_id == consultation_id,
            Payment.status == "succeeded",
        )
    )
    if existing_succeeded is not None:
        raise ConflictError(
            message="This consultation has already been paid.",
            code="CONSULTATION_ALREADY_PAID",
        )

    doctor = await session.scalar(select(Doctor).where(Doctor.id == consultation.doctor_id))
    amount_minor = doctor.consultation_fee_minor if doctor else 1_000
    currency = doctor.currency if doctor else "INR"

    if payload.amount_minor is not None and payload.amount_minor != amount_minor:
        raise ConflictError(
            message=(
                f"Specified amount '{payload.amount_minor}' does not match "
                f"consultation fee '{amount_minor}'."
            ),
            code="PAYMENT_AMOUNT_MISMATCH",
        )

    # 3. External provider intent creation call outside DB transaction lock
    adapter = provider_adapter or MockPaymentProviderAdapter()
    intent_result = await adapter.create_payment_intent(
        amount_minor=amount_minor,
        currency=currency,
        idempotency_key=idempotency_key,
        metadata={
            "consultation_id": str(consultation_id),
            "patient_id": str(current_user.id),
        },
        simulation=payload.simulation,
    )

    # 4. Record payment in database
    payment = Payment(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        amount_minor=amount_minor,
        currency=currency,
        status=intent_result.status.value,
        provider=intent_result.provider,
        provider_reference=intent_result.provider_reference,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(payment)
    await session.flush()

    # Record safe audit event
    await record_audit_event(
        session,
        action="payment.initiate",
        resource_type="payment",
        resource_id=payment.id,
        actor_user_id=current_user.id,
        metadata={
            "consultation_id": str(consultation.id),
            "amount_minor": amount_minor,
            "currency": currency,
            "status": payment.status,
            "provider": payment.provider,
        },
    )

    # Record outbox event
    session.add(
        OutboxEvent(
            event_type=f"payment.{payment.status}",
            aggregate_type="payment",
            aggregate_id=payment.id,
            payload={
                "payment_id": str(payment.id),
                "consultation_id": str(consultation.id),
                "amount_minor": amount_minor,
                "currency": currency,
                "status": payment.status,
            },
        )
    )

    # Record idempotency success
    response = PaymentResponse.model_validate(payment)
    status_code = 201 if payment.status == "succeeded" else 200
    await record_success(
        session=session,
        record_id=idempotency.idempotency_record_id,
        response_code=status_code,
        response_body=response.model_dump(mode="json"),
        resource_id=payment.id,
    )
    await session.flush()

    return response


async def get_payment_by_id(
    session: AsyncSession,
    *,
    payment_id: uuid.UUID,
    current_user: User,
    provider_adapter: PaymentProviderAdapter | None = None,
) -> PaymentResponse:
    """Retrieve payment status subject to caller authorization and reconcile timeouts."""
    payment = await session.scalar(
        select(Payment).where(Payment.id == payment_id).options(selectinload(Payment.consultation))
    )
    if payment is None:
        raise NotFoundError(message="Payment not found.", code="PAYMENT_NOT_FOUND")

    # Authorize caller
    consultation = payment.consultation
    if current_user.role != "admin":
        if current_user.role == "patient" and consultation.patient_id != current_user.id:
            raise ForbiddenError(
                message="You do not have permission to view this payment.",
                code="PAYMENT_ACCESS_FORBIDDEN",
            )
        if current_user.role == "doctor":
            doctor_id = await session.scalar(
                select(Doctor.id).where(Doctor.user_id == current_user.id)
            )
            if doctor_id != consultation.doctor_id:
                raise ForbiddenError(
                    message="You do not have permission to view this payment.",
                    code="PAYMENT_ACCESS_FORBIDDEN",
                )

    # Reconcile timeout/unknown state if needed
    if payment.status == "requires_reconciliation" and payment.provider_reference:
        adapter = provider_adapter or MockPaymentProviderAdapter()
        reconciled = await adapter.reconcile_payment(provider_reference=payment.provider_reference)
        payment.status = reconciled.status.value
        payment.updated_at = datetime.now(UTC)

        await record_audit_event(
            session,
            action="payment.reconciled",
            resource_type="payment",
            resource_id=payment.id,
            actor_user_id=current_user.id,
            metadata={
                "provider_reference": payment.provider_reference,
                "status": payment.status,
            },
        )
        await session.flush()

    return PaymentResponse.model_validate(payment)


async def process_provider_webhook(
    session: AsyncSession,
    *,
    provider: str,
    payload_bytes: bytes,
    signature_header: str | None,
    payload: WebhookEventPayload,
    provider_adapter: PaymentProviderAdapter | None = None,
) -> dict[str, str]:
    """Process incoming provider callback idempotently with HMAC signature verification."""
    if provider != MockPaymentProviderAdapter.PROVIDER_NAME:
        raise BadRequestError(
            message=f"Unsupported payment provider '{provider}'.",
            code="UNSUPPORTED_PROVIDER",
        )

    adapter = provider_adapter or MockPaymentProviderAdapter()
    if not adapter.verify_webhook_signature(
        payload_bytes=payload_bytes,
        signature_header=signature_header or "",
        secret=MockPaymentProviderAdapter.DEFAULT_SECRET,
    ):
        raise UnauthorizedError(
            message="Invalid webhook signature.",
            code="INVALID_WEBHOOK_SIGNATURE",
        )

    # Lock payment record
    payment = await session.scalar(
        select(Payment)
        .where(Payment.provider_reference == payload.provider_reference)
        .with_for_update()
    )
    if payment is None:
        raise NotFoundError(
            message="Payment record not found for provider reference.",
            code="PAYMENT_NOT_FOUND",
        )

    # Map webhook event type to target payment status
    event_status_map = {
        "payment.succeeded": "succeeded",
        "payment.failed": "failed",
        "payment.refunded": "refunded",
    }
    target_status = event_status_map.get(payload.event_type)
    if not target_status:
        raise BadRequestError(
            message=f"Unsupported event type '{payload.event_type}'.",
            code="UNSUPPORTED_EVENT_TYPE",
        )

    # Idempotent replay: already in target status
    if payment.status == target_status:
        return {"status": "already_processed", "current_status": payment.status}

    allowed_from_map = {
        "succeeded": ["pending", "requires_reconciliation"],
        "failed": ["pending", "requires_reconciliation"],
        "refunded": ["succeeded"],
    }
    allowed_from = allowed_from_map.get(target_status, [])
    if payment.status not in allowed_from:
        raise ConflictError(
            message=f"Cannot transition payment from '{payment.status}' to '{target_status}'.",
            code="PAYMENT_INVALID_TRANSITION",
        )

    payment.status = target_status
    payment.updated_at = datetime.now(UTC)
    await session.flush()

    await record_audit_event(
        session,
        action=f"payment.{target_status}",
        resource_type="payment",
        resource_id=payment.id,
        metadata={
            "event_id": payload.event_id,
            "provider": provider,
            "status": target_status,
        },
    )

    session.add(
        OutboxEvent(
            event_type=f"payment.{target_status}",
            aggregate_type="payment",
            aggregate_id=payment.id,
            payload={
                "payment_id": str(payment.id),
                "consultation_id": str(payment.consultation_id),
                "status": target_status,
            },
        )
    )
    await session.flush()

    return {"status": "processed", "payment_status": target_status}
