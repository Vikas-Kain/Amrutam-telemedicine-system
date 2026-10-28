"""Schemas for payment initiation, status retrieval, and webhook processing."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PaymentStatus(StrEnum):
    """Allowed states for payment transactions."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    REQUIRES_RECONCILIATION = "requires_reconciliation"


class PaymentCreateRequest(BaseModel):
    """Request payload to initiate a consultation payment intent."""

    simulation: str | None = Field(
        default=None,
        description=(
            "Optional simulation mode for evaluation "
            "(e.g. 'success', 'failure', 'timeout', 'pending')"
        ),
    )
    amount_minor: int | None = Field(
        default=None,
        ge=0,
        description="Optional expected consultation fee minor units for client-side assertion",
    )


class PaymentResponse(BaseModel):
    """Payment transaction representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique payment identifier")
    consultation_id: uuid.UUID = Field(..., description="Associated consultation ID")
    amount_minor: int = Field(..., description="Payment amount in minor units (e.g. paise)")
    currency: str = Field(..., description="ISO 4217 three-letter currency code (e.g. INR)")
    status: str = Field(..., description="Payment lifecycle status")
    provider: str = Field(..., description="Payment provider identifier")
    provider_reference: str | None = Field(
        default=None, description="External provider transaction reference"
    )
    created_at: datetime = Field(..., description="Timestamp in UTC when record was created")
    updated_at: datetime = Field(..., description="Timestamp in UTC when record was last updated")


class WebhookEventPayload(BaseModel):
    """Standardized provider webhook callback payload."""

    event_id: str = Field(..., description="Unique webhook event identifier from provider")
    event_type: str = Field(
        ...,
        description=(
            "Event classification (e.g. payment.succeeded, payment.failed, payment.refunded)"
        ),
    )
    provider_reference: str = Field(..., description="External provider payment intent reference")

    amount_minor: int | None = Field(default=None, description="Payment amount in minor units")
    currency: str | None = Field(default="INR", description="Currency code")
