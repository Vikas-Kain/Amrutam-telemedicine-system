"""Doctor search, filtering, and public profile API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.doctor import DoctorListResponse, DoctorPublicResponse
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
