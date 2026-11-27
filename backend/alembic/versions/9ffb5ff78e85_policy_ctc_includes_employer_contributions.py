"""policy: CTC includes employer contributions (India)

Revision ID: 9ffb5ff78e85
Revises: c8d2f6a4e1b9
Create Date: 2026-11-27 00:00:00.000000

payroll_policies.ctc_includes_employer_contributions (default false).

Off (every organisation, unchanged): monthly gross = annual CTC / 12 and
the employer's statutory contributions are paid on top of CTC. On (India):
the fixed monthly gross is solved so that gross + employer PF + employer
ESI + EDLI = CTC / 12 — the common Indian CTC convention.

Additive only; skipped when the column already exists. Both directions are
idempotent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9ffb5ff78e85'
down_revision: Union[str, Sequence[str], None] = 'c8d2f6a4e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'payroll_policies'
COLUMN = 'ctc_includes_employer_contributions'


def _columns():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return None
    return {c['name'] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _columns()
    if existing is not None and COLUMN not in existing:
        op.add_column(TABLE, sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    existing = _columns()
    if existing is not None and COLUMN in existing:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column(COLUMN)
