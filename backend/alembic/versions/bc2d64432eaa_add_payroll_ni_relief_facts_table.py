"""add payroll_ni_relief_facts table

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-09-09 04:00:00.000000

ZP-TAX-UK-2026-27-001 §9.1/§9.3 gap-closure Part 2: NI category relief
eligibility (Freeport/Investment Zone/veteran/apprentice) needs to be
stored as its own evidence, separate from the NI category letter, per
the document's explicit "Relief eligibility is not a rate toggle"
instruction. A brand-new table, not a repeat of the payroll_ytd_
accumulators/payroll_source_artifacts "never migrated" bug — created
correctly the first time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc2d64432eaa'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_ni_relief_facts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('relief_type', sa.String(length=20), nullable=False),
        sa.Column('reference', sa.String(length=200), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payroll_ni_relief_facts')
