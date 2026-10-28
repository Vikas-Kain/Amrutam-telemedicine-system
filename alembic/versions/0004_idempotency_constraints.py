"""Add idempotency status check constraint and expires_at index.

Revision ID: 0004_idempotency_constraints
Revises: 0003_slot_constraints_and_idx
Create Date: 2026-10-28 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (max 32 chars).
revision: str = "0004_idempotency_constraints"
down_revision: str | None = "0003_slot_constraints_and_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add check constraint enforcing valid idempotency record statuses
    op.create_check_constraint(
        "chk_idempotency_keys_status",
        "idempotency_keys",
        "status IN ('in_progress', 'completed', 'failed')",
    )

    # 2. Add index on expires_at for efficient cleanup and pruning of expired keys
    op.create_index(
        "ix_idempotency_keys_expires_at",
        "idempotency_keys",
        ["expires_at"],
    )


def downgrade() -> None:
    # 1. Remove index on expires_at
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")

    # 2. Remove check constraint
    op.drop_constraint("chk_idempotency_keys_status", "idempotency_keys", type_="check")
