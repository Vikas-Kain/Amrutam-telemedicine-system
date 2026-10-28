"""Schemas for prescription creation, amendment, and retrieval."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrescriptionItemCreate(BaseModel):
    """Line item specification for a medical prescription."""

    medicine_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Standard or brand medication name",
    )
    dosage: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Medication dosage strength (e.g. 500mg, 10ml)",
    )
    route: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Administration route (e.g. oral, topical, sublingual)",
    )
    frequency: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Intake frequency (e.g. twice daily, every 8 hours)",
    )
    duration: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Treatment duration (e.g. 5 days, 2 weeks)",
    )
    instructions: str | None = Field(
        default=None,
        max_length=2_000,
        description="Optional special clinical instructions for the patient",
    )

    @field_validator("medicine_name", "dosage", "route", "frequency", "duration")
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or purely whitespace.")
        return stripped


class PrescriptionCreate(BaseModel):
    """Request payload for issuing or amending a consultation prescription."""

    notes: str | None = Field(
        default=None,
        max_length=5_000,
        description="Optional clinical notes or diagnosis summary",
    )
    items: list[PrescriptionItemCreate] = Field(
        ...,
        min_length=1,
        description="Structured medication line items (at least one item required)",
    )


class PrescriptionItemResponse(BaseModel):
    """Prescription line item response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prescription_id: uuid.UUID
    medicine_name: str
    dosage: str
    route: str
    frequency: str
    duration: str
    instructions: str | None = None


class PrescriptionResponse(BaseModel):
    """Prescription response model."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    consultation_id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    notes: str | None = None
    version: int
    issued_at: datetime
    created_at: datetime
    updated_at: datetime
    items: list[PrescriptionItemResponse] = Field(default_factory=list)
