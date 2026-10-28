"""Add composite and date indexes for admin analytics.

Revision ID: 0009_analytics_indexes
Revises: 0008_payment_status_chk
Create Date: 2026-10-28 19:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0009_analytics_indexes"
down_revision: str | None = "0008_payment_status_chk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Indexes on consultations for efficient time-series aggregation and status filtering
    op.create_index(
        "ix_consultations_created_at",
        "consultations",
        ["created_at"],
    )
    op.create_index(
        "ix_consultations_status_created_at",
        "consultations",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_consultations_doctor_created_at",
        "consultations",
        ["doctor_id", "created_at"],
    )

    # Indexes on payments for volume aggregation and status/currency filtering
    op.create_index(
        "ix_payments_created_at",
        "payments",
        ["created_at"],
    )
    op.create_index(
        "ix_payments_status_created_at",
        "payments",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_payments_currency_created_at",
        "payments",
        ["currency", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_payments_currency_created_at", table_name="payments")
    op.drop_index("ix_payments_status_created_at", table_name="payments")
    op.drop_index("ix_payments_created_at", table_name="payments")
    op.drop_index("ix_consultations_doctor_created_at", table_name="consultations")
    op.drop_index("ix_consultations_status_created_at", table_name="consultations")
    op.drop_index("ix_consultations_created_at", table_name="consultations")
