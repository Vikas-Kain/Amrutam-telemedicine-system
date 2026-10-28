"""Consultation API endpoints for listing, retrieval, and lifecycle transitions."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_doctor,
    require_doctor_or_admin,
    require_patient,
    require_patient_or_admin,
)
from app.core.rate_limit import rate_limit_write
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.consultation import (
    ConsultationListResponse,
    ConsultationResponse,
    ConsultationStatus,
)
from app.schemas.payment import PaymentCreateRequest, PaymentResponse
from app.schemas.prescription import PrescriptionCreate, PrescriptionResponse
from app.services.booking_service import cancel_booking
from app.services.consultation_service import (
    get_consultation,
    list_consultations,
    transition_consultation,
)
from app.services.idempotency_service import require_idempotency_key
from app.services.payment_service import initiate_consultation_payment
from app.services.prescription_service import (
    get_prescription_by_consultation,
    issue_or_amend_prescription,
)

router = APIRouter()


@router.get(
    "",
    response_model=ConsultationListResponse,
    summary="List consultations scoped to caller identity",
    description=(
        "Returns a paginated list of consultations strictly filtered by the authenticated user's "
        "role: patients only see their own appointments, doctors only see their assigned "
        "consultations, and administrators can view all or filter by patient/doctor."
    ),
    responses={
        400: {"description": "Invalid query parameters or status filter."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller lacks permission to list consultations."},
    },
)
async def list_consultations_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Filter by status (e.g. booked, confirmed, in_progress, completed)",
        ),
    ] = None,
    patient_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by patient ID (admin only)"),
    ] = None,
    doctor_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by doctor ID (admin only)"),
    ] = None,
    page: Annotated[int, Query(ge=1, description="Page number (1-indexed)")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Results per page (max 100)")] = 20,
) -> ConsultationListResponse:
    """List consultations scoped by role and optional status filter."""
    return await list_consultations(
        session=session,
        current_user=current_user,
        status=status_filter,
        patient_id=patient_id,
        doctor_id=doctor_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{consultation_id}",
    response_model=ConsultationResponse,
    summary="Retrieve an authorized consultation",
    description="Retrieve consultation detail subject to patient ownership or doctor assignment.",
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the patient, assigned doctor, or an administrator."},
        404: {"description": "Consultation was not found."},
    },
)
async def get_consultation_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConsultationResponse:
    """Retrieve consultation details for authorized callers."""
    return await get_consultation(
        session=session,
        consultation_id=consultation_id,
        current_user=current_user,
    )


@router.post(
    "/{consultation_id}/confirm",
    dependencies=[Depends(rate_limit_write)],
    response_model=ConsultationResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm an appointment (booked -> confirmed)",
    description=(
        "Transition consultation status from 'booked' to 'confirmed'. Only the assigned "
        "doctor or an administrator can confirm the appointment."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the assigned doctor or administrator."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation is not in 'booked' state."},
    },
)
async def confirm_consultation_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_doctor_or_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConsultationResponse:
    """Transition consultation to confirmed state."""
    return await transition_consultation(
        session=session,
        consultation_id=consultation_id,
        target_status=ConsultationStatus.CONFIRMED,
        current_user=current_user,
    )


@router.post(
    "/{consultation_id}/start",
    dependencies=[Depends(rate_limit_write)],
    response_model=ConsultationResponse,
    status_code=status.HTTP_200_OK,
    summary="Begin consultation (confirmed -> in_progress)",
    description=(
        "Transition consultation status from 'confirmed' to 'in_progress'. Only the assigned "
        "doctor can start the consultation session."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the assigned doctor."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation is not in 'confirmed' state."},
    },
)
async def start_consultation_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_doctor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConsultationResponse:
    """Transition consultation to in_progress state."""
    return await transition_consultation(
        session=session,
        consultation_id=consultation_id,
        target_status=ConsultationStatus.IN_PROGRESS,
        current_user=current_user,
    )


@router.post(
    "/{consultation_id}/complete",
    dependencies=[Depends(rate_limit_write)],
    response_model=ConsultationResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete consultation (in_progress -> completed)",
    description=(
        "Transition consultation status from 'in_progress' to 'completed'. Only the assigned "
        "doctor can mark the consultation complete."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the assigned doctor."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation is not in 'in_progress' state."},
    },
)
async def complete_consultation_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_doctor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConsultationResponse:
    """Transition consultation to completed state."""
    return await transition_consultation(
        session=session,
        consultation_id=consultation_id,
        target_status=ConsultationStatus.COMPLETED,
        current_user=current_user,
    )


@router.post(
    "/{consultation_id}/no-show",
    dependencies=[Depends(rate_limit_write)],
    response_model=ConsultationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark patient no-show (confirmed -> no_show)",
    description=(
        "Transition consultation status from 'confirmed' to 'no_show'. Only the assigned "
        "doctor or an administrator can record a patient no-show."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the assigned doctor or administrator."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation is not in 'confirmed' state."},
    },
)
async def mark_no_show_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_doctor_or_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConsultationResponse:
    """Transition consultation to no_show state."""
    return await transition_consultation(
        session=session,
        consultation_id=consultation_id,
        target_status=ConsultationStatus.NO_SHOW,
        current_user=current_user,
    )


@router.post(
    "/{consultation_id}/cancel",
    dependencies=[Depends(rate_limit_write)],
    response_model=ConsultationResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an eligible consultation and release its slot",
    description=(
        "Patients may cancel only their own future consultations in the 'booked' state; "
        "administrators may perform the same action. Releases the slot atomically and returns "
        "the preserved cancelled consultation."
    ),
    responses={
        400: {"description": "The Idempotency-Key header was missing or invalid."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the patient owner or an administrator."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation cannot be cancelled in its current state."},
    },
)
async def cancel_consultation_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_patient_or_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ConsultationResponse:
    """Cancel a consultation safely and return the cancelled representation."""
    result = await cancel_booking(
        session=session,
        booking_id=consultation_id,
        current_user=current_user,
        idempotency_key=idempotency_key,
    )
    return ConsultationResponse.model_validate(result.booking)


@router.post(
    "/{consultation_id}/prescriptions",
    dependencies=[Depends(rate_limit_write)],
    response_model=PrescriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue or amend prescription for an eligible consultation",
    description=(
        "Issues a medical prescription with structured line items. Only the doctor assigned "
        "to the consultation may issue or amend a prescription. Consultations must be in "
        "'in_progress' or 'completed' status. Creates prescription and items atomically."
    ),
    responses={
        400: {"description": "Validation error in structured items."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the assigned doctor."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation is not in an eligible status."},
    },
)
async def create_prescription_endpoint(
    consultation_id: uuid.UUID,
    payload: PrescriptionCreate,
    current_user: Annotated[User, Depends(require_doctor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PrescriptionResponse:
    """Create a new prescription or amend existing for the given consultation."""
    return await issue_or_amend_prescription(
        session=session,
        consultation_id=consultation_id,
        payload=payload,
        current_user=current_user,
    )


@router.put(
    "/{consultation_id}/prescriptions",
    dependencies=[Depends(rate_limit_write)],
    response_model=PrescriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Amend an existing prescription",
    description=(
        "Corrects or amends an issued prescription. Increments the version counter and "
        "atomically updates medication items. Restricted to the assigned doctor."
    ),
    responses={
        400: {"description": "Validation error in structured items."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the assigned doctor."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation is not in an eligible status."},
    },
)
async def amend_prescription_endpoint(
    consultation_id: uuid.UUID,
    payload: PrescriptionCreate,
    current_user: Annotated[User, Depends(require_doctor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PrescriptionResponse:
    """Amend an existing prescription for the consultation."""
    return await issue_or_amend_prescription(
        session=session,
        consultation_id=consultation_id,
        payload=payload,
        current_user=current_user,
    )


@router.get(
    "/{consultation_id}/prescription",
    response_model=PrescriptionResponse,
    summary="Retrieve the prescription for a consultation",
    description=(
        "Returns the prescription issued for a consultation. Accessible only to the "
        "patient recipient, the assigned doctor, or an administrator."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller lacks permission to view this prescription."},
        404: {"description": "Consultation or prescription not found."},
    },
)
async def get_consultation_prescription_endpoint(
    consultation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PrescriptionResponse:
    """Retrieve prescription by consultation ID."""
    return await get_prescription_by_consultation(
        session=session,
        consultation_id=consultation_id,
        current_user=current_user,
    )


@router.post(
    "/{consultation_id}/payments",
    dependencies=[Depends(rate_limit_write)],
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate payment intent for an appointment consultation",
    description=(
        "Initiates a payment intent through the simulated payment provider adapter. "
        "Requires patient authentication and an Idempotency-Key header. External provider "
        "calls occur outside database locks; matching completed retries return original results."
    ),
    responses={
        200: {"description": "Original completed payment replayed."},
        201: {"description": "Payment successfully initiated/completed."},
        400: {"description": "Missing or invalid Idempotency-Key header."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not the patient who booked the consultation."},
        404: {"description": "Consultation was not found."},
        409: {"description": "Consultation already paid or in an ineligible status."},
    },
)
async def create_consultation_payment_endpoint(
    consultation_id: uuid.UUID,
    payload: PaymentCreateRequest,
    current_user: Annotated[User, Depends(require_patient)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> PaymentResponse:
    """Initiate an idempotent consultation payment."""
    return await initiate_consultation_payment(
        session=session,
        consultation_id=consultation_id,
        payload=payload,
        current_user=current_user,
        idempotency_key=idempotency_key,
    )
