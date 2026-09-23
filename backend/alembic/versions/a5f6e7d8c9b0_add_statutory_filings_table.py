"""add statutory filings table

Revision ID: a5f6e7d8c9b0
Revises: 4f7c2d9a1b6e
Create Date: 2026-09-22

Filings & Remittances dashboard (Super Admin): the persisted
cross-jurisdiction filing-status model behind the page. One row per
(organization, jurisdiction, filing type, period) — see
models.StatutoryFiling's own docstring. Germany continues to derive its
wage-tax filings from GermanyElsterTransmission; this table is how every
other jurisdiction (AU GST/BAS, IN TDS/GST, …) records filing status and
how a manual override coexists with an ELSTER transmission.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5f6e7d8c9b0'
down_revision: Union[str, Sequence[str], None] = '4f7c2d9a1b6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'statutory_filings',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('jurisdiction', sa.String(10), nullable=False, index=True),
        sa.Column('filing_type', sa.String(50), nullable=False, server_default=''),
        sa.Column('period_label', sa.String(50), nullable=False, server_default=''),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='NOT_STARTED'),
        sa.Column('blocked_reason', sa.String(300), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint(
            'organization_id', 'jurisdiction', 'filing_type', 'period_label',
            name='uq_statutory_filing_per_period',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('statutory_filings')