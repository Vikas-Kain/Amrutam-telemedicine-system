"""Schemas for consultation retrieval and lifecycle management."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConsultationStatus(StrEnum):
    """Allowed states in the consultation lifecycle state machine."""

    BOOKED = "booked"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class ConsultationResponse(BaseModel):
    """Consultation entity representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique consultation identifier")
    patient_id: uuid.UUID = Field(..., description="ID of the patient who booked the consultation")
    doctor_id: uuid.UUID = Field(..., description="ID of the assigned doctor")
    slot_id: uuid.UUID = Field(..., description="ID of the reserved availability slot")
    status: str = Field(..., description="Current lifecycle status")
    reason: str | None = Field(default=None, description="Patient appointment reason")
    created_at: datetime = Field(..., description="Creation timestamp in UTC")
    updated_at: datetime = Field(..., description="Last update timestamp in UTC")


class ConsultationListResponse(BaseModel):
    """Bounded, paginated list of consultations."""

    items: list[ConsultationResponse] = Field(..., description="List of consultations on this page")
    total: int = Field(..., description="Total count matching caller scope and filters")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total available pages")
