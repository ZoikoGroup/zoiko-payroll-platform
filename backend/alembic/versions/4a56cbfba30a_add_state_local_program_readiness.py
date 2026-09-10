"""add payroll_state_local_program_readiness table

Revision ID: 4a56cbfba30a
Revises: d852cecc3ae2
Create Date: 2026-09-10 00:05:00.000000

ZP-TAX-IN-2026-27-001 §16's India state/local readiness registry — one
row per (state/UT, optional local authority, statutory program), even
when the status is NOT_APPLICABLE or SOURCE_REQUIRED. Informational/
admin-facing only in this pass; no calculation or onboarding path reads
it yet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a56cbfba30a'
down_revision: Union[str, Sequence[str], None] = 'd852cecc3ae2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_state_local_program_readiness',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction_country', sa.String(length=10), nullable=False),
        sa.Column('jurisdiction_state', sa.String(length=100), nullable=False),
        sa.Column('jurisdiction_locality', sa.String(length=100), nullable=True),
        sa.Column('program', sa.String(length=30), nullable=False),
        sa.Column('legal_status', sa.String(length=20), nullable=False, server_default='SOURCE_REQUIRED'),
        sa.Column('local_authority_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('registration_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['source_document_id'], ['payroll_source_artifacts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'jurisdiction_country', 'jurisdiction_state', 'jurisdiction_locality', 'program',
            name='uq_state_local_program_readiness_scope',
        ),
    )
    op.create_index(
        op.f('ix_payroll_state_local_program_readiness_id'),
        'payroll_state_local_program_readiness', ['id'], unique=False,
    )

    # Seed rows for every India state/local program this same gap-closure
    # pass actually implemented (§13/§14/§15) — pure descriptive status
    # metadata, never a statutory rate, so unlike ContributionRate/TaxSlab
    # seed data this carries no payroll-calculation risk to seed directly
    # in a migration. registration_required=True on every row below
    # reflects PT/LWF's well-established real-world employer-registration
    # requirement generically, not a per-state fact this specific pack
    # separately confirms.
    readiness_table = sa.table(
        'payroll_state_local_program_readiness',
        sa.column('jurisdiction_country', sa.String),
        sa.column('jurisdiction_state', sa.String),
        sa.column('jurisdiction_locality', sa.String),
        sa.column('program', sa.String),
        sa.column('legal_status', sa.String),
        sa.column('local_authority_required', sa.Boolean),
        sa.column('registration_required', sa.Boolean),
        sa.column('notes', sa.String),
    )
    op.bulk_insert(readiness_table, [
        dict(jurisdiction_country='IN', jurisdiction_state='Karnataka', jurisdiction_locality=None,
             program='STATE_PT', legal_status='APPLICABLE', local_authority_required=False, registration_required=True,
             notes='§13.1 — seeded and VERIFIED via hardcoded_defaults.py'),
        dict(jurisdiction_country='IN', jurisdiction_state='Maharashtra', jurisdiction_locality=None,
             program='STATE_PT', legal_status='APPLICABLE', local_authority_required=False, registration_required=True,
             notes='§13.2 — gender-tagged + February adjustment, seeded and VERIFIED'),
        dict(jurisdiction_country='IN', jurisdiction_state='Telangana', jurisdiction_locality=None,
             program='STATE_PT', legal_status='APPLICABLE', local_authority_required=False, registration_required=True,
             notes='§13.3 — seeded and VERIFIED (pre-existing, before this gap-closure pass)'),
        dict(jurisdiction_country='IN', jurisdiction_state='Odisha', jurisdiction_locality=None,
             program='STATE_PT', legal_status='APPLICABLE', local_authority_required=False, registration_required=True,
             notes='§14.2 — full bracket ladder, seeded and VERIFIED; source-age control applies before each annual publish'),
        dict(jurisdiction_country='IN', jurisdiction_state='Gujarat', jurisdiction_locality=None,
             program='STATE_PT', legal_status='SOURCE_REQUIRED', local_authority_required=False, registration_required=True,
             notes='§13.4 — activation blocked: document requires the current rate-schedule artifact attached before publishing this rate'),
        dict(jurisdiction_country='IN', jurisdiction_state='Tamil Nadu', jurisdiction_locality='Chennai',
             program='LOCAL_PT', legal_status='APPLICABLE', local_authority_required=True, registration_required=True,
             notes='§14.1 — Greater Chennai Corporation half-yearly schedule seeded; collection month NOT sourced, so PT resolves ₹0 until pt_half_year_deduct_month_1/_2 is configured'),
        dict(jurisdiction_country='IN', jurisdiction_state='Karnataka', jurisdiction_locality=None,
             program='LWF', legal_status='APPLICABLE', local_authority_required=False, registration_required=True,
             notes='§15.1 — seeded and VERIFIED, deduction month January'),
        dict(jurisdiction_country='IN', jurisdiction_state='Tamil Nadu', jurisdiction_locality=None,
             program='LWF', legal_status='APPLICABLE', local_authority_required=False, registration_required=True,
             notes='§15.2 — employee/employer amounts seeded; deduction month NOT sourced, so LWF resolves ₹0 until lwf_deduct_month is configured'),
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_payroll_state_local_program_readiness_id'), table_name='payroll_state_local_program_readiness')
    op.drop_table('payroll_state_local_program_readiness')
