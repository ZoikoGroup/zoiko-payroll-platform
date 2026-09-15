"""add germany health fund registry table

Revision ID: 4be49aedff7c
Revises: 6b2f7dbccf37
Create Date: 2026-09-02 19:00:00.000000

Additive only: one brand-new table, payroll_germany_health_funds — the
effective-dated Krankenkasse (health fund) Zusatzbeitrag rate registry
(ZP-TAX-DE-2026-001 §11). Configuration/registry only; no GKV calculation,
no existing table/column changes, no seed data (no real health-fund
identity or rate value is invented by this migration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4be49aedff7c'
down_revision: Union[str, Sequence[str], None] = '6b2f7dbccf37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_health_funds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('health_fund_id', sa.String(length=50), nullable=False),
        sa.Column('fund_name', sa.String(length=200), nullable=False),
        sa.Column('supplementary_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('is_average_rate', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('member_applicability', sa.String(length=200), nullable=True),
        sa.Column('payroll_recalc_policy', sa.String(length=200), nullable=True),
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
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_health_funds.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_germany_health_funds_id'), 'payroll_germany_health_funds', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_germany_health_funds_health_fund_id'), 'payroll_germany_health_funds',
        ['health_fund_id'], unique=False,
    )
    op.create_index(
        'ix_health_fund_id_period', 'payroll_germany_health_funds',
        ['health_fund_id', 'effective_from'], unique=False,
    )
    op.create_index(
        'uq_health_fund_one_open_period', 'payroll_germany_health_funds',
        ['health_fund_id'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_health_fund_one_open_period', table_name='payroll_germany_health_funds')
    op.drop_index('ix_health_fund_id_period', table_name='payroll_germany_health_funds')
    op.drop_index(op.f('ix_payroll_germany_health_funds_health_fund_id'), table_name='payroll_germany_health_funds')
    op.drop_index(op.f('ix_payroll_germany_health_funds_id'), table_name='payroll_germany_health_funds')
    op.drop_table('payroll_germany_health_funds')
