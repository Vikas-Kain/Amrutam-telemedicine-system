"""Consultation lifecycle service enforcing explicit state transitions and access policy."""

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.schemas.consultation import (
    ConsultationListResponse,
    ConsultationResponse,
    ConsultationStatus,
)
from app.services.audit_service import record_audit_event

# Explicit state transition rules mapping each target status to its valid predecessor states,
# authorized actor roles, audit actions, and transactional outbox event types.
TRANSITION_RULES: dict[ConsultationStatus, dict[str, Any]] = {
    ConsultationStatus.CONFIRMED: {
        "from": [ConsultationStatus.BOOKED],
        "allowed_roles": ["doctor", "admin"],
        "require_assigned_doctor": True,
        "event_type": "consultation.confirmed",
        "audit_action": "consultation.confirm",
    },
    ConsultationStatus.IN_PROGRESS: {
        "from": [ConsultationStatus.CONFIRMED],
        "allowed_roles": ["doctor"],
        "require_assigned_doctor": True,
        "event_type": "consultation.in_progress",
        "audit_action": "consultation.start",
    },
    ConsultationStatus.COMPLETED: {
        "from": [ConsultationStatus.IN_PROGRESS],
        "allowed_roles": ["doctor"],
        "require_assigned_doctor": True,
        "event_type": "consultation.completed",
        "audit_action": "consultation.complete",
    },
    ConsultationStatus.NO_SHOW: {
        "from": [ConsultationStatus.CONFIRMED],
        "allowed_roles": ["doctor", "admin"],
        "require_assigned_doctor": True,
        "event_type": "consultation.no_show",
        "audit_action": "consultation.mark_no_show",
    },
}


async def get_doctor_id_for_user(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve the Doctor entity ID for a given user account ID."""
    return await session.scalar(select(Doctor.id).where(Doctor.user_id == user_id))


async def list_consultations(
    session: AsyncSession,
    *,
    current_user: User,
    status: str | None = None,
    patient_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ConsultationListResponse:
    """List consultations scoped strictly to the caller's authorized identity."""
    if status is not None:
        valid_statuses = {s.value for s in ConsultationStatus}
        if status not in valid_statuses:
            allowed = ", ".join(sorted(valid_statuses))
            raise BadRequestError(
                message=f"Invalid status filter '{status}'. Must be one of: {allowed}.",
                code="INVALID_STATUS_FILTER",
            )

    query = select(Consultation)

    if current_user.role == "patient":
        query = query.where(Consultation.patient_id == current_user.id)
    elif current_user.role == "doctor":
        resolved_doctor_id = await get_doctor_id_for_user(session, current_user.id)
        if resolved_doctor_id is None:
            return ConsultationListResponse(
                items=[], total=0, page=page, page_size=page_size, total_pages=0
            )
        query = query.where(Consultation.doctor_id == resolved_doctor_id)
    elif current_user.role == "admin":
        if patient_id is not None:
            query = query.where(Consultation.patient_id == patient_id)
        if doctor_id is not None:
            query = query.where(Consultation.doctor_id == doctor_id)
    else:
        raise ForbiddenError(
            message="You do not have permission to list consultations.",
            code="CONSULTATION_LIST_FORBIDDEN",
        )

    if status is not None:
        query = query.where(Consultation.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.scalar(count_query)) or 0

    ordered_query = (
        query.order_by(Consultation.created_at.desc(), Consultation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = (await session.scalars(ordered_query)).all()
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return ConsultationListResponse(
        items=[ConsultationResponse.model_validate(r) for r in records],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


async def get_consultation(
    session: AsyncSession,
    *,
    consultation_id: uuid.UUID,
    current_user: User,
) -> ConsultationResponse:
    """Retrieve consultation detail subject to patient ownership or doctor assignment."""
    consultation = await session.scalar(
        select(Consultation).where(Consultation.id == consultation_id)
    )
    if consultation is None:
        raise NotFoundError(message="Consultation not found.", code="CONSULTATION_NOT_FOUND")

    if current_user.role == "admin":
        return ConsultationResponse.model_validate(consultation)

    if current_user.role == "patient" and consultation.patient_id == current_user.id:
        return ConsultationResponse.model_validate(consultation)

    if current_user.role == "doctor":
        resolved_doctor_id = await get_doctor_id_for_user(session, current_user.id)
        if resolved_doctor_id == consultation.doctor_id:
            return ConsultationResponse.model_validate(consultation)

    raise ForbiddenError(
        message="You do not have permission to view this consultation.",
        code="CONSULTATION_ACCESS_FORBIDDEN",
    )


async def transition_consultation(
    session: AsyncSession,
    *,
    consultation_id: uuid.UUID,
    target_status: ConsultationStatus,
    current_user: User,
    reason: str | None = None,
) -> ConsultationResponse:
    """Execute an explicit, concurrency-safe consultation status transition.

    Acquires a row-level lock on the consultation record using SELECT ... FOR UPDATE,
    validates the predecessor state, verifies actor authorization, and records an
    audit trail entry and outbox event in the same transaction.
    """
    rule = TRANSITION_RULES.get(target_status)
    if rule is None:
        raise ConflictError(
            message=f"Transition to status '{target_status.value}' is not permitted.",
            code="CONSULTATION_INVALID_TRANSITION",
        )

    # Lock row before reading state to prevent concurrent transitions from racing
    consultation = await session.scalar(
        select(Consultation).where(Consultation.id == consultation_id).with_for_update()
    )
    if consultation is None:
        raise NotFoundError(message="Consultation not found.", code="CONSULTATION_NOT_FOUND")

    # Authorize caller
    if current_user.role not in rule["allowed_roles"]:
        raise ForbiddenError(
            message=(
                f"Role '{current_user.role}' is not authorized to transition "
                f"to '{target_status.value}'."
            ),
            code="CONSULTATION_TRANSITION_FORBIDDEN",
        )

    if current_user.role == "doctor" and rule.get("require_assigned_doctor", True):
        doctor_id = await get_doctor_id_for_user(session, current_user.id)
        if doctor_id != consultation.doctor_id:
            raise ForbiddenError(
                message="Only the assigned doctor may update this consultation's status.",
                code="CONSULTATION_NOT_ASSIGNED_DOCTOR",
            )

    # Validate state transition
    if consultation.status not in rule["from"]:
        raise ConflictError(
            message=(
                f"Cannot transition consultation from current status '{consultation.status}' "
                f"to '{target_status.value}'."
            ),
            code="CONSULTATION_INVALID_TRANSITION",
        )

    from_status = consultation.status
    consultation.status = target_status.value
    consultation.updated_at = datetime.now(UTC)
    await session.flush()

    # Record tamper-evident audit log
    await record_audit_event(
        session,
        action=rule["audit_action"],
        resource_type="consultation",
        resource_id=consultation.id,
        actor_user_id=current_user.id,
        metadata={
            "consultation_id": str(consultation.id),
            "doctor_id": str(consultation.doctor_id),
            "patient_id": str(consultation.patient_id),
            "from_status": from_status,
            "to_status": target_status.value,
            "reason": reason,
        },
    )

    # Enqueue transactional outbox event
    session.add(
        OutboxEvent(
            event_type=rule["event_type"],
            aggregate_type="consultation",
            aggregate_id=consultation.id,
            payload={
                "consultation_id": str(consultation.id),
                "doctor_id": str(consultation.doctor_id),
                "patient_id": str(consultation.patient_id),
                "slot_id": str(consultation.slot_id),
                "from_status": from_status,
                "to_status": target_status.value,
            },
        )
    )
    await session.flush()

    return ConsultationResponse.model_validate(consultation)
