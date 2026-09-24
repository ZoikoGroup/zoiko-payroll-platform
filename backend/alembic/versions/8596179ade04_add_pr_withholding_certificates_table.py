"""add pr withholding certificates table

Revision ID: 8596179ade04
Revises: d4e5f6a7c8b9
Create Date: 2026-09-23

Puerto Rico Form 499 R-4/R-4.1 (ZP-PR-ENG-001 PR-005): an employee's own
versioned Puerto Rico withholding exemption certificate. See
models.PRWithholdingCertificate's own docstring — same immutable
create-Draft -> submit -> approve-supersedes-prior versioning convention
as models.SalaryTdsDeclaration. PR-only table; does not touch, extend, or
conflict with any other jurisdiction's schema.

Re-parented from its original down_revision ('a5f6e7d8c9b0') to
'd4e5f6a7c8b9' during the venu/main alembic-fork reconciliation
(2026-09-24): this migration and 'd4e5f6a7c8b9' (Rugvedh's
create_auth_email_events_table, merged via main PR #67) were both
independently authored on top of the same 'a5f6e7d8c9b0' base on two
diverged branches. No schema overlap between the two — this is a pure
chain re-linking, not a data or logic change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8596179ade04'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7c8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_pr_withholding_certificates',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('personal_exemption_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('dependents_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dependent_exemption_per_dependent', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('deduction_allowance_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('optional_married_computation', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('msrra_election', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('additional_withholding_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payroll_pr_withholding_certificates')
