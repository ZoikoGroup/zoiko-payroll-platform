"""add tax hierarchy v2 columns

Revision ID: dde9b427b6bf
Revises: b61caa15ac1d
Create Date: 2026-08-19 16:58:07.941421

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'dde9b427b6bf'
down_revision: Union[str, Sequence[str], None] = 'b61caa15ac1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_company_compliance',
        sa.Column('tax_hierarchy_v2_enabled', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'payslip_items',
        sa.Column('tax_version_id', sa.Integer(), nullable=True),
    )
    # NOTE: FK to payroll_hierarchy_tax_versions removed — that table does not
    # exist anywhere in migration history or app models as of this repo state.
    # Flagged upstream; re-add if/when the table is actually introduced.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'tax_version_id')
    op.drop_column('payroll_company_compliance', 'tax_hierarchy_v2_enabled')
