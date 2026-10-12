"""add report template system tables

Revision ID: c4a91e7bd026
Revises: 4140bc2c394d
Create Date: 2026-09-01 00:00:00.000000

Adds the Report Template system: payroll_report_templates (Super
Admin-authored, jurisdiction-wide, versioned statutory report templates),
payroll_report_template_components and
payroll_report_template_component_fields (its component/field structure),
and payroll_generated_reports (the immutable, organization-scoped output
artifact produced when an org renders a published template against a
finalized payroll run). Purely additive — no existing table/column is
touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a91e7bd026'
down_revision: Union[str, Sequence[str], None] = '4140bc2c394d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_report_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('report_type', sa.String(length=50), nullable=False),
        sa.Column('jurisdiction_country', sa.String(length=100), nullable=False),
        sa.Column('jurisdiction_state', sa.String(length=100), nullable=True),
        sa.Column('jurisdiction_locality', sa.String(length=100), nullable=True),
        sa.Column('reporting_year', sa.String(length=20), nullable=False),
        sa.Column('version', sa.String(length=20), server_default='1.0', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='Draft', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('regulatory_authority', sa.String(length=200), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('source_references', sa.Text(), nullable=True),
        sa.Column('reconciliation_tolerance', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_report_templates.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_key', 'version', name='uq_report_template_key_version'),
    )
    op.create_index(op.f('ix_payroll_report_templates_id'), 'payroll_report_templates', ['id'], unique=False)
    op.create_index(
        'ix_report_templates_jurisdiction_year_type', 'payroll_report_templates',
        ['jurisdiction_country', 'jurisdiction_state', 'reporting_year', 'report_type'], unique=False,
    )

    op.create_table(
        'payroll_report_template_components',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_template_id', sa.Integer(), nullable=False),
        sa.Column('component_key', sa.String(length=50), nullable=False),
        sa.Column('label', sa.String(length=150), nullable=False),
        sa.Column('component_category', sa.String(length=30), server_default='standard', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['report_template_id'], ['payroll_report_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_template_id', 'component_key', name='uq_report_component_template_key'),
    )
    op.create_index(op.f('ix_payroll_report_template_components_id'), 'payroll_report_template_components', ['id'], unique=False)
    op.create_index(
        op.f('ix_payroll_report_template_components_report_template_id'),
        'payroll_report_template_components', ['report_template_id'], unique=False,
    )

    op.create_table(
        'payroll_report_template_component_fields',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('component_id', sa.Integer(), nullable=False),
        sa.Column('field_key', sa.String(length=50), nullable=False),
        sa.Column('label', sa.String(length=150), nullable=False),
        sa.Column('field_type', sa.String(length=20), nullable=False),
        sa.Column('data_source_kind', sa.String(length=20), nullable=False),
        sa.Column('source_column', sa.String(length=50), nullable=False),
        sa.Column('aggregation', sa.String(length=20), nullable=True),
        sa.Column('enum_values', sa.JSON(), nullable=True),
        sa.Column('format_hint', sa.String(length=50), nullable=True),
        sa.Column('is_required', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['component_id'], ['payroll_report_template_components.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('component_id', 'field_key', name='uq_report_field_component_key'),
    )
    op.create_index(op.f('ix_payroll_report_template_component_fields_id'), 'payroll_report_template_component_fields', ['id'], unique=False)
    op.create_index(
        op.f('ix_payroll_report_template_component_fields_component_id'),
        'payroll_report_template_component_fields', ['component_id'], unique=False,
    )

    op.create_table(
        'payroll_generated_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('report_template_id', sa.Integer(), nullable=False),
        sa.Column('template_version', sa.String(length=20), nullable=False),
        sa.Column('report_type', sa.String(length=50), nullable=False),
        sa.Column('payroll_run_id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction_country', sa.String(length=100), nullable=False),
        sa.Column('jurisdiction_state', sa.String(length=100), nullable=True),
        sa.Column('reporting_year', sa.String(length=20), nullable=False),
        sa.Column('reporting_period', sa.String(length=50), nullable=True),
        sa.Column('applicable_tax_pack_id', sa.Integer(), nullable=True),
        sa.Column('applicable_tax_pack_version', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='Generated', nullable=False),
        sa.Column('generated_by_id', sa.Integer(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('rendered_data', sa.JSON(), nullable=False),
        sa.Column('reconciliation', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['report_template_id'], ['payroll_report_templates.id']),
        sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id']),
        sa.ForeignKeyConstraint(['applicable_tax_pack_id'], ['payroll_jurisdiction_packs.id']),
        sa.ForeignKeyConstraint(['generated_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_generated_reports_id'), 'payroll_generated_reports', ['id'], unique=False)
    op.create_index(op.f('ix_payroll_generated_reports_organization_id'), 'payroll_generated_reports', ['organization_id'], unique=False)
    op.create_index(op.f('ix_payroll_generated_reports_report_template_id'), 'payroll_generated_reports', ['report_template_id'], unique=False)
    op.create_index(op.f('ix_payroll_generated_reports_payroll_run_id'), 'payroll_generated_reports', ['payroll_run_id'], unique=False)
    op.create_index(
        'ix_generated_reports_org_run', 'payroll_generated_reports', ['organization_id', 'payroll_run_id'], unique=False,
    )
    op.create_index(
        'ix_generated_reports_template', 'payroll_generated_reports', ['report_template_id'], unique=False,
    )
    op.create_index(
        'uq_generated_report_org_run_template_active', 'payroll_generated_reports',
        ['organization_id', 'payroll_run_id', 'report_template_id'],
        unique=True, postgresql_where=sa.text("status = 'Generated'"), sqlite_where=sa.text("status = 'Generated'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_generated_report_org_run_template_active', table_name='payroll_generated_reports',
        postgresql_where=sa.text("status = 'Generated'"), sqlite_where=sa.text("status = 'Generated'"),
    )
    op.drop_index('ix_generated_reports_template', table_name='payroll_generated_reports')
    op.drop_index('ix_generated_reports_org_run', table_name='payroll_generated_reports')
    op.drop_index(op.f('ix_payroll_generated_reports_payroll_run_id'), table_name='payroll_generated_reports')
    op.drop_index(op.f('ix_payroll_generated_reports_report_template_id'), table_name='payroll_generated_reports')
    op.drop_index(op.f('ix_payroll_generated_reports_organization_id'), table_name='payroll_generated_reports')
    op.drop_index(op.f('ix_payroll_generated_reports_id'), table_name='payroll_generated_reports')
    op.drop_table('payroll_generated_reports')

    op.drop_index(op.f('ix_payroll_report_template_component_fields_component_id'), table_name='payroll_report_template_component_fields')
    op.drop_index(op.f('ix_payroll_report_template_component_fields_id'), table_name='payroll_report_template_component_fields')
    op.drop_table('payroll_report_template_component_fields')

    op.drop_index(op.f('ix_payroll_report_template_components_report_template_id'), table_name='payroll_report_template_components')
    op.drop_index(op.f('ix_payroll_report_template_components_id'), table_name='payroll_report_template_components')
    op.drop_table('payroll_report_template_components')

    op.drop_index('ix_report_templates_jurisdiction_year_type', table_name='payroll_report_templates')
    op.drop_index(op.f('ix_payroll_report_templates_id'), table_name='payroll_report_templates')
    op.drop_table('payroll_report_templates')
