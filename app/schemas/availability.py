"""Schemas for doctor availability slots and time intervals."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SlotBase(BaseModel):
    """Base schema for availability time slots with timezone handling."""

    start_at: datetime = Field(
        ...,
        description="Slot start timestamp in UTC (ISO-8601)",
        examples=["2026-10-30T09:00:00Z"],
    )
    end_at: datetime = Field(
        ...,
        description="Slot end timestamp in UTC (ISO-8601)",
        examples=["2026-10-30T09:30:00Z"],
    )

    @field_validator("start_at", "end_at")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime) -> datetime:
        """Ensure all timestamps are timezone-aware and normalized to UTC."""
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class SlotCreateRequest(SlotBase):
    """Payload to create an availability time slot."""

    @field_validator("end_at")
    @classmethod
    def validate_interval(cls, v: datetime, info) -> datetime:
        """Validate end_at is strictly after start_at and bounds duration."""
        start_at = info.data.get("start_at")
        if start_at:
            if v <= start_at:
                raise ValueError("Slot end_at must be strictly after start_at.")
            duration_seconds = (v - start_at).total_seconds()
            if duration_seconds < 600:  # Minimum 10 minutes
                raise ValueError("Slot duration must be at least 10 minutes.")
            if duration_seconds > 14400:  # Maximum 4 hours
                raise ValueError("Slot duration cannot exceed 4 hours.")
        return v


class SlotBatchCreateRequest(BaseModel):
    """Payload to create multiple availability slots in a single atomic request."""

    slots: list[SlotCreateRequest] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of availability slot intervals (minimum 1, maximum 50)",
    )


class SlotUpdateRequest(BaseModel):
    """Payload to update an unbooked availability slot."""

    start_at: datetime | None = Field(
        default=None,
        description="Updated slot start timestamp in UTC",
        examples=["2026-10-30T10:00:00Z"],
    )
    end_at: datetime | None = Field(
        default=None,
        description="Updated slot end timestamp in UTC",
        examples=["2026-10-30T10:30:00Z"],
    )
    status: Literal["available", "blocked"] | None = Field(
        default=None,
        description="Updated slot status ('available' or 'blocked')",
        examples=["blocked"],
    )

    @field_validator("start_at", "end_at")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime | None) -> datetime | None:
        """Ensure all timestamps are timezone-aware and normalized to UTC."""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class SlotResponse(BaseModel):
    """Public representation of an availability slot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique slot identifier")
    doctor_id: uuid.UUID = Field(..., description="Doctor identifier")
    start_at: datetime = Field(..., description="Slot start timestamp in UTC")
    end_at: datetime = Field(..., description="Slot end timestamp in UTC")
    status: str = Field(..., description="Slot status ('available', 'booked', 'blocked')")
    created_at: datetime = Field(..., description="Slot creation timestamp in UTC")
    updated_at: datetime = Field(..., description="Slot last update timestamp in UTC")


class SlotListResponse(BaseModel):
    """Envelope for listing doctor availability slots."""

    items: list[SlotResponse] = Field(..., description="List of availability slots")
    total: int = Field(..., description="Total matching slots count")
