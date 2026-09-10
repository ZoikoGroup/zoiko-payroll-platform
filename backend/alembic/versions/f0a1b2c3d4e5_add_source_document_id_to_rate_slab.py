"""add source_document_id to contribution rates and tax slabs

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-09-09 03:00:00.000000

ZP-TAX-UK-2026-27-001 §4.2 gap-closure Part 1B: evidence (SourceArtifact)
could previously only be linked to a whole JurisdictionPack (or a few
US-specific side tables) — never to one individual rate/slab row, even
though §4.2 requires an evidence record per PUBLISHED RULE. Adds a
nullable FK to the existing payroll_source_artifacts table directly on
payroll_contribution_rates and payroll_tax_slabs. NULL (every existing
row) means "no row-specific evidence recorded" — purely additive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e9f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_contribution_rates', sa.Column('source_document_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_contribution_rate_source_document', 'payroll_contribution_rates', 'payroll_source_artifacts',
        ['source_document_id'], ['id'],
    )
    op.add_column('payroll_tax_slabs', sa.Column('source_document_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_tax_slab_source_document', 'payroll_tax_slabs', 'payroll_source_artifacts',
        ['source_document_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_tax_slab_source_document', 'payroll_tax_slabs', type_='foreignkey')
    op.drop_column('payroll_tax_slabs', 'source_document_id')
    op.drop_constraint('fk_contribution_rate_source_document', 'payroll_contribution_rates', type_='foreignkey')
    op.drop_column('payroll_contribution_rates', 'source_document_id')
