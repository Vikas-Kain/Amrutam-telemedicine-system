"""Idempotency schemas, status enumeration, and operation result contracts."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IdempotencyStatus(StrEnum):
    """Lifecycle states for idempotent operation claims."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IdempotencyResult(BaseModel):
    """Encapsulates the claim or replay outcome of an idempotency evaluation."""

    model_config = ConfigDict(frozen=True)

    is_replayed: bool = Field(
        ...,
        description="True if the request matched a completed execution and was replayed",
    )
    key: str = Field(..., description="The client-provided idempotency key")
    operation: str = Field(..., description="The operation identifier/route")
    status: IdempotencyStatus = Field(..., description="Current status of the idempotency record")
    response_code: int | None = Field(
        default=None,
        description="HTTP response status code stored from the original completed execution",
    )
    response_body: dict[str, Any] | None = Field(
        default=None,
        description="Serialized JSON response body stored from the original completed execution",
    )
    resource_id: uuid.UUID | None = Field(
        default=None,
        description="Primary entity UUID created or modified by the idempotent operation",
    )
    idempotency_record_id: uuid.UUID | None = Field(
        default=None,
        description="Database primary key of the idempotency persistence record",
    )


class IdempotencyRecordResponse(BaseModel):
    """Public representation of an idempotency record for audit and inspection."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    key: str
    operation: str
    request_hash: str
    status: IdempotencyStatus
    response_code: int | None = None
    resource_id: uuid.UUID | None = None
    expires_at: datetime
    created_at: datetime
