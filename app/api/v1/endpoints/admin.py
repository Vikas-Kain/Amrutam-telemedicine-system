"""Administrative security and audit review API endpoints."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.services.audit_service import list_audit_logs, record_audit_event

router = APIRouter()


@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="Review security audit logs",
    description=(
        "Retrieves a paginated list of tamper-evident security audit logs. "
        "Strictly restricted to authorized administrators. Supports filtering by action, "
        "resource type, resource ID, actor, and date ranges with deterministic sorting "
        "(created_at DESC, id DESC)."
    ),
    responses={
        200: {"description": "Paginated audit trail log entries."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not an administrator."},
        422: {"description": "Invalid query filter parameters or pagination values."},
    },
)
async def list_audit_logs_endpoint(
    current_user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    action: Annotated[
        str | None,
        Query(description="Filter by specific action identifier (e.g. 'booking.create')"),
    ] = None,
    resource_type: Annotated[
        str | None,
        Query(description="Filter by entity type (e.g. 'consultation', 'payment')"),
    ] = None,
    resource_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by target resource UUID"),
    ] = None,
    actor_user_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by actor user UUID"),
    ] = None,
    date_from: Annotated[
        datetime | None,
        Query(description="Filter events created on or after UTC timestamp"),
    ] = None,
    date_to: Annotated[
        datetime | None,
        Query(description="Filter events created on or before UTC timestamp"),
    ] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Entries per page")] = 20,
) -> AuditLogListResponse:
    """List and filter security audit logs with administrative access auditing."""
    # Audit this administrative review access
    await record_audit_event(
        session,
        action="admin.audit_read",
        resource_type="audit_log",
        actor_user_id=current_user.id,
        metadata={"page": page, "page_size": page_size},
    )
    await session.flush()

    entries, total, total_pages = await list_audit_logs(
        session=session,
        current_user=current_user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )

    items = [AuditLogResponse.model_validate(e) for e in entries]
    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
