"""add germany pap algorithm asset table

Revision ID: 6b2f7dbccf37
Revises: 3d05d138d022
Create Date: 2026-09-02 18:00:00.000000

Additive only: one brand-new table, payroll_germany_pap_assets — the
versioned, source-hashed, immutable-once-published container for the
German BMF PAP wage-tax algorithm (ZP-TAX-DE-2026-001 §5/§17/§18). No
execution logic; no existing table/column changes. No seed data — no PAP
version/hash is invented by this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b2f7dbccf37'
down_revision: Union[str, Sequence[str], None] = '3d05d138d022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_pap_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction_country', sa.String(length=10), server_default='DE', nullable=False),
        sa.Column('tax_year', sa.String(length=20), nullable=False),
        sa.Column('pap_version', sa.String(length=100), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('source_content_path', sa.String(length=500), nullable=True),
        sa.Column('source_content_sha256', sa.String(length=64), nullable=True),
        sa.Column('build_identifier', sa.String(length=100), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['source_document_id'], ['payroll_source_artifacts.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_pap_assets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jurisdiction_country', 'tax_year', 'pap_version', name='uq_pap_asset_country_year_version'),
    )
    op.create_index(
        op.f('ix_payroll_germany_pap_assets_id'), 'payroll_germany_pap_assets', ['id'], unique=False,
    )
    op.create_index(
        'ix_pap_asset_country_year_status', 'payroll_germany_pap_assets',
        ['jurisdiction_country', 'tax_year', 'status'], unique=False,
    )
    op.create_index(
        'uq_pap_asset_one_published_per_year', 'payroll_germany_pap_assets',
        ['jurisdiction_country', 'tax_year'], unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
        sqlite_where=sa.text("status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_pap_asset_one_published_per_year', table_name='payroll_germany_pap_assets')
    op.drop_index('ix_pap_asset_country_year_status', table_name='payroll_germany_pap_assets')
    op.drop_index(op.f('ix_payroll_germany_pap_assets_id'), table_name='payroll_germany_pap_assets')
    op.drop_table('payroll_germany_pap_assets')
