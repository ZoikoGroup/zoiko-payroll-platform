"""add germany pap release governance table

Revision ID: d1e2f3a4b5c6
Revises: c4d6e8f9a0b1
Create Date: 2026-09-03 00:00:00.000000

Phase 8G-1 (docs/PHASE_8G_1_GERMANY_PAP_RELEASE_GOVERNANCE_IMPLEMENTATION_REPORT.md).

Additive only: one brand-new table, payroll_germany_pap_releases — a
production release/activation governance record, one row per
PapAlgorithmAsset (1:1), deliberately separate from that table's own
DRAFT/REVIEW/APPROVED/PUBLISHED/SUPERSEDED statutory lifecycle (unchanged,
not touched by this migration). No existing table/column is altered, no
data is migrated, and no seed/default-satisfied evidence row is inserted
— the table starts, and remains after this migration, completely empty.
Every boolean/status default is the UNSATISFIED state (False / OPEN /
PENDING / NOT_READY), matching the model's own column defaults exactly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c4d6e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_pap_releases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pap_asset_id', sa.Integer(), nullable=False),
        sa.Column('bound_source_content_sha256', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='NOT_READY'),

        sa.Column('source_identity_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('source_identity_verified_by_id', sa.Integer(), nullable=True),
        sa.Column('source_identity_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_identity_notes', sa.Text(), nullable=True),

        sa.Column('source_hash_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('source_hash_verified_by_id', sa.Integer(), nullable=True),
        sa.Column('source_hash_verified_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('source_finality_status', sa.String(length=20), nullable=False, server_default='OPEN'),
        sa.Column('source_finality_authority', sa.String(length=200), nullable=True),
        sa.Column('source_finality_reference', sa.String(length=200), nullable=True),
        sa.Column('source_finality_verified_by_id', sa.Integer(), nullable=True),
        sa.Column('source_finality_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_finality_notes', sa.Text(), nullable=True),

        sa.Column('licensing_status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('licensing_authority', sa.String(length=200), nullable=True),
        sa.Column('licensing_reference', sa.String(length=200), nullable=True),
        sa.Column('licensing_authorization_date', sa.Date(), nullable=True),
        sa.Column('licensing_effective_date', sa.Date(), nullable=True),
        sa.Column('licensing_expiry_date', sa.Date(), nullable=True),
        sa.Column('licensing_evidence_location', sa.String(length=500), nullable=True),
        sa.Column('licensing_evidence_hash', sa.String(length=64), nullable=True),
        sa.Column('licensing_notes', sa.Text(), nullable=True),
        sa.Column('licensing_recorded_by_id', sa.Integer(), nullable=True),

        sa.Column('golden_vectors_passed', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('golden_vectors_source_sha256', sa.String(length=64), nullable=True),
        sa.Column('golden_vectors_verified_by_id', sa.Integer(), nullable=True),
        sa.Column('golden_vectors_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('golden_vectors_notes', sa.Text(), nullable=True),

        sa.Column('security_certified', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('security_certified_by_id', sa.Integer(), nullable=True),
        sa.Column('security_certified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('security_notes', sa.Text(), nullable=True),

        sa.Column('prepared_by_id', sa.Integer(), nullable=True),
        sa.Column('prepared_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by_id', sa.Integer(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),

        sa.Column('activated_by_id', sa.Integer(), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('rolled_back_by_id', sa.Integer(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=True),
        sa.Column('previous_release_id', sa.Integer(), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['pap_asset_id'], ['payroll_germany_pap_assets.id']),
        sa.ForeignKeyConstraint(['source_identity_verified_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['source_hash_verified_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['source_finality_verified_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['licensing_recorded_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['golden_vectors_verified_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['security_certified_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['prepared_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['rejected_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['activated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['rolled_back_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_release_id'], ['payroll_germany_pap_releases.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pap_asset_id', name='uq_pap_release_one_per_asset'),
    )
    op.create_index(
        op.f('ix_payroll_germany_pap_releases_id'),
        'payroll_germany_pap_releases', ['id'], unique=False,
    )
    op.create_index(
        'ix_pap_release_status', 'payroll_germany_pap_releases', ['status'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_pap_release_status', table_name='payroll_germany_pap_releases')
    op.drop_index(op.f('ix_payroll_germany_pap_releases_id'), table_name='payroll_germany_pap_releases')
    op.drop_table('payroll_germany_pap_releases')
