"""Payments API endpoints for status retrieval and provider webhooks."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.payment import PaymentResponse, WebhookEventPayload
from app.services.payment_service import get_payment_by_id, process_provider_webhook

router = APIRouter()


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    summary="Retrieve payment status",
    description=(
        "Returns payment details and current status. Automatically reconciles pending/timeout "
        "transactions if required. Accessible to the paying patient, doctor, or administrator."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller lacks permission to view this payment."},
        404: {"description": "Payment was not found."},
    },
)
async def get_payment_endpoint(
    payment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PaymentResponse:
    """Retrieve payment status by ID."""
    return await get_payment_by_id(
        session=session,
        payment_id=payment_id,
        current_user=current_user,
    )


@router.post(
    "/webhooks/{provider}",
    status_code=status.HTTP_200_OK,
    summary="Process external payment provider webhook callback",
    description=(
        "Idempotently processes payment status events from the payment provider adapter. "
        "Verifies HMAC webhook signatures and enforces valid state machine transitions."
    ),
    responses={
        200: {"description": "Webhook processed or replayed successfully."},
        400: {"description": "Malformed payload or unsupported provider/event."},
        401: {"description": "Invalid webhook HMAC signature."},
        404: {"description": "Associated payment record was not found."},
        409: {"description": "Invalid payment state transition."},
    },
)
async def payment_webhook_endpoint(
    provider: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_webhook_signature: Annotated[str | None, Header(alias="X-Webhook-Signature")] = None,
) -> dict[str, str]:
    """Process incoming provider callback with raw payload signature validation."""
    raw_body = await request.body()
    data = json.loads(raw_body)
    payload = WebhookEventPayload.model_validate(data)

    return await process_provider_webhook(
        session=session,
        provider=provider,
        payload_bytes=raw_body,
        signature_header=x_webhook_signature,
        payload=payload,
    )
