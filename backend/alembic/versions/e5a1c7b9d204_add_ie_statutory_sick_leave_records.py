"""add payroll_ie_statutory_sick_leave_records

Revision ID: e5a1c7b9d204
Revises: c7d4e9f1a2b3

ZP-IE-ENG-001 §11 / IE-037. One new table, additive only.

Ireland's statutory sick pay is a 5-day CALENDAR-YEAR entitlement, paid at 70%
of usual daily earnings and capped at EUR 110 per day, available only after 13
weeks' service and subject to medical certification. Until now the four rate
rows (ie_sick_leave_days / _pct / _daily_cap / _service_weeks) existed and
engine/countries/ireland.py echoed them into the labour trace, but nothing
assessed an actual claim, so there was nowhere to record:

  - the absence dates,
  - how much of the calendar-year entitlement was already used,
  - the usual daily earnings the 70% was applied to,
  - the rate before and after the cap, and whether the cap bound,
  - the service qualification actually evidenced, and
  - the reason the claim was allowed, partly allowed or disallowed.

IE-037 requires all of that to be preserved and retained. The existing UK
Statutory Family Pay columns on payroll_leave_requests (statutory_pay_type /
statutory_awe_snapshot / statutory_pay_total_amount / statutory_pay_note) are
deliberately NOT reused: those model an HMRC payment CODE plus a frozen AWE
for a weekly top-up product, whereas Irish statutory sick pay is a capped
calendar-year entitlement whose evidence is per-claim. leave_request_id is a
nullable FK so the two stay linked where the leave workflow produced the claim
without either side depending on the other.

Scope discipline, matching the existing IE tables:
  - Additive only. No existing table is altered, so this is a no-op for every
    non-Irish row and every existing leave request.
  - No backfill and no inference. Sick-leave claims that happened before this
    table existed are not reconstructed; their days are simply not counted
    against a calendar-year entitlement, which is visible as a claim
    succeeding one that should have been limited, not hidden.
  - The assessment is NOT wired into net pay by this migration. The payroll
    mechanism stays gated behind G5 via
    _IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES, so this table records statutory
    EVIDENCE without changing what any Irish employee is paid.
  - down_revision is c7d4e9f1a2b3, the head added for the Ireland calculation
    snapshot, so this is the only revision that can be at the tip.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a1c7b9d204'
down_revision: str = 'c7d4e9f1a2b3'
branch_labels: str = None
depends_on: str = None


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
    if not _has_table('payroll_ie_statutory_sick_leave_records'):
        op.create_table(
            'payroll_ie_statutory_sick_leave_records',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('organization_id', sa.Integer(), nullable=False),
            sa.Column('employee_id', sa.Integer(), nullable=False),
            sa.Column('leave_request_id', sa.Integer(), nullable=True),
            sa.Column('calendar_year', sa.Integer(), nullable=False),
            sa.Column('absence_start_date', sa.Date(), nullable=False),
            sa.Column('absence_end_date', sa.Date(), nullable=True),
            sa.Column('days_claimed', sa.Numeric(5, 2), nullable=False, server_default='0'),
            sa.Column('days_credited', sa.Numeric(5, 2), nullable=False, server_default='0'),
            sa.Column('days_disallowed', sa.Numeric(5, 2), nullable=False, server_default='0'),
            sa.Column('days_taken_before', sa.Numeric(5, 2), nullable=False, server_default='0'),
            sa.Column('entitlement_remaining_after', sa.Numeric(5, 2), nullable=True),
            sa.Column('entitlement_days', sa.Numeric(5, 2), nullable=True),
            sa.Column('pct_applied', sa.Numeric(6, 4), nullable=True),
            sa.Column('daily_cap', sa.Numeric(12, 2), nullable=True),
            sa.Column('usual_daily_earnings', sa.Numeric(12, 2), nullable=True),
            sa.Column('daily_rate_before_cap', sa.Numeric(12, 2), nullable=True),
            sa.Column('daily_rate', sa.Numeric(12, 2), nullable=True),
            sa.Column('cap_applied', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('service_start_date', sa.Date(), nullable=True),
            sa.Column('service_weeks_actual', sa.Numeric(8, 2), nullable=True),
            sa.Column('service_weeks_required', sa.Numeric(8, 2), nullable=True),
            sa.Column('service_qualified', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('certified', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('eligible', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='ASSESSED'),
            sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('reversal_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
            sa.ForeignKeyConstraint(['employee_id'], ['payroll_employees.id']),
            sa.ForeignKeyConstraint(['leave_request_id'], ['payroll_leave_requests.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', op.f('ix_payroll_ie_statutory_sick_leave_records_id')):
        op.create_index(
            op.f('ix_payroll_ie_statutory_sick_leave_records_id'),
            'payroll_ie_statutory_sick_leave_records', ['id'], unique=False,
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', op.f('ix_payroll_ie_statutory_sick_leave_records_organization_id')):
        op.create_index(
            op.f('ix_payroll_ie_statutory_sick_leave_records_organization_id'),
            'payroll_ie_statutory_sick_leave_records', ['organization_id'], unique=False,
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', op.f('ix_payroll_ie_statutory_sick_leave_records_employee_id')):
        op.create_index(
            op.f('ix_payroll_ie_statutory_sick_leave_records_employee_id'),
            'payroll_ie_statutory_sick_leave_records', ['employee_id'], unique=False,
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', op.f('ix_payroll_ie_statutory_sick_leave_records_leave_request_id')):
        op.create_index(
            op.f('ix_payroll_ie_statutory_sick_leave_records_leave_request_id'),
            'payroll_ie_statutory_sick_leave_records', ['leave_request_id'], unique=False,
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', op.f('ix_payroll_ie_statutory_sick_leave_records_calendar_year')):
        op.create_index(
            op.f('ix_payroll_ie_statutory_sick_leave_records_calendar_year'),
            'payroll_ie_statutory_sick_leave_records', ['calendar_year'], unique=False,
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', 'ix_ie_sick_leave_emp_year'):
        op.create_index(
            'ix_ie_sick_leave_emp_year',
            'payroll_ie_statutory_sick_leave_records', ['employee_id', 'calendar_year'], unique=False,
        )
    if not _has_index('payroll_ie_statutory_sick_leave_records', 'ix_ie_sick_leave_org_period'):
        op.create_index(
            'ix_ie_sick_leave_org_period',
            'payroll_ie_statutory_sick_leave_records', ['organization_id', 'absence_start_date'], unique=False,
        )


def downgrade() -> None:
    op.drop_index('ix_ie_sick_leave_org_period', table_name='payroll_ie_statutory_sick_leave_records')
    op.drop_index('ix_ie_sick_leave_emp_year', table_name='payroll_ie_statutory_sick_leave_records')
    op.drop_index(
        op.f('ix_payroll_ie_statutory_sick_leave_records_calendar_year'),
        table_name='payroll_ie_statutory_sick_leave_records',
    )
    op.drop_index(
        op.f('ix_payroll_ie_statutory_sick_leave_records_leave_request_id'),
        table_name='payroll_ie_statutory_sick_leave_records',
    )
    op.drop_index(
        op.f('ix_payroll_ie_statutory_sick_leave_records_employee_id'),
        table_name='payroll_ie_statutory_sick_leave_records',
    )
    op.drop_index(
        op.f('ix_payroll_ie_statutory_sick_leave_records_organization_id'),
        table_name='payroll_ie_statutory_sick_leave_records',
    )
    op.drop_index(
        op.f('ix_payroll_ie_statutory_sick_leave_records_id'),
        table_name='payroll_ie_statutory_sick_leave_records',
    )
    op.drop_table('payroll_ie_statutory_sick_leave_records')
