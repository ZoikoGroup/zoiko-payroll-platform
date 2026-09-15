"""add payroll_salary_tds_declarations, payroll_salary_tds_claims, payroll_employee_benefit_valuations tables

Revision ID: 581578d8b7e3
Revises: 4a56cbfba30a
Create Date: 2026-09-10 01:00:00.000000

ZP-TAX-IN-2026-27-001 §6.2 Forms 122 (prior-employer salary/other-income/
house-property-loss declaration), 124 (Chapter VIII claims/evidence), and
123 (employer-recorded perquisite valuation) — gap-closure Phase E.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '581578d8b7e3'
down_revision: Union[str, Sequence[str], None] = '4a56cbfba30a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_salary_tds_declarations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('tax_year', sa.String(length=20), nullable=False),
        sa.Column('prior_employer_salary', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('prior_employer_tds_deducted', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('other_income', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('house_property_loss', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['payroll_employees.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_salary_tds_declarations_id'), 'payroll_salary_tds_declarations', ['id'], unique=False)
    op.create_index(op.f('ix_payroll_salary_tds_declarations_employee_id'), 'payroll_salary_tds_declarations', ['employee_id'], unique=False)
    op.create_index(op.f('ix_payroll_salary_tds_declarations_organization_id'), 'payroll_salary_tds_declarations', ['organization_id'], unique=False)

    op.create_table(
        'payroll_salary_tds_claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('tax_year', sa.String(length=20), nullable=False),
        sa.Column('claim_type', sa.String(length=50), nullable=False),
        sa.Column('claimed_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('evidence_reference', sa.String(length=300), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
        sa.Column('rejection_reason', sa.String(length=300), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['payroll_employees.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_salary_tds_claims_id'), 'payroll_salary_tds_claims', ['id'], unique=False)
    op.create_index(op.f('ix_payroll_salary_tds_claims_employee_id'), 'payroll_salary_tds_claims', ['employee_id'], unique=False)
    op.create_index(op.f('ix_payroll_salary_tds_claims_organization_id'), 'payroll_salary_tds_claims', ['organization_id'], unique=False)

    op.create_table(
        'payroll_employee_benefit_valuations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('tax_year', sa.String(length=20), nullable=False),
        sa.Column('benefit_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('taxable_value', sa.Numeric(14, 2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['payroll_employees.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_employee_benefit_valuations_id'), 'payroll_employee_benefit_valuations', ['id'], unique=False)
    op.create_index(op.f('ix_payroll_employee_benefit_valuations_employee_id'), 'payroll_employee_benefit_valuations', ['employee_id'], unique=False)
    op.create_index(op.f('ix_payroll_employee_benefit_valuations_organization_id'), 'payroll_employee_benefit_valuations', ['organization_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_payroll_employee_benefit_valuations_organization_id'), table_name='payroll_employee_benefit_valuations')
    op.drop_index(op.f('ix_payroll_employee_benefit_valuations_employee_id'), table_name='payroll_employee_benefit_valuations')
    op.drop_index(op.f('ix_payroll_employee_benefit_valuations_id'), table_name='payroll_employee_benefit_valuations')
    op.drop_table('payroll_employee_benefit_valuations')

    op.drop_index(op.f('ix_payroll_salary_tds_claims_organization_id'), table_name='payroll_salary_tds_claims')
    op.drop_index(op.f('ix_payroll_salary_tds_claims_employee_id'), table_name='payroll_salary_tds_claims')
    op.drop_index(op.f('ix_payroll_salary_tds_claims_id'), table_name='payroll_salary_tds_claims')
    op.drop_table('payroll_salary_tds_claims')

    op.drop_index(op.f('ix_payroll_salary_tds_declarations_organization_id'), table_name='payroll_salary_tds_declarations')
    op.drop_index(op.f('ix_payroll_salary_tds_declarations_employee_id'), table_name='payroll_salary_tds_declarations')
    op.drop_index(op.f('ix_payroll_salary_tds_declarations_id'), table_name='payroll_salary_tds_declarations')
    op.drop_table('payroll_salary_tds_declarations')
