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

Upgrade gives the table created on the other branch - payroll_mx_vacation_records
- the policy d7f9b1c3e5a6 derives for it (a WORKER table, strategy "org"), on
THAT table only and only when it has none yet. The "unset mode" stored by
d7f9b1c3e5a6 is left as it is.

Corrected 2026-10-21 before it ever applied anywhere (production deploy
39561229230 failed and rolled back): it used to re-run apply_rls() over every
tenant and worker table, i.e. ALTER TABLE "users" ENABLE ROW LEVEL SECURITY
and DROP / CREATE POLICY on each - an ACCESS EXCLUSIVE lock on every hot table
for the whole migration transaction. Against the live database that timed out
on "users" (lock_timeout 5s, set by a6d2f9c4b8e1 for the transaction). Every
table that existed when d7f9b1c3e5a6 / e1a3c5e7f9b2 ran already has its policy.
Proved on PostgreSQL 17 with a live reader on "users":
tests/test_privacy_mexico_merge_migration.py.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

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


# Tables created on the Mexico branch after f5c1a8d3e9b2 -> d7f9 classify() strategy.
MERGED_IN = {"payroll_mx_vacation_records": "org"}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    rls = _rls_module()
    for table, strategy in MERGED_IN.items():
        if bind.execute(sa.text("SELECT to_regclass(:t)"), {"t": table}).scalar() is None:
            continue
        if bind.execute(sa.text("SELECT 1 FROM pg_policies WHERE tablename = :t AND policyname = :p"),
                        {"t": table, "p": rls.POLICY}).first() is not None:
            continue                                    # d7f9b1c3e5a6 ran after it: already protected
        predicate = rls._worker_predicate(strategy)
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    # Policies on the merged-in tables are dropped with those tables by their
    # own migration's downgrade; nothing to undo here.
    pass
