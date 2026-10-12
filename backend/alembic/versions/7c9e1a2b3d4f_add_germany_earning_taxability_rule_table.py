"""add germany earning taxability rule table

Revision ID: 7c9e1a2b3d4f
Revises: 5aa73d9f462d
Create Date: 2026-09-04 00:00:00.000000

Phase 8T (docs/PHASE_8T_GERMANY_EARNINGS_TAXABILITY_AND_EMPLOYER_CONTRIBUTIONS_REPORT.md).

Additive only: one new table, payroll_germany_earning_taxability_rules —
the four-dimension Germany earning/deduction taxability registry (spec
§15). Mirrors GermanyPvConfiguration's exact lifecycle/evidence/maker-
checker shape. No existing table/column altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c9e1a2b3d4f'
down_revision: Union[str, Sequence[str], None] = '5aa73d9f462d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_earning_taxability_rules',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('earning_type', sa.String(50), nullable=False, index=True),
        sa.Column('wage_tax_treatment', sa.String(30), nullable=False),
        sa.Column('gkv_pv_treatment', sa.String(30), nullable=False),
        sa.Column('rv_alv_treatment', sa.String(30), nullable=False),
        sa.Column('reporting_classification', sa.Text(), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('authority_source_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), sa.ForeignKey('payroll_germany_earning_taxability_rules.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_earning_taxability_type_period', 'payroll_germany_earning_taxability_rules',
        ['earning_type', 'effective_from'],
    )
    op.create_index(
        'uq_earning_taxability_one_open_period', 'payroll_germany_earning_taxability_rules',
        ['earning_type'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'), sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_earning_taxability_one_open_period', table_name='payroll_germany_earning_taxability_rules')
    op.drop_index('ix_earning_taxability_type_period', table_name='payroll_germany_earning_taxability_rules')
    op.drop_table('payroll_germany_earning_taxability_rules')
