"""add sweden jurisdiction support

Revision ID: e8f1a2b3c4d5
Revises: 66072e2d80a9
Create Date: 2026-09-30 00:00:00.000000

ZP-SE-ENG-001 (Sweden Payroll Engineering Implementation and Acceptance
Wireframe v1.0). Strictly ADDITIVE - no existing column/table is altered or
dropped, and every new column is nullable so every pre-existing row keeps
its exact current behavior (regression requirement §39).

1. Three new country-extension tables (models.py Sweden section, precedent:
   Germany*/France*/Ireland* extension tables):
     - payroll_collective_agreements  (§9/§22 governed CBA overlay; no
       national default is ever seeded)
     - payroll_sweden_sick_episodes   (§24 recurrence-aware 14-day employer
       period with stored qualifying-deduction state)
     - payroll_sweden_leave_ledgers   (§7/SE-006 separate entitlement /
       paid-day / saved-day / money ledgers)

2. 36 new nullable se_* columns on payroll_employee_statutory_profiles
   (§2/§20/§21 worker tax + social-insurance profile; same additive-column
   pattern as the de_/ie_ blocks before them). se_cba_id FKs the new
   agreements table (created first below).

3. Two nullable discriminator columns on payroll_tax_slabs
   (tax_table_number, tax_column) for rule_type SE_TAX_TABLE /
   SE_ONE_TIME_PAYMENT (§7/§8/§10) - same convention as ni_category /
   assessment_basis; NULL on every pre-existing row.

4. Five generic nullable AGI-linkage columns on statutory_filings
   (§10/§26): submission_status, receipt_id, correction_reference,
   schema_version, validation_status - NULL on every pre-existing filing.

5. Two nullable Sweden-deadline columns on payroll_statutory_filing_calendar
   (§10/§27): payment_due_date, variation - NULL on every pre-existing row.

6. One nullable JSON snapshot column on payslip_items
   (se_calculation_snapshot, §34 compliance calculation trace) - same
   "one JSON snapshot column per country" pattern as germany_/fr_/ie_.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = '66072e2d80a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Idempotency guards (same pattern as 74aeb450aeee, commit 7bedb5f) ─────
# The 2026-09-29 deploy failed because an unmerged branch had already run
# part of a schema against production. Every operation below is skipped when
# its object already exists (or, for a drop, is already gone). A pre-existing
# object with the wrong SHAPE is not papered over: scripts.check_schema_drift
# runs right after the upgrade and fails the deploy before the restart.
def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column(table, column):
    if _has_column(table, column.name):
        return
    if column.foreign_keys and op.get_bind().dialect.name == "sqlite":
        # SQLite cannot ADD a foreign-keyed column in place (se_cba_id) and
        # does not enforce foreign keys in this project's dev/test setup, so
        # the dev fallback gets the plain column; PostgreSQL keeps the FK.
        op.add_column(table, sa.Column(column.name, column.type, nullable=column.nullable))
    else:
        op.add_column(table, column)


def _drop_column(table, column_name):
    if not _has_column(table, column_name):
        return
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot DROP a column that carries a foreign key in place
        # (se_cba_id); batch mode rebuilds the table. PostgreSQL drops directly.
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column_name)
    else:
        op.drop_column(table, column_name)


def _drop_table(name):
    if _has_table(name):
        op.drop_table(name)


def upgrade() -> None:
    """Upgrade schema."""

    # ── 1. New tables (collective agreements FIRST: se_cba_id FKs it) ──────
    if not _has_table('payroll_collective_agreements'):
        op.create_table(
            'payroll_collective_agreements',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=True, index=True),
            sa.Column('jurisdiction_country', sa.String(10), nullable=False, index=True),
            sa.Column('agreement_code', sa.String(50), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('agreement_type', sa.String(30), nullable=False),
            sa.Column('employer_scope', sa.Text(), nullable=True),
            sa.Column('employee_group', sa.String(100), nullable=True),
            sa.Column('occupation', sa.String(100), nullable=True),
            sa.Column('grade', sa.String(50), nullable=True),
            sa.Column('version', sa.String(20), nullable=False, server_default='1.0'),
            sa.Column('effective_from', sa.Date(), nullable=True),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),
            sa.Column('modules', sa.JSON(), nullable=True),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('previous_version_id', sa.Integer(), sa.ForeignKey('payroll_collective_agreements.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint('agreement_code', 'version', name='uq_collective_agreement_code_version'),
            sa.Index('ix_collective_agreement_lookup', 'jurisdiction_country', 'organization_id', 'status'),
        )

    if not _has_table('payroll_sweden_sick_episodes'):
        op.create_table(
            'payroll_sweden_sick_episodes',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
            sa.Column('episode_start', sa.Date(), nullable=False),
            sa.Column('episode_end', sa.Date(), nullable=True),
            sa.Column('recurrence_group_id', sa.Integer(), sa.ForeignKey('payroll_sweden_sick_episodes.id'), nullable=True),
            sa.Column('work_capacity_pct', sa.Numeric(5, 2), nullable=True),
            sa.Column('expected_weekly_sick_pay', sa.Numeric(14, 2), nullable=True),
            sa.Column('qualifying_deduction_pct', sa.Numeric(5, 2), nullable=True),
            sa.Column('qualifying_deduction_amount', sa.Numeric(14, 2), nullable=True),
            sa.Column('deduction_already_applied', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('employer_period_day_from', sa.Integer(), nullable=True),
            sa.Column('employer_period_day_to', sa.Integer(), nullable=True),
            sa.Column('transfer_to_forsakringskassan', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('medical_certificate_ref', sa.String(100), nullable=True),
            sa.Column('absence_reported', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('employer_sick_pay_amount', sa.Numeric(14, 2), nullable=True),
            sa.Column('cba_supplement_amount', sa.Numeric(14, 2), nullable=True),
            sa.Column('cba_agreement_id', sa.Integer(), sa.ForeignKey('payroll_collective_agreements.id'), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='OPEN'),
            sa.Column('source', sa.String(200), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.Index('ix_se_sick_episode_employee_dates', 'employee_id', 'episode_start'),
            sa.Index('ix_se_sick_episode_org', 'organization_id'),
        )

    if not _has_table('payroll_sweden_leave_ledgers'):
        op.create_table(
            'payroll_sweden_leave_ledgers',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
            sa.Column('entitlement_year', sa.String(10), nullable=False),
            sa.Column('qualifying_year', sa.String(10), nullable=True),
            sa.Column('paid_days', sa.Numeric(6, 2), nullable=False, server_default='0'),
            sa.Column('unpaid_days', sa.Numeric(6, 2), nullable=False, server_default='0'),
            sa.Column('saved_days', sa.Numeric(6, 2), nullable=False, server_default='0'),
            sa.Column('carryover_days', sa.Numeric(6, 2), nullable=False, server_default='0'),
            sa.Column('carryover_expiry', sa.Date(), nullable=True),
            sa.Column('qualifying_earnings', sa.Numeric(14, 2), nullable=True),
            sa.Column('vacation_pay_method', sa.String(20), nullable=False, server_default='PERCENTAGE_12'),
            sa.Column('credited_absence', sa.JSON(), nullable=True),
            sa.Column('final_vacation_allowance', sa.Numeric(14, 2), nullable=True),
            sa.Column('cba_agreement_id', sa.Integer(), sa.ForeignKey('payroll_collective_agreements.id'), nullable=True),
            sa.Column('effective_from', sa.Date(), nullable=True),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('version', sa.String(20), nullable=False, server_default='1.0'),
            sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint('employee_id', 'entitlement_year', name='uq_se_leave_ledger_emp_year'),
            sa.Index('ix_se_leave_ledger_org_year', 'organization_id', 'entitlement_year'),
        )

    # ── 2. Worker statutory profile: se_* applicability facts (§2/§20/§21) ─
    profile_cols = [
        sa.Column('se_tax_status', sa.String(30), nullable=True),
        sa.Column('se_income_role', sa.String(30), nullable=True),
        sa.Column('se_tax_table', sa.String(10), nullable=True),
        sa.Column('se_tax_column', sa.String(10), nullable=True),
        sa.Column('se_skatteverket_decision_id', sa.String(60), nullable=True),
        sa.Column('se_decision_effective_from', sa.Date(), nullable=True),
        sa.Column('se_decision_effective_to', sa.Date(), nullable=True),
        sa.Column('se_decision_override', sa.Boolean(), nullable=True),
        sa.Column('se_decision_monthly_withholding', sa.Numeric(14, 2), nullable=True),
        sa.Column('se_decision_rate_pct', sa.Numeric(6, 4), nullable=True),
        sa.Column('se_sink_status', sa.String(30), nullable=True),
        sa.Column('se_sink_decision', sa.String(60), nullable=True),
        sa.Column('se_residence_municipality', sa.String(100), nullable=True),
        sa.Column('se_tax_table_area', sa.String(100), nullable=True),
        sa.Column('se_social_insurance_status', sa.String(30), nullable=True),
        sa.Column('se_foreign_coverage_status', sa.String(30), nullable=True),
        sa.Column('se_a1_status', sa.String(30), nullable=True),
        sa.Column('se_agreement_country', sa.String(10), nullable=True),
        sa.Column('se_coverage_start', sa.Date(), nullable=True),
        sa.Column('se_coverage_end', sa.Date(), nullable=True),
        sa.Column('se_evidence_document', sa.String(200), nullable=True),
        sa.Column('se_evidence_validation', sa.String(30), nullable=True),
        sa.Column('se_cba_status', sa.String(30), nullable=True),
        sa.Column('se_cba_id', sa.Integer(), sa.ForeignKey('payroll_collective_agreements.id'), nullable=True),
        sa.Column('se_cba_version', sa.String(20), nullable=True),
        sa.Column('se_occupation', sa.String(100), nullable=True),
        sa.Column('se_grade', sa.String(50), nullable=True),
        sa.Column('se_pension_plan', sa.String(100), nullable=True),
        sa.Column('se_pension_provider', sa.String(100), nullable=True),
        sa.Column('se_employee_pension_share', sa.Numeric(7, 4), nullable=True),
        sa.Column('se_employer_pension_share', sa.Numeric(7, 4), nullable=True),
        sa.Column('se_payroll_period', sa.String(20), nullable=True),
        sa.Column('se_agi_reporting_period', sa.String(20), nullable=True),
        sa.Column('se_monthly_gross', sa.Numeric(14, 2), nullable=True),
        sa.Column('se_taxable_benefits', sa.Numeric(14, 2), nullable=True),
        sa.Column('se_annual_income', sa.Numeric(14, 2), nullable=True),
    ]
    for col in profile_cols:
        _add_column('payroll_employee_statutory_profiles', col)

    # ── 3. Tax slabs: tax table + column discriminators (§7/§8/§10) ────────
    _add_column('payroll_tax_slabs', sa.Column('tax_table_number', sa.String(10), nullable=True))
    _add_column('payroll_tax_slabs', sa.Column('tax_column', sa.String(10), nullable=True))

    # ── 4. Statutory filings: generic AGI linkage columns (§10/§26) ────────
    _add_column('statutory_filings', sa.Column('submission_status', sa.String(30), nullable=True))
    _add_column('statutory_filings', sa.Column('receipt_id', sa.String(100), nullable=True))
    _add_column('statutory_filings', sa.Column('correction_reference', sa.String(100), nullable=True))
    _add_column('statutory_filings', sa.Column('schema_version', sa.String(30), nullable=True))
    _add_column('statutory_filings', sa.Column('validation_status', sa.String(30), nullable=True))

    # ── 5. Filing calendar: separate payment due date + variation (§27) ────
    _add_column('payroll_statutory_filing_calendar', sa.Column('payment_due_date', sa.Date(), nullable=True))
    _add_column('payroll_statutory_filing_calendar', sa.Column('variation', sa.String(50), nullable=True))

    # ── 6. Payslip: frozen Sweden calculation trace (§34) ──────────────────
    _add_column('payslip_items', sa.Column('se_calculation_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema - strictly mirrors upgrade(); additive changes only
    mean downgrade is a pure drop of the objects this revision created."""
    _drop_column('payslip_items', 'se_calculation_snapshot')
    _drop_column('payroll_statutory_filing_calendar', 'variation')
    _drop_column('payroll_statutory_filing_calendar', 'payment_due_date')
    _drop_column('statutory_filings', 'validation_status')
    _drop_column('statutory_filings', 'schema_version')
    _drop_column('statutory_filings', 'correction_reference')
    _drop_column('statutory_filings', 'receipt_id')
    _drop_column('statutory_filings', 'submission_status')
    _drop_column('payroll_tax_slabs', 'tax_column')
    _drop_column('payroll_tax_slabs', 'tax_table_number')

    for col_name in (
        'se_tax_status', 'se_income_role', 'se_tax_table', 'se_tax_column',
        'se_skatteverket_decision_id', 'se_decision_effective_from',
        'se_decision_effective_to', 'se_decision_override',
        'se_decision_monthly_withholding', 'se_decision_rate_pct',
        'se_sink_status',
        'se_sink_decision', 'se_residence_municipality', 'se_tax_table_area',
        'se_social_insurance_status', 'se_foreign_coverage_status',
        'se_a1_status', 'se_agreement_country', 'se_coverage_start',
        'se_coverage_end', 'se_evidence_document', 'se_evidence_validation',
        'se_cba_status', 'se_cba_id', 'se_cba_version', 'se_occupation',
        'se_grade', 'se_pension_plan', 'se_pension_provider',
        'se_employee_pension_share', 'se_employer_pension_share',
        'se_payroll_period', 'se_agi_reporting_period', 'se_monthly_gross',
        'se_taxable_benefits', 'se_annual_income',
    ):
        _drop_column('payroll_employee_statutory_profiles', col_name)

    _drop_table('payroll_sweden_leave_ledgers')
    _drop_table('payroll_sweden_sick_episodes')
    _drop_table('payroll_collective_agreements')
