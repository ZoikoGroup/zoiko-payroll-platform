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
  python - >/dev/null 2>&1 <<'PY' || true
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

# --- Migration steps -------------------------------------------------------

echo "==> alembic upgrade head"
if upgrade_output="$(alembic upgrade head 2>&1)"; then
  printf '%s\n' "$upgrade_output"
  echo "==> Up to date. Running sync_schema drift safety-net..."
  python -m migrations.sync_schema
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

echo "==> Schema matches models. Re-stamping alembic to current head..."
HEAD_REV="$(alembic heads | head -1 | awk '{print $1}')"
if [ -z "$HEAD_REV" ]; then
  echo "!! Could not resolve alembic head revision. State:"
  print_diagnostics
  exit 1
fi

alembic stamp "$HEAD_REV"
echo "==> Re-stamped to '${HEAD_REV}'. Re-running upgrade..."
alembic upgrade head
echo "==> Running sync_schema drift safety-net..."
python -m migrations.sync_schema
echo "==> Migration step complete."