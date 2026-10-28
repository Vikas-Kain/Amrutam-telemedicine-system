"""Request and response contracts for appointment booking."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BookingCreateRequest(BaseModel):
    """A patient's request to reserve one specific doctor availability slot."""

    doctor_id: uuid.UUID = Field(..., description="Doctor who owns the requested slot")
    slot_id: uuid.UUID = Field(..., description="Availability slot to reserve")
    reason: str | None = Field(
        default=None,
        max_length=2_000,
        description="Optional patient-provided reason for the appointment",
    )


class BookingResponse(BaseModel):
    """The consultation created by a successful booking operation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    slot_id: uuid.UUID
    status: str
    reason: str | None = None
    created_at: datetime
    updated_at: datetime
