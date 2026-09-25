#!/usr/bin/env bash
# deploy_migrate.sh
# -----------------
# Deploy-time schema migration for the backend. Alembic is the source of
# truth for schema changes.
#
#  1. Runs `alembic upgrade head` (applies any pending migrations).
#  2. Runs `python -m migrations.sync_schema` afterwards as a non-destructive
#     safety-net for columns that used to be managed via create_all during the
#     early dev days and may still lag the models.
#  3. Self-heals one specific historical failure mode: the database's
#     `alembic_version` row referencing a revision that no longer exists in
#     alembic/versions (an orphan revision authored on another branch and
#     never merged, which makes `alembic upgrade head` abort with
#     "Can't locate revision identified by '<id>'"). It only repairs that by
#     re-stamping to the current head AFTER proving the live schema already
#     matches the models (sync_schema reports no drift). If the schema still
#     lags, it aborts with instructions instead of silently skipping
#     migrations.
#
# Expected invocation: from the deployment host, inside the repo (the script
# resolves its own location and cd's into backend/ automatically).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

# --- Convenience -----------------------------------------------------------

print_diagnostics() {
  echo "  ---- alembic current ----"
  alembic current 2>&1 || true
  echo "  ---- alembic heads ----"
  alembic heads 2>&1 || true
  echo "  ---- alembic history (tail) ----"
  alembic history 2>&1 | tail -15 || true
  echo "  ---- alembic_version table ----"
  python - <<'PY' || true
from sqlalchemy import text

from app.database import engine

with engine.connect() as conn:
    rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
for row in rows:
    print("  " + row[0])
PY
}

known_revisions() {
  python - <<'PY'
import re
import glob

revisions = set()
for path in glob.glob("alembic/versions/*.py"):
    content = open(path, encoding="utf-8").read()
    match = re.search(r"revision[^=\n]*=\s*['\"]([0-9a-f]+)['\"]", content)
    if match:
        revisions.add(match.group(1))
print(" ".join(sorted(revisions)))
PY
}

schema_drift() {
  python - <<'PY'
from migrations.sync_schema import sync_schema

for column in sync_schema():
    print(column)
PY
}

check_model_drift() {
  echo "==> Checking for model/schema drift against declared SQLAlchemy models..."
  python -m scripts.check_schema_drift
}

verify_at_head() {
  echo "==> Verifying database is at the Alembic head..."

  python - <<'PY'
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.database import engine

config = Config("alembic.ini")
script = ScriptDirectory.from_config(config)

expected = set(script.get_heads())

with engine.connect() as connection:
    actual = set(
        MigrationContext.configure(connection).get_current_heads()
    )

print(f"expected heads: {sorted(expected)}")
print(f"database heads: {sorted(actual)}")

if actual != expected:
    raise SystemExit(
        "Database is not at the Alembic head: "
        f"missing={sorted(expected - actual)}, "
        f"unexpected={sorted(actual - expected)}"
    )

print("Database is at the Alembic head.")
PY
}

# --- Migration steps -------------------------------------------------------

echo "==> alembic upgrade head"
if upgrade_output="$(alembic upgrade head 2>&1)"; then
  printf '%s\n' "$upgrade_output"
  check_model_drift
  echo "==> Up to date. Running sync_schema drift safety-net..."
  python -m migrations.sync_schema
  verify_at_head
  exit 0
fi

printf '%s\n' "$upgrade_output" >&2
echo "!! alembic upgrade head FAILED."

# Pull the orphan revision out of the failure message (if this is that
# historical failure mode). Resolution happens before any migration runs, so
# the failed attempt above is non-mutating and safe to build upon.
ORPHAN="$(printf '%s\n' "$upgrade_output" \
  | sed -n "s/.*Can't locate revision identified by '\([0-9a-f]\{12\}\)'.*/\1/p" \
  | head -1)"

if [ -z "$ORPHAN" ]; then
  echo "!! Unhandled migration failure (not an orphan-revision case). State:"
  print_diagnostics
  exit 1
fi

echo "!! alembic_version references unknown revision '${ORPHAN}'. Verifying it is truly absent from the files..."

if printf '%s\n' "$(known_revisions)" | grep -q -x "$ORPHAN"; then
  echo "!! Revision '${ORPHAN}' IS present in alembic/versions - the failure is not an orphan row. State:"
  print_diagnostics
  exit 1
fi

echo "==> '${ORPHAN}' absent from alembic/versions - orphan version row confirmed. Checking schema matches models before re-stamping..."
DRIFT="$(schema_drift)"

if [ -n "$DRIFT" ]; then
  echo "!! Schema is NOT in sync with the models. Refusing to stamp over pending migrations."
  echo "    sync_schema reconciled these (manual review required):"
  printf '%s\n' "$DRIFT" | sed 's/^/      - /'
  echo "    Re-run this script after the DB is brought to head; it will auto-resolve once drift is gone."
  print_diagnostics
  exit 1
fi

echo "==> Schema matches models. Finding correct stamp ancestor..."
# Rather than stamping directly to HEAD (upgrade = no-op, missing tables stay
# missing) or blindly one step before HEAD (only runs the last migration), we
# walk the revision chain from HEAD backwards and find the deepest revision
# whose expected DB objects already exist.  We stamp there so that
# `alembic upgrade head` applies every migration that has NOT yet been run.
#
# The walk inspects the alembic_version table is irrelevant here — we query
# the actual DB tables/columns via the SQLAlchemy inspector, which is
# immune to the orphan revision ID.
STAMP_REV="$(python - <<'PY'
import sys
from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)

heads = script.get_heads()
if len(heads) != 1:
    raise SystemExit(f"Expected exactly 1 head, found {len(heads)}: {heads}")

# Build the linear chain from HEAD back to base (handles simple linear chains
# and merge-point chains by always following the first parent).
chain = []
rev_id = heads[0]
while rev_id is not None:
    rev = script.get_revision(rev_id)
    chain.append(rev_id)
    parents = rev.down_revision
    if parents is None:
        rev_id = None
    elif isinstance(parents, str):
        rev_id = parents
    else:
        rev_id = list(parents)[0]

# Import here so DB is only touched once we need it.
from app.database import engine
with engine.connect() as conn:
    insp = sa.inspect(engine)
    db_tables = set(insp.get_table_names())
    db_columns = {t: {c["name"] for c in insp.get_columns(t)} for t in db_tables}

def rev_objects_present(rev_id):
    """Return True if the migration file's upgrade() creates nothing new.

    We read the migration source and look for op.create_table / op.add_column
    calls. For each one we check the DB.  If all created objects already exist,
    the migration has effectively been applied (or was never needed).
    """
    import re, importlib.util, pathlib
    rev = script.get_revision(rev_id)
    if rev is None:
        return True
    path = rev.module.__file__  # type: ignore[attr-defined]
    src = pathlib.Path(path).read_text(encoding="utf-8")

    # Tables created by this migration.
    created_tables = re.findall(r'op\.create_table\s*\(\s*[\'"](\w+)[\'"]', src)
    for t in created_tables:
        if t not in db_tables:
            return False  # table missing -> migration not applied

    # Columns added by this migration.
    added_cols = re.findall(
        r'op\.add_column\s*\(\s*[\'"](\w+)[\'"].*?sa\.Column\s*\(\s*[\'"](\w+)[\'"]',
        src, re.DOTALL
    )
    for tbl, col in added_cols:
        if tbl in db_columns and col not in db_columns[tbl]:
            return False  # column missing -> migration not applied

    return True  # nothing new detected as missing

# Walk from HEAD toward base; find the deepest rev whose changes are present.
# We stamp to that revision, then upgrade head runs everything after it.
stamp_to = "base"
for rev_id in chain:
    if rev_objects_present(rev_id):
        stamp_to = rev_id
        break  # found the deepest applied revision

print(stamp_to)
PY
)"
if [ -z "$STAMP_REV" ]; then
  echo "!! Could not determine correct stamp revision. State:"
  print_diagnostics
  exit 1
fi

echo "==> Stamping to '${STAMP_REV}' (deepest revision already reflected in DB)..."
# --purge truncates alembic_version unconditionally before writing the new
# revision, so Alembic never tries to look up the orphan row.
alembic stamp --purge "$STAMP_REV"
echo "==> Running upgrade head from '${STAMP_REV}' to apply all pending migrations..."
alembic upgrade head
check_model_drift
echo "==> Running sync_schema drift safety-net..."
python -m migrations.sync_schema
verify_at_head
echo "==> Migration step complete."
