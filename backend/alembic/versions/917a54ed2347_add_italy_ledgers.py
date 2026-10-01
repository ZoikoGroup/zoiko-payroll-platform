"""Italy P2 ledgers: CCNL level terms, TFR ledger, F24 lines, LUL entries

Revision ID: 917a54ed2347
Revises: 7a1b2c3d4e5f
Create Date: 2026-10-01 00:00:00.000000

ZP-IT-ENG-001 phase P2. Four tables and one employee-profile column, each for
a fact no generic table can express (see the "Italy P2 ledgers" note in
models.py for everything mapped onto the generic model instead):

  payroll_it_ccnl_level_terms    §9 / IT-026 / IT-053 — per-level minimum pay,
                                 fixed elements, mensilita and normal week,
                                 effective-dated by renewal
  payroll_it_tfr_ledger_entries  §13 / IT-037 / IT-038 — append-only TFR
                                 liability ledger with destination per entry
  payroll_it_f24_lines           §16 / IT-046 — F24 lines by section, code,
                                 authority and period
  payroll_it_lul_entries         §20 / IT-058 — sequenced, hashed, retained
                                 Libro Unico registrations
  payroll_employee_statutory_profiles.it_contractual_weekly_hours
                                 IT-018 — contractual hours for the part-time
                                 INPS minimum

Additive only: new tables and one nullable column. Every operation is guarded
(skipped when its object already exists), the pattern adopted after the
2026-09-29 deploy failed on a table an unmerged branch had already created.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '917a54ed2347'
down_revision: Union[str, Sequence[str], None] = '7a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROFILE_TABLE = 'payroll_employee_statutory_profiles'


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table('payroll_it_ccnl_level_terms'):
        op.create_table(
            'payroll_it_ccnl_level_terms',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('collective_agreement_id', sa.Integer(),
                      sa.ForeignKey('payroll_collective_agreements.id'), nullable=False, index=True),
            sa.Column('level_code', sa.String(20), nullable=False),
            sa.Column('worker_category', sa.String(30), nullable=True),
            sa.Column('minimum_monthly', sa.Numeric(12, 2), nullable=False),
            sa.Column('contingenza_monthly', sa.Numeric(12, 2), nullable=True),
            sa.Column('edr_monthly', sa.Numeric(12, 2), nullable=True),
            sa.Column('other_fixed_elements', sa.JSON(), nullable=True),
            sa.Column('mensilita', sa.Integer(), nullable=False),
            sa.Column('weekly_hours', sa.Numeric(5, 2), nullable=False),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('renewal_reference', sa.String(100), nullable=True),
            sa.Column('source_document_id', sa.Integer(),
                      sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint('collective_agreement_id', 'level_code', 'effective_from',
                                name='uq_it_ccnl_level_terms_level_from'),
        )

    if not _has_table('payroll_it_tfr_ledger_entries'):
        op.create_table(
            'payroll_it_tfr_ledger_entries',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'),
                      nullable=False, index=True),
            sa.Column('entry_type', sa.String(30), nullable=False),
            sa.Column('tax_year', sa.Integer(), nullable=False),
            sa.Column('entry_date', sa.Date(), nullable=False),
            sa.Column('amount', sa.Numeric(14, 2), nullable=False),
            sa.Column('destination', sa.String(30), nullable=True),
            sa.Column('pension_fund', sa.String(30), nullable=True),
            sa.Column('payslip_item_id', sa.Integer(), sa.ForeignKey('payslip_items.id'),
                      nullable=True, index=True),
            sa.Column('payroll_run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=True),
            sa.Column('reverses_entry_id', sa.Integer(),
                      sa.ForeignKey('payroll_it_tfr_ledger_entries.id'), nullable=True),
            sa.Column('evidence', sa.JSON(), nullable=True),
            sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table('payroll_it_f24_lines'):
        op.create_table(
            'payroll_it_f24_lines',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            sa.Column('statutory_filing_id', sa.Integer(), sa.ForeignKey('statutory_filings.id'),
                      nullable=True, index=True),
            sa.Column('payroll_run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'),
                      nullable=True, index=True),
            sa.Column('section', sa.String(20), nullable=False),
            sa.Column('tax_code', sa.String(10), nullable=False),
            sa.Column('region_code', sa.String(10), nullable=True),
            sa.Column('comune_code', sa.String(10), nullable=True),
            sa.Column('reference_period', sa.String(10), nullable=False),
            sa.Column('debit_amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
            sa.Column('credit_amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
            sa.Column('source_lines', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table('payroll_it_lul_entries'):
        op.create_table(
            'payroll_it_lul_entries',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'),
                      nullable=False, index=True),
            sa.Column('reference_month', sa.String(7), nullable=False),
            sa.Column('sequence_number', sa.Integer(), nullable=False),
            sa.Column('entry_type', sa.String(20), nullable=False),
            sa.Column('corrects_entry_id', sa.Integer(),
                      sa.ForeignKey('payroll_it_lul_entries.id'), nullable=True),
            sa.Column('payslip_item_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
            sa.Column('payroll_run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=True),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('registered_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column('retention_until', sa.Date(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('organization_id', 'sequence_number', name='uq_it_lul_org_sequence'),
        )

    if not _has_column(PROFILE_TABLE, 'it_contractual_weekly_hours'):
        op.add_column(PROFILE_TABLE, sa.Column('it_contractual_weekly_hours', sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    if _has_column(PROFILE_TABLE, 'it_contractual_weekly_hours'):
        if op.get_bind().dialect.name == 'sqlite':
            with op.batch_alter_table(PROFILE_TABLE) as batch:
                batch.drop_column('it_contractual_weekly_hours')
        else:
            op.drop_column(PROFILE_TABLE, 'it_contractual_weekly_hours')
    for table in ('payroll_it_lul_entries', 'payroll_it_f24_lines',
                  'payroll_it_tfr_ledger_entries', 'payroll_it_ccnl_level_terms'):
        if _has_table(table):
            op.drop_table(table)
