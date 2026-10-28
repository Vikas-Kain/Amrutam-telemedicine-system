"""Add payment status check constraint.

Revision ID: 0008_payment_status_chk
Revises: 0007_prescription_version
Create Date: 2026-10-28 18:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0008_payment_status_chk"
down_revision: str | None = "0007_prescription_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "chk_payments_status",
        "payments",
        "status IN ('pending', 'succeeded', 'failed', 'refunded', 'requires_reconciliation')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_payments_status", "payments", type_="check")
