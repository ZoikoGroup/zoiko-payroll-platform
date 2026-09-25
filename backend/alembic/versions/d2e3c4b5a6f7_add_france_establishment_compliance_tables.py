"""add france establishment compliance tables

Revision ID: d2e3c4b5a6f7
Revises: 8596179ade04

France (ZP-FR-ENG-001, 2026-09-24) payroll-compliant schema landed in
models.py but was never migrated — live databases 503 on every
/api/super-admin/compliance/france/* endpoint with
``relation "payroll_fr_*" does not exist``. This migration back-fills
exactly the five tables the models declared (see models.py's France
block for the FR-xxx spec references):

  - payroll_fr_employer_profiles         org-level SIREN/IDCC/Urssaf/DSN/PAS
  - payroll_fr_establishment_rate_packs  SIRET-scoped AT/MP + versement mobilité
  - payroll_fr_pas_rates                 authority-supplied DGFiP PAS rate
  - payroll_fr_dsn_submissions           P26V01 DSN lifecycle
  - payroll_fr_dsn_outbox_items          durable idempotent outbox

Additive only: five brand-new tables, no changes to any existing table or
row. All FKs reference pre-existing tables (organizations, users,
payroll_employees) or tables created earlier in this migration. Column-level
indexes come from the Column(index=True) declarations exactly as the models
declare them; the two composite indexes are the only explicit op.create_index
calls.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3c4b5a6f7'
down_revision: Union[str, Sequence[str], None] = '8596179ade04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Idempotent (see merge 5ae06cfda828): an environment upgraded along
    # main's branch can already hold all five tables. A PARTIAL set is a
    # genuinely inconsistent schema — stop with the exact list, never guess.
    france_tables = {
        "payroll_fr_employer_profiles", "payroll_fr_establishment_rate_packs", "payroll_fr_pas_rates",
        "payroll_fr_dsn_submissions", "payroll_fr_dsn_outbox_items",
    }
    present = france_tables & set(sa.inspect(op.get_bind()).get_table_names())
    if present == france_tables:
        return
    if present:
        raise RuntimeError(f"France compliance tables partially present ({sorted(present)}); reconcile manually.")

    # ── payroll_fr_employer_profiles (1:1 org-level France employer profile) ──
    op.create_table(
        'payroll_fr_employer_profiles',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, unique=True, index=True),
        sa.Column('siren', sa.String(length=9), nullable=False),
        sa.Column('legal_name', sa.String(length=200), nullable=True),
        sa.Column('legal_form', sa.String(length=50), nullable=True),
        sa.Column('idcc', sa.String(length=20), nullable=True),
        sa.Column('urssaf_account', sa.String(length=50), nullable=True),
        sa.Column('dsn_declarant', sa.String(length=50), nullable=True),
        sa.Column('filing_due_date_class', sa.String(length=20), nullable=False, server_default='M15'),
        sa.Column('payment_mandate_ref', sa.String(length=100), nullable=True),
        sa.Column('pas_collector_identity', sa.String(length=100), nullable=True),
        sa.Column('pas_crm_status', sa.String(length=20), nullable=False, server_default='NOT_CONNECTED'),
        sa.Column('effectif_state', sa.JSON(), nullable=True),
        sa.Column('readiness_status', sa.String(length=30), nullable=False, server_default='NOT_READY'),
        sa.Column('readiness_evidence', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # ── payroll_fr_establishment_rate_packs (SIRET-scoped rates, effective-dated) ──
    op.create_table(
        'payroll_fr_establishment_rate_packs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employer_profile_id', sa.Integer(), sa.ForeignKey('payroll_fr_employer_profiles.id'), nullable=True),
        sa.Column('siret', sa.String(length=14), nullable=False),
        sa.Column('commune_insee', sa.String(length=10), nullable=True),
        sa.Column('workplace_label', sa.String(length=200), nullable=True),
        sa.Column('at_mp_rate_pct', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('at_mp_risk_code', sa.String(length=30), nullable=True),
        sa.Column('at_mp_evidence', sa.Text(), nullable=True),
        sa.Column('at_mp_source', sa.String(length=120), nullable=True),
        sa.Column('vm_rate_pct', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('vm_threshold_applies', sa.Boolean(), nullable=True),
        sa.Column('vm_threshold_history', sa.JSON(), nullable=True),
        sa.Column('vm_source', sa.String(length=120), nullable=True),
        sa.Column('fnal_class', sa.String(length=20), nullable=True),
        sa.Column('cfp_class', sa.String(length=20), nullable=True),
        sa.Column('effectif', sa.Integer(), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('organization_id', 'siret', 'effective_from', name='uq_fr_estab_pack_per_period'),
    )

    # ── payroll_fr_pas_rates (DGFiP PAS authority rates, read-only) ──
    op.create_table(
        'payroll_fr_pas_rates',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('rate_type', sa.String(length=20), nullable=False),
        sa.Column('rate_pct', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('dgfip_rate_id', sa.String(length=100), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('received_date', sa.Date(), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('correction_of_id', sa.Integer(), sa.ForeignKey('payroll_fr_pas_rates.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index(
        'ix_fr_pas_rate_org_emp_window', 'payroll_fr_pas_rates',
        ['organization_id', 'employee_id', 'effective_from'], unique=False,
    )

    # ── payroll_fr_dsn_submissions (P26V01 lifecycle) ──
    op.create_table(
        'payroll_fr_dsn_submissions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('dsn_version', sa.String(length=20), nullable=False, server_default='P26V01'),
        sa.Column('release_ref', sa.String(length=50), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='DRAFT'),
        sa.Column('validation_errors', sa.JSON(), nullable=True),
        sa.Column('blocked_reason', sa.Text(), nullable=True),
        sa.Column('technical_ack', sa.String(length=30), nullable=True),
        sa.Column('business_crm', sa.JSON(), nullable=True),
        sa.Column('payment_state', sa.String(length=20), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correction_of_id', sa.Integer(), sa.ForeignKey('payroll_fr_dsn_submissions.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index(
        'ix_fr_dsn_org_period', 'payroll_fr_dsn_submissions', ['organization_id', 'period_start'], unique=False,
    )

    # ── payroll_fr_dsn_outbox_items (durable idempotent outbox) ──
    op.create_table(
        'payroll_fr_dsn_outbox_items',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('submission_id', sa.Integer(), sa.ForeignKey('payroll_fr_dsn_submissions.id'), nullable=False, index=True),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False, unique=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payroll_fr_dsn_outbox_items')
    op.drop_table('payroll_fr_dsn_submissions')
    op.drop_table('payroll_fr_pas_rates')
    op.drop_table('payroll_fr_establishment_rate_packs')
    op.drop_table('payroll_fr_employer_profiles')