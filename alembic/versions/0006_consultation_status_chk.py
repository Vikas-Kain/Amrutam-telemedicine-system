"""Add consultation status check constraint.

Revision ID: 0006_consultation_status_chk
Revises: 0005_consultation_slot_doctor_fk
Create Date: 2026-10-28 17:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0006_consultation_status_chk"
down_revision: str | None = "0005_consultation_slot_doctor_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "chk_consultations_status",
        "consultations",
        "status IN ('booked', 'confirmed', 'in_progress', 'completed', 'cancelled', 'no_show')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_consultations_status", "consultations", type_="check")
