"""Analytics request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConsultationDailyTrend(BaseModel):
    """Daily aggregate bucket for consultation volume and status counts."""

    model_config = ConfigDict(from_attributes=True)

    date: str = Field(..., description="Date string in YYYY-MM-DD format")
    total: int = Field(..., ge=0, description="Total consultations on this date")
    by_status: dict[str, int] = Field(
        default_factory=dict, description="Consultation counts grouped by status"
    )


class ConsultationAnalyticsResponse(BaseModel):
    """Aggregate analytics for consultations."""

    model_config = ConfigDict(from_attributes=True)

    date_from: datetime = Field(..., description="Start of evaluated time range (UTC)")
    date_to: datetime = Field(..., description="End of evaluated time range (UTC)")
    total_consultations: int = Field(..., ge=0, description="Total consultations created in range")
    status_counts: dict[str, int] = Field(..., description="Counts grouped by consultation status")
    completion_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of completed to total consultations (0.0 - 1.0)"
    )
    daily_trends: list[ConsultationDailyTrend] = Field(
        default_factory=list, description="Chronological daily aggregate trends"
    )


class BookingDailyTrend(BaseModel):
    """Daily aggregate bucket for booking and cancellation volume."""

    model_config = ConfigDict(from_attributes=True)

    date: str = Field(..., description="Date string in YYYY-MM-DD format")
    total_bookings: int = Field(..., ge=0, description="Total bookings created on this date")
    cancelled_bookings: int = Field(..., ge=0, description="Total cancellations on this date")
    no_show_bookings: int = Field(..., ge=0, description="Total no-shows on this date")


class BookingAnalyticsResponse(BaseModel):
    """Aggregate analytics for booking, cancellation, and no-show rates."""

    model_config = ConfigDict(from_attributes=True)

    date_from: datetime = Field(..., description="Start of evaluated time range (UTC)")
    date_to: datetime = Field(..., description="End of evaluated time range (UTC)")
    total_bookings: int = Field(..., ge=0, description="Total bookings in evaluated range")
    confirmed_bookings: int = Field(..., ge=0, description="Total confirmed bookings")
    completed_bookings: int = Field(..., ge=0, description="Total completed bookings")
    cancelled_bookings: int = Field(..., ge=0, description="Total cancelled bookings")
    cancellation_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of cancelled to total bookings (0.0 - 1.0)"
    )
    no_show_bookings: int = Field(..., ge=0, description="Total no-show appointments")
    no_show_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of no-shows to total bookings (0.0 - 1.0)"
    )
    daily_trends: list[BookingDailyTrend] = Field(
        default_factory=list, description="Chronological daily aggregate booking trends"
    )


class PaymentDailyTrend(BaseModel):
    """Daily aggregate bucket for payment outcomes."""

    model_config = ConfigDict(from_attributes=True)

    date: str = Field(..., description="Date string in YYYY-MM-DD format")
    total_payments: int = Field(..., ge=0, description="Total payment transactions on this date")
    succeeded_count: int = Field(..., ge=0, description="Number of successful transactions")
    failed_count: int = Field(..., ge=0, description="Number of failed transactions")
    succeeded_volume_minor: int = Field(
        ..., ge=0, description="Total succeeded amount in integer minor units"
    )


class PaymentAnalyticsResponse(BaseModel):
    """Aggregate analytics for payment volume, outcomes, and failure ratios."""

    model_config = ConfigDict(from_attributes=True)

    date_from: datetime = Field(..., description="Start of evaluated time range (UTC)")
    date_to: datetime = Field(..., description="End of evaluated time range (UTC)")
    currency: str = Field(default="INR", description="Currency code for evaluated volume")
    total_payments: int = Field(..., ge=0, description="Total payment attempts in evaluated range")
    total_volume_minor: int = Field(
        ..., ge=0, description="Total succeeded payment volume in minor currency units"
    )
    status_counts: dict[str, int] = Field(..., description="Counts grouped by payment status")
    success_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of succeeded to total payments (0.0 - 1.0)"
    )
    failure_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of failed to total payments (0.0 - 1.0)"
    )
    refund_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of refunded to total payments (0.0 - 1.0)"
    )
    daily_trends: list[PaymentDailyTrend] = Field(
        default_factory=list, description="Chronological daily aggregate payment trends"
    )
