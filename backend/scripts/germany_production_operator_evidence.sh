#!/usr/bin/env bash
set -u

# Read-only Germany 2026 production evidence collector.
# Run this on the deployment server from /var/www/zoiko-payroll/backend.
# It never pulls, mutates git, runs a migration, changes a service, or writes
# to PostgreSQL. The only local writes are evidence files in OUTDIR.

OUTDIR="${1:-$PWD/germany_production_operator_evidence}"
mkdir -p "$OUTDIR" || { echo "ERROR: cannot create evidence directory" >&2; exit 1; }

DB_URL="${DATABASE_URL:-${PAYROLL_DATABASE_URL:-}}"
ALEMBIC_CMD="${ALEMBIC_CMD:-alembic}"

redact() {
    sed -E 's#(postgres(ql)?\+?[^:]*://[^:]+):[^@]+@#\1:***@#g; s#(://[^:]+):[^@]+@#\1:***@#g'
}

capture() {
    local name="$1"
    shift
    {
        echo "===== $name ====="
        "$@" 2>&1 | redact
        echo
    } | tee "$OUTDIR/$name.txt"
}

capture_shell() {
    local name="$1"
    local command_text="$2"
    {
        echo "===== $name ====="
        bash -c "$command_text" 2>&1 | redact
        echo
    } | tee "$OUTDIR/$name.txt"
}

echo "Germany 2026 production operator evidence"
echo "Collected UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Host: $(hostname)"
echo "Evidence directory: $OUTDIR"
echo "No production mutation is performed by this script."

capture_shell git_state 'git rev-parse --show-toplevel; git rev-parse HEAD; git branch --show-current; git status --short; git remote -v; git log -10 --oneline --decorate'
capture_shell migration_inventory 'find backend/alembic/versions -maxdepth 1 -type f -print | sort'
capture_shell revision_search 'grep -R -n -E "2b8cb41dfbed|9f06735e9259|bbd80be2fee1|36d83be4bc14|2b3c4d5e6f70" . --exclude-dir=.git || true'
capture_shell branch_refs 'git show-ref --heads --tags | grep -E "(^|/)(main|nikhil)$|refs/tags" || true'
capture alembic_current "$ALEMBIC_CMD" current
capture alembic_heads "$ALEMBIC_CMD" heads
capture alembic_branches "$ALEMBIC_CMD" branches
capture alembic_history_verbose "$ALEMBIC_CMD" history --verbose
capture_shell alembic_config 'sed -n "1,240p" alembic.ini; printf "\n===== alembic/env.py =====\n"; sed -n "1,280p" alembic/env.py'

if [ -z "$DB_URL" ]; then
    echo "DATABASE_URL/PAYROLL_DATABASE_URL is not configured; database evidence is NOT CONFIRMED."
else
    pg_dump --schema-only --no-owner --no-privileges "$DB_URL" > "$OUTDIR/germany_production_schema_only.sql"
    sha256sum "$OUTDIR/germany_production_schema_only.sql" | tee "$OUTDIR/germany_production_schema_only.sha256"

    capture_shell database_facts "psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -At -c \"SELECT version(); SELECT 'alembic_version'; SELECT version_num FROM alembic_version; SELECT 'public_table_count'; SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';\""
    capture_shell table_inventory "psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -P pager=off -c \"SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND (table_name ILIKE '%payroll%' OR table_name ILIKE '%payslip%' OR table_name ILIKE '%employee%' OR table_name ILIKE '%germany%' OR table_name ILIKE '%pap%' OR table_name ILIKE '%elstam%' OR table_name ILIKE '%elster%' OR table_name ILIKE '%overtime%') ORDER BY table_name;\""
    capture_shell registry_counts "psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -At -c \"SELECT format('SELECT %L AS table_name, COUNT(*) AS row_count FROM %I;', table_name, table_name) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'payroll_germany_%' ORDER BY table_name;\" | psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -P pager=off"
    capture_shell registry_status_counts "psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -At -c \"SELECT format('SELECT %L AS table_name, COUNT(*) AS row_count, COUNT(*) FILTER (WHERE status = ''PUBLISHED'') AS published_count, COUNT(*) FILTER (WHERE status = ''APPROVED'') AS approved_count, COUNT(*) FILTER (WHERE status = ''VERIFIED'') AS verified_count, COUNT(*) FILTER (WHERE status = ''DRAFT'') AS draft_count, MIN(effective_from) AS earliest_effective_from, MAX(effective_from) AS latest_effective_from FROM %I;', table_name, table_name) FROM information_schema.columns WHERE table_schema='public' AND table_name LIKE 'payroll_germany_%' GROUP BY table_name HAVING COUNT(*) FILTER (WHERE column_name='status') > 0 AND COUNT(*) FILTER (WHERE column_name='effective_from') > 0;\" | psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -P pager=off"
    capture_shell schema_compatibility "psql -X -v ON_ERROR_STOP=1 --dbname=\"$DB_URL\" -P pager=off -c \"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema='public' AND ((table_name='payslip_items' AND column_name IN ('soli')) OR (table_name='payroll_germany_overtime_premium_components' AND column_name IN ('applied_wage_tax_delta','applied_soli_delta','applied_church_tax_delta')) OR table_name LIKE 'payroll_germany_%') ORDER BY table_name, ordinal_position; SELECT table_name, constraint_name, constraint_type FROM information_schema.table_constraints WHERE table_schema='public' AND (table_name ILIKE '%elstam%' OR table_name LIKE 'payroll_germany_%') ORDER BY table_name, constraint_name;\""
    capture_shell backup_evidence 'printf "%s\\n" "BACKUP/PITR: NOT CONFIRMED by this read-only database collector."'
fi

echo "PAP evidence remains an operator verification item; this script does not activate or create PAP artifacts."
echo "Completed read-only evidence collection."
