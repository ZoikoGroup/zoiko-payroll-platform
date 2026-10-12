"""create sgp_ir8a_modifications

Revision ID: 445abd6a9083
Revises: b8e3d5f2a9c7
Create Date: 2026-09-28

Singapore G3 (Phase 6.8): IR8A Revision / Amendment of an IRAS-acknowledged
original extract — IRAS myTax Portal "Modify previously submitted data"
(Quick Guide, 15 Sep 2025). One additive, Singapore-only table linking a
modification's own SG_IR8A extract (report_id) to the original it modifies
(base_report_id), with the frozen previous / resulting positions and the
amendment delta; payroll_generated_reports is unchanged. See
models.SgpIr8aModification and docs/SINGAPORE_G3_IR8A_AMENDMENT_AND_AIS_DECISION.md.

Parent: b8e3d5f2a9c7 — the tip of the Singapore chain. (Phase 6.8 had
parked this revision on a release-line merge 6247da96d605 that no longer
exists: origin/main moved on, so the Singapore chain now carries its own
table and one merge revision joins it to main's head at merge time.)
Idempotent (inspector-guarded), same shape as b8e3d5f2a9c7.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '445abd6a9083'
down_revision: Union[str, Sequence[str], None] = 'b8e3d5f2a9c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "sgp_ir8a_modifications"


def upgrade() -> None:
    """Upgrade schema."""
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "sgp_ir8a_modifications",  # literal: tests/test_model_tables_have_migrations.py
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('reporting_year', sa.String(length=20), nullable=False),
        sa.Column('base_report_id', sa.Integer(), sa.ForeignKey('payroll_generated_reports.id'), nullable=False),
        sa.Column('report_id', sa.Integer(), sa.ForeignKey('payroll_generated_reports.id'), nullable=False),
        sa.Column('method', sa.String(length=12), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('previous_position', sa.JSON(), nullable=False),
        sa.Column('resulting_position', sa.JSON(), nullable=False),
        sa.Column('delta', sa.JSON(), nullable=True),
        sa.Column('prepared_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('recorded_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint('base_report_id', 'sequence', name='uq_sgp_ir8a_modification_sequence'),
        sa.UniqueConstraint('report_id', name='uq_sgp_ir8a_modification_report'),
    )
    op.create_index(op.f('ix_sgp_ir8a_modifications_id'), _TABLE, ['id'], unique=False)
    op.create_index(op.f('ix_sgp_ir8a_modifications_organization_id'), _TABLE, ['organization_id'], unique=False)
    op.create_index(op.f('ix_sgp_ir8a_modifications_base_report_id'), _TABLE, ['base_report_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index(op.f('ix_sgp_ir8a_modifications_base_report_id'), table_name=_TABLE)
    op.drop_index(op.f('ix_sgp_ir8a_modifications_organization_id'), table_name=_TABLE)
    op.drop_index(op.f('ix_sgp_ir8a_modifications_id'), table_name=_TABLE)
    op.drop_table(_TABLE)
