"""Schemas for public doctor profiles and bounded search listings."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DoctorPublicResponse(BaseModel):
    """Public doctor profile representation.

    Strictly shields sensitive information: license_number, user account credentials,
    email, phone number, and internal identifiers are intentionally excluded.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique doctor public identifier")
    name: str = Field(..., description="Doctor's full legal name from verified profile")
    specialization: str = Field(..., description="Primary clinical specialization")
    is_verified: bool = Field(..., description="Whether doctor credentials have been verified")
    consultation_fee_minor: int = Field(
        ...,
        description="Standard consultation fee represented in integer minor units (e.g. paise)",
    )
    currency: str = Field(..., description="ISO 4217 three-letter currency code (e.g. INR)")
    bio: str | None = Field(default=None, description="Public biographical summary")
    created_at: datetime = Field(..., description="Profile creation timestamp in UTC")
    updated_at: datetime = Field(..., description="Profile last update timestamp in UTC")


class DoctorListResponse(BaseModel):
    """Bounded, paginated listing of public doctor profiles with metadata."""

    items: list[DoctorPublicResponse] = Field(
        ...,
        description="Doctor profiles corresponding to the current page",
    )
    total: int = Field(..., description="Total matching doctors matching query filters")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of results per page (bounded 1-100)")
    total_pages: int = Field(..., description="Total number of available pages")
