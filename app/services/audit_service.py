"""Audit service interface for recording security and operational events."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record_audit_event(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record a tamper-evident audit log entry within the current transaction."""
    entry = AuditLog(
        id=uuid.uuid4(),
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        correlation_id=correlation_id,
        metadata_=metadata,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    return entry
