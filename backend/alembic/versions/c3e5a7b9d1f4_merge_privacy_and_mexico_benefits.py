"""merge ZP-PRIV chain (e1a3c5e7f9b2) with Mexico benefits M8 (a6d2f9c4b8e1)

Revision ID: c3e5a7b9d1f4
Revises: a6d2f9c4b8e1, e1a3c5e7f9b2
Create Date: 2026-10-19

Both chains grow from f5c1a8d3e9b2 (Mexico corrections M7):

  f5c1a8d3e9b2 -> a6d2f9c4b8e1 (Mexico benefits M8, main)
  f5c1a8d3e9b2 -> a7c3e91f2b60 .. e1a3c5e7f9b2 (ZP-PRIV, rugvedh; already
                  applied to the shared database)

A merge revision (rather than re-parenting the ZP-PRIV chain onto M8) keeps
every database correct: one at e1a3c5e7f9b2 runs only M8 and this merge; one
at a6d2f9c4b8e1 runs only the ZP-PRIV chain and this merge.

Upgrade re-applies row-level security (idempotent) so tables created by the
other branch - here payroll_mx_vacation_records - get their policy too. The
"unset mode" stored by d7f9b1c3e5a6 is left as it is.
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "c3e5a7b9d1f4"
down_revision = ("a6d2f9c4b8e1", "e1a3c5e7f9b2")
branch_labels = None
depends_on = None


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _rls_module().apply_rls(bind)


def downgrade() -> None:
    # Policies on the merged-in tables are dropped with those tables by their
    # own migration's downgrade; nothing to undo here.
    pass
