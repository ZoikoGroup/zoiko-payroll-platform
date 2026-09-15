"""add germany pv configuration table

Revision ID: b3c8d9e2f147
Revises: 5a472144d222
Create Date: 2026-09-02 21:00:00.000000

Additive only: one brand-new table, payroll_germany_pv_configurations —
child-category × Saxony-aware effective-dated PV (Long-Term Care Insurance)
rate configuration (ZP-TAX-DE-2026-001 §10). Configuration/registry only;
no PV contribution calculation, no existing table/column changes, no seed
data (the 2026 values from the spec are used only in tests/docs as
clearly-labeled fixtures, never inserted by this migration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c8d9e2f147'
down_revision: Union[str, Sequence[str], None] = '5a472144d222'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_pv_configurations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('child_category', sa.String(length=20), nullable=False),
        sa.Column('is_saxony', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('total_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('standard_employee_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('employer_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('saxony_employee_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('saxony_employer_rate_pct', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('authority_source_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['authority_source_id'], ['payroll_source_artifacts.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['payroll_germany_pv_configurations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_payroll_germany_pv_configurations_id'),
        'payroll_germany_pv_configurations', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_payroll_germany_pv_configurations_child_category'),
        'payroll_germany_pv_configurations', ['child_category'], unique=False,
    )
    op.create_index(
        'ix_pv_config_child_saxony_period',
        'payroll_germany_pv_configurations',
        ['child_category', 'is_saxony', 'effective_from'], unique=False,
    )
    op.create_index(
        'uq_pv_config_one_open_period',
        'payroll_germany_pv_configurations',
        ['child_category', 'is_saxony'], unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_pv_config_one_open_period', table_name='payroll_germany_pv_configurations')
    op.drop_index('ix_pv_config_child_saxony_period', table_name='payroll_germany_pv_configurations')
    op.drop_index(op.f('ix_payroll_germany_pv_configurations_child_category'), table_name='payroll_germany_pv_configurations')
    op.drop_index(op.f('ix_payroll_germany_pv_configurations_id'), table_name='payroll_germany_pv_configurations')
    op.drop_table('payroll_germany_pv_configurations')
