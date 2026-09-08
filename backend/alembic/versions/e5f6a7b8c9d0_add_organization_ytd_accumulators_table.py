"""add organization_ytd_accumulators table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-03 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'organization_ytd_accumulators',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('tax_year', sa.String(length=10), nullable=False),
        sa.Column('tax_component', sa.String(length=30), nullable=False),
        sa.Column('ytd_taxable_wages', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('ytd_tax_withheld', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('last_updated_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('organization_id', 'tax_year', 'tax_component', name='uq_org_ytd_accumulator_org_year_component'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('organization_ytd_accumulators')
