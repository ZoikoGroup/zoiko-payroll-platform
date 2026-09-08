"""add germany u1 tariff table and statutory profile field

Revision ID: a4b5c6d7e8f1
Revises: 9d2f4b6c8e1a
Create Date: 2026-09-04 00:00:00.000000

Phase 8W (docs/PHASE_8W_GERMANY_U1_TARIFF_MODEL_EXTENSION_REPORT.md).

Phase 8BK note: renamed from the original revision ID `a1b2c3d4e5f6` to
`a4b5c6d7e8f1` during the main<->nikhil merge, purely to resolve an
accidental Alembic revision-ID collision with an unrelated `main`-branch
migration (`add_payslip_items_employer_cpp2_column`) that independently
generated the same 12-hex identifier. This migration's content, table,
column, and down_revision are otherwise byte-for-byte unchanged. Verified
safe to rename via extensive read-only remote-database forensics
(Phases 8BC-8BF): this revision, and everything after it in the Germany
migration chain, has never been applied to any environment.

Additive only: new table payroll_germany_health_fund_u1_tariffs for
employer-elected U1 tariff configuration per Krankenkasse, and a new
nullable column de_u1_tariff_id on payroll_employee_statutory_profiles
for the employer's selected tariff. No existing column/table altered or
dropped. GermanyHealthFund.u1_rate_pct is retained for backward
compatibility but deprecated in production resolution.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f1'
down_revision: Union[str, Sequence[str], None] = '9d2f4b6c8e1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New table: U1 tariff options per Krankenkasse
    op.create_table(
        'payroll_germany_health_fund_u1_tariffs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('health_fund_id', sa.String(50), nullable=False),
        sa.Column('tariff_identifier', sa.String(50), nullable=False),
        sa.Column('tariff_name', sa.String(200), nullable=True),
        sa.Column('reimbursement_pct', sa.Numeric(6, 4), nullable=False),
        sa.Column('levy_rate_pct', sa.Numeric(6, 4), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('authority_source_id', sa.Integer(), sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('previous_version_id', sa.Integer(), sa.ForeignKey('payroll_germany_health_fund_u1_tariffs.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_u1_tariff_fund_tariff_period', 'payroll_germany_health_fund_u1_tariffs', ['health_fund_id', 'tariff_identifier', 'effective_from'])
    op.create_index('ix_u1_tariff_health_fund_id', 'payroll_germany_health_fund_u1_tariffs', ['health_fund_id'])
    op.create_index('ix_u1_tariff_tariff_identifier', 'payroll_germany_health_fund_u1_tariffs', ['tariff_identifier'])

    # Partial unique index: at most one open-ended row per (fund, tariff)
    op.create_index(
        'uq_u1_tariff_one_open_period',
        'payroll_germany_health_fund_u1_tariffs',
        ['health_fund_id', 'tariff_identifier'],
        unique=True,
        postgresql_where=sa.text('effective_to IS NULL'),
        sqlite_where=sa.text('effective_to IS NULL'),
    )

    # New column on EmployeeStatutoryProfile: employer's selected U1 tariff
    op.add_column('payroll_employee_statutory_profiles', sa.Column('de_u1_tariff_id', sa.String(50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employee_statutory_profiles', 'de_u1_tariff_id')
    op.drop_index('uq_u1_tariff_one_open_period', 'payroll_germany_health_fund_u1_tariffs')
    op.drop_index('ix_u1_tariff_tariff_identifier', 'payroll_germany_health_fund_u1_tariffs')
    op.drop_index('ix_u1_tariff_health_fund_id', 'payroll_germany_health_fund_u1_tariffs')
    op.drop_index('ix_u1_tariff_fund_tariff_period', 'payroll_germany_health_fund_u1_tariffs')
    op.drop_table('payroll_germany_health_fund_u1_tariffs')
