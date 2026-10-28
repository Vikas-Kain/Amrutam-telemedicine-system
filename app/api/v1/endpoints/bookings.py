"""Appointment booking API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_patient, require_patient_or_admin
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.booking import BookingCreateRequest, BookingResponse
from app.services.booking_service import cancel_booking, create_booking, get_booking
from app.services.idempotency_service import require_idempotency_key

router = APIRouter()


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Atomically reserve an availability slot",
    description=(
        "Reserves an available doctor slot and creates a consultation within one PostgreSQL "
        "transaction. A patient identity and Idempotency-Key header are required. Matching "
        "completed retries replay the original booking with HTTP 200."
    ),
    responses={
        200: {"description": "Original completed booking replayed."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not a patient."},
        404: {"description": "Availability slot was not found."},
        409: {"description": "Idempotency, doctor-slot, or availability conflict."},
        400: {"description": "The Idempotency-Key header was missing or invalid."},
        422: {"description": "Request schema validation failed."},
    },
)
async def create_booking_endpoint(
    payload: BookingCreateRequest,
    response: Response,
    current_user: Annotated[User, Depends(require_patient)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> BookingResponse:
    """Create or replay an idempotent patient booking."""
    result = await create_booking(
        session=session,
        patient=current_user,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    if result.is_replayed:
        response.status_code = status.HTTP_200_OK
    return result.booking


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="Retrieve an authorized booking",
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the patient, assigned doctor, or an administrator."},
        404: {"description": "Booking was not found."},
    },
)
async def get_booking_endpoint(
    booking_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BookingResponse:
    """Retrieve a booking subject to patient ownership or doctor assignment policy."""
    return await get_booking(session=session, booking_id=booking_id, current_user=current_user)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an eligible booking and release its slot",
    description=(
        "Patients may cancel only their own future bookings that remain in the booked state; "
        "administrators may perform the same operational action. The cancelled consultation is "
        "retained and its slot becomes available atomically."
    ),
    responses={
        400: {"description": "The Idempotency-Key header was missing or invalid."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the patient owner or an administrator."},
        404: {"description": "Booking was not found."},
        409: {"description": "Booking cannot be cancelled in its current state."},
    },
)
async def cancel_booking_endpoint(
    booking_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_patient_or_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> BookingResponse:
    """Cancel a booking safely and return the current cancelled representation."""
    result = await cancel_booking(
        session=session,
        booking_id=booking_id,
        current_user=current_user,
        idempotency_key=idempotency_key,
    )
    return result.booking
