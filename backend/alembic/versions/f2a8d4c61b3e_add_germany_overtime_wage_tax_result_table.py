"""add germany overtime wage tax result table

Revision ID: f2a8d4c61b3e
Revises: e7c3a5f92d1b
Create Date: 2026-09-04 00:00:00.000000

Phase 8AF (docs/PHASE_8AF_GERMANY_OVERTIME_WAGE_TAX_CALCULATION.md).

Additive only:

One new table — payroll_germany_overtime_wage_tax_results — the WAGE-TAX
(§3b EStG) calculation-preview result for one physical time range of a
GermanyOvertimeWorkRecord. No social-insurance field exists on this table.
Not populated by any existing code path; starts empty in every
environment. No existing column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a8d4c61b3e'
down_revision: Union[str, Sequence[str], None] = 'e7c3a5f92d1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_overtime_wage_tax_results',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column(
            'work_record_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_work_records.id'), nullable=False, index=True,
        ),
        sa.Column('segment_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('segment_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('work_date_local', sa.Date(), nullable=False, index=True),
        sa.Column('qualifying_hours', sa.Numeric(6, 4), nullable=False),
        sa.Column('actual_grundlohn_hourly', sa.Numeric(10, 2), nullable=True),
        sa.Column('tax_grundlohn_hourly', sa.Numeric(10, 2), nullable=True),
        sa.Column(
            'grundlohn_cap_rule_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_grundlohn_caps.id'), nullable=True,
        ),
        sa.Column('primary_category_code', sa.String(30), nullable=True),
        sa.Column(
            'primary_category_rule_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_premium_categories.id'), nullable=True,
        ),
        sa.Column('concurrent_category_code', sa.String(30), nullable=True),
        sa.Column(
            'concurrent_category_rule_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_premium_categories.id'), nullable=True,
        ),
        sa.Column('combined_tax_free_pct', sa.Numeric(6, 2), nullable=True),
        sa.Column('gross_qualifying_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('tax_free_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('taxable_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('calculation_status', sa.String(30), nullable=False),
        sa.Column('calculation_note', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        'ix_overtime_wage_tax_result_work_record', 'payroll_germany_overtime_wage_tax_results', ['work_record_id'],
    )
    op.create_index(
        'ix_overtime_wage_tax_result_org_date',
        'payroll_germany_overtime_wage_tax_results', ['organization_id', 'work_date_local'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_overtime_wage_tax_result_org_date', table_name='payroll_germany_overtime_wage_tax_results')
    op.drop_index('ix_overtime_wage_tax_result_work_record', table_name='payroll_germany_overtime_wage_tax_results')
    op.drop_table('payroll_germany_overtime_wage_tax_results')
