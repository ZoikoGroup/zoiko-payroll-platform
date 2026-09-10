"""add payroll_court_ordered_deductions table

Revision ID: 36d83be4bc14
Revises: 5ee0c0da1001
Create Date: 2026-09-09 08:00:00.000000

ZP-TAX-UK-2026-27-001 §17 gap-closure Part 8: England & Wales
Attachment of Earnings Orders, Scottish arrestments, and Northern
Ireland's own equivalent orders — one new table, empty for every
employee until an order is manually recorded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36d83be4bc14'
down_revision: Union[str, Sequence[str], None] = '5ee0c0da1001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_court_ordered_deductions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction', sa.String(length=20), nullable=False),
        sa.Column('order_type', sa.String(length=40), nullable=False),
        sa.Column('court_reference', sa.String(length=100), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('fixed_deduction_rate_pct', sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column('fixed_deduction_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('protected_earnings_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('total_amount_to_collect', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('total_amount_collected', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['employee_id'], ['payroll_employees.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payroll_court_ordered_deductions_id', 'payroll_court_ordered_deductions', ['id'], unique=False)
    op.create_index('ix_court_order_employee', 'payroll_court_ordered_deductions', ['employee_id'], unique=False)
    op.create_index('ix_court_order_org_status', 'payroll_court_ordered_deductions', ['organization_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_court_order_org_status', table_name='payroll_court_ordered_deductions')
    op.drop_index('ix_court_order_employee', table_name='payroll_court_ordered_deductions')
    op.drop_index('ix_payroll_court_ordered_deductions_id', table_name='payroll_court_ordered_deductions')
    op.drop_table('payroll_court_ordered_deductions')
