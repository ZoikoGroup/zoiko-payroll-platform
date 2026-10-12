"""add germany overtime work record table

Revision ID: c8a1e6f39b7d
Revises: b3f7c1a9d4e2
Create Date: 2026-09-04 00:00:00.000000

Phase 8AC (docs/PHASE_8AC_GERMANY_OVERTIME_WORK_RECORD_FACT_CAPTURE_REPORT.md).

Additive only:

One new table — payroll_germany_overtime_work_records — the "work
performed" FACT layer of Phase 8AA's ARCHITECTURE_D design. Records only
date/time/hours/entry-source/HR-approval-status; carries no premium, tax,
or social-insurance columns (those belong to a future calculation phase's
own output table). Not populated by any existing code path; starts empty
in every environment. No existing column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a1e6f39b7d'
down_revision: Union[str, Sequence[str], None] = 'b3f7c1a9d4e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_overtime_work_records',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column(
            'source_attendance_id', sa.Integer(),
            sa.ForeignKey('payroll_attendance_records.id'), nullable=True,
        ),
        sa.Column('work_date', sa.Date(), nullable=False, index=True),
        sa.Column('start_datetime', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_datetime', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('entry_source', sa.String(20), nullable=False),
        sa.Column('hr_approval_status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('source_attendance_id', name='uq_germany_overtime_work_record_source_attendance'),
    )
    op.create_index(
        'ix_germany_overtime_work_record_org_emp_date',
        'payroll_germany_overtime_work_records', ['organization_id', 'employee_id', 'work_date'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_germany_overtime_work_record_org_emp_date', table_name='payroll_germany_overtime_work_records')
    op.drop_table('payroll_germany_overtime_work_records')
