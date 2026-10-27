"""Add slot status constraint, range index, and exclusion constraint for overlap prevention.

Revision ID: 0003_slot_constraints_and_idx
Revises: 0002_create_core_models
Create Date: 2026-10-28 01:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0003_slot_constraints_and_idx"
down_revision: str | None = "0002_create_core_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enable btree_gist extension for GiST index on uuid and timestamp types
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # 2. Add status check constraint enforcing exact valid slot statuses
    op.create_check_constraint(
        "chk_availability_slots_status",
        "availability_slots",
        "status IN ('available', 'booked', 'blocked')",
    )

    # 3. Add composite range index for fast doctor slot date-range lookups
    op.create_index(
        "ix_availability_slots_doctor_range",
        "availability_slots",
        ["doctor_id", "start_at", "end_at"],
    )

    # 4. Add exclusion constraint preventing overlapping time intervals for the same doctor
    op.execute(
        """
        ALTER TABLE availability_slots
        ADD CONSTRAINT exclude_overlapping_doctor_slots
        EXCLUDE USING gist (
            doctor_id WITH =,
            tstzrange(start_at, end_at) WITH &&
        );
        """
    )


def downgrade() -> None:
    # 1. Remove exclusion constraint
    op.execute(
        "ALTER TABLE availability_slots DROP CONSTRAINT IF EXISTS exclude_overlapping_doctor_slots;"
    )

    # 2. Remove composite range index
    op.drop_index("ix_availability_slots_doctor_range", table_name="availability_slots")

    # 3. Remove status check constraint
    op.drop_constraint("chk_availability_slots_status", "availability_slots", type_="check")
