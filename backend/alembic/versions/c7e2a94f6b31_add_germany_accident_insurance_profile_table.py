"""add germany accident insurance profile table

Revision ID: c7e2a94f6b31
Revises: b1d6e94a7c58
Create Date: 2026-09-07 00:00:00.000000

Phase 8AJ (2nd pass) — docs/PHASE_8AJ_GERMANY_EMPLOYER_TAX_PROFILE_ACCIDENT_INSURANCE_UI_REPORT.md.

Additive only: one brand-new table,
payroll_germany_accident_insurance_profiles — the maker-checker
(DRAFT/VERIFIED/APPROVED/PUBLISHED/SUPERSEDED) workspace for one
organization's German statutory accident-insurance (Unfallversicherung)
configuration, mirroring payroll_germany_health_funds's exact lifecycle
shape but organization-scoped (accident insurance is carrier/employer-
specific per spec DE-D06, unlike every other Germany registry). No
existing table/column changed. No statutory rate is seeded by this
migration — every row starts as an operator-entered DRAFT.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2a94f6b31'
down_revision: Union[str, Sequence[str], None] = 'b1d6e94a7c58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_accident_insurance_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('carrier_name', sa.String(length=200), nullable=False),
        sa.Column('agency_account_id', sa.String(length=100), nullable=True),
        sa.Column('risk_class_description', sa.String(length=200), nullable=True),
        sa.Column('employer_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
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
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['authority_source_id'], ['payroll_source_artifacts.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_accident_insurance_profiles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_germany_accident_insurance_profiles_id'),
        'payroll_germany_accident_insurance_profiles', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_germany_accident_insurance_profiles_organization_id'),
        'payroll_germany_accident_insurance_profiles', ['organization_id'], unique=False,
    )
    op.create_index(
        'ix_accident_insurance_profile_org_period', 'payroll_germany_accident_insurance_profiles',
        ['organization_id', 'effective_from'], unique=False,
    )
    op.create_index(
        'uq_accident_insurance_profile_one_open_period', 'payroll_germany_accident_insurance_profiles',
        ['organization_id'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_accident_insurance_profile_one_open_period', table_name='payroll_germany_accident_insurance_profiles')
    op.drop_index('ix_accident_insurance_profile_org_period', table_name='payroll_germany_accident_insurance_profiles')
    op.drop_index(op.f('ix_payroll_germany_accident_insurance_profiles_organization_id'), table_name='payroll_germany_accident_insurance_profiles')
    op.drop_index(op.f('ix_payroll_germany_accident_insurance_profiles_id'), table_name='payroll_germany_accident_insurance_profiles')
    op.drop_table('payroll_germany_accident_insurance_profiles')
