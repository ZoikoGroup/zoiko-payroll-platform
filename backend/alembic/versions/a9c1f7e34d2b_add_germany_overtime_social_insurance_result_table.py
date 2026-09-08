"""add germany overtime social insurance result table

Revision ID: a9c1f7e34d2b
Revises: f2a8d4c61b3e
Create Date: 2026-09-04 00:00:00.000000

Phase 8AG (docs/PHASE_8AG_GERMANY_OVERTIME_SOCIAL_INSURANCE_TREATMENT_REPORT.md).

Additive only:

One new table — payroll_germany_overtime_social_insurance_results — the
SOCIAL-INSURANCE (§1 SvEV) calculation-preview result for one physical
time range of a GermanyOvertimeWorkRecord. No wage-tax field exists on
this table, and it shares no row with GermanyOvertimeWageTaxResult (Phase
8AF) — completely independent calculation path. Not populated by any
existing code path; starts empty in every environment. No existing
column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c1f7e34d2b'
down_revision: Union[str, Sequence[str], None] = 'f2a8d4c61b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_overtime_social_insurance_results',
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
        sa.Column('si_grundlohn_hourly', sa.Numeric(10, 2), nullable=True),
        sa.Column(
            'si_cap_rule_id', sa.Integer(),
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
        sa.Column('combined_premium_pct', sa.Numeric(6, 2), nullable=True),
        sa.Column('applicable_si_branches', sa.String(30), nullable=True, server_default='GKV_PV_RV_ALV'),
        sa.Column('gross_qualifying_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('si_free_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('si_contributory_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('calculation_status', sa.String(30), nullable=False),
        sa.Column('calculation_note', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        'ix_overtime_si_result_work_record', 'payroll_germany_overtime_social_insurance_results', ['work_record_id'],
    )
    op.create_index(
        'ix_overtime_si_result_org_date',
        'payroll_germany_overtime_social_insurance_results', ['organization_id', 'work_date_local'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_overtime_si_result_org_date', table_name='payroll_germany_overtime_social_insurance_results')
    op.drop_index('ix_overtime_si_result_work_record', table_name='payroll_germany_overtime_social_insurance_results')
    op.drop_table('payroll_germany_overtime_social_insurance_results')
