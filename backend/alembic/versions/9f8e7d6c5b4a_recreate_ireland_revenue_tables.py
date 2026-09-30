"""recreate Ireland Revenue submission + monthly return tables (WP2)

Revision ID: 9f8e7d6c5b4a
Revises: 2c7d9e0f3a5b
Create Date: 2026-09-28

ZP-IE-ENG-001 WP2: Recreate the two Revenue tables that were dropped in
Phase 1 refactor (f6b2c4d8e1a3), with corrected schema per the spec:

1. payroll_ie_revenue_submissions — one row per employee per payroll run
   (real-time reporting on/before pay date, IE-022). Includes:
   - line_item_id (Revenue) + previous_line_item_id (correction linkage)
   - payload_hash for idempotency (IE-025)
   - all reported statutory figures (PAYE, USC, PRSI employee/employer, LPT)
   - status: PENDING/SENT/ACKNOWLEDGED/REJECTED/UNKNOWN
   - full payload JSON + payload_hash for audit

2. payroll_ie_revenue_monthly_returns — one row per employer per month
   (monthly statement/return/payment, IE-026/IE-027). Includes:
   - statement period, versioned return (multiple versions per period)
   - status: DRAFT/ACCEPTED/DEEMED/RECONCILED
   - calculated_liability vs revenue_liability + reconciliation_state (JSON)
   - payment tracking separate from return filing (IE-026)
"""
from alembic import op
import sqlalchemy as sa

revision: str = '9f8e7d6c5b4a'
down_revision: str = '2c7d9e0f3a5b'
branch_labels = None
depends_on = None


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
    # ── payroll_ie_revenue_submissions (append-only real-time reporting) ──
    if not _has_table('payroll_ie_revenue_submissions'):
        op.create_table(
            'payroll_ie_revenue_submissions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
            sa.Column('run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=False, index=True),
            sa.Column('payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True, index=True),
            # Revenue identifiers
            sa.Column('line_item_id', sa.String(length=50), nullable=True, index=True),
            sa.Column('previous_line_item_id', sa.String(length=50), nullable=True),
            # RPN snapshot used for this submission
            sa.Column('rpn_snapshot_id', sa.Integer(), sa.ForeignKey('payroll_ie_rpn_snapshots.id'), nullable=True),
            # Correction linkage
            sa.Column('correction_kind', sa.String(length=30), nullable=False, server_default='ORIGINAL'),
            # Period
            sa.Column('period_start', sa.Date(), nullable=False),
            sa.Column('period_end', sa.Date(), nullable=False),
            sa.Column('pay_date', sa.Date(), nullable=False),
            # Reported statutory figures (all distinct per IE-003/IE-012/IE-017/IE-020)
            sa.Column('reported_gross', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_paye', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_usc', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_prsi_employee', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_prsi_employer', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_lpt', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_myfuturefund_employee', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reported_myfuturefund_employer', sa.Numeric(precision=14, scale=2), nullable=True),
            # Payload & idempotency (IE-025: submission attempts must be idempotent)
            sa.Column('payload', sa.JSON(), nullable=True),
            sa.Column('payload_hash', sa.String(length=64), nullable=False, index=True),
            # Status machine (IE-022/IE-027)
            sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('rejection_reason', sa.Text(), nullable=True),
            sa.Column('reconciliation_note', sa.Text(), nullable=True),
            # Idempotency key prevents duplicate submissions on retry
            sa.Column('idempotency_key', sa.String(length=64), nullable=False, unique=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_index('payroll_ie_revenue_submissions', 'ix_ie_revsub_org_period'):
        op.create_index('ix_ie_revsub_org_period', 'payroll_ie_revenue_submissions', ['organization_id', 'period_start'])
    if not _has_index('payroll_ie_revenue_submissions', 'ix_ie_revsub_employee_paydate'):
        op.create_index('ix_ie_revsub_employee_paydate', 'payroll_ie_revenue_submissions', ['employee_id', 'pay_date'])

    # ── payroll_ie_revenue_monthly_returns (monthly statement + reconciliation) ──
    if not _has_table('payroll_ie_revenue_monthly_returns'):
        op.create_table(
            'payroll_ie_revenue_monthly_returns',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('statement_period_start', sa.Date(), nullable=False),
            sa.Column('statement_period_end', sa.Date(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('status', sa.String(length=30), nullable=False, server_default='DRAFT'),
            sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('deemed_accepted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('rejection_reason', sa.Text(), nullable=True),
            # Liability reconciliation (IE-026/IE-027)
            sa.Column('calculated_liability', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('revenue_liability', sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column('reconciled_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('reconciliation_notes', sa.Text(), nullable=True),
            sa.Column('reconciliation_state', sa.JSON(), nullable=True),
            sa.Column('payload_hash', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                'organization_id', 'statement_period_start', 'statement_period_end', 'version',
                name='uq_ie_monthly_return_org_period_version',
            ),
        )
    if not _has_index('payroll_ie_revenue_monthly_returns', 'ix_ie_monthly_return_org_period'):
        op.create_index('ix_ie_monthly_return_org_period', 'payroll_ie_revenue_monthly_returns', ['organization_id', 'statement_period_start'])


def downgrade() -> None:
    op.drop_index('ix_ie_monthly_return_org_period', table_name='payroll_ie_revenue_monthly_returns')
    op.drop_table('payroll_ie_revenue_monthly_returns')

    op.drop_index('ix_ie_revsub_employee_paydate', table_name='payroll_ie_revenue_submissions')
    op.drop_index('ix_ie_revsub_org_period', table_name='payroll_ie_revenue_submissions')
    op.drop_table('payroll_ie_revenue_submissions')