"""saudi_arabia_approval_fingerprint

Revision ID: c7d3e8f1a2b4
Revises: b08f04497195
Create Date: 2026-10-09 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c7d3e8f1a2b4"
down_revision = "b08f04497195"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sa_approval_fingerprint column to payroll_runs for Saudi Arabia
    # JSON column storing the approval fingerprint and its components
    # (mirrors Switzerland's CH approval fingerprint pattern)
    op.add_column(
        "payroll_runs",
        sa.Column("sa_approval_fingerprint", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payroll_runs", "sa_approval_fingerprint")