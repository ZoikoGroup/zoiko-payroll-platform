"""add germany overtime premium component table

Revision ID: b1d6e94a7c58
Revises: a9c1f7e34d2b
Create Date: 2026-09-07 00:00:00.000000

Phase 8AH (docs/PHASE_8AH_GERMANY_OVERTIME_PREMIUM_COMPONENT_PAYSLIP_INTEGRATION_REPORT.md).

Additive only:

One new table — payroll_germany_overtime_premium_components — combines one
GermanyOvertimeWageTaxResult (Phase 8AF) row and one
GermanyOvertimeSocialInsuranceResult (Phase 8AG) row for the same physical
time range into a single presentable, four-dimension output unit. Never
recomputes either calculation. Attachment to a real payslip line
(payslip_allowance_item_id) is a separate, explicit operator action — the
column starts NULL for every row and is set only via
service.attach_germany_overtime_premium_component_to_payslip. No existing
column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1d6e94a7c58'
down_revision: Union[str, Sequence[str], None] = 'a9c1f7e34d2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_overtime_premium_components',
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
        sa.Column(
            'wage_tax_result_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_wage_tax_results.id'), nullable=True,
        ),
        sa.Column(
            'social_insurance_result_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_social_insurance_results.id'), nullable=True,
        ),
        sa.Column('combination_status', sa.String(30), nullable=False),
        sa.Column('calculation_note', sa.Text(), nullable=True),
        sa.Column('gross_premium_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('wage_tax_free_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('wage_taxable_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('si_exempt_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('si_contributory_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column(
            'payslip_allowance_item_id', sa.Integer(),
            sa.ForeignKey('payslip_allowance_items.id'), nullable=True,
        ),
        sa.Column('attached_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attached_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            'work_record_id', 'segment_start', 'segment_end',
            name='uq_overtime_premium_component_work_record_range',
        ),
    )
    op.create_index(
        'ix_overtime_premium_component_work_record', 'payroll_germany_overtime_premium_components', ['work_record_id'],
    )
    op.create_index(
        'ix_overtime_premium_component_org_date',
        'payroll_germany_overtime_premium_components', ['organization_id', 'work_date_local'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_overtime_premium_component_org_date', table_name='payroll_germany_overtime_premium_components')
    op.drop_index('ix_overtime_premium_component_work_record', table_name='payroll_germany_overtime_premium_components')
    op.drop_table('payroll_germany_overtime_premium_components')
