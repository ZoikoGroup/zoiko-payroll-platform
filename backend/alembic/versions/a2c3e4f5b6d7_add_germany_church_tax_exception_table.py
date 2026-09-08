"""add germany church tax exception table

Revision ID: a2c3e4f5b6d7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-08 00:00:00.000000

Phase 8BC — schema reconciliation forensics found that
GermanyChurchTaxException (models.py, `payroll_germany_church_tax_exceptions`,
added Phase 8AM) has NEVER had a corresponding Alembic migration — confirmed
by a repo-wide search of every migration file for the table name, which
returns zero matches. This is the 18th of 18 `payroll_germany_*` tables and
the reason it exists in the SQLite test database (built via
`Base.metadata.create_all()`) but could never exist in any Alembic-managed
environment, even one fully migrated to `head`. Additive only: one new
table, mirrors `payroll_germany_accident_insurance_profiles`'s exact
maker-checker/effective-dating/self-referencing-history shape
(c7e2a94f6b31). No existing table/column changed. No exception row is
seeded by this migration — the Bad Wimpfen row (Phase 8AM) remains an
operator-entered DRAFT pending a real Super Admin publish action, per
Phase 8AM/8BB/8BC's own explicit "no auto-publish" rule.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2c3e4f5b6d7'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_church_tax_exceptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('land_code', sa.String(length=6), nullable=False),
        sa.Column('denomination', sa.String(length=30), nullable=False),
        sa.Column('municipality_postal_code', sa.String(length=10), nullable=False),
        sa.Column('scope_description', sa.String(length=300), nullable=True),
        sa.Column('exception_rate_pct', sa.Numeric(precision=5, scale=2), nullable=False),
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
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_church_tax_exceptions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_germany_church_tax_exceptions_id'),
        'payroll_germany_church_tax_exceptions', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_germany_church_tax_exceptions_land_code'),
        'payroll_germany_church_tax_exceptions', ['land_code'], unique=False,
    )
    op.create_index(
        'ix_church_tax_exception_scope', 'payroll_germany_church_tax_exceptions',
        ['land_code', 'denomination', 'municipality_postal_code'], unique=False,
    )
    op.create_index(
        'uq_church_tax_exception_one_open_period', 'payroll_germany_church_tax_exceptions',
        ['land_code', 'denomination', 'municipality_postal_code'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_church_tax_exception_one_open_period', table_name='payroll_germany_church_tax_exceptions')
    op.drop_index('ix_church_tax_exception_scope', table_name='payroll_germany_church_tax_exceptions')
    op.drop_index(op.f('ix_payroll_germany_church_tax_exceptions_land_code'), table_name='payroll_germany_church_tax_exceptions')
    op.drop_index(op.f('ix_payroll_germany_church_tax_exceptions_id'), table_name='payroll_germany_church_tax_exceptions')
    op.drop_table('payroll_germany_church_tax_exceptions')
