"""add payslip_items.tax_week and tax_month columns

Revision ID: 1a6f89e93080
Revises: e3c314b687e6
Create Date: 2026-09-09 06:00:00.000000

ZP-TAX-UK-2026-27-001 §18.1 gap-closure Part 6: HMRC tax week (1-53) and
tax month (1-12) metadata, pure calendar-derived, no calculation impact.
NULL for every existing payslip.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a6f89e93080'
down_revision: Union[str, Sequence[str], None] = 'e3c314b687e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payslip_items', sa.Column('tax_week', sa.Integer(), nullable=True))
    op.add_column('payslip_items', sa.Column('tax_month', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'tax_month')
    op.drop_column('payslip_items', 'tax_week')
