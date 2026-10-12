"""add germany contribution ceiling configuration table

Revision ID: 5a472144d222
Revises: 4be49aedff7c
Create Date: 2026-09-02 20:00:00.000000

Additive only: one brand-new table, payroll_germany_contribution_ceilings —
branch-aware (GKV_PV vs RV_ALV) effective-dated contribution ceiling
configuration (ZP-TAX-DE-2026-001 §9). Configuration/registry only; no
contribution calculation, no existing table/column changes (including
ContributionRate, which is left completely untouched), no seed data (the
2026 figures from the spec are used only in tests/docs as clearly-labeled
fixtures, never inserted by this migration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a472144d222'
down_revision: Union[str, Sequence[str], None] = '4be49aedff7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_contribution_ceilings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch', sa.String(length=20), nullable=False),
        sa.Column('monthly_ceiling', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('annual_ceiling', sa.Numeric(precision=12, scale=2), nullable=False),
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
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_contribution_ceilings.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_germany_contribution_ceilings_id'),
        'payroll_germany_contribution_ceilings', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_germany_contribution_ceilings_branch'),
        'payroll_germany_contribution_ceilings', ['branch'], unique=False,
    )
    op.create_index(
        'ix_contribution_ceiling_branch_period', 'payroll_germany_contribution_ceilings',
        ['branch', 'effective_from'], unique=False,
    )
    op.create_index(
        'uq_contribution_ceiling_one_open_period', 'payroll_germany_contribution_ceilings',
        ['branch'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_contribution_ceiling_one_open_period', table_name='payroll_germany_contribution_ceilings')
    op.drop_index('ix_contribution_ceiling_branch_period', table_name='payroll_germany_contribution_ceilings')
    op.drop_index(op.f('ix_payroll_germany_contribution_ceilings_branch'), table_name='payroll_germany_contribution_ceilings')
    op.drop_index(op.f('ix_payroll_germany_contribution_ceilings_id'), table_name='payroll_germany_contribution_ceilings')
    op.drop_table('payroll_germany_contribution_ceilings')
