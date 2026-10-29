"""
scripts/drift_pending_filter.py
-------------------------------
Used ONLY by scripts/deploy_migrate.sh in its orphan-revision self-heal.

That path re-stamps the database to the deepest revision already reflected in
the schema and then runs `alembic upgrade head`. Before stamping it requires
the live schema to match the models (scripts.check_schema_drift) — but the
models already include what the PENDING migrations (after the stamp point, up
to head) are about to create, so a deploy that brings a new table or column
could never self-heal (2026-10-19, PR #112: the new Mexico table
payroll_mx_vacation_records was "missing" and the script refused).

This filter reads the drift report on stdin and prints only the problems the
pending migrations do NOT explain:

  explained   "Model table 'X' has no matching DB table."  — X is created by a
              pending migration (op.create_table)
              "T: model has columns not in the DB: [...]"  — every listed
              column is added to T by a pending migration (op.add_column)
  never       "T: DB has columns not on the model: [...]"  — something changed
              the schema outside this repository; always unexplained

Read-only: it inspects migration sources, never the database. Empty output =
every problem is explained by the migrations about to run.

Usage: python -m scripts.drift_pending_filter <stamp_revision>  < drift_report
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TABLE_MISSING = re.compile(r"Model table '(\w+)' has no matching DB table\.")
_MODEL_ONLY = re.compile(r"(\w+): model has columns not in the DB: \[(.*)\]")
_CREATE_TABLE = re.compile(r"op\.create_table\s*\(\s*['\"](\w+)['\"]")
_ADD_COLUMN = re.compile(r"op\.add_column\s*\(\s*['\"](\w+)['\"].*?sa\.Column\s*\(\s*['\"](\w+)['\"]", re.S)
_BATCH = re.compile(r"op\.batch_alter_table\s*\(\s*['\"](\w+)['\"][^)]*\)\s+as\s+(\w+)")
_UPGRADE = re.compile(r"^def upgrade\b.*?(?=^def |\Z)", re.S | re.M)


def _upgrade_body(src: str) -> str:
    """Only what upgrade() does counts (a downgrade may re-add a column)."""
    found = _UPGRADE.search(src)
    return found.group(0) if found else ""


def _added_columns(src: str) -> list:
    """(table, column) added by op.add_column or inside a batch_alter_table block."""
    out = list(_ADD_COLUMN.findall(src))
    marks = list(_BATCH.finditer(src))
    for i, m in enumerate(marks):
        block = src[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(src)]
        alias = re.escape(m.group(2))
        out += [(m.group(1), col) for col in
                re.findall(alias + r"\.add_column\s*\(\s*sa\.Column\s*\(\s*['\"](\w+)['\"]", block)]
    return out


def pending_revisions(stamp_rev: str, alembic_ini: str = "alembic.ini") -> list:
    """Revisions after `stamp_rev` up to the single head, newest first."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(alembic_ini))
    heads = script.get_heads()
    if len(heads) != 1:
        raise SystemExit(f"Expected exactly 1 head, found {len(heads)}: {heads}")
    # Every ancestor of the head that the stamp does not already include: across
    # a merge revision this also covers the OTHER branch (a database at one side
    # of the merge runs the other side too), which a stamp -> head walk misses.
    done = set() if stamp_rev == "base" else {r.revision for r in script.iterate_revisions(stamp_rev, "base")}
    return [rev for rev in script.walk_revisions(base="base", head=heads[0]) if rev.revision not in done]


def pending_objects(stamp_rev: str, alembic_ini: str = "alembic.ini") -> tuple:
    """(tables, {table: columns}) the pending migrations create / add."""
    tables, columns = set(), {}
    for rev in pending_revisions(stamp_rev, alembic_ini):
        src = _upgrade_body(Path(rev.module.__file__).read_text(encoding="utf-8"))
        tables.update(_CREATE_TABLE.findall(src))
        for table, column in _added_columns(src):
            columns.setdefault(table, set()).add(column)
    return tables, columns


def unexplained(drift_report: str, tables: set, columns: dict) -> list:
    """The drift problems the pending migrations do not explain."""
    out = []
    for raw in drift_report.splitlines():
        line = raw.strip().lstrip("- ").strip()
        if not line or line.startswith("Schema drift detected") or line.startswith("No schema drift"):
            continue
        missing = _TABLE_MISSING.fullmatch(line)
        if missing and missing.group(1) in tables:
            continue
        model_only = _MODEL_ONLY.fullmatch(line)
        if model_only:
            listed = {c.strip().strip("'\"") for c in model_only.group(2).split(",") if c.strip()}
            if listed and listed <= columns.get(model_only.group(1), set()):
                continue
        out.append(line)
    return out


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.drift_pending_filter <stamp_revision>", file=sys.stderr)
        return 2
    tables, columns = pending_objects(argv[1])
    for line in unexplained(sys.stdin.read(), tables, columns):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
