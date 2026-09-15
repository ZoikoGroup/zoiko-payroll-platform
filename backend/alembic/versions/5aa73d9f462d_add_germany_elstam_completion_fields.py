"""add germany elstam completion fields

Revision ID: 5aa73d9f462d
Revises: f3a4b5c6d7e8
Create Date: 2026-09-04 00:00:00.000000

Phase 8N (docs/PHASE_8N_GERMANY_ELSTAM_COMPLETION_REPORT.md).

Additive only:

1. Ten new nullable columns on payroll_employee_statutory_profiles —
   de_zkf_override, de_jfreib, de_lzzfreib, de_jhinzu, de_lzzhinzu,
   de_pkpv, de_pkpvagz, de_main_employment, de_elstam_schema_version,
   de_elstam_import_reference. All NULL on every existing row (identical
   to the pre-8N behavior of always feeding the PAP a zero/absent value
   for these — see models.py's own field-level docstrings for the full
   citation).

2. Two new tables — payroll_germany_elstam_change_list_batches and
   payroll_germany_elstam_import_attempts — the Phase 8N ELStAM
   change-list/import-boundary architecture. Neither is populated by any
   existing code path; both start empty in every environment.

No existing column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5aa73d9f462d'
down_revision: Union[str, Sequence[str], None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_zkf_override', sa.Numeric(4, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_jfreib', sa.Numeric(10, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_lzzfreib', sa.Numeric(10, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_jhinzu', sa.Numeric(10, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_lzzhinzu', sa.Numeric(10, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_pkpv', sa.Numeric(10, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_pkpvagz', sa.Numeric(10, 2), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_main_employment', sa.Boolean(), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_elstam_schema_version', sa.String(30), nullable=True))
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_elstam_import_reference', sa.String(100), nullable=True))

    op.create_table(
        'payroll_germany_elstam_change_list_batches',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('batch_reference', sa.String(100), nullable=False),
        sa.Column('source', sa.String(50), nullable=False, server_default='MANUAL_UPLOAD'),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('scope_description', sa.Text(), nullable=True),
        sa.Column('processing_status', sa.String(20), nullable=False, server_default='RECEIVED'),
        sa.Column('validation_result', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_germany_elstam_change_list_batches_org', 'payroll_germany_elstam_change_list_batches', ['organization_id'],
    )

    op.create_table(
        'payroll_germany_elstam_import_attempts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('schema_version', sa.String(30), nullable=False),
        sa.Column('import_reference', sa.String(100), nullable=True),
        sa.Column(
            'change_list_batch_id', sa.Integer(),
            sa.ForeignKey('payroll_germany_elstam_change_list_batches.id'), nullable=True, index=True,
        ),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('validation_status', sa.String(20), nullable=False),
        sa.Column('validation_errors', sa.JSON(), nullable=True),
        sa.Column(
            'applied_statutory_profile_id', sa.Integer(),
            sa.ForeignKey('payroll_employee_statutory_profiles.id'), nullable=True,
        ),
        sa.Column('imported_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index(
        'ix_elstam_import_attempt_employee', 'payroll_germany_elstam_import_attempts', ['employee_id', 'imported_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_elstam_import_attempt_employee', table_name='payroll_germany_elstam_import_attempts')
    op.drop_table('payroll_germany_elstam_import_attempts')
    op.drop_index('ix_germany_elstam_change_list_batches_org', table_name='payroll_germany_elstam_change_list_batches')
    op.drop_table('payroll_germany_elstam_change_list_batches')

    op.drop_column('payroll_employee_statutory_profiles', 'de_elstam_import_reference')
    op.drop_column('payroll_employee_statutory_profiles', 'de_elstam_schema_version')
    op.drop_column('payroll_employee_statutory_profiles', 'de_main_employment')
    op.drop_column('payroll_employee_statutory_profiles', 'de_pkpvagz')
    op.drop_column('payroll_employee_statutory_profiles', 'de_pkpv')
    op.drop_column('payroll_employee_statutory_profiles', 'de_lzzhinzu')
    op.drop_column('payroll_employee_statutory_profiles', 'de_jhinzu')
    op.drop_column('payroll_employee_statutory_profiles', 'de_lzzfreib')
    op.drop_column('payroll_employee_statutory_profiles', 'de_jfreib')
    op.drop_column('payroll_employee_statutory_profiles', 'de_zkf_override')
