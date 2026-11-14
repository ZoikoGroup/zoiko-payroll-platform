"""merge the Belgium and Malaysia migration chains

Revision ID: cf348b09db2b
Revises: 8a1f5ef9fa5d, f793f6074257
Create Date: 2026-11-14

Both chains grew from the payslip-templates revision f3a9c1d7e2b4:
Belgium on main (1d76678ef1a1 -> 2943a0490b5b -> 8a1f5ef9fa5d, PR #161) and
Malaysia on venu (13574b996ccf -> 5f314f975ac3 -> efdc07f97eb5 ->
f793f6074257). Neither chain is edited: this revision only joins the two
heads so the graph has a single head again, whichever chain a database has
already applied. No schema change.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "cf348b09db2b"
down_revision: Union[str, Sequence[str], None] = ("8a1f5ef9fa5d", "f793f6074257")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join the two heads; nothing to change in the schema."""
    pass


def downgrade() -> None:
    """Split back into the two heads; nothing to change in the schema."""
    pass
