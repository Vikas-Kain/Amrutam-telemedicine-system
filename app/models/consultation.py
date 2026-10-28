"""Consultation entity model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.doctor import AvailabilitySlot, Doctor
    from app.models.payment import Payment
    from app.models.prescription import Prescription
    from app.models.user import User


class Consultation(Base):
    """Appointment and clinical consultation record."""

    __tablename__ = "consultations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("availability_slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="booked",
        server_default="booked",
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        # Partial unique index guarantees atomic, exclusive booking per slot
        # where status is not cancelled
        Index(
            "uq_consultations_active_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status NOT IN ('cancelled')"),
        ),
        # Composite FK: the consultation's doctor must own the referenced slot.
        ForeignKeyConstraint(
            ["slot_id", "doctor_id"],
            ["availability_slots.id", "availability_slots.doctor_id"],
            name="fk_consultations_slot_doctor",
            ondelete="RESTRICT",
        ),
    )

    patient: Mapped["User"] = relationship("User", foreign_keys=[patient_id])
    doctor: Mapped["Doctor"] = relationship(
        "Doctor", foreign_keys=[doctor_id], back_populates="consultations"
    )
    slot: Mapped["AvailabilitySlot"] = relationship(
        "AvailabilitySlot",
        back_populates="consultations",
        foreign_keys=[slot_id],
        primaryjoin="Consultation.slot_id == AvailabilitySlot.id",
    )
    prescription: Mapped["Prescription | None"] = relationship(
        "Prescription",
        back_populates="consultation",
        uselist=False,
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="consultation",
    )
