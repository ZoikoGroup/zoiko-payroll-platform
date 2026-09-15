"""add employee statutory profile table

Revision ID: 3d05d138d022
Revises: d7e2f4a91b53
Create Date: 2026-09-02 17:00:00.000000

Additive only: one brand-new table, payroll_employee_statutory_profiles —
an effective-dated history of one employee's jurisdiction-specific
statutory facts (Germany tax class/church tax/care-insurance status/etc.
for now; India/UK/US continue to use PayrollEmployee's existing mutable
columns unchanged). No existing table/column changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d05d138d022'
down_revision: Union[str, Sequence[str], None] = 'd7e2f4a91b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_employee_statutory_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('country_code', sa.String(length=2), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('de_tax_class', sa.String(length=4), nullable=True),
        sa.Column('de_factor', sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column('de_church_tax_liable', sa.Boolean(), nullable=True),
        sa.Column('de_church_tax_land', sa.String(length=6), nullable=True),
        sa.Column('de_child_count', sa.Integer(), nullable=True),
        sa.Column('de_childless', sa.Boolean(), nullable=True),
        sa.Column('de_saxony', sa.Boolean(), nullable=True),
        sa.Column('de_health_insurance_status', sa.String(length=10), nullable=True),
        sa.Column('de_health_fund_code', sa.String(length=50), nullable=True),
        sa.Column('de_pension_insurance_exempt', sa.Boolean(), nullable=True),
        sa.Column('de_unemployment_insurance_exempt', sa.Boolean(), nullable=True),
        sa.Column('de_employment_classification', sa.String(length=10), nullable=True),
        sa.Column('de_elstam_source', sa.String(length=20), nullable=True),
        sa.Column('de_elstam_fallback_reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['payroll_employees.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_employee_statutory_profiles_id'),
        'payroll_employee_statutory_profiles', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_employee_statutory_profiles_employee_id'),
        'payroll_employee_statutory_profiles', ['employee_id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_employee_statutory_profiles_organization_id'),
        'payroll_employee_statutory_profiles', ['organization_id'], unique=False,
    )
    op.create_index(
        'ix_statutory_profile_employee_period', 'payroll_employee_statutory_profiles',
        ['employee_id', 'effective_from'], unique=False,
    )
    op.create_index(
        'ix_statutory_profile_org', 'payroll_employee_statutory_profiles',
        ['organization_id'], unique=False,
    )
    op.create_index(
        'uq_statutory_profile_one_open_per_employee', 'payroll_employee_statutory_profiles',
        ['employee_id'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_statutory_profile_one_open_per_employee', table_name='payroll_employee_statutory_profiles')
    op.drop_index('ix_statutory_profile_org', table_name='payroll_employee_statutory_profiles')
    op.drop_index('ix_statutory_profile_employee_period', table_name='payroll_employee_statutory_profiles')
    op.drop_index(op.f('ix_payroll_employee_statutory_profiles_organization_id'), table_name='payroll_employee_statutory_profiles')
    op.drop_index(op.f('ix_payroll_employee_statutory_profiles_employee_id'), table_name='payroll_employee_statutory_profiles')
    op.drop_index(op.f('ix_payroll_employee_statutory_profiles_id'), table_name='payroll_employee_statutory_profiles')
    op.drop_table('payroll_employee_statutory_profiles')
