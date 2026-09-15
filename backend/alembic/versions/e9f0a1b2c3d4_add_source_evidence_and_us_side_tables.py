"""add payroll_source_artifacts and 4 sibling tables (never migrated)

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-09-09 02:00:00.000000

Found during a Sources & Evidence audit (ZP-TAX-UK-2026-27-001 §4.2/§20/
AC-29 gap-closure Part 1B, 2026-09-09): payroll_source_artifacts,
payroll_locality_datasets, payroll_locality_rates,
payroll_employer_tax_profiles, and payroll_reciprocity_rules have existed
in models.py since the earlier US locality/SUI/reciprocity work, but NO
migration anywhere in this history ever creates any of them — confirmed
by walking every migration and finding zero `op.create_table` calls for
any of the 5. A later migration
(71d815f06d78_add_us_locality_sui_reciprocity_source_.py) explicitly
documents the assumption that these 5 tables "already exist on the
target database" via `initialize_database()`'s `Base.metadata.
create_all()` fallback and only adds columns to them — the exact same
class of gap already found and fixed once this session for
payroll_ytd_accumulators (c7d8e9f0a1b2).

Unlike that fix, this one is genuinely uncertain whether the 5 tables
already exist on any given real database: `create_all()` only ever runs
on a database where the `users` table doesn't exist yet (a truly fresh
boot) — if these tables were added to models.py AFTER a target
database's very first boot, they were never created there, but if the
whole platform's database predates them by little enough that a manual/
scripted `Base.metadata.create_all()` was run since, they might already
exist. Each `op.create_table` below is guarded by an existence check so
this migration is safe to run against EITHER case — it fills the gap on
a target where the tables are genuinely missing, and is a safe no-op per
table where they already exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if 'payroll_source_artifacts' not in existing:
        op.create_table(
            'payroll_source_artifacts',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('agency', sa.String(length=200), nullable=False),
            sa.Column('title', sa.String(length=300), nullable=False),
            sa.Column('form_number', sa.String(length=50), nullable=True),
            sa.Column('source_url', sa.String(length=500), nullable=True),
            sa.Column('publication_date', sa.Date(), nullable=True),
            sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
            sa.Column('reviewer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('reviewer_approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('superseded_by_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        existing.add('payroll_source_artifacts')

    if 'payroll_locality_datasets' not in existing:
        op.create_table(
            'payroll_locality_datasets',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('jurisdiction_country', sa.String(length=10), nullable=False),
            sa.Column('jurisdiction_state', sa.String(length=100), nullable=False),
            sa.Column('version', sa.String(length=50), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
            sa.Column('effective_from', sa.Date(), nullable=True),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('imported_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        existing.add('payroll_locality_datasets')

    if 'payroll_locality_rates' not in existing:
        op.create_table(
            'payroll_locality_rates',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('locality_dataset_id', sa.Integer(), sa.ForeignKey('payroll_locality_datasets.id'), nullable=False, index=True),
            sa.Column('locality_code', sa.String(length=20), nullable=False),
            sa.Column('locality_type', sa.String(length=30), nullable=False),
            sa.Column('locality_name', sa.String(length=200), nullable=True),
            sa.Column('resident_rate_pct', sa.Numeric(precision=6, scale=4), nullable=True),
            sa.Column('nonresident_rate_pct', sa.Numeric(precision=6, scale=4), nullable=True),
            sa.Column('flat_amount', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('tax_collector_id', sa.String(length=100), nullable=True),
            sa.UniqueConstraint('locality_dataset_id', 'locality_code', name='uq_locality_rate_dataset_code'),
        )
        existing.add('payroll_locality_rates')

    if 'payroll_employer_tax_profiles' not in existing:
        op.create_table(
            'payroll_employer_tax_profiles',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('jurisdiction_id', sa.String(length=10), nullable=False),
            sa.Column('component_code', sa.String(length=20), nullable=False),
            sa.Column('taxable_wage_base', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('rate_source', sa.String(length=20), nullable=False, server_default='STATE_DEFAULT'),
            sa.Column('employer_rate_pct', sa.Numeric(precision=6, scale=4), nullable=True),
            sa.Column('assessment_rate_pct', sa.Numeric(precision=6, scale=4), nullable=True),
            sa.Column('covered_employee_count', sa.Integer(), nullable=True),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('agency_account_id', sa.String(length=100), nullable=True),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('reimbursable_status', sa.String(length=20), nullable=False, server_default='CONTRIBUTORY'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index(
            'ix_employer_tax_profile_org_jur_comp', 'payroll_employer_tax_profiles',
            ['organization_id', 'jurisdiction_id', 'component_code'],
        )
        existing.add('payroll_employer_tax_profiles')

    if 'payroll_reciprocity_rules' not in existing:
        op.create_table(
            'payroll_reciprocity_rules',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('resident_jurisdiction', sa.String(length=10), nullable=False),
            sa.Column('work_jurisdiction', sa.String(length=10), nullable=False),
            sa.Column('agreement_type', sa.String(length=40), nullable=False, server_default='RECIPROCAL_WAGE_WITHHOLDING'),
            sa.Column('employee_certificate', sa.String(length=50), nullable=True),
            sa.Column('certificate_required', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('result_when_valid', sa.String(length=200), nullable=True),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.UniqueConstraint('resident_jurisdiction', 'work_jurisdiction', 'effective_from', name='uq_reciprocity_pair_effective'),
        )
        existing.add('payroll_reciprocity_rules')


def downgrade() -> None:
    """Downgrade schema. Guarded the same way upgrade() is — only drops a
    table this migration actually created, never one that pre-existed
    (which this migration never touched in the first place)."""
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in ('payroll_reciprocity_rules', 'payroll_employer_tax_profiles',
                  'payroll_locality_rates', 'payroll_locality_datasets', 'payroll_source_artifacts'):
        if table in existing:
            op.drop_table(table)
