"""add germany overtime statutory registries

Revision ID: d4e9b2f81a6c
Revises: c8a1e6f39b7d
Create Date: 2026-09-04 00:00:00.000000

Phase 8AD (docs/PHASE_8AD_GERMANY_OVERTIME_STATUTORY_REGISTRIES_IMPLEMENTATION.md).

Additive only:

Two new GLOBAL (not tenant-scoped) statutory registry tables —
payroll_germany_overtime_premium_categories and
payroll_germany_overtime_grundlohn_caps — mirroring
payroll_germany_contribution_ceilings' exact lifecycle shape (DRAFT ->
VERIFIED -> APPROVED -> PUBLISHED -> SUPERSEDED, SourceArtifact-linked,
maker-checker enforced at the service layer, at-most-one-open-ended-row-
per-key). Neither table holds a calculated amount, an overtime work
record, employee data, or an executable formula. Not populated by any
existing code path; both start empty in every environment. No existing
column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e9b2f81a6c'
down_revision: Union[str, Sequence[str], None] = 'c8a1e6f39b7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_overtime_premium_categories',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('category_code', sa.String(30), nullable=False, index=True),
        sa.Column('wage_tax_free_pct', sa.Numeric(6, 2), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('authority_source_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column(
            'previous_version_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_premium_categories.id'), nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_overtime_premium_category_period',
        'payroll_germany_overtime_premium_categories', ['category_code', 'effective_from'],
    )
    op.create_index(
        'uq_overtime_premium_category_one_open_period',
        'payroll_germany_overtime_premium_categories', ['category_code'],
        unique=True, sqlite_where=sa.text('effective_to IS NULL'), postgresql_where=sa.text('effective_to IS NULL'),
    )

    op.create_table(
        'payroll_germany_overtime_grundlohn_caps',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('dimension', sa.String(20), nullable=False, index=True),
        sa.Column('hourly_cap_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('authority_source_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column(
            'previous_version_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_overtime_grundlohn_caps.id'), nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_overtime_grundlohn_cap_period',
        'payroll_germany_overtime_grundlohn_caps', ['dimension', 'effective_from'],
    )
    op.create_index(
        'uq_overtime_grundlohn_cap_one_open_period',
        'payroll_germany_overtime_grundlohn_caps', ['dimension'],
        unique=True, sqlite_where=sa.text('effective_to IS NULL'), postgresql_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_overtime_grundlohn_cap_one_open_period', table_name='payroll_germany_overtime_grundlohn_caps')
    op.drop_index('ix_overtime_grundlohn_cap_period', table_name='payroll_germany_overtime_grundlohn_caps')
    op.drop_table('payroll_germany_overtime_grundlohn_caps')

    op.drop_index('uq_overtime_premium_category_one_open_period', table_name='payroll_germany_overtime_premium_categories')
    op.drop_index('ix_overtime_premium_category_period', table_name='payroll_germany_overtime_premium_categories')
    op.drop_table('payroll_germany_overtime_premium_categories')
