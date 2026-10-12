"""add super guarantee liabilities table

Revision ID: 226e01315a66
Revises: 2fdc8b69e57d
Create Date: 2026-09-16

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), Payday Super
Phase 2 — payroll_super_guarantee_liabilities, one row per (employee,
payslip) Superannuation Guarantee payment obligation. See
models.SuperGuaranteeLiability's own docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '226e01315a66'
down_revision: Union[str, Sequence[str], None] = '2fdc8b69e57d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_super_guarantee_liabilities',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('payslip_item_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True, index=True),
        sa.Column('pay_date', sa.Date(), nullable=False),
        sa.Column('qualifying_earnings', sa.Numeric(14, 2), nullable=False),
        sa.Column('sg_rate_pct', sa.Numeric(6, 4), nullable=False),
        sa.Column('sg_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('ytd_qualifying_earnings_after', sa.Numeric(14, 2), nullable=True),
        sa.Column('mcb_reached', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('fund_receipt_deadline', sa.Date(), nullable=False),
        sa.Column('deadline_extended_to', sa.Date(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exception_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payroll_super_guarantee_liabilities')
