"""Add version column to prescriptions table for tracking amendments.

Revision ID: 0007_prescription_version
Revises: 0006_consultation_status_chk
Create Date: 2026-10-28 18:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0007_prescription_version"
down_revision: str | None = "0006_consultation_status_chk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prescriptions",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("prescriptions", "version")
