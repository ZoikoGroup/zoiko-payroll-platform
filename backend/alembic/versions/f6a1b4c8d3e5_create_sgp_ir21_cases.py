"""create sgp_ir21_cases

Revision ID: f6a1b4c8d3e5
Revises: e5f9a3b7c2d4
Create Date: 2026-09-24

Singapore IR21 tax-clearance hold / clearance / release workflow (approved
Phase 2) — one employee-level case table (see models.SgpIr21Case for why
StatutoryFiling cannot hold it). Additive only: no existing table changes.
Idempotent (inspector-guarded), same shape as 76e050fd5ffd.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a1b4c8d3e5'
down_revision: Union[str, Sequence[str], None] = 'e5f9a3b7c2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "sgp_ir21_cases"


def upgrade() -> None:
    """Upgrade schema."""
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "sgp_ir21_cases",  # literal: tests/test_model_tables_have_migrations.py
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False),
        sa.Column('final_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
        sa.Column('trigger_type', sa.String(length=20), nullable=False),
        sa.Column('trigger_date', sa.Date(), nullable=False),
        sa.Column('aware_date', sa.Date(), nullable=False),
        sa.Column('file_by_date', sa.Date(), nullable=False),
        sa.Column('filed_date', sa.Date(), nullable=True),
        sa.Column('filing_reference', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='DRAFT'),
        sa.Column('held_amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('directive_date', sa.Date(), nullable=True),
        sa.Column('directive_reference', sa.String(length=100), nullable=True),
        sa.Column('directive_tax_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('released_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exception_reason', sa.Text(), nullable=True),
        sa.Column('prepared_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('organization_id', 'employee_id', 'trigger_date', name='uq_sgp_ir21_case_trigger'),
    )
    op.create_index(op.f('ix_sgp_ir21_cases_id'), _TABLE, ['id'], unique=False)
    op.create_index(op.f('ix_sgp_ir21_cases_organization_id'), _TABLE, ['organization_id'], unique=False)
    op.create_index(op.f('ix_sgp_ir21_cases_employee_id'), _TABLE, ['employee_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index(op.f('ix_sgp_ir21_cases_employee_id'), table_name=_TABLE)
    op.drop_index(op.f('ix_sgp_ir21_cases_organization_id'), table_name=_TABLE)
    op.drop_index(op.f('ix_sgp_ir21_cases_id'), table_name=_TABLE)
    op.drop_table(_TABLE)
