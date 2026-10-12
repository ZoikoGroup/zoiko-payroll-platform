"""ensure communication_events table exists

Revision ID: 4b13831d574b
Revises: 5ae06cfda828

The shared database was recorded at e7f1a2b3c4d5 (create_communication_events_
table) without the table actually existing — scripts/check_schema_drift.py
reported "Model table 'communication_events' has no matching DB table" after
upgrading to 5ae06cfda828. Alembic will never re-run a revision it considers
applied, so this follow-up re-executes e7f1a2b3c4d5's own upgrade() — which
is already idempotent (it returns immediately when the table exists) — so
there is exactly ONE definition of the table and this is a no-op everywhere
the table is already present.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '4b13831d574b'
down_revision: Union[str, Sequence[str], None] = '5ae06cfda828'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _communication_events_migration():
    path = Path(__file__).with_name("e7f1a2b3c4d5_create_communication_events_table.py")
    spec = importlib.util.spec_from_file_location("_e7f1a2b3c4d5_communication_events", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    """Create communication_events (and its indexes) only if missing."""
    _communication_events_migration().upgrade()


def downgrade() -> None:
    """Nothing to undo: e7f1a2b3c4d5's own downgrade owns the table."""
