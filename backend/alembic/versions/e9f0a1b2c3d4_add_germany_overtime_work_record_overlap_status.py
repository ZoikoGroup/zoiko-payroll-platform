"""add germany overtime work record overlap status

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-09-07 00:00:00.000000

Phase 8AQ — docs/PHASE_8AQ_GERMANY_OVERTIME_REVERSAL_AND_SOURCE_PRECEDENCE_HARDENING_REPORT.md.

Additive only: one new nullable column, overlap_status, on the existing
payroll_germany_overtime_work_records table. NULL means no detected
ambiguity (the default for every pre-existing row — this migration does
NOT retroactively scan existing rows for overlaps; the recompute helper
runs going forward on create/approval-status-change, matching this
phase's own "do not invent precedence, only prevent ambiguous records
from silently becoming payable going forward" scope). No existing
column is altered or dropped.

LOCAL/TEST VERIFICATION ONLY per this phase's explicit database-safety
rule — never applied to the shared remote Postgres instance.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'payroll_germany_overtime_work_records',
        sa.Column('overlap_status', sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payroll_germany_overtime_work_records', 'overlap_status')
