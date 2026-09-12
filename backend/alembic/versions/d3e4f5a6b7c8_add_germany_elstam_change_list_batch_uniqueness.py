"""add germany elstam change list batch org+reference uniqueness

Revision ID: d3e4f5a6b7c8
Revises: f61cb4b650f4
Create Date: 2026-09-09 00:00:00.000000

Phase 8BE — genuine engineering gap closure. `GermanyElstamChangeListBatch`
(payroll_germany_elstam_change_list_batches) had no uniqueness guard on
(organization_id, batch_reference): resubmitting the same change-list batch
reference for the same organization silently created a second, duplicate
row, with no dedup check anywhere on the create path. Purely additive —
adds one unique constraint, no column/table changes, no data migration, no
existing row can violate it today (this phase's own forensic audit found
zero rows in any environment for this table). Fails loudly if a real
environment happens to already carry a duplicate pair, which is the
intended, safe, fail-closed behavior for this fix.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'f61cb4b650f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        'uq_germany_elstam_change_list_batch_org_ref',
        'payroll_germany_elstam_change_list_batches',
        ['organization_id', 'batch_reference'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'uq_germany_elstam_change_list_batch_org_ref',
        'payroll_germany_elstam_change_list_batches',
        type_='unique',
    )
