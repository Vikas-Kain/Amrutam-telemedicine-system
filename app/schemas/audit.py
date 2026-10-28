"""Audit log schemas for administrative review and compliance reporting."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogResponse(BaseModel):
    """Schema representing an immutable, tamper-evident audit log entry."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID = Field(..., description="Unique audit event UUID")
    actor_user_id: uuid.UUID | None = Field(
        default=None, description="User UUID of the actor who performed the action"
    )
    action: str = Field(..., description="Action classification identifier (e.g. booking.create)")
    resource_type: str = Field(..., description="Target entity type (e.g. consultation, payment)")
    resource_id: uuid.UUID | None = Field(
        default=None, description="Target entity UUID if applicable"
    )
    correlation_id: str | None = Field(
        default=None, description="Request or correlation trace identifier"
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="metadata_",
        description="Safe, allowlisted operational metadata with sensitive details redacted",
    )
    created_at: datetime = Field(..., description="UTC timestamp when the event was recorded")


class AuditLogListResponse(BaseModel):
    """Paginated collection of audit log entries."""

    items: list[AuditLogResponse] = Field(..., description="List of audit log records")
    total: int = Field(..., ge=0, description="Total matching records count")
    page: int = Field(..., ge=1, description="Current page number")
    page_size: int = Field(..., ge=1, le=100, description="Page size limit")
    total_pages: int = Field(..., ge=0, description="Total pages count")
