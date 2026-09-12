"""add germany minijob midijob parameter table

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-10 00:00:00.000000

Phase 8BK — one new table, payroll_germany_minijob_midijob_parameters:
an effective-dated, maker-checker-governed registry for the Germany
Minijob/Midijob statutory rates/thresholds/formula coefficients that
were previously plain hardcoded Python constants
(hardcoded_defaults.py) with no effective dating at all — see
docs/PHASE_8BK_GERMANY_MINIJOB_MIDIJOB_STATUTORY_REGISTRY_REPORT.md for
the full architecture decision (why this is a new, dedicated,
parameter_code+value table rather than routed through
ContributionRate/rate_map or folded into GermanyPvConfiguration).

Purely additive: one brand-new table, identical lifecycle/overlap-guard
shape as payroll_germany_contribution_ceilings (Phase 5) — no existing
table/column altered or dropped, no seed data (every 2026 value used in
this phase's own tests is a clearly-labeled synthetic/test fixture,
never inserted by this migration). Starts empty in every environment;
every consuming calculation falls back to its existing hardcoded
default until/unless a real PUBLISHED row is entered by a Super Admin.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_minijob_midijob_parameters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('parameter_code', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column('value_type', sa.String(length=30), nullable=False),
        sa.Column('label', sa.String(length=150), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('authority_source_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['authority_source_id'], ['payroll_source_artifacts.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_minijob_midijob_parameters.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_germany_minijob_midijob_parameters_id'),
        'payroll_germany_minijob_midijob_parameters', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_germany_minijob_midijob_parameters_parameter_code'),
        'payroll_germany_minijob_midijob_parameters', ['parameter_code'], unique=False,
    )
    op.create_index(
        'ix_minijob_midijob_parameter_code_period', 'payroll_germany_minijob_midijob_parameters',
        ['parameter_code', 'effective_from'], unique=False,
    )
    op.create_index(
        'uq_minijob_midijob_parameter_one_open_period', 'payroll_germany_minijob_midijob_parameters',
        ['parameter_code'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_minijob_midijob_parameter_one_open_period', table_name='payroll_germany_minijob_midijob_parameters')
    op.drop_index('ix_minijob_midijob_parameter_code_period', table_name='payroll_germany_minijob_midijob_parameters')
    op.drop_index(
        op.f('ix_payroll_germany_minijob_midijob_parameters_parameter_code'),
        table_name='payroll_germany_minijob_midijob_parameters',
    )
    op.drop_index(op.f('ix_payroll_germany_minijob_midijob_parameters_id'), table_name='payroll_germany_minijob_midijob_parameters')
    op.drop_table('payroll_germany_minijob_midijob_parameters')
