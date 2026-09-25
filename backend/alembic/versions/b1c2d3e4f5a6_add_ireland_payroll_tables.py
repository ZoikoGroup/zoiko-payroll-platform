"""add ireland payroll tables

Revision ID: b1c2d3e4f5a6
Revises: 74aeb450aeee

Ireland (ZP-IE-ENG-001, 2026-09-25) schema. Covers §12's "Ireland-specific
minimum" object list, reusing existing generic tables wherever the platform
already models the concept:

  RulePackIE            -> reused JurisdictionPack / ContributionRate /
                          TaxSlab (already effective-dated and Super-Admin
                          configurable; no new table, and no hardcoded
                          runtime fallback in the engine).
  EmployeeIrelandProfile-> the Ireland block of columns added to the existing
                          payroll_employee_statutory_profiles (already
                          effective-dated per country_code, which is exactly
                          the versioning a PRSI-class or pension-exemption
                          change needs).

New tables:

  - payroll_ie_employer_profiles           ROS/remitter/bank/PRSI-scope/
                                           MyFutureFund-employer + IE-028 gate
  - payroll_ie_rpn_snapshots               frozen Revenue Payroll Notification
                                           (immutable, content-addressed)
  - payroll_ie_myfuturefund_statuses       NAERSA authority status, effective
                                           dated (no admin enrolment control)
  - payroll_ie_ytd_accumulators            independent USC/PRSI/MyFutureFund
                                           bases; COMMIT-only (IE-032)
  - payroll_ie_revenue_submissions         append-only reported line items
  - payroll_ie_revenue_monthly_returns     versioned statement + reconciliation

Additive only: six brand-new tables plus nullable columns on the existing
payroll_employee_statutory_profiles. No existing column is altered, dropped
or retyped, and no existing row is touched, so this is backward compatible
for every other jurisdiction. All FKs reference pre-existing tables
(organizations, users, payroll_employees, payroll_runs, payslip_items) or
tables created earlier in this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = '74aeb450aeee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── Ireland columns on the existing effective-dated statutory profile ──
    # All nullable, so no existing row (any jurisdiction) is affected and the
    # open-ended-row uniqueness guard above them is untouched.
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_ppsn', sa.String(length=15), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_employer_reference', sa.String(length=32), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_revenue_employment_id', sa.String(length=64), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_prsi_class', sa.String(length=10), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_prsi_exemption_reference', sa.String(length=64), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_usc_status', sa.String(length=20), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_pension_scheme_reference', sa.String(length=64), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_pension_qualifying_exemption_reference', sa.String(length=64), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_pension_qualifying_exemption_effective_from', sa.Date(), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_contracted_weekly_hours', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_sector_wage_order', sa.String(length=10), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_emergency_reason', sa.Text(), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('ie_emergency_week', sa.Integer(), nullable=True))

    # ── payroll_ie_employer_profiles (1:1 org-level Ireland employer profile) ──
    op.create_table(
        'payroll_ie_employer_profiles',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, unique=True, index=True),
        sa.Column('paye_registration_number', sa.String(length=20), nullable=True),
        sa.Column('prsi_registration_number', sa.String(length=20), nullable=True),
        sa.Column('ros_sub_user_reference', sa.String(length=64), nullable=True),
        sa.Column('eircode', sa.String(length=10), nullable=True),
        sa.Column('ros_certificate_status', sa.String(length=30), nullable=False, server_default='NOT_VALIDATED'),
        sa.Column('ros_certificate_reference', sa.String(length=100), nullable=True),
        sa.Column('ros_certificate_expires_on', sa.Date(), nullable=True),
        sa.Column('remitter_frequency', sa.String(length=20), nullable=True),
        sa.Column('revenue_collector_identity', sa.String(length=100), nullable=True),
        sa.Column('settlement_bank', sa.String(length=100), nullable=True),
        sa.Column('settlement_account_iban', sa.String(length=34), nullable=True),
        sa.Column('settlement_account_bic', sa.String(length=11), nullable=True),
        sa.Column('bank_adapter_version', sa.String(length=30), nullable=True),
        sa.Column('bank_cutoff_reference', sa.String(length=100), nullable=True),
        sa.Column('prsi_scope', sa.String(length=30), nullable=False, server_default='A_ONLY'),
        sa.Column('prsi_supported_classes', sa.JSON(), nullable=True),
        sa.Column('myfuturefund_employer_status', sa.String(length=30), nullable=False, server_default='UNKNOWN'),
        sa.Column('myfuturefund_payment_method', sa.String(length=50), nullable=True),
        sa.Column('readiness_status', sa.String(length=30), nullable=False, server_default='NOT_READY'),
        sa.Column('readiness_evidence', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # ── payroll_ie_rpn_snapshots (frozen Revenue Payroll Notification) ──
    op.create_table(
        'payroll_ie_rpn_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('statutory_profile_id', sa.Integer(), sa.ForeignKey('payroll_employee_statutory_profiles.id'), nullable=True),
        sa.Column('rpn_number', sa.String(length=50), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('tax_year', sa.String(length=10), nullable=False),
        sa.Column('calculation_basis', sa.String(length=20), nullable=False),
        sa.Column('ppsn_supplied', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('standard_rate_band', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('tax_credit', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('standard_rate_band_period', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('tax_credit_period', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('previous_taxable_pay_ytd', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('previous_pay_ytd', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('periods_elapsed', sa.Integer(), nullable=True),
        sa.Column('lpt_instructed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('lpt_rate_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('emergency_tax_credit_weekly', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('raw_hash', sa.String(length=64), nullable=False, index=True),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_stale', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('employee_id', 'tax_year', 'raw_hash', name='uq_ie_rpn_snapshot_employee_year_hash'),
    )
    op.create_index('ix_ie_rpn_snapshot_org_employee', 'payroll_ie_rpn_snapshots', ['organization_id', 'employee_id'])

    # ── payroll_ie_myfuturefund_statuses (NAERSA authority status) ──
    op.create_table(
        'payroll_ie_myfuturefund_statuses',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('employee_contribution_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('employer_contribution_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('state_contribution_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('threshold_state', sa.String(length=30), nullable=True),
        sa.Column('contributions_ceased', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('ceased_from_pay_date', sa.Date(), nullable=True),
        sa.Column('exemption_reference', sa.String(length=64), nullable=True),
        sa.Column('exemption_effective_from', sa.Date(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False, server_default='NAERSA_NOTIFICATION'),
        sa.Column('source_notification_hash', sa.String(length=64), nullable=True),
        sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ie_mff_emp_effective', 'payroll_ie_myfuturefund_statuses', ['employee_id', 'effective_from'])
    op.create_index('ix_ie_mff_org_employee', 'payroll_ie_myfuturefund_statuses', ['organization_id', 'employee_id'])

    # ── payroll_ie_ytd_accumulators (independent USC/PRSI/MyFutureFund bases) ──
    op.create_table(
        'payroll_ie_ytd_accumulators',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('tax_year', sa.String(length=10), nullable=False),
        sa.Column('usc_payable_ytd', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('usc_paid_ytd', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('prsi_reckonable_ytd', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('prsi_contribution_weeks_ytd', sa.Numeric(precision=8, scale=3), nullable=False, server_default='0'),
        sa.Column('mff_earnings_ytd_before', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('mff_threshold_crossed_at_pay_date', sa.Date(), nullable=True),
        sa.Column('last_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('employee_id', 'tax_year', name='uq_ie_ytd_accumulator_employee_year'),
    )
    op.create_index('ix_ie_ytd_org_employee', 'payroll_ie_ytd_accumulators', ['organization_id', 'employee_id'])

    # ── payroll_ie_revenue_submissions (append-only reported line items) ──
    op.create_table(
        'payroll_ie_revenue_submissions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True, index=True),
        sa.Column('line_item_id', sa.String(length=50), nullable=True),
        sa.Column('previous_line_item_id', sa.String(length=50), nullable=True),
        sa.Column('rpn_snapshot_id', sa.Integer(), sa.ForeignKey('payroll_ie_rpn_snapshots.id'), nullable=True),
        sa.Column('correction_kind', sa.String(length=30), nullable=False, server_default='ORIGINAL'),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('pay_date', sa.Date(), nullable=False),
        sa.Column('reported_gross', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_paye', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_prsi_employee', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('reported_prsi_employer', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
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

    # ── payroll_ie_revenue_monthly_returns (versioned statement + reconciliation) ──
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ie_monthly_return_org_period', table_name='payroll_ie_revenue_monthly_returns')
    op.drop_table('payroll_ie_revenue_monthly_returns')

    op.drop_index('ix_ie_revsub_org_period', table_name='payroll_ie_revenue_submissions')
    op.drop_table('payroll_ie_revenue_submissions')

    op.drop_index('ix_ie_ytd_org_employee', table_name='payroll_ie_ytd_accumulators')
    op.drop_table('payroll_ie_ytd_accumulators')

    op.drop_index('ix_ie_mff_org_employee', table_name='payroll_ie_myfuturefund_statuses')
    op.drop_index('ix_ie_mff_emp_effective', table_name='payroll_ie_myfuturefund_statuses')
    op.drop_table('payroll_ie_myfuturefund_statuses')

    op.drop_index('ix_ie_rpn_snapshot_org_employee', table_name='payroll_ie_rpn_snapshots')
    op.drop_table('payroll_ie_rpn_snapshots')

    op.drop_table('payroll_ie_employer_profiles')

    op.drop_column('payroll_employee_statutory_profiles', 'ie_emergency_week')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_emergency_reason')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_sector_wage_order')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_contracted_weekly_hours')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_pension_qualifying_exemption_effective_from')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_pension_qualifying_exemption_reference')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_pension_scheme_reference')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_usc_status')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_prsi_exemption_reference')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_prsi_class')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_revenue_employment_id')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_employer_reference')
    op.drop_column('payroll_employee_statutory_profiles', 'ie_ppsn')
