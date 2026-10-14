"""reconcile_partial_nl_schema

Repairs a database whose alembic_version says 4c5d6e7f8a9b while some of the
objects of the migrations since b08f04497195 were never created (production,
2026-10-14: the version marker was moved to 4c5d6e7f8a9b from a local
machine, but e.g. payroll_nl_company_cars / payroll_nl_absence_pay_policies /
payroll_nl_wkr_accumulators do not exist).

It replays the upgrade() of every migration from c7d3e8f1a2b4 to 4c5d6e7f8a9b
in CREATE-IF-MISSING mode: a table, column, index or unique constraint that
already exists is skipped (for an existing table, its declared columns that
are missing are added — an older draft of M8/M9 lacked idempotency_key /
prepared_by); nothing is dropped, altered or rewritten and no
data is touched (every replayed migration is purely additive). On a database
that is already complete this is a no-op. The deploy's post-migration drift
check then verifies the result against the models.

Revision ID: 08f0f142574e
Revises: 4c5d6e7f8a9b
Create Date: 2026-10-14
"""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "08f0f142574e"
down_revision: Union[str, Sequence[str], None] = "4c5d6e7f8a9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Oldest first — the migrations whose objects may be missing.
_REPLAY = (
    "c7d3e8f1a2b4", "43662178315b", "ac68f3723174", "774eeaf9b33c", "972ecd8c1dba", "1080702411b1",
    "2ad71ebff6b5", "2f905bb1c296", "8b14824fb575", "3b4e5c6d7e8f", "4c5d6e7f8a9b",
)


class _CreateIfMissing:
    """The subset of alembic `op` these migrations use, skipping what exists."""

    def __init__(self, real):
        self._op = real

    def _insp(self):
        return sa.inspect(self._op.get_bind())  # fresh inspector: sees DDL done earlier in this run

    def _has_named(self, table, name):
        insp = self._insp()
        if not insp.has_table(table):
            return False
        names = {i["name"] for i in insp.get_indexes(table)} | {u["name"] for u in insp.get_unique_constraints(table)}
        return name in names

    def create_table(self, name, *args, **kwargs):
        if not self._insp().has_table(name):
            return self._op.create_table(name, *args, **kwargs)
        # The table exists, possibly from an older draft of its migration:
        # add whichever of its declared columns are missing.
        for column in args:
            if isinstance(column, sa.Column):
                self.add_column(name, column)
        return None

    def add_column(self, table, column, **kwargs):
        if column.name in {c["name"] for c in self._insp().get_columns(table)}:
            return None
        if not column.nullable and column.server_default is None:
            rows = self._op.get_bind().execute(sa.text(f'SELECT count(*) FROM "{table}"')).scalar()
            if rows:
                raise RuntimeError(
                    f"{table}.{column.name} is NOT NULL without a default but {table} has {rows} row(s); "
                    "backfill it by hand — this migration does not invent data"
                )
        # add_column does not honour index= / unique=; create those explicitly.
        index, unique = column.index, column.unique
        column = column._copy()
        column.index = column.unique = None
        self._op.add_column(table, column, **kwargs)
        if index:
            self.create_index(f"ix_{table}_{column.name}", table, [column.name], unique=bool(unique))
        elif unique:
            self.create_unique_constraint(f"{table}_{column.name}_key", table, [column.name])
        return None

    def create_index(self, name, table, columns, **kwargs):
        if self._has_named(table, name):
            return None
        return self._op.create_index(name, table, columns, **kwargs)

    def create_unique_constraint(self, name, table, columns, **kwargs):
        if self._has_named(table, name):
            return None
        return self._op.create_unique_constraint(name, table, columns, **kwargs)

    @contextmanager
    def batch_alter_table(self, table, **kwargs):
        yield _BatchIfMissing(self, table)

    def __getattr__(self, attr):
        raise NotImplementedError(f"reconcile migration does not replay op.{attr} — only additive operations are allowed")


class _BatchIfMissing:
    def __init__(self, parent, table):
        self._parent, self._table = parent, table

    def add_column(self, column, **kwargs):
        return self._parent.add_column(self._table, column)

    def __getattr__(self, attr):
        raise NotImplementedError(f"reconcile migration does not replay batch.{attr}")


def _load(rev: str):
    path = next((Path(__file__).parent).glob(f"{rev}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_reconcile_{rev}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    proxy = _CreateIfMissing(op)
    for rev in _REPLAY:
        module = _load(rev)
        module.op = proxy  # the module did `from alembic import op`
        module.upgrade()


def downgrade() -> None:
    # Nothing to undo: whatever this created belongs to the replayed migrations.
    pass
