"""add UK RTI data-gap columns, widen GeneratedReport, add RtiSubmission

Revision ID: bbd80be2fee1
Revises: 36d83be4bc14
Create Date: 2026-09-09 09:00:00.000000

ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9:
- CompanyComplianceDetails gains paye_reference/accounts_office_reference.
- PayrollEmployee gains address fields + starter_declaration.
- GeneratedReport.payroll_run_id widened to nullable, gains employee_id
  and scope_key, for per-employee (P45/P60) and per-period (EPS) reports
  that aren't tied to one PayrollRun. The old run-based partial unique
  index is recreated with an added "payroll_run_id IS NOT NULL" guard;
  a new scope-based partial unique index is added alongside it.
- New payroll_rti_submissions table (status tracking only, Part 9B).

All additive/nullable — no existing row's data or behavior changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbd80be2fee1'
down_revision: Union[str, Sequence[str], None] = '36d83be4bc14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_company_compliance', sa.Column('paye_reference', sa.String(length=20), nullable=True))
    op.add_column('payroll_company_compliance', sa.Column('accounts_office_reference', sa.String(length=20), nullable=True))

    op.add_column('payroll_employees', sa.Column('address_line1', sa.String(length=200), nullable=True))
    op.add_column('payroll_employees', sa.Column('address_line2', sa.String(length=200), nullable=True))
    op.add_column('payroll_employees', sa.Column('address_town', sa.String(length=100), nullable=True))
    op.add_column('payroll_employees', sa.Column('address_county', sa.String(length=100), nullable=True))
    op.add_column('payroll_employees', sa.Column('address_postcode', sa.String(length=20), nullable=True))
    op.add_column('payroll_employees', sa.Column('starter_declaration', sa.String(length=1), nullable=True))

    op.alter_column('payroll_generated_reports', 'payroll_run_id', existing_type=sa.Integer(), nullable=True)
    op.add_column('payroll_generated_reports', sa.Column('employee_id', sa.Integer(), nullable=True))
    op.add_column('payroll_generated_reports', sa.Column('scope_key', sa.String(length=100), nullable=True))
    op.create_foreign_key(
        'fk_generated_report_employee', 'payroll_generated_reports', 'payroll_employees',
        ['employee_id'], ['id'],
    )
    op.create_index('ix_payroll_generated_reports_employee_id', 'payroll_generated_reports', ['employee_id'], unique=False)

    # Recreate the run-based partial unique index with the added
    # "payroll_run_id IS NOT NULL" guard (a NULL run_id no longer
    # belongs in this index's scope now that it's a legitimate state).
    op.drop_index('uq_generated_report_org_run_template_active', table_name='payroll_generated_reports')
    op.create_index(
        'uq_generated_report_org_run_template_active', 'payroll_generated_reports',
        ['organization_id', 'payroll_run_id', 'report_template_id'], unique=True,
        postgresql_where=sa.text("status = 'Generated' AND payroll_run_id IS NOT NULL"),
        sqlite_where=sa.text("status = 'Generated' AND payroll_run_id IS NOT NULL"),
    )
    op.create_index(
        'uq_generated_report_org_scope_template_active', 'payroll_generated_reports',
        ['organization_id', 'scope_key', 'report_template_id'], unique=True,
        postgresql_where=sa.text("status = 'Generated' AND scope_key IS NOT NULL"),
        sqlite_where=sa.text("status = 'Generated' AND scope_key IS NOT NULL"),
    )

    op.create_table(
        'payroll_rti_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('generated_report_id', sa.Integer(), nullable=False),
        sa.Column('submission_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='DRAFT'),
        sa.Column('hmrc_correlation_id', sa.String(length=100), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['generated_report_id'], ['payroll_generated_reports.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payroll_rti_submissions_id', 'payroll_rti_submissions', ['id'], unique=False)
    op.create_index('ix_payroll_rti_submissions_organization_id', 'payroll_rti_submissions', ['organization_id'], unique=False)
    op.create_index('ix_payroll_rti_submissions_generated_report_id', 'payroll_rti_submissions', ['generated_report_id'], unique=False)
    op.create_index('ix_rti_submission_org_status', 'payroll_rti_submissions', ['organization_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rti_submission_org_status', table_name='payroll_rti_submissions')
    op.drop_index('ix_payroll_rti_submissions_generated_report_id', table_name='payroll_rti_submissions')
    op.drop_index('ix_payroll_rti_submissions_organization_id', table_name='payroll_rti_submissions')
    op.drop_index('ix_payroll_rti_submissions_id', table_name='payroll_rti_submissions')
    op.drop_table('payroll_rti_submissions')

    op.drop_index('uq_generated_report_org_scope_template_active', table_name='payroll_generated_reports')
    op.drop_index('uq_generated_report_org_run_template_active', table_name='payroll_generated_reports')
    op.create_index(
        'uq_generated_report_org_run_template_active', 'payroll_generated_reports',
        ['organization_id', 'payroll_run_id', 'report_template_id'], unique=True,
        postgresql_where=sa.text("status = 'Generated'"),
        sqlite_where=sa.text("status = 'Generated'"),
    )
    op.drop_index('ix_payroll_generated_reports_employee_id', table_name='payroll_generated_reports')
    op.drop_constraint('fk_generated_report_employee', 'payroll_generated_reports', type_='foreignkey')
    op.drop_column('payroll_generated_reports', 'scope_key')
    op.drop_column('payroll_generated_reports', 'employee_id')
    op.alter_column('payroll_generated_reports', 'payroll_run_id', existing_type=sa.Integer(), nullable=False)

    op.drop_column('payroll_employees', 'starter_declaration')
    op.drop_column('payroll_employees', 'address_postcode')
    op.drop_column('payroll_employees', 'address_county')
    op.drop_column('payroll_employees', 'address_town')
    op.drop_column('payroll_employees', 'address_line2')
    op.drop_column('payroll_employees', 'address_line1')

    op.drop_column('payroll_company_compliance', 'accounts_office_reference')
    op.drop_column('payroll_company_compliance', 'paye_reference')
