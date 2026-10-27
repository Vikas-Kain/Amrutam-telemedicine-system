"""Initial schema bootstrap verification migration.

Revision ID: 0001_initial_bootstrap
Revises: None
Create Date: 2026-10-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_bootstrap"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create minimal bootstrap probe table to verify migration infrastructure."""
    op.create_table(
        "_schema_bootstrap_probe",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="initialized"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    """Drop bootstrap probe table."""
    op.drop_table("_schema_bootstrap_probe")
