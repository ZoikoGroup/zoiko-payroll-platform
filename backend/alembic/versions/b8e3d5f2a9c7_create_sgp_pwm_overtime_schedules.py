"""create sgp_pwm_overtime_schedules

Revision ID: b8e3d5f2a9c7
Revises: a7c2e9f4b1d6
Create Date: 2026-09-25

Singapore PWM overtime gross requirements (Phase 5.5, SG-018; OPTION A
approved 2026-09-25). MOM publishes the "Total PWM Gross Wage Requirement"
for 0–72 overtime hours per month as tables (retail, food services,
Occupational PW) with no formula — 6,132 authoritative cells. Stored in
this dedicated, tenant-independent, effective-dated table instead of pack
ContributionRate rows, because every pack row is copied into each
payslip's tax_rule_snapshot; these compliance-only rows must not be.
One additive table, no change to any existing table. Idempotent
(inspector-guarded), same shape as f6a1b4c8d3e5.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e3d5f2a9c7'
down_revision: Union[str, Sequence[str], None] = 'a7c2e9f4b1d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'sgp_pwm_overtime_schedules'


def upgrade() -> None:
    """Upgrade schema."""
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "sgp_pwm_overtime_schedules",  # literal: tests/test_model_tables_have_migrations.py
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('jurisdiction_country', sa.String(length=10), nullable=False, server_default='SG'),
        sa.Column('sector', sa.String(length=30), nullable=False),
        sa.Column('occupation_group', sa.String(length=30), nullable=False),
        sa.Column('job_level', sa.String(length=40), nullable=False),
        sa.Column('role_label', sa.String(length=120), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('overtime_hours', sa.Integer(), nullable=False),
        sa.Column('required_gross', sa.Numeric(12, 2), nullable=False),
        sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint('jurisdiction_country', 'sector', 'occupation_group', 'job_level', 'effective_from',
                            'overtime_hours', 'source_document_id', name='uq_sgp_pwm_ot_schedule_row'),
    )
    op.create_index(op.f('ix_sgp_pwm_overtime_schedules_id'), _TABLE, ['id'], unique=False)
    op.create_index('ix_sgp_pwm_ot_lookup', _TABLE, ['sector', 'occupation_group', 'job_level', 'effective_from'],
                    unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index('ix_sgp_pwm_ot_lookup', table_name=_TABLE)
    op.drop_index(op.f('ix_sgp_pwm_overtime_schedules_id'), table_name=_TABLE)
    op.drop_table(_TABLE)
