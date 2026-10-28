"""Doctor profile and availability slot models."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.consultation import Consultation
    from app.models.user import User


class Doctor(Base):
    """Doctor professional profile entity."""

    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    specialization: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    license_number: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    consultation_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("consultation_fee_minor >= 0", name="chk_doctors_fee_non_negative"),
    )

    user: Mapped["User"] = relationship("User", back_populates="doctor", lazy="selectin")
    slots: Mapped[list["AvailabilitySlot"]] = relationship(
        "AvailabilitySlot",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    consultations: Mapped[list["Consultation"]] = relationship(
        "Consultation",
        back_populates="doctor",
    )

    @property
    def name(self) -> str:
        """Return doctor's full legal name from associated profile."""
        if self.user and self.user.profile and self.user.profile.full_name:
            return self.user.profile.full_name
        return ""

    @property
    def full_name(self) -> str:
        """Alias for doctor name."""
        return self.name


class AvailabilitySlot(Base):
    """Doctor availability time slot for appointment scheduling."""

    __tablename__ = "availability_slots"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="available",
        server_default="available",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("end_at > start_at", name="chk_slot_time_interval"),
        CheckConstraint(
            "status IN ('available', 'booked', 'blocked')",
            name="chk_availability_slots_status",
        ),
        Index("ix_availability_slots_doctor_start_status", "doctor_id", "start_at", "status"),
        Index("ix_availability_slots_doctor_range", "doctor_id", "start_at", "end_at"),
        # Referenced by consultations' composite FK (slot_id, doctor_id).
        UniqueConstraint("id", "doctor_id", name="uq_availability_slots_id_doctor"),
    )

    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="slots")
    consultations: Mapped[list["Consultation"]] = relationship(
        "Consultation",
        back_populates="slot",
        foreign_keys="Consultation.slot_id",
        primaryjoin="AvailabilitySlot.id == Consultation.slot_id",
    )
