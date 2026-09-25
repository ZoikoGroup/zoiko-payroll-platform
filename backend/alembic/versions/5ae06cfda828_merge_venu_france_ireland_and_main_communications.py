"""merge venu (PR certificates / France / Ireland) and main (communications / SGP cleanup)

Revision ID: 5ae06cfda828
Revises: b1c2d3e4f5a6, f0b1c2d3e4f5

The two branches forked at ``d4e5f6a7c8b9`` (auth_email_events):

  venu: 8596179ade04 (PR withholding certificates) -> d2e3c4b5a6f7 (France
        compliance tables) -> 74aeb450aeee (France establishments + editable
        fields) -> b1c2d3e4f5a6 (Ireland payroll tables)
  main: e7f1a2b3c4d5 (communication_events) -> f0b1c2d3e4f5 (drop orphan SGP
        columns)

Pure merge point — no schema change of its own. Note for already-running
databases: 8596179ade04 and d2e3c4b5a6f7 skip tables that already exist
(an environment on main's e7f1a2b3c4d5 can already hold them), so upgrading
such a database to this head is safe.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '5ae06cfda828'
down_revision: Union[str, Sequence[str], None] = ('b1c2d3e4f5a6', 'f0b1c2d3e4f5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge point — nothing to apply."""


def downgrade() -> None:
    """Merge point — nothing to revert."""
