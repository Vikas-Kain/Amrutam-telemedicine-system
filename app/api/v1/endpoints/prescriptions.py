"""Prescriptions direct API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.prescription import PrescriptionResponse
from app.services.prescription_service import get_prescription_by_id

router = APIRouter()


@router.get(
    "/{prescription_id}",
    response_model=PrescriptionResponse,
    summary="Retrieve a prescription by its direct identifier",
    description=(
        "Returns the complete prescription and structured medication items. Restricted to "
        "the patient who received the prescription, the issuing doctor, or an administrator."
    ),
    responses={
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not authorized to view this prescription."},
        404: {"description": "Prescription was not found."},
    },
)
async def get_prescription_endpoint(
    prescription_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PrescriptionResponse:
    """Retrieve prescription by direct ID subject to authorization policy."""
    return await get_prescription_by_id(
        session=session,
        prescription_id=prescription_id,
        current_user=current_user,
    )
