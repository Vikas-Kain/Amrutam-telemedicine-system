"""Service layer for aggregate administrative analytics.

Provides grouped, index-accelerated aggregation queries over consultations,
bookings, and payment records without exposing patient-level rows or clinical details.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError
from app.models.consultation import Consultation
from app.models.payment import Payment
from app.schemas.analytics import (
    BookingAnalyticsResponse,
    BookingDailyTrend,
    ConsultationAnalyticsResponse,
    ConsultationDailyTrend,
    PaymentAnalyticsResponse,
    PaymentDailyTrend,
)

MAX_ANALYTICS_RANGE_DAYS: int = 90
ALL_CONSULTATION_STATUSES: tuple[str, ...] = (
    "booked",
    "confirmed",
    "in_progress",
    "completed",
    "cancelled",
    "no_show",
)
ALL_PAYMENT_STATUSES: tuple[str, ...] = (
    "pending",
    "succeeded",
    "failed",
    "refunded",
    "requires_reconciliation",
)


def validate_date_range(
    date_from: datetime | None,
    date_to: datetime | None,
    max_days: int = MAX_ANALYTICS_RANGE_DAYS,
) -> tuple[datetime, datetime]:
    """Validate and resolve bounded time ranges for aggregate reporting.

    Defaults to the past 30 days if omitted. Enforces chronological order
    and caps the evaluated window to prevent unbounded table scans.
    """
    now = datetime.now(UTC)
    resolved_to = date_to or now
    if resolved_to.tzinfo is None:
        resolved_to = resolved_to.replace(tzinfo=UTC)

    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from.tzinfo is None:
        resolved_from = resolved_from.replace(tzinfo=UTC)

    if resolved_from > resolved_to:
        raise BadRequestError(
            message="date_from must be earlier than or equal to date_to.",
            code="INVALID_DATE_RANGE",
        )

    if (resolved_to - resolved_from).total_seconds() > max_days * 86400:
        raise BadRequestError(
            message=f"Date range cannot exceed {max_days} days.",
            code="DATE_RANGE_TOO_LARGE",
        )

    return resolved_from, resolved_to


def _format_date(val: Any) -> str:
    """Format a date or datetime object into ISO YYYY-MM-DD string."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10]


async def get_consultation_analytics(
    session: AsyncSession,
    date_from: datetime,
    date_to: datetime,
    doctor_id: uuid.UUID | None = None,
) -> ConsultationAnalyticsResponse:
    """Aggregate consultation trends, status breakdowns, and completion rates.

    Never returns patient identifiers, clinical notes, or prescription contents.
    """
    # 1. Status count aggregation
    stmt_status = select(Consultation.status, func.count(Consultation.id)).where(
        Consultation.created_at >= date_from,
        Consultation.created_at <= date_to,
    )
    if doctor_id:
        stmt_status = stmt_status.where(Consultation.doctor_id == doctor_id)
    stmt_status = stmt_status.group_by(Consultation.status)

    res_status = await session.execute(stmt_status)
    status_counts: dict[str, int] = dict.fromkeys(ALL_CONSULTATION_STATUSES, 0)
    for st, count in res_status.all():
        status_counts[st] = count

    total_consultations = sum(status_counts.values())
    completed_count = status_counts.get("completed", 0)
    completion_rate = (
        round(completed_count / total_consultations, 4) if total_consultations > 0 else 0.0
    )

    # 2. Chronological daily trends aggregation
    day_col = cast(Consultation.created_at, Date).label("d")
    stmt_trend = select(day_col, Consultation.status, func.count(Consultation.id)).where(
        Consultation.created_at >= date_from,
        Consultation.created_at <= date_to,
    )
    if doctor_id:
        stmt_trend = stmt_trend.where(Consultation.doctor_id == doctor_id)
    stmt_trend = stmt_trend.group_by(day_col, Consultation.status).order_by(day_col)

    res_trend = await session.execute(stmt_trend)
    trends_map: dict[str, dict[str, Any]] = {}
    for day_val, st, count in res_trend.all():
        date_str = _format_date(day_val)
        if date_str not in trends_map:
            trends_map[date_str] = {"date": date_str, "total": 0, "by_status": {}}
        trends_map[date_str]["total"] += count
        trends_map[date_str]["by_status"][st] = count

    daily_trends = [
        ConsultationDailyTrend(
            date=v["date"],
            total=v["total"],
            by_status=v["by_status"],
        )
        for v in trends_map.values()
    ]

    return ConsultationAnalyticsResponse(
        date_from=date_from,
        date_to=date_to,
        total_consultations=total_consultations,
        status_counts=status_counts,
        completion_rate=completion_rate,
        daily_trends=daily_trends,
    )


async def get_booking_analytics(
    session: AsyncSession,
    date_from: datetime,
    date_to: datetime,
    doctor_id: uuid.UUID | None = None,
) -> BookingAnalyticsResponse:
    """Aggregate appointment booking volume, cancellation rates, and no-show statistics."""
    # 1. Total booking counts grouped by status
    stmt_status = select(Consultation.status, func.count(Consultation.id)).where(
        Consultation.created_at >= date_from,
        Consultation.created_at <= date_to,
    )
    if doctor_id:
        stmt_status = stmt_status.where(Consultation.doctor_id == doctor_id)
    stmt_status = stmt_status.group_by(Consultation.status)

    res_status = await session.execute(stmt_status)
    counts: dict[str, int] = dict.fromkeys(ALL_CONSULTATION_STATUSES, 0)
    for st, count in res_status.all():
        counts[st] = count

    total_bookings = sum(counts.values())
    confirmed_bookings = counts.get("confirmed", 0)
    completed_bookings = counts.get("completed", 0)
    cancelled_bookings = counts.get("cancelled", 0)
    no_show_bookings = counts.get("no_show", 0)

    cancellation_rate = round(cancelled_bookings / total_bookings, 4) if total_bookings > 0 else 0.0
    no_show_rate = round(no_show_bookings / total_bookings, 4) if total_bookings > 0 else 0.0

    # 2. Chronological daily booking trends
    day_col = cast(Consultation.created_at, Date).label("d")
    stmt_trend = select(day_col, Consultation.status, func.count(Consultation.id)).where(
        Consultation.created_at >= date_from,
        Consultation.created_at <= date_to,
    )
    if doctor_id:
        stmt_trend = stmt_trend.where(Consultation.doctor_id == doctor_id)
    stmt_trend = stmt_trend.group_by(day_col, Consultation.status).order_by(day_col)

    res_trend = await session.execute(stmt_trend)
    trends_map: dict[str, dict[str, Any]] = {}
    for day_val, st, count in res_trend.all():
        date_str = _format_date(day_val)
        if date_str not in trends_map:
            trends_map[date_str] = {
                "date": date_str,
                "total_bookings": 0,
                "cancelled_bookings": 0,
                "no_show_bookings": 0,
            }
        trends_map[date_str]["total_bookings"] += count
        if st == "cancelled":
            trends_map[date_str]["cancelled_bookings"] += count
        elif st == "no_show":
            trends_map[date_str]["no_show_bookings"] += count

    daily_trends = [
        BookingDailyTrend(
            date=v["date"],
            total_bookings=v["total_bookings"],
            cancelled_bookings=v["cancelled_bookings"],
            no_show_bookings=v["no_show_bookings"],
        )
        for v in trends_map.values()
    ]

    return BookingAnalyticsResponse(
        date_from=date_from,
        date_to=date_to,
        total_bookings=total_bookings,
        confirmed_bookings=confirmed_bookings,
        completed_bookings=completed_bookings,
        cancelled_bookings=cancelled_bookings,
        cancellation_rate=cancellation_rate,
        no_show_bookings=no_show_bookings,
        no_show_rate=no_show_rate,
        daily_trends=daily_trends,
    )


async def get_payment_analytics(
    session: AsyncSession,
    date_from: datetime,
    date_to: datetime,
    currency: str | None = None,
) -> PaymentAnalyticsResponse:
    """Aggregate payment volumes, success rates, and failure ratios."""
    # 1. Status counts and monetary volume aggregation
    stmt_status = select(
        Payment.status,
        func.count(Payment.id),
        func.coalesce(func.sum(Payment.amount_minor), 0),
    ).where(
        Payment.created_at >= date_from,
        Payment.created_at <= date_to,
    )
    if currency:
        stmt_status = stmt_status.where(Payment.currency == currency)
    stmt_status = stmt_status.group_by(Payment.status)

    res_status = await session.execute(stmt_status)
    status_counts: dict[str, int] = dict.fromkeys(ALL_PAYMENT_STATUSES, 0)
    total_volume_minor = 0
    for st, count, vol in res_status.all():
        status_counts[st] = count
        if st == "succeeded":
            total_volume_minor = int(vol)

    total_payments = sum(status_counts.values())
    succeeded_count = status_counts.get("succeeded", 0)
    failed_count = status_counts.get("failed", 0)
    refunded_count = status_counts.get("refunded", 0)

    success_rate = round(succeeded_count / total_payments, 4) if total_payments > 0 else 0.0
    failure_rate = round(failed_count / total_payments, 4) if total_payments > 0 else 0.0
    refund_rate = round(refunded_count / total_payments, 4) if total_payments > 0 else 0.0

    # 2. Chronological daily payment trends
    day_col = cast(Payment.created_at, Date).label("d")
    stmt_trend = select(
        day_col,
        Payment.status,
        func.count(Payment.id),
        func.coalesce(func.sum(Payment.amount_minor), 0),
    ).where(
        Payment.created_at >= date_from,
        Payment.created_at <= date_to,
    )
    if currency:
        stmt_trend = stmt_trend.where(Payment.currency == currency)
    stmt_trend = stmt_trend.group_by(day_col, Payment.status).order_by(day_col)

    res_trend = await session.execute(stmt_trend)
    trends_map: dict[str, dict[str, Any]] = {}
    for day_val, st, count, vol in res_trend.all():
        date_str = _format_date(day_val)
        if date_str not in trends_map:
            trends_map[date_str] = {
                "date": date_str,
                "total_payments": 0,
                "succeeded_count": 0,
                "failed_count": 0,
                "succeeded_volume_minor": 0,
            }
        trends_map[date_str]["total_payments"] += count
        if st == "succeeded":
            trends_map[date_str]["succeeded_count"] += count
            trends_map[date_str]["succeeded_volume_minor"] += int(vol)
        elif st == "failed":
            trends_map[date_str]["failed_count"] += count

    daily_trends = [
        PaymentDailyTrend(
            date=v["date"],
            total_payments=v["total_payments"],
            succeeded_count=v["succeeded_count"],
            failed_count=v["failed_count"],
            succeeded_volume_minor=v["succeeded_volume_minor"],
        )
        for v in trends_map.values()
    ]

    return PaymentAnalyticsResponse(
        date_from=date_from,
        date_to=date_to,
        currency=currency or "INR",
        total_payments=total_payments,
        total_volume_minor=total_volume_minor,
        status_counts=status_counts,
        success_rate=success_rate,
        failure_rate=failure_rate,
        refund_rate=refund_rate,
        daily_trends=daily_trends,
    )
