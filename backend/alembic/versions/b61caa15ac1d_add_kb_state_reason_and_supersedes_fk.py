"""add kb state_reason and supersedes fk

Revision ID: b61caa15ac1d
Revises: 8f3a2c9b6de1
Create Date: 2026-08-13 15:03:51.028165

Adds AssistKbItem.state_reason (reason/evidence retained for REJECTED,
WITHDRAWN, QUARANTINED and CORRECTION_REQUIRED transitions) and promotes
supersedes_item_id to a real self-referential foreign key, now that the KB
governance lifecycle actually uses both. Autogenerate against the live DB
also picked up unrelated pre-existing drift in organizations/payroll_employees/
payroll_jurisdiction_packs/payslip_items (predates this change, other
modules) — deliberately left out of this migration, same as the prior
assist-tables migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b61caa15ac1d'
down_revision: Union[str, Sequence[str], None] = '8f3a2c9b6de1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('assist_kb_items', sa.Column('state_reason', sa.Text(), nullable=True))
    op.create_foreign_key(
        'assist_kb_items_supersedes_item_id_fkey',
        'assist_kb_items', 'assist_kb_items', ['supersedes_item_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('assist_kb_items_supersedes_item_id_fkey', 'assist_kb_items', type_='foreignkey')
    op.drop_column('assist_kb_items', 'state_reason')
