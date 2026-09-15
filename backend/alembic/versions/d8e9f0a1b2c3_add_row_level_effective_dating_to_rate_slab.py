"""add row-level effective_from/effective_to to contribution rates and tax slabs

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-09 01:00:00.000000

ZP-TAX-UK-2026-27-001 §3.2 gap-closure Part 1A: a JurisdictionPack has one
effective window for everything in it, but some rule families (National
Minimum Wage, Advisory Fuel Rates) need their OWN effective date distinct
from the pack's own tax-year window. Adds nullable effective_from/
effective_to directly to payroll_contribution_rates and payroll_tax_slabs
— NULL (every existing row) means "governed entirely by the parent pack's
window," so this is purely additive. Enforced only by tax_resolver.py's
canonical-pack resolution path (resolve_tax_configuration), which already
takes a payroll date; the legacy per-org get_contribution_rates/
get_tax_slabs path has no date parameter at all and does not consult
these columns — a deliberately scoped first pass.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_contribution_rates', sa.Column('effective_from', sa.Date(), nullable=True))
    op.add_column('payroll_contribution_rates', sa.Column('effective_to', sa.Date(), nullable=True))
    op.add_column('payroll_tax_slabs', sa.Column('effective_from', sa.Date(), nullable=True))
    op.add_column('payroll_tax_slabs', sa.Column('effective_to', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_tax_slabs', 'effective_to')
    op.drop_column('payroll_tax_slabs', 'effective_from')
    op.drop_column('payroll_contribution_rates', 'effective_to')
    op.drop_column('payroll_contribution_rates', 'effective_from')
