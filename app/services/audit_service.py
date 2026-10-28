"""Audit trail service managing tamper-evident security logging and administrative review."""

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.core.logging import correlation_id_ctx_var, request_id_ctx_var
from app.models.audit import AuditLog
from app.models.user import User

# Substrings that must never appear in audit metadata keys to protect credentials and PHI
SENSITIVE_KEY_SUBSTRINGS: set[str] = {
    "password",
    "token",
    "secret",
    "mfa",
    "prescription",
    "diagnosis",
    "item",
    "items",
    "note",
    "notes",
    "medicine",
    "dosage",
    "instruction",
    "cvv",
    "pan",
    "card",
    "cookie",
    "auth",
    "credential",
    "body",
    "payload",
}

# Explicitly allowlisted operational metadata keys
ALLOWLISTED_METADATA_KEYS: set[str] = {
    "doctor_id",
    "slot_id",
    "consultation_id",
    "patient_id",
    "previous_status",
    "new_status",
    "status",
    "version",
    "item_count",
    "amount_minor",
    "currency",
    "provider",
    "provider_reference",
    "actor_role",
    "action",
    "slot_count",
    "event_id",
    "page",
    "page_size",
}


def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sanitize and allowlist audit metadata.

    Discards any key containing sensitive substrings (passwords, tokens, PHI, card details).
    Enforces allowlisted keys or safe scalar values, capping string lengths to 255 characters
    to prevent accidental body dumping.
    """
    if not metadata:
        return None

    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_lower = str(key).lower().strip()
        # Allowlisted keys always take precedence
        if key_lower in ALLOWLISTED_METADATA_KEYS:
            sanitized[key] = value
            continue

        # Drop any key matching sensitive substrings
        if any(substr in key_lower for substr in SENSITIVE_KEY_SUBSTRINGS):
            continue

        # Retain other safe scalar fields
        if isinstance(value, (int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, str):
            sanitized[key] = value[:255]

            sanitized[key] = value[:255]

    return sanitized if sanitized else None


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
    """Record an audit log entry within the current transaction.

    Failure Policy (Deliberate Transactional Atomicity):
    For events tied to business state changes (e.g. booking, status transitions, prescriptions,
    payments, availability), the audit log entry is added to the active database session without
    an independent commit. This guarantees that:
    1. If the surrounding business transaction succeeds, the audit trail is committed atomically.
    2. If the business transaction fails or rolls back, the audit record rolls back with it,
    Exceptions to this policy (such as standalone read access logging)
    flush or commit independently.

    Sensitive data redaction:
    Never stores passwords, tokens, MFA secrets, prescription items/notes, or raw request bodies.
    All metadata is strictly sanitized and allowlisted.
    """
    # Auto-extract correlation/request identifier from async context if omitted
    resolved_correlation_id = (
        correlation_id or correlation_id_ctx_var.get() or request_id_ctx_var.get()
    )

    clean_metadata = sanitize_audit_metadata(metadata)

    entry = AuditLog(
        id=uuid.uuid4(),
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        correlation_id=resolved_correlation_id,
        metadata_=clean_metadata,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    return entry


async def list_audit_logs(
    session: AsyncSession,
    *,
    current_user: User,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AuditLog], int, int]:
    """Retrieve paginated audit logs subject to administrative authorization.

    Restricted strictly to administrators; returns deterministically sorted entries
    (created_at DESC, id DESC) with bounded pagination.
    """
    if current_user.role != "admin":
        raise ForbiddenError(
            message="Access to security audit logs is restricted to administrators.",
            code="AUDIT_ACCESS_FORBIDDEN",
        )

    base_query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if action:
        base_query = base_query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if resource_type:
        base_query = base_query.where(AuditLog.resource_type == resource_type)
        count_query = count_query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        base_query = base_query.where(AuditLog.resource_id == resource_id)
        count_query = count_query.where(AuditLog.resource_id == resource_id)
    if actor_user_id:
        base_query = base_query.where(AuditLog.actor_user_id == actor_user_id)
        count_query = count_query.where(AuditLog.actor_user_id == actor_user_id)
    if date_from:
        base_query = base_query.where(AuditLog.created_at >= date_from)
        count_query = count_query.where(AuditLog.created_at >= date_from)
    if date_to:
        base_query = base_query.where(AuditLog.created_at <= date_to)
        count_query = count_query.where(AuditLog.created_at <= date_to)

    total = (await session.scalar(count_query)) or 0
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await session.scalars(paged_query)
    entries = list(result.all())

    return entries, total, total_pages
