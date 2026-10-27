"""Doctor search, filtering, public profile, and availability slot API endpoints."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_doctor, require_doctor_or_admin
from app.core.errors import NotFoundError
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.availability import (
    SlotBatchCreateRequest,
    SlotCreateRequest,
    SlotListResponse,
    SlotResponse,
    SlotUpdateRequest,
)
from app.schemas.doctor import DoctorListResponse, DoctorPublicResponse
from app.services.availability_service import (
    create_doctor_slots,
    delete_doctor_slot,
    get_doctor_by_user_id,
    list_doctor_slots,
    update_doctor_slot,
)
from app.services.doctor_service import get_doctor_by_id, list_doctors

router = APIRouter()


@router.get(
    "",
    response_model=DoctorListResponse,
    status_code=status.HTTP_200_OK,
    summary="Search and list doctor profiles",
    description=(
        "Retrieves a paginated list of public doctor profiles with deterministic sorting "
        "(created_at DESC, id DESC). Supports filtering by specialization, name, and "
        "verification status. Strictly bounded to a maximum of 100 items per page. "
        "Sensitive data is redacted."
    ),
    responses={
        200: {
            "description": "Paginated list of matching doctor profiles.",
        },
        422: {
            "description": "Invalid pagination parameters or query formatting.",
        },
    },
)
async def list_doctors_endpoint(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    specialization: Annotated[
        str | None,
        Query(description="Filter by area of specialization (case-insensitive substring)"),
    ] = None,
    name: Annotated[
        str | None,
        Query(description="Filter by doctor full legal name (case-insensitive substring)"),
    ] = None,
    is_verified: Annotated[
        bool | None,
        Query(description="Filter by doctor verification status"),
    ] = None,
    search: Annotated[
        str | None,
        Query(description="General keyword search matching name, specialization, or bio"),
    ] = None,
    page: Annotated[
        int,
        Query(ge=1, description="Page number (1-indexed, minimum 1)"),
    ] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100, description="Items per page (minimum 1, maximum 100)"),
    ] = 20,
) -> DoctorListResponse:
    """Retrieve public doctor profiles matching query filters with bounded pagination."""
    doctors, total, total_pages = await list_doctors(
        session=session,
        specialization=specialization,
        name=name,
        is_verified=is_verified,
        search=search,
        page=page,
        page_size=page_size,
    )

    items = [DoctorPublicResponse.model_validate(doc) for doc in doctors]

    return DoctorListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/me/slots",
    response_model=list[SlotResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create doctor availability slots",
    description=(
        "Creates one or more availability time slots for the authenticated doctor. "
        "Enforces rejection of past intervals, internal overlaps within the request batch, "
        "and database-level overlap constraints against existing slots."
    ),
    responses={
        201: {"description": "Availability slots successfully created."},
        400: {"description": "Invalid time interval or slot in the past."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller does not hold the doctor role."},
        404: {"description": "Doctor profile not found for authenticated user."},
        409: {"description": "Slot interval overlaps with an existing slot."},
        422: {"description": "Request schema validation failed."},
    },
)
async def create_doctor_slots_endpoint(
    payload: SlotBatchCreateRequest | SlotCreateRequest,
    current_user: Annotated[User, Depends(require_doctor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[SlotResponse]:
    """Create availability slots for the authenticated doctor."""
    doctor = await get_doctor_by_user_id(session=session, user_id=current_user.id)
    if doctor is None:
        raise NotFoundError("Doctor profile not found for user.", code="DOCTOR_PROFILE_NOT_FOUND")

    slot_items = [payload] if isinstance(payload, SlotCreateRequest) else payload.slots
    slots = await create_doctor_slots(session=session, doctor=doctor, slot_requests=slot_items)
    return [SlotResponse.model_validate(s) for s in slots]


@router.patch(
    "/me/slots/{slot_id}",
    response_model=SlotResponse,
    status_code=status.HTTP_200_OK,
    summary="Update doctor availability slot",
    description=(
        "Updates an unbooked availability slot interval or changes its status "
        "('available' / 'blocked'). Enforces ownership (only owning doctor or admin "
        "can modify) and guarantees that booked slots cannot be edited."
    ),
    responses={
        200: {"description": "Availability slot updated successfully."},
        400: {"description": "Invalid time interval or update in the past."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller lacks permission to modify this slot."},
        404: {"description": "Availability slot not found."},
        409: {"description": "Slot is already booked or overlaps with an existing slot."},
        422: {"description": "Request schema validation failed."},
    },
)
async def update_doctor_slot_endpoint(
    slot_id: uuid.UUID,
    payload: SlotUpdateRequest,
    current_user: Annotated[User, Depends(require_doctor_or_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SlotResponse:
    """Update slot interval or mark blocked for the owning doctor or admin."""
    slot = await update_doctor_slot(
        session=session,
        slot_id=slot_id,
        current_user=current_user,
        update_data=payload,
    )
    return SlotResponse.model_validate(slot)


@router.delete(
    "/me/slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete doctor availability slot",
    description=(
        "Deletes an unbooked availability slot. Enforces ownership (only owning doctor or admin "
        "can delete) and guarantees that booked slots cannot be deleted."
    ),
    responses={
        204: {"description": "Availability slot deleted successfully."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller lacks permission to delete this slot."},
        404: {"description": "Availability slot not found."},
        409: {"description": "Slot is already booked and cannot be deleted."},
    },
)
async def delete_doctor_slot_endpoint(
    slot_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_doctor_or_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Delete an unbooked availability slot."""
    await delete_doctor_slot(session=session, slot_id=slot_id, current_user=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{doctor_id}",
    response_model=DoctorPublicResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve doctor public profile",
    description=(
        "Retrieves public professional details and consultation fee for a specific doctor. "
        "Sensitive information including license numbers, credentials, and contact details "
        "are strictly redacted."
    ),
    responses={
        200: {
            "description": "Doctor public profile details.",
        },
        404: {
            "description": "Doctor not found.",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "DOCTOR_NOT_FOUND",
                            "message": "Doctor not found.",
                            "request_id": "req_01j9a4k7...",
                        }
                    }
                }
            },
        },
    },
)
async def get_doctor_endpoint(
    doctor_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DoctorPublicResponse:
    """Retrieve public details for a single doctor by unique identifier."""
    doctor = await get_doctor_by_id(session=session, doctor_id=doctor_id)
    return DoctorPublicResponse.model_validate(doctor)


@router.get(
    "/{doctor_id}/slots",
    response_model=SlotListResponse,
    status_code=status.HTTP_200_OK,
    summary="List doctor availability slots",
    description=(
        "Retrieves availability slots for a doctor with optional date range and status filters. "
        "Defaults to returning available future slots in chronological order."
    ),
    responses={
        200: {"description": "List of doctor availability slots."},
        404: {"description": "Doctor not found."},
    },
)
async def list_doctor_slots_endpoint(
    doctor_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    date_from: Annotated[
        datetime | None,
        Query(description="Filter slots ending on or after timestamp (UTC)"),
    ] = None,
    date_to: Annotated[
        datetime | None,
        Query(description="Filter slots starting on or before timestamp (UTC)"),
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by slot status (e.g. 'available', 'blocked')"),
    ] = "available",
) -> SlotListResponse:
    """List availability slots for a specific doctor within optional date bounds."""
    slots = await list_doctor_slots(
        session=session,
        doctor_id=doctor_id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
    )
    items = [SlotResponse.model_validate(s) for s in slots]
    return SlotListResponse(items=items, total=len(items))
