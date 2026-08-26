"""add US locality, SUI, reciprocity, source evidence, filing status, and federal state local tax split

Revision ID: 71d815f06d78
Revises: 7f92c2c49457
Create Date: 2026-08-24 16:30:08.473635

Hand-pruned from a raw `alembic revision --autogenerate` dump: the raw diff
also proposed dropping ~17 unrelated tables (payroll_hierarchy_*,
platform_statutory_rates, assist_public_*, payroll_inbound_*) that predate
this branch's model history and are out of scope here; converting several
JSONB columns to JSON (organizations.tax_identifiers,
payroll_company_compliance.tax_identifiers, payroll_jurisdiction_packs.
policy_defaults, payslip_items.compliance_fields/tax_rule_snapshot) — an
unrelated, unrequested, and potentially costly type change; several
unrelated NOT NULL tightenings; and — most importantly — dropping the real
`payslip_items.tax_version_id` column and its FK, which this migration must
NOT touch. This file keeps ONLY the additive changes that actually belong
to this session's work (US locality/SUI/reciprocity/source-evidence/filing-
status/tax-split). The 5 new tables these features need
(payroll_locality_datasets, payroll_locality_rates,
payroll_employer_tax_profiles, payroll_reciprocity_rules,
payroll_source_artifacts) already exist on the target database — this
app's own `initialize_database()` calls `Base.metadata.create_all()` on
every startup, which already created them; only NEW COLUMNS on
already-existing tables needed an explicit migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '71d815f06d78'
down_revision: Union[str, Sequence[str], None] = '7f92c2c49457'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payroll_contribution_rates', sa.Column('filing_status', sa.String(length=20), nullable=True))
    op.drop_index('uq_contribution_rate_canonical_country_state_component', table_name='payroll_contribution_rates', postgresql_where='(organization_id IS NULL)')
    op.create_index(
        'uq_contribution_rate_canonical_country_state_component', 'payroll_contribution_rates',
        ['jurisdiction_country', 'jurisdiction_state', 'component_key', 'tax_regime', 'filing_status'],
        unique=True, postgresql_where=sa.text('organization_id IS NULL'), sqlite_where=sa.text('organization_id IS NULL'),
    )
    op.drop_index('uq_contribution_rate_org_country_component', table_name='payroll_contribution_rates', postgresql_where='(organization_id IS NOT NULL)')
    op.create_index(
        'uq_contribution_rate_org_country_component', 'payroll_contribution_rates',
        ['organization_id', 'jurisdiction_country', 'component_key', 'tax_regime', 'filing_status'],
        unique=True, postgresql_where=sa.text('organization_id IS NOT NULL'), sqlite_where=sa.text('organization_id IS NOT NULL'),
    )

    op.add_column('payroll_employees', sa.Column('w4_filing_status', sa.String(length=20), nullable=True))
    op.add_column('payroll_employees', sa.Column('w4_form_vintage', sa.String(length=10), nullable=True))
    op.add_column('payroll_employees', sa.Column('residence_state', sa.String(length=100), nullable=True))
    op.add_column('payroll_employees', sa.Column('reciprocity_certificate_on_file', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('payroll_employees', sa.Column('reciprocity_certificate_expiry', sa.Date(), nullable=True))

    op.add_column('payroll_jurisdiction_packs', sa.Column('source_document_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_payroll_jurisdiction_packs_source_document_id', 'payroll_jurisdiction_packs',
        'payroll_source_artifacts', ['source_document_id'], ['id'],
    )

    op.add_column('payroll_tax_slabs', sa.Column('filing_status', sa.String(length=20), nullable=True))

    op.add_column('payslip_items', sa.Column('federal_income_tax', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True))
    op.add_column('payslip_items', sa.Column('state_income_tax', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True))
    op.add_column('payslip_items', sa.Column('local_tax', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True))
    op.add_column('payslip_items', sa.Column('employer_sui', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True))


def downgrade() -> None:
    op.drop_column('payslip_items', 'employer_sui')
    op.drop_column('payslip_items', 'local_tax')
    op.drop_column('payslip_items', 'state_income_tax')
    op.drop_column('payslip_items', 'federal_income_tax')

    op.drop_column('payroll_tax_slabs', 'filing_status')

    op.drop_constraint('fk_payroll_jurisdiction_packs_source_document_id', 'payroll_jurisdiction_packs', type_='foreignkey')
    op.drop_column('payroll_jurisdiction_packs', 'source_document_id')

    op.drop_column('payroll_employees', 'reciprocity_certificate_expiry')
    op.drop_column('payroll_employees', 'reciprocity_certificate_on_file')
    op.drop_column('payroll_employees', 'residence_state')
    op.drop_column('payroll_employees', 'w4_form_vintage')
    op.drop_column('payroll_employees', 'w4_filing_status')

    op.drop_index('uq_contribution_rate_org_country_component', table_name='payroll_contribution_rates', postgresql_where=sa.text('organization_id IS NOT NULL'), sqlite_where=sa.text('organization_id IS NOT NULL'))
    op.create_index(
        'uq_contribution_rate_org_country_component', 'payroll_contribution_rates',
        ['organization_id', 'jurisdiction_country', 'component_key', 'tax_regime'],
        unique=True, postgresql_where=sa.text('organization_id IS NOT NULL'),
    )
    op.drop_index('uq_contribution_rate_canonical_country_state_component', table_name='payroll_contribution_rates', postgresql_where=sa.text('organization_id IS NULL'), sqlite_where=sa.text('organization_id IS NULL'))
    op.create_index(
        'uq_contribution_rate_canonical_country_state_component', 'payroll_contribution_rates',
        ['jurisdiction_country', 'jurisdiction_state', 'component_key', 'tax_regime'],
        unique=True, postgresql_where=sa.text('organization_id IS NULL'),
    )
    op.drop_column('payroll_contribution_rates', 'filing_status')
