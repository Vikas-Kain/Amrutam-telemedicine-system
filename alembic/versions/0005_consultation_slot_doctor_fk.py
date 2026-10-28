"""Enforce consultation slot-to-doctor consistency at the database level.

Adds a composite unique key on availability_slots (id, doctor_id) and a composite foreign key
from consultations (slot_id, doctor_id) so PostgreSQL rejects any consultation whose doctor_id
does not own the referenced slot (defense in depth behind the booking service check).

Revision ID: 0005_consultation_slot_doctor_fk
Revises: 0004_idempotency_constraints
Create Date: 2026-10-28 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0005_consultation_slot_doctor_fk"
down_revision: str | None = "0004_idempotency_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_availability_slots_id_doctor",
        "availability_slots",
        ["id", "doctor_id"],
    )
    op.create_foreign_key(
        "fk_consultations_slot_doctor",
        "consultations",
        "availability_slots",
        ["slot_id", "doctor_id"],
        ["id", "doctor_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_consultations_slot_doctor", "consultations", type_="foreignkey")
    op.drop_constraint("uq_availability_slots_id_doctor", "availability_slots", type_="unique")
