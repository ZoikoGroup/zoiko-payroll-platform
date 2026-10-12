"""add france establishments and editable authority fields

Revision ID: 74aeb450aeee
Revises: 4856e62160ac

France Super Admin "everything read-only" fix, Phase 2 (ZP-FR-ENG-001 §11
panels A/B/E, §18 EmployerFranceProfile / EstablishmentRatePack):

  - payroll_fr_establishments (NEW)   the SIRET registry an employer owns —
    address, commune INSEE, workforce location, establishment payroll id.
    Before this, a SIRET only existed as a free-text field on a rate-pack
    period row, so there was nothing to create/edit/deactivate.
  - payroll_fr_employer_profiles      + address, payroll_contact (panel A),
    idcc_status (FR-035: APPLICABLE / NOT_APPLICABLE / UNDER_REVIEW — IDCC
    is mandatory or explicitly "unknown under review", never silently empty).
  - payroll_fr_establishment_rate_packs + establishment_id (link to the new
    registry), vm_evidence (VM is authority data like AT/MP — FR-013),
    ags_special_status (panel E).
  - payroll_fr_pas_rates             + crm_reference — the DGFiP CRM message
    a PERSONALIZED rate was transcribed from (FR-008/FR-010 provenance).
  - payslip_items                    + fr_calculation_snapshot — the frozen
    France result incl. the RGDU/CSG YTD state the next period reads back.

Additive only: one new table and nullable columns; no existing row or
column is changed, so upgrade is safe on a populated database and
downgrade drops only what this migration added.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74aeb450aeee'
down_revision: Union[str, Sequence[str], None] = '4856e62160ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Idempotency guards (2026-09-30) ──────────────────────────────────────
# Production already holds part of this schema: an earlier, unmerged
# France/Ireland branch ran these same migrations against it, and the
# 2026-09-29 deploy failed with DuplicateTable on payroll_fr_establishments.
# Each operation below is therefore skipped when its object already exists
# (or, for a drop, is already gone). A pre-existing object with the wrong
# SHAPE is not papered over: scripts.check_schema_drift runs right after
# the upgrade and fails the deploy, before the service restarts.
def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table('payroll_fr_establishments'):
        op.create_table(
            'payroll_fr_establishments',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('employer_profile_id', sa.Integer(), sa.ForeignKey('payroll_fr_employer_profiles.id'), nullable=True),
            sa.Column('siret', sa.String(length=14), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=True),
            sa.Column('address', sa.Text(), nullable=True),
            sa.Column('commune_insee', sa.String(length=10), nullable=True),
            sa.Column('workforce_location', sa.String(length=200), nullable=True),
            sa.Column('payroll_identifier', sa.String(length=50), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint('organization_id', 'siret', name='uq_fr_establishment_org_siret'),
        )

    if not _has_column('payroll_fr_employer_profiles', 'address'):
        op.add_column('payroll_fr_employer_profiles', sa.Column('address', sa.Text(), nullable=True))
    if not _has_column('payroll_fr_employer_profiles', 'payroll_contact'):
        op.add_column('payroll_fr_employer_profiles', sa.Column('payroll_contact', sa.String(length=200), nullable=True))
    if not _has_column('payroll_fr_employer_profiles', 'idcc_status'):
        op.add_column('payroll_fr_employer_profiles', sa.Column('idcc_status', sa.String(length=20), nullable=True))

    if not _has_column('payroll_fr_establishment_rate_packs', 'establishment_id'):
        op.add_column(
            'payroll_fr_establishment_rate_packs',
            sa.Column('establishment_id', sa.Integer(), sa.ForeignKey('payroll_fr_establishments.id'), nullable=True),
        )
    if not _has_column('payroll_fr_establishment_rate_packs', 'vm_evidence'):
        op.add_column('payroll_fr_establishment_rate_packs', sa.Column('vm_evidence', sa.Text(), nullable=True))
    if not _has_column('payroll_fr_establishment_rate_packs', 'ags_special_status'):
        op.add_column('payroll_fr_establishment_rate_packs', sa.Column('ags_special_status', sa.String(length=30), nullable=True))

    if not _has_column('payroll_fr_pas_rates', 'crm_reference'):
        op.add_column('payroll_fr_pas_rates', sa.Column('crm_reference', sa.String(length=100), nullable=True))
    if not _has_column('payslip_items', 'fr_calculation_snapshot'):
        op.add_column('payslip_items', sa.Column('fr_calculation_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'fr_calculation_snapshot')
    op.drop_column('payroll_fr_pas_rates', 'crm_reference')
    op.drop_column('payroll_fr_establishment_rate_packs', 'ags_special_status')
    op.drop_column('payroll_fr_establishment_rate_packs', 'vm_evidence')
    op.drop_column('payroll_fr_establishment_rate_packs', 'establishment_id')
    op.drop_column('payroll_fr_employer_profiles', 'idcc_status')
    op.drop_column('payroll_fr_employer_profiles', 'payroll_contact')
    op.drop_column('payroll_fr_employer_profiles', 'address')
    op.drop_table('payroll_fr_establishments')
