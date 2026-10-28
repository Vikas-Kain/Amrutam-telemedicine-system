"""Add next_retry_at column and composite index to outbox_events.

Revision ID: 0010_outbox_retry_fields
Revises: 0009_analytics_indexes
Create Date: 2026-10-28 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0010_outbox_retry_fields"
down_revision: str | None = "0009_analytics_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add next_retry_at timestamp for bounded exponential backoff scheduling
    op.add_column(
        "outbox_events",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_status_next_retry",
        "outbox_events",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_next_retry", table_name="outbox_events")
    op.drop_column("outbox_events", "next_retry_at")
