"""drop the Ireland Revenue tables recreated by 9f8e7d6c5b4a

Revision ID: c4d5e6f7a8b9
Revises: 7c3e1a9d5f20
Create Date: 2026-09-28

Undoes 9f8e7d6c5b4a.

9f8e7d6c5b4a recreated payroll_ie_revenue_submissions and
payroll_ie_revenue_monthly_returns to back ZP-IE-ENG-001 WP2. That work was
built on a premise that turned out to be wrong twice over:

1. It assumed the two tables were wanted. The 2026-09-28 Ireland schema
   refactor had already removed both as dead weight, and
   tests/test_ireland_statutory_catalog.py::
   test_ie_has_no_dedicated_ytd_accumulator_table pins that they must never
   return. The tables were recreated in the database while the ORM models that
   everything else referenced did not exist, so every reader of them
   (service.submit_ie_payroll, the Super Admin list endpoints, the Celery
   revenue tasks) raised ImportError/AttributeError.

2. It assumed the filing protocol was known. Those functions wrote
   status="ACKNOWLEDGED" with no ROS transport behind them, so a run would
   have recorded Revenue as having answered when no call had been made. At
   audit time a fabricated acknowledgement is indistinguishable from a real one.

Ireland therefore keeps exactly its three dedicated tables
(payroll_ie_rpn_snapshots, payroll_ie_myfuturefund_statuses,
payroll_ie_statutory_sick_leave_records). Real-time filing and monthly
returns stay a manual, out-of-band step until the official ROS contract and
credentials exist. Reinstating these tables is a separate piece of work that
must bring its own ORM models, correction chain and payment record, not a
revert of this migration.

Both tables were created empty by 9f8e7d6c5b4a and nothing ever wrote to them
(the code paths that would have raised on import first), so this drops no data.
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: str = '7c3e1a9d5f20'
branch_labels = None
depends_on = None

_DROPPED_TABLES = (
    'payroll_ie_revenue_submissions',
    'payroll_ie_revenue_monthly_returns',
)


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
    if _has_table('payroll_ie_revenue_monthly_returns'):
        op.drop_table('payroll_ie_revenue_monthly_returns')
    if _has_table('payroll_ie_revenue_submissions'):
        op.drop_table('payroll_ie_revenue_submissions')


def downgrade() -> None:
    import sqlalchemy as sa

    op.create_table(
        'payroll_ie_revenue_submissions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=False, index=True),
        sa.Column('payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True, index=True),
        sa.Column('line_item_id', sa.String(length=50), nullable=True, index=True),
        sa.Column('previous_line_item_id', sa.String(length=50), nullable=True),
        sa.Column('rpn_snapshot_id', sa.Integer(), sa.ForeignKey('payroll_ie_rpn_snapshots.id'), nullable=True),
        sa.Column('correction_kind', sa.String(length=30), nullable=False, server_default='ORIGINAL'),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('pay_date', sa.Date(), nullable=False),
        sa.Column('reported_gross', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_paye', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_usc', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_prsi_employee', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_prsi_employer', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_lpt', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_myfuturefund_employee', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_myfuturefund_employer', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False, index=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reconciliation_note', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_ie_revsub_org_period', 'payroll_ie_revenue_submissions', ['organization_id', 'period_start'])
    op.create_index('ix_ie_revsub_employee_paydate', 'payroll_ie_revenue_submissions', ['employee_id', 'pay_date'])

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
    op.create_index('ix_ie_monthly_return_org_period', 'payroll_ie_revenue_monthly_returns', ['organization_id', 'statement_period_start'])
