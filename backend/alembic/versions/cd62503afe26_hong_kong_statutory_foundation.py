"""hong kong statutory foundation

Revision ID: cd62503afe26
Revises: e8f1a2b3c4d5
Create Date: 2026-09-30

Hong Kong statutory build (ZP-HK-ENG-001 v1.0). Additive only — no existing
row or column is touched:

  * payroll_employee_statutory_profiles.hkg_* — Hong Kong worker FACTS on the
    shared, effective-dated statutory profile (never a calculated MPF / tax /
    net-pay figure). NULL for every non-HK row.
  * payslip_items.hkg_calculation_trace — the HK payroll snapshot trace (same
    country-scoped JSON-column precedent as sgp_/au_calculation_trace).
  * hkg_work_hours, hkg_ird_reporting_cases, hkg_tax_clearance_holds,
    hkg_tax_clearance_hold_lines, hkg_average_wage_snapshots,
    hkg_termination_results, hkg_empf_submissions, hkg_payslip_corrections
    (D-14), hkg_access_events and hkg_legal_holds (D-19) — the only HK objects no
    shared table can represent (docs/HONG_KONG_CURRENT_STATE_ARCHITECTURE_MAP.md §7).

Parent: e8f1a2b3c4d5 (Sweden) — re-parented from 445abd6a9083 when nikhil integrated main
(France / Ireland / Sweden chain via 66072e2d80a9); still the single head. Idempotent (inspector-guarded: skips a
column/table that already exists, e.g. a dev DB synced via create_all), same
shape as c3d9e1f4a7b2 / 445abd6a9083. No data is seeded here: the Hong Kong
rule packs are seeded Draft by scripts/seed_hong_kong_canonical_pack.py only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd62503afe26'
down_revision: Union[str, Sequence[str], None] = 'e8f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROFILE_TABLE = 'payroll_employee_statutory_profiles'
_PROFILE_COLUMNS = (
    ('hkg_employment_relationship', sa.String(30)),
    ('hkg_identity_document_type', sa.String(10)),
    ('hkg_identity_token', sa.String(80)),     # 'v2:' + HMAC-SHA256 hex (D-19)
    ('hkg_residency_status', sa.String(20)),
    ('hkg_visa_type', sa.String(40)),
    ('hkg_entered_for_employment', sa.Boolean()),
    ('hkg_permission_to_stay_until', sa.Date()),
    ('hkg_overseas_scheme_member', sa.Boolean()),
    ('hkg_mpf_exemption_code', sa.String(30)),
    ('hkg_mpf_exemption_reason', sa.Text()),
    ('hkg_mpf_exemption_evidence_ref', sa.String(200)),
    ('hkg_mpf_scheme_ref', sa.String(60)),
    ('hkg_employment_continuity_start', sa.Date()),
    ('hkg_pay_basis', sa.String(20)),
    ('hkg_contractual_weekly_hours', sa.Numeric(6, 2)),
    ('hkg_likely_chargeable', sa.Boolean()),
    ('hkg_arrival_date', sa.Date()),
    ('hkg_expected_departure_date', sa.Date()),
    ('hkg_frequent_travel_exempt', sa.Boolean()),
    ('hkg_termination_date', sa.Date()),
    ('hkg_termination_reason', sa.String(40)),
    ('hkg_pre_transition_monthly_wage', sa.Numeric(12, 2)),
    ('hkg_pre_transition_wage_basis', sa.String(30)),
    ('hkg_pre_transition_evidence_ref', sa.String(200)),
)

_TABLES = (
    'hkg_retention_policies',
    'hkg_empf_configurations',
    'hkg_ird_software_approvals',
    'hkg_legal_holds',
    'hkg_access_events',
    'hkg_payslip_corrections',
    'hkg_empf_submissions',
    'hkg_termination_results',
    'hkg_average_wage_snapshots',
    'hkg_tax_clearance_hold_lines',
    'hkg_tax_clearance_holds',
    'hkg_work_hours',
    'hkg_ird_reporting_cases',
)

# Hong Kong's IRD returns and eMPF remittance are produced through the SHARED
# reporting architecture (payroll_generated_reports + a seeded ReportTemplate),
# exactly like every other jurisdiction. The HK-specific tables stay the FILING
# TRACKER — the same split the UK uses between GeneratedReport and
# RtiSubmission — and these two nullable FKs are the link back to the report that
# was generated for them. Folding them into cd62503afe26 rather than adding a
# second revision is safe: this migration is uncommitted and has never been
# applied to any database, and the head stays cd62503afe26 either way.
_REPORT_LINK_COLUMNS = (
    ('hkg_ird_reporting_cases', 'generated_report_id', 'payroll_generated_reports.id'),
    ('hkg_empf_submissions', 'generated_report_id', 'payroll_generated_reports.id'),
)


def _existing_columns(table: str) -> set:
    """Column names of ``table``, or an EMPTY set when the table does not exist.

    Every caller in this revision is written to be idempotent - a dev database
    synced with ``Base.metadata.create_all`` already has some or all of these
    tables, and a re-run must be a no-op. ``Inspector.get_columns`` raises
    NoSuchTableError for a missing table rather than returning [], so the
    emptiness has to be normalised here; without this a database that predates
    the parent chain's table would abort the migration with a reflection error
    instead of simply having the table created for it.
    """
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


# The two link columns are declared INSIDE the create_table calls below rather
# than added with ALTER TABLE ... ADD COLUMN, and that placement is load-bearing
# rather than stylistic. Both alternatives were built and run against SQLite
# first, and both are broken there:
#   * op.add_column with an inline ForeignKey raises NotImplementedError ("No
#     support for ALTER of constraints in SQLite dialect");
#   * batch_alter_table().add_column() with the same inline FK raises ValueError
#     ("Constraint must have a name"), and a NAMED batch.create_foreign_key
#     instead succeeds while silently producing a column with NO foreign key at
#     all - the worst of the three, because it loses referential integrity
#     without failing.
# Mirroring the model's inline declaration also removes the downgrade problem:
# this revision's downgrade drops these two tables anyway, so the columns need no
# ALTER to remove - and SQLite refuses DROP COLUMN for a column a foreign key
# still references regardless. A dev database synced with create_all already has
# both columns, and the create_table guards skip the tables entirely, so that
# path stays a no-op.


def upgrade() -> None:
    """Upgrade schema."""
    existing_profile = _existing_columns(_PROFILE_TABLE)
    for name, type_ in _PROFILE_COLUMNS:
        if name not in existing_profile:
            op.add_column(_PROFILE_TABLE, sa.Column(name, type_, nullable=True))
    if 'hkg_calculation_trace' not in _existing_columns('payslip_items'):
        op.add_column('payslip_items', sa.Column('hkg_calculation_trace', sa.JSON(), nullable=True))

    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'hkg_ird_reporting_cases' not in existing:
        op.create_table(
            'hkg_ird_reporting_cases',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=True),
            sa.Column('form_type', sa.String(10), nullable=False),
            sa.Column('year_of_assessment', sa.String(9), nullable=False),
            sa.Column('event_date', sa.Date(), nullable=True),
            sa.Column('due_date', sa.Date(), nullable=True),
            sa.Column('income_period_start', sa.Date(), nullable=True),
            sa.Column('income_period_end', sa.Date(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='DUE'),
            sa.Column('schema_version', sa.String(40), nullable=True),
            sa.Column('schema_hash', sa.String(64), nullable=True),
            sa.Column('payload', sa.JSON(), nullable=True),
            sa.Column('payload_hash', sa.String(64), nullable=True),
            sa.Column('source_payroll_hash', sa.String(64), nullable=True),
            sa.Column('reported_income', sa.JSON(), nullable=True),
            sa.Column('validation_errors', sa.JSON(), nullable=True),
            sa.Column('filing_reference', sa.String(100), nullable=True),
            sa.Column('receipt_reference', sa.String(100), nullable=True),
            sa.Column('filed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('amends_case_id', sa.Integer(), sa.ForeignKey('hkg_ird_reporting_cases.id'), nullable=True),
            sa.Column('suppression_reason', sa.Text(), nullable=True),
            sa.Column('employee_copy_delivered_at', sa.DateTime(timezone=True), nullable=True),
            # Link back to the shared report TRACKER — the same split the UK uses
            # between GeneratedReport and RtiSubmission. Declared inline in
            # create_table rather than added afterwards with ALTER TABLE: SQLite
            # cannot ALTER a constraint into existence (alembic raises
            # "No support for ALTER of constraints in SQLite dialect") and
            # cannot drop a column a foreign key still references, so an
            # add-then-drop column is not reversible there. Inline is real on
            # both supported dialects and dies with the table on downgrade.
            sa.Column('generated_report_id', sa.Integer(), sa.ForeignKey('payroll_generated_reports.id'), nullable=True),
            sa.Column('amendment_type', sa.String(15), nullable=False, server_default='ORIGINAL'),
            sa.Column('submission_mode', sa.String(30), nullable=True),
            sa.Column('authorized_signer', sa.String(200), nullable=True),
            sa.Column('transaction_reference', sa.String(100), nullable=True),
            sa.Column('control_list_reference', sa.String(100), nullable=True),
            sa.Column('submitted_on', sa.Date(), nullable=True),
            sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('prepared_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_hkg_ird_reporting_cases_id', 'hkg_ird_reporting_cases', ['id'], unique=False)
        op.create_index('ix_hkg_ird_reporting_cases_organization_id', 'hkg_ird_reporting_cases', ['organization_id'], unique=False)
        op.create_index('ix_hkg_ird_reporting_cases_employee_id', 'hkg_ird_reporting_cases', ['employee_id'], unique=False)
        op.create_index('ix_hkg_ird_case_lookup', 'hkg_ird_reporting_cases', ['organization_id', 'employee_id', 'form_type', 'year_of_assessment'], unique=False)
        op.create_index('ix_hkg_ird_reporting_cases_generated_report_id', 'hkg_ird_reporting_cases', ['generated_report_id'], unique=False)
    if 'hkg_work_hours' not in existing:
        op.create_table(
            'hkg_work_hours',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False),
            sa.Column('work_date', sa.Date(), nullable=False),
            sa.Column('hours', sa.Numeric(6, 2), nullable=False),
            sa.Column('source', sa.String(30), nullable=False),
            sa.Column('evidence_ref', sa.String(200), nullable=True),
            sa.Column('superseded_by_id', sa.Integer(), sa.ForeignKey('hkg_work_hours.id'), nullable=True),
            sa.Column('supersede_reason', sa.Text(), nullable=True),
            sa.Column('recorded_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
        op.create_index('ix_hkg_work_hours_organization_id', 'hkg_work_hours', ['organization_id'], unique=False)
        op.create_index('ix_hkg_work_hours_employee_id', 'hkg_work_hours', ['employee_id'], unique=False)
        op.create_index('ix_hkg_work_hours_id', 'hkg_work_hours', ['id'], unique=False)
        op.create_index('ix_hkg_work_hours_employee_date', 'hkg_work_hours', ['employee_id', 'work_date'], unique=False)
    if 'hkg_tax_clearance_holds' not in existing:
        op.create_table(
            'hkg_tax_clearance_holds',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False),
            sa.Column('ird_case_id', sa.Integer(), sa.ForeignKey('hkg_ird_reporting_cases.id'), nullable=True),
            sa.Column('state', sa.String(40), nullable=False, server_default='DEPARTURE_IDENTIFIED'),
            sa.Column('expected_departure_date', sa.Date(), nullable=False),
            sa.Column('identified_on', sa.Date(), nullable=False),
            sa.Column('filing_deadline', sa.Date(), nullable=False),
            sa.Column('filed_date', sa.Date(), nullable=True),
            sa.Column('statutory_hold_expiry', sa.Date(), nullable=True),
            sa.Column('release_basis', sa.String(40), nullable=True),
            sa.Column('release_reference', sa.String(100), nullable=True),
            sa.Column('release_evidence_ref', sa.String(200), nullable=True),
            sa.Column('release_requested_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('released_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('released_amount', sa.Numeric(14, 2), nullable=True),
            sa.Column('change_reason', sa.Text(), nullable=True),
            sa.Column('change_evidence_ref', sa.String(200), nullable=True),
            sa.Column('prepared_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_hkg_tax_clearance_holds_id', 'hkg_tax_clearance_holds', ['id'], unique=False)
        op.create_index('ix_hkg_tax_clearance_holds_employee_id', 'hkg_tax_clearance_holds', ['employee_id'], unique=False)
        op.create_index('ix_hkg_tax_clearance_holds_organization_id', 'hkg_tax_clearance_holds', ['organization_id'], unique=False)
    if 'hkg_tax_clearance_hold_lines' not in existing:
        op.create_table(
            'hkg_tax_clearance_hold_lines',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('hold_id', sa.Integer(), sa.ForeignKey('hkg_tax_clearance_holds.id'), nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('payslip_item_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=False),
            sa.Column('amount', sa.Numeric(14, 2), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='HELD'),
            sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.UniqueConstraint('hold_id', 'payslip_item_id', name='uq_hkg_hold_line_payslip'),
        )
        op.create_index('ix_hkg_tax_clearance_hold_lines_hold_id', 'hkg_tax_clearance_hold_lines', ['hold_id'], unique=False)
        op.create_index('ix_hkg_tax_clearance_hold_lines_id', 'hkg_tax_clearance_hold_lines', ['id'], unique=False)
        op.create_index('ix_hkg_tax_clearance_hold_lines_organization_id', 'hkg_tax_clearance_hold_lines', ['organization_id'], unique=False)
    if 'hkg_average_wage_snapshots' not in existing:
        op.create_table(
            'hkg_average_wage_snapshots',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False),
            sa.Column('benefit_type', sa.String(30), nullable=False),
            sa.Column('reference_date', sa.Date(), nullable=False),
            sa.Column('lookback_start', sa.Date(), nullable=False),
            sa.Column('lookback_end', sa.Date(), nullable=False),
            sa.Column('included_rows', sa.JSON(), nullable=False),
            sa.Column('excluded_periods', sa.JSON(), nullable=False),
            sa.Column('excluded_amounts', sa.JSON(), nullable=False),
            sa.Column('total_wages', sa.Numeric(14, 2), nullable=False),
            sa.Column('total_days', sa.Integer(), nullable=False),
            sa.Column('average_daily_wage', sa.Numeric(14, 4), nullable=False),
            sa.Column('average_monthly_wage', sa.Numeric(14, 2), nullable=True),
            sa.Column('four_fifths_daily', sa.Numeric(14, 2), nullable=True),
            sa.Column('result', sa.JSON(), nullable=False),
            sa.Column('source_revision_hash', sa.String(64), nullable=False),
            sa.Column('evidence_hash', sa.String(64), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='CALCULATED'),
            sa.Column('override_average_daily_wage', sa.Numeric(14, 4), nullable=True),
            sa.Column('override_reason', sa.Text(), nullable=True),
            sa.Column('override_evidence_ref', sa.String(200), nullable=True),
            sa.Column('override_requested_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('override_approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
        op.create_index('ix_hkg_average_wage_snapshots_id', 'hkg_average_wage_snapshots', ['id'], unique=False)
        op.create_index('ix_hkg_average_wage_snapshots_organization_id', 'hkg_average_wage_snapshots', ['organization_id'], unique=False)
        op.create_index('ix_hkg_average_wage_snapshots_employee_id', 'hkg_average_wage_snapshots', ['employee_id'], unique=False)
    if 'hkg_termination_results' not in existing:
        op.create_table(
            'hkg_termination_results',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False),
            sa.Column('termination_date', sa.Date(), nullable=False),
            sa.Column('termination_reason', sa.String(40), nullable=False),
            sa.Column('payment_type', sa.String(10), nullable=False),
            sa.Column('gross_entitlement', sa.Numeric(14, 2), nullable=False),
            sa.Column('total_offsets', sa.Numeric(14, 2), nullable=False),
            sa.Column('net_statutory_payment', sa.Numeric(14, 2), nullable=False),
            sa.Column('result', sa.JSON(), nullable=False),
            sa.Column('evidence_hash', sa.String(64), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='CALCULATED'),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
        op.create_index('ix_hkg_termination_results_employee_id', 'hkg_termination_results', ['employee_id'], unique=False)
        op.create_index('ix_hkg_termination_results_organization_id', 'hkg_termination_results', ['organization_id'], unique=False)
        op.create_index('ix_hkg_termination_results_id', 'hkg_termination_results', ['id'], unique=False)
    if 'hkg_empf_submissions' not in existing:
        op.create_table(
            'hkg_empf_submissions',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('contribution_period', sa.String(7), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='PREPARED'),
            sa.Column('rows', sa.JSON(), nullable=False),
            sa.Column('totals', sa.JSON(), nullable=False),
            sa.Column('payload_hash', sa.String(64), nullable=False),
            sa.Column('validation_errors', sa.JSON(), nullable=True),
            sa.Column('submission_reference', sa.String(100), nullable=True),
            sa.Column('row_outcomes', sa.JSON(), nullable=True),
            sa.Column('settlement_reference', sa.String(100), nullable=True),
            sa.Column('contribution_day', sa.Date(), nullable=True),
            sa.Column('amends_submission_id', sa.Integer(), sa.ForeignKey('hkg_empf_submissions.id'), nullable=True),
            sa.Column('supplements_submission_id', sa.Integer(), sa.ForeignKey('hkg_empf_submissions.id'), nullable=True),
            # See the note on hkg_ird_reporting_cases.generated_report_id: inline
            # so this FK is created and removed reversibly on SQLite as well as
            # PostgreSQL.
            sa.Column('generated_report_id', sa.Integer(), sa.ForeignKey('payroll_generated_reports.id'), nullable=True),
            sa.Column('prepared_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('submitted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_hkg_empf_submissions_id', 'hkg_empf_submissions', ['id'], unique=False)
        op.create_index('ix_hkg_empf_submissions_organization_id', 'hkg_empf_submissions', ['organization_id'], unique=False)
        op.create_index('ix_hkg_empf_submissions_generated_report_id', 'hkg_empf_submissions', ['generated_report_id'], unique=False)
    # D-14 linked corrections and D-19 access log / legal hold: HK-owned tables
    # folded into this never-deployed revision (same reasoning as the report-link
    # columns above; the head stays cd62503afe26).
    if 'hkg_payslip_corrections' not in existing:
        op.create_table(
            'hkg_payslip_corrections',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False),
            sa.Column('original_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=False),
            sa.Column('original_run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=False),
            sa.Column('correction_run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=True),
            sa.Column('delta_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
            sa.Column('sequence', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='REQUESTED'),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('original_trace_hash', sa.String(64), nullable=False),
            sa.Column('before', sa.JSON(), nullable=False),
            sa.Column('after', sa.JSON(), nullable=False),
            sa.Column('delta', sa.JSON(), nullable=False),
            sa.Column('warnings', sa.JSON(), nullable=True),
            sa.Column('consequences', sa.JSON(), nullable=True),
            sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('rejected_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('rejected_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.UniqueConstraint('original_payslip_id', 'sequence', name='uq_hkg_correction_sequence'),
        )
        op.create_index('ix_hkg_payslip_corrections_id', 'hkg_payslip_corrections', ['id'], unique=False)
        op.create_index('ix_hkg_payslip_corrections_organization_id', 'hkg_payslip_corrections', ['organization_id'], unique=False)
        op.create_index('ix_hkg_payslip_corrections_employee_id', 'hkg_payslip_corrections', ['employee_id'], unique=False)
        op.create_index('ix_hkg_payslip_corrections_original_payslip_id', 'hkg_payslip_corrections', ['original_payslip_id'], unique=False)
    if 'hkg_access_events' not in existing:
        op.create_table(
            'hkg_access_events',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('action', sa.String(40), nullable=False),
            sa.Column('resource_type', sa.String(40), nullable=False),
            sa.Column('resource_id', sa.Integer(), nullable=True),
            sa.Column('employee_id', sa.Integer(), nullable=True),
            sa.Column('report_type', sa.String(40), nullable=True),
            sa.Column('purpose', sa.String(200), nullable=True),
            sa.Column('result', sa.String(20), nullable=False, server_default='SUCCESS'),
            sa.Column('client_address', sa.String(64), nullable=True),
            sa.Column('user_agent', sa.String(300), nullable=True),
            sa.Column('assisted_access_session_id', sa.Integer(), nullable=True),
            sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_hkg_access_events_id', 'hkg_access_events', ['id'], unique=False)
        op.create_index('ix_hkg_access_events_organization_id', 'hkg_access_events', ['organization_id'], unique=False)
        op.create_index('ix_hkg_access_events_employee_id', 'hkg_access_events', ['employee_id'], unique=False)
    if 'hkg_legal_holds' not in existing:
        op.create_table(
            'hkg_legal_holds',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('reference', sa.String(200), nullable=True),
            sa.Column('placed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('placed_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('released_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('release_reason', sa.Text(), nullable=True),
        )
        op.create_index('ix_hkg_legal_holds_id', 'hkg_legal_holds', ['id'], unique=False)
        op.create_index('ix_hkg_legal_holds_organization_id', 'hkg_legal_holds', ['organization_id'], unique=False)
        op.create_index('ix_hkg_legal_holds_employee_id', 'hkg_legal_holds', ['employee_id'], unique=False)

    # Production-readiness pass: platform-level HK control tables (Super
    # Admin). Folded into this never-applied revision like the report links.
    if 'hkg_ird_software_approvals' not in existing:
        op.create_table(
            'hkg_ird_software_approvals',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('status', sa.String(30), nullable=False, server_default='NOT_APPLIED'),
            sa.Column('forms_covered', sa.JSON(), nullable=False),
            sa.Column('specification_version', sa.String(40), nullable=True),
            sa.Column('application_reference', sa.String(100), nullable=True),
            sa.Column('application_submitted_on', sa.Date(), nullable=True),
            sa.Column('test_data_submitted_on', sa.Date(), nullable=True),
            sa.Column('approval_reference', sa.String(100), nullable=True),
            sa.Column('approval_received_on', sa.Date(), nullable=True),
            sa.Column('expires_on', sa.Date(), nullable=True),
            sa.Column('approval_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('document_sha256', sa.String(64), nullable=True),
            sa.Column('reviewer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_hkg_ird_software_approvals_id', 'hkg_ird_software_approvals', ['id'], unique=False)
    if 'hkg_empf_configurations' not in existing:
        op.create_table(
            'hkg_empf_configurations',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
            sa.Column('submission_method', sa.String(40), nullable=False),
            sa.Column('file_format', sa.String(40), nullable=True),
            sa.Column('format_version', sa.String(40), nullable=True),
            sa.Column('environment', sa.String(20), nullable=False),
            sa.Column('endpoint_reference', sa.String(300), nullable=True),
            sa.Column('credential_status', sa.String(30), nullable=False, server_default='NOT_CONFIGURED'),
            sa.Column('certificate_status', sa.String(30), nullable=False, server_default='NOT_CONFIGURED'),
            sa.Column('certification_status', sa.String(30), nullable=False, server_default='NOT_CERTIFIED'),
            sa.Column('certification_evidence_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.UniqueConstraint('version', name='uq_hkg_empf_configuration_version'),
        )
        op.create_index('ix_hkg_empf_configurations_id', 'hkg_empf_configurations', ['id'], unique=False)
    if 'hkg_retention_policies' not in existing:
        op.create_table(
            'hkg_retention_policies',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('record_category', sa.String(60), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
            sa.Column('retention_years', sa.Integer(), nullable=True),
            sa.Column('end_of_retention', sa.String(20), nullable=True),
            sa.Column('legal_basis', sa.Text(), nullable=True),
            sa.Column('decision_reference', sa.String(60), nullable=True),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
        op.create_index('ix_hkg_retention_policies_id', 'hkg_retention_policies', ['id'], unique=False)
        op.create_index('ix_hkg_retention_policies_record_category', 'hkg_retention_policies', ['record_category'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _TABLES:          # children first
        if table in existing:
            op.drop_table(table)
    if 'hkg_calculation_trace' in _existing_columns('payslip_items'):
        op.drop_column('payslip_items', 'hkg_calculation_trace')
    existing_profile = _existing_columns(_PROFILE_TABLE)
    for name, _type in reversed(_PROFILE_COLUMNS):
        if name in existing_profile:
            op.drop_column(_PROFILE_TABLE, name)
