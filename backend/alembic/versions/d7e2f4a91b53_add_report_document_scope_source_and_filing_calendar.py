"""add report document_scope/source_document_id and filing calendar table

Revision ID: d7e2f4a91b53
Revises: c4a91e7bd026
Create Date: 2026-09-01 12:00:00.000000

Additive only: two new nullable/defaulted columns on
payroll_report_templates (document_scope, source_document_id — the latter
reusing the existing payroll_source_artifacts table, no new evidence
system) plus a brand-new payroll_statutory_filing_calendar table. No
existing column/table semantics change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e2f4a91b53'
down_revision: Union[str, Sequence[str], None] = 'c4a91e7bd026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_report_templates',
        sa.Column('document_scope', sa.String(length=20), server_default='AGGREGATE', nullable=False),
    )
    op.add_column(
        'payroll_report_templates',
        sa.Column('source_document_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_payroll_report_templates_source_document_id', 'payroll_report_templates',
        'payroll_source_artifacts', ['source_document_id'], ['id'],
    )

    op.create_table(
        'payroll_statutory_filing_calendar',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction_country', sa.String(length=100), nullable=False),
        sa.Column('jurisdiction_state', sa.String(length=100), nullable=True),
        sa.Column('report_type', sa.String(length=50), nullable=False),
        sa.Column('reporting_year', sa.String(length=20), nullable=False),
        sa.Column('period_key', sa.String(length=20), nullable=False),
        sa.Column('period_label', sa.String(length=100), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='Draft', nullable=False),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['source_document_id'], ['payroll_source_artifacts.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_statutory_filing_calendar.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_statutory_filing_calendar_id'), 'payroll_statutory_filing_calendar', ['id'], unique=False)
    op.create_index(
        'ix_filing_calendar_lookup', 'payroll_statutory_filing_calendar',
        ['jurisdiction_country', 'jurisdiction_state', 'report_type', 'reporting_year'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_filing_calendar_lookup', table_name='payroll_statutory_filing_calendar')
    op.drop_index(op.f('ix_payroll_statutory_filing_calendar_id'), table_name='payroll_statutory_filing_calendar')
    op.drop_table('payroll_statutory_filing_calendar')

    op.drop_constraint('fk_payroll_report_templates_source_document_id', 'payroll_report_templates', type_='foreignkey')
    op.drop_column('payroll_report_templates', 'source_document_id')
    op.drop_column('payroll_report_templates', 'document_scope')
