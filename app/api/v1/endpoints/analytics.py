"""Administrative analytics endpoints for aggregate metrics and trends."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.analytics import (
    BookingAnalyticsResponse,
    ConsultationAnalyticsResponse,
    PaymentAnalyticsResponse,
)
from app.services.analytics_service import (
    get_booking_analytics,
    get_consultation_analytics,
    get_payment_analytics,
    validate_date_range,
)
from app.services.audit_service import record_audit_event

router = APIRouter()


@router.get(
    "/consultations",
    response_model=ConsultationAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultation volume and status trends",
    description=(
        "Returns aggregate counts grouped by consultation status, overall completion rate, "
        "and daily volume trends. Strictly role-restricted to administrators. Never exposes "
        "individual patient clinical details."
    ),
    responses={
        200: {"description": "Aggregate consultation metrics and daily trends."},
        400: {"description": "Invalid date range or window exceeds maximum limit."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not an administrator."},
    },
)
async def get_consultations_analytics_endpoint(
    current_user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    date_from: Annotated[
        datetime | None,
        Query(description="Evaluation start timestamp (UTC, defaults to 30 days ago)"),
    ] = None,
    date_to: Annotated[
        datetime | None,
        Query(description="Evaluation end timestamp (UTC, defaults to current time)"),
    ] = None,
    doctor_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional filter by assigned doctor UUID"),
    ] = None,
) -> ConsultationAnalyticsResponse:
    """Retrieve consultation metrics within a bounded date window."""
    resolved_from, resolved_to = validate_date_range(date_from=date_from, date_to=date_to)

    await record_audit_event(
        session,
        action="admin.analytics_read",
        resource_type="consultations",
        actor_user_id=current_user.id,
        metadata={
            "target": "consultations",
            "doctor_id": str(doctor_id) if doctor_id else None,
        },
    )
    await session.flush()

    return await get_consultation_analytics(
        session=session,
        date_from=resolved_from,
        date_to=resolved_to,
        doctor_id=doctor_id,
    )


@router.get(
    "/bookings",
    response_model=BookingAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Booking, cancellation, and no-show rates",
    description=(
        "Returns aggregated booking metrics including total bookings, cancellation rate, "
        "no-show rate, and daily chronological trends. Role-restricted to administrators."
    ),
    responses={
        200: {"description": "Aggregate booking metrics and cancellation rates."},
        400: {"description": "Invalid date range or window exceeds maximum limit."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not an administrator."},
    },
)
async def get_bookings_analytics_endpoint(
    current_user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    date_from: Annotated[
        datetime | None,
        Query(description="Evaluation start timestamp (UTC, defaults to 30 days ago)"),
    ] = None,
    date_to: Annotated[
        datetime | None,
        Query(description="Evaluation end timestamp (UTC, defaults to current time)"),
    ] = None,
    doctor_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional filter by assigned doctor UUID"),
    ] = None,
) -> BookingAnalyticsResponse:
    """Retrieve booking and cancellation metrics within a bounded date window."""
    resolved_from, resolved_to = validate_date_range(date_from=date_from, date_to=date_to)

    await record_audit_event(
        session,
        action="admin.analytics_read",
        resource_type="bookings",
        actor_user_id=current_user.id,
        metadata={
            "target": "bookings",
            "doctor_id": str(doctor_id) if doctor_id else None,
        },
    )
    await session.flush()

    return await get_booking_analytics(
        session=session,
        date_from=resolved_from,
        date_to=resolved_to,
        doctor_id=doctor_id,
    )


@router.get(
    "/payments",
    response_model=PaymentAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Payment volume and outcome ratios",
    description=(
        "Returns aggregated payment metrics including total transaction volume (in minor units), "
        "success/failure/refund rates, and daily chronological trends. Role-restricted to "
        "administrators. Never exposes cardholder data or sensitive payment provider secrets."
    ),
    responses={
        200: {"description": "Aggregate payment volume and outcome ratios."},
        400: {"description": "Invalid date range or window exceeds maximum limit."},
        401: {"description": "Authentication credentials missing or invalid."},
        403: {"description": "Caller is not an administrator."},
    },
)
async def get_payments_analytics_endpoint(
    current_user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    date_from: Annotated[
        datetime | None,
        Query(description="Evaluation start timestamp (UTC, defaults to 30 days ago)"),
    ] = None,
    date_to: Annotated[
        datetime | None,
        Query(description="Evaluation end timestamp (UTC, defaults to current time)"),
    ] = None,
    currency: Annotated[
        str | None,
        Query(description="Optional currency filter (e.g. 'INR')"),
    ] = None,
) -> PaymentAnalyticsResponse:
    """Retrieve payment volume and outcome ratios within a bounded date window."""
    resolved_from, resolved_to = validate_date_range(date_from=date_from, date_to=date_to)

    await record_audit_event(
        session,
        action="admin.analytics_read",
        resource_type="payments",
        actor_user_id=current_user.id,
        metadata={
            "target": "payments",
            "currency": currency,
        },
    )
    await session.flush()

    return await get_payment_analytics(
        session=session,
        date_from=resolved_from,
        date_to=resolved_to,
        currency=currency,
    )
