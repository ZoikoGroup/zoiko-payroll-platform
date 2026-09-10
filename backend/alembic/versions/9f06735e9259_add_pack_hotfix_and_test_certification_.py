"""add pack_hotfix_activations and test_certification_runs tables

Revision ID: 9f06735e9259
Revises: bbd80be2fee1
Create Date: 2026-09-09 10:00:00.000000

Super Admin UI Part 11 (§19) gap-closure: Emergency Hotfix Mode's
retrospective-review record, and Test Certification's golden-test run
history. Two new, independent tables — no existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f06735e9259'
down_revision: Union[str, Sequence[str], None] = 'bbd80be2fee1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_pack_hotfix_activations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction_pack_id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.String(length=100), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('activated_by_id', sa.Integer(), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('reviewed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['jurisdiction_pack_id'], ['payroll_jurisdiction_packs.id']),
        sa.ForeignKeyConstraint(['activated_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payroll_pack_hotfix_activations_id', 'payroll_pack_hotfix_activations', ['id'], unique=False)
    op.create_index('ix_pack_hotfix_pack', 'payroll_pack_hotfix_activations', ['jurisdiction_pack_id'], unique=False)
    op.create_index('ix_pack_hotfix_unreviewed', 'payroll_pack_hotfix_activations', ['reviewed'], unique=False)

    op.create_table(
        'payroll_test_certification_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('triggered_by_id', sa.Integer(), nullable=True),
        sa.Column('real_case_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_cases', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('passed_cases', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_cases', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('failure_details', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['triggered_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payroll_test_certification_runs_id', 'payroll_test_certification_runs', ['id'], unique=False)
    op.create_index('ix_test_cert_run_at', 'payroll_test_certification_runs', ['run_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_test_cert_run_at', table_name='payroll_test_certification_runs')
    op.drop_index('ix_payroll_test_certification_runs_id', table_name='payroll_test_certification_runs')
    op.drop_table('payroll_test_certification_runs')

    op.drop_index('ix_pack_hotfix_unreviewed', table_name='payroll_pack_hotfix_activations')
    op.drop_index('ix_pack_hotfix_pack', table_name='payroll_pack_hotfix_activations')
    op.drop_index('ix_payroll_pack_hotfix_activations_id', table_name='payroll_pack_hotfix_activations')
    op.drop_table('payroll_pack_hotfix_activations')
