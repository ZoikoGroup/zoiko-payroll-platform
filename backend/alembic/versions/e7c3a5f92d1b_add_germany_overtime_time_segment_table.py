"""add germany overtime time segment table

Revision ID: e7c3a5f92d1b
Revises: d4e9b2f81a6c
Create Date: 2026-09-04 00:00:00.000000

Phase 8AE (docs/PHASE_8AE_GERMANY_OVERTIME_STATUTORY_CLASSIFICATION.md).

Additive only:

One new table — payroll_germany_overtime_time_segments — the §3b EStG
time-window CLASSIFICATION result for a GermanyOvertimeWorkRecord. Holds
only statutory/calendar facts (segment start/end, hours, premium category,
whether a PUBLISHED GermanyOvertimePremiumCategory rule exists for it, and
which exact rule row) — no monetary field of any kind. Not populated by
any existing code path; starts empty in every environment. No existing
column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c3a5f92d1b'
down_revision: Union[str, Sequence[str], None] = 'd4e9b2f81a6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_overtime_time_segments',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column(
            'work_record_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_work_records.id'), nullable=False, index=True,
        ),
        sa.Column('segment_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('segment_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hours', sa.Numeric(6, 4), nullable=False),
        sa.Column('premium_category', sa.String(30), nullable=False, index=True),
        sa.Column('classification_status', sa.String(20), nullable=False),
        sa.Column(
            'category_rule_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_premium_categories.id'), nullable=True,
        ),
        sa.Column('work_date_local', sa.Date(), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        'ix_overtime_time_segment_work_record', 'payroll_germany_overtime_time_segments', ['work_record_id'],
    )
    op.create_index(
        'ix_overtime_time_segment_category_date',
        'payroll_germany_overtime_time_segments', ['premium_category', 'work_date_local'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_overtime_time_segment_category_date', table_name='payroll_germany_overtime_time_segments')
    op.drop_index('ix_overtime_time_segment_work_record', table_name='payroll_germany_overtime_time_segments')
    op.drop_table('payroll_germany_overtime_time_segments')
