"""add organizations.workspace_type column

Revision ID: 38263fcf0a1d
Revises: 2b3c4d5e6f70
Create Date: 2026-09-15 00:00:00.000000

Prompt 2 — organizations.workspace_type: the workspace flavor of a tenant,
"PRODUCTION" (regular tenant onboarded via /auth/register) or "EVALUATION"
(30-day free evaluation onboarded via /auth/register-trial).

Written defensively: the column may already exist in some environments as a
nullable column with no default, because migrations/sync_schema.py added it
ad hoc on the live database before this real Alembic revision was authored.
The migration therefore:

  1. Checks the live table for the column (via sa.inspect) before adding it —
     a plain op.add_column would abort with "column already exists" on the
     live database.
  2. Backfills every NULL value to 'PRODUCTION' — the documented reading of
     an absent/legacy value (a row predating the column is a production
     tenant, not an evaluation trial).
  3. Applies NOT NULL + DEFAULT 'PRODUCTION' whether the column was just
     added or found already present.

Purely additive: one column on an existing table, no table altered/dropped,
no data rewritten other than the NULL -> 'PRODUCTION' backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38263fcf0a1d'
down_revision: Union[str, Sequence[str], None] = '2b3c4d5e6f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("organizations")}

    if "workspace_type" not in existing_columns:
        op.add_column(
            "organizations",
            sa.Column("workspace_type", sa.String(length=20), nullable=True, server_default="PRODUCTION"),
        )

    op.execute("UPDATE organizations SET workspace_type = 'PRODUCTION' WHERE workspace_type IS NULL")

    op.alter_column(
        "organizations",
        "workspace_type",
        existing_type=sa.String(length=20),
        nullable=False,
        server_default="PRODUCTION",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("organizations", "workspace_type")