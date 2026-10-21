#!/usr/bin/env bash
# deploy/scripts/restore_drill.sh
# -------------------------------
# STATUS: AWAITING INFRASTRUCTURE OWNER (HP-02). Not yet run against any real
# backup. ZP-PRIV-VERIFY-001 controls D02, B05, D09.
#
# Restores one backup into an ISOLATED drill database, de-identifies it when
# the drill target is non-production, then verifies that row-level security
# and tenant segregation survived the restore. Writes a JSON result (UTC, Z)
# and exits non-zero on any failure.
#
# Idempotent: the drill database's public schema is dropped and recreated on
# every run, so re-running gives the same result for the same backup.
#
# Required env:
#   DRILL_DATABASE_URL       admin URL of the drill database (will be WIPED)
#   BACKUP_URI               gs://bucket/path.dump | /path/file.dump | /path/file.sql[.gz]
#   PRODUCTION_DATABASE_URL  production URL (only used to refuse; never connected to)
# Optional env:
#   PRODUCTION_DB_HOSTS      extra comma-separated production hostnames to refuse
#   DRILL_ENVIRONMENT        environment name of the drill target (default: drill).
#                            Anything other than production/prod is non-production
#                            and is de-identified before verification.
#   APP_ROLE                 application role expected to be NOBYPASSRLS (default: zoiko_app)
#   DRILL_APP_DATABASE_URL   URL of the drill DB as APP_ROLE; if empty the checks use
#                            SET LOCAL ROLE (the admin must be a member of APP_ROLE)
#   EXPECTED_RLS_TABLES_FILE file with one table name per line (e.g. captured from
#                            production with rls_runbook.md V4); default: derived from
#                            columns organization_id / employee_id / payroll_employee_id / payslip_item_id
#   TENANT_ID                organization id for the tenant check (default: smallest with workers)
#   RESULT_FILE              output path (default: ./restore_drill_<UTC>.json)
#   BACKEND_DIR              backend directory for de-identification (default: repo backend/)
#
# Usage:
#   DRILL_DATABASE_URL=postgresql://drill_admin@drill-db.internal.example:5432/zp_drill \
#   PRODUCTION_DATABASE_URL=postgresql://app@prod-db.internal.example:5432/zp \
#   BACKUP_URI=gs://zp-payroll-backups-eu-example/2026-10-18/zp.dump \
#   bash deploy/scripts/restore_drill.sh

set -Eeuo pipefail

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
STARTED_AT="$(ts)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="${BACKEND_DIR:-$REPO_ROOT/backend}"
RESULT_FILE="${RESULT_FILE:-./restore_drill_$(date -u +%Y%m%dT%H%M%SZ).json}"
APP_ROLE="${APP_ROLE:-zoiko_app}"
DRILL_ENVIRONMENT="${DRILL_ENVIRONMENT:-drill}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

CHECKS=()
FAILED=0

json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '; }

record() {  # name ok(true|false) detail
    CHECKS+=("{\"check\":\"$(json_escape "$1")\",\"ok\":$2,\"detail\":\"$(json_escape "$3")\"}")
    if [ "$2" != "true" ]; then FAILED=1; echo "FAIL: $1 - $3" >&2; else echo "ok:   $1 - $3"; fi
}

write_result() {
    local status="passed_checks"
    [ "$FAILED" -ne 0 ] && status="failed"
    {
        printf '{\n'
        printf '  "drill": "zp-priv-restore-drill",\n'
        printf '  "started_at": "%s",\n' "$STARTED_AT"
        printf '  "finished_at": "%s",\n' "$(ts)"
        printf '  "backup_uri": "%s",\n' "$(json_escape "${BACKUP_URI:-}")"
        printf '  "drill_host": "%s",\n' "$(json_escape "${DRILL_HOST:-}")"
        printf '  "drill_environment": "%s",\n' "$(json_escape "$DRILL_ENVIRONMENT")"
        printf '  "app_role": "%s",\n' "$(json_escape "$APP_ROLE")"
        printf '  "status": "%s",\n' "$status"
        printf '  "note": "Automated drill output. Not a review or attestation; HP-02 needs the Infrastructure owner sign-off.",\n'
        printf '  "checks": [\n'
        local i
        for i in "${!CHECKS[@]}"; do
            printf '    %s' "${CHECKS[$i]}"
            [ "$i" -lt $((${#CHECKS[@]} - 1)) ] && printf ','
            printf '\n'
        done
        printf '  ]\n}\n'
    } > "$RESULT_FILE"
    echo "Result written to $RESULT_FILE ($status)"
}

die() { trap - ERR; record "precondition" false "$1"; write_result; exit 1; }
on_error() { local line="$1"; trap - ERR; record "unexpected_error" false "command failed at line $line"; write_result; exit 1; }
trap 'on_error $LINENO' ERR

# ── Preconditions ───────────────────────────────────────────────────────────
command -v psql >/dev/null || die "psql not found"
[ -n "${DRILL_DATABASE_URL:-}" ] || die "DRILL_DATABASE_URL is required"
[ -n "${BACKUP_URI:-}" ] || die "BACKUP_URI is required"
[ -n "${PRODUCTION_DATABASE_URL:-}" ] || die "PRODUCTION_DATABASE_URL is required (used only to refuse it)"

libpq_url() { printf '%s' "$1" | sed -E 's#^(postgres(ql)?)\+[a-z0-9_]+://#\1://#'; }
url_host() { printf '%s' "$1" | sed -E 's#^[a-z0-9+]+://([^@/]*@)?(\[[^]]+\]|[^:/?]+).*#\2#' | tr 'A-Z' 'a-z'; }
url_db() { printf '%s' "$1" | sed -E 's#^[a-z0-9+]+://[^/]*/([^?]*).*#\1#'; }

DRILL_URL="$(libpq_url "$DRILL_DATABASE_URL")"
PROD_URL="$(libpq_url "$PRODUCTION_DATABASE_URL")"
DRILL_HOST="$(url_host "$DRILL_URL")"
PROD_HOST="$(url_host "$PROD_URL")"

[ "$DRILL_URL" != "$PROD_URL" ] || die "DRILL_DATABASE_URL equals the production URL - refusing"
[ "$DRILL_HOST" != "$PROD_HOST" ] || die "drill host $DRILL_HOST is the production host - refusing"
IFS=',' read -r -a EXTRA_HOSTS <<< "${PRODUCTION_DB_HOSTS:-}"
for h in "${EXTRA_HOSTS[@]}"; do
    h="$(printf '%s' "$h" | tr 'A-Z' 'a-z' | xargs)"
    [ -z "$h" ] || [ "$DRILL_HOST" != "$h" ] || die "drill host $DRILL_HOST is listed in PRODUCTION_DB_HOSTS - refusing"
done
case "$(url_db "$DRILL_URL")" in
    *drill*|*restore*) ;;
    *) die "drill database name must contain 'drill' or 'restore' (safety convention)";;
esac
record "target_is_not_production" true "drill host $DRILL_HOST differs from production host"

PSQL=(psql -X -q -A -t -v ON_ERROR_STOP=1)
# Statements are fed on stdin (not -c) so each statement runs separately and
# every SELECT result is printed; callers take the last line where needed.
q_admin() { printf '%s\n' "$1" | "${PSQL[@]}" "$DRILL_URL" -f -; }

# ── Fetch backup ────────────────────────────────────────────────────────────
LOCAL_BACKUP="$WORKDIR/backup"
case "$BACKUP_URI" in
    gs://*)
        if command -v gcloud >/dev/null; then gcloud storage cp "$BACKUP_URI" "$LOCAL_BACKUP" >/dev/null
        elif command -v gsutil >/dev/null; then gsutil -q cp "$BACKUP_URI" "$LOCAL_BACKUP"
        else die "gcloud/gsutil not found for $BACKUP_URI"; fi ;;
    *)
        [ -f "$BACKUP_URI" ] || die "backup file not found: $BACKUP_URI"
        cp "$BACKUP_URI" "$LOCAL_BACKUP" ;;
esac
BACKUP_SHA="$(sha256sum "$LOCAL_BACKUP" | cut -d' ' -f1)"
record "backup_fetched" true "sha256=$BACKUP_SHA"

# ── Restore (idempotent: wipe the drill schema first) ───────────────────────
q_admin "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;" >/dev/null
case "$BACKUP_URI" in
    *.sql.gz) gunzip -c "$LOCAL_BACKUP" | "${PSQL[@]}" "$DRILL_URL" >/dev/null ;;
    *.sql)    "${PSQL[@]}" "$DRILL_URL" -f "$LOCAL_BACKUP" >/dev/null ;;
    *)        command -v pg_restore >/dev/null || die "pg_restore not found"
              pg_restore --no-owner --no-privileges --exit-on-error -d "$DRILL_URL" "$LOCAL_BACKUP" ;;
esac
record "restore_completed" true "restored into $(url_db "$DRILL_URL")"

# Admin queries run in system mode so FORCE RLS does not hide rows from an owner admin.
SYS="SELECT set_config('app.rls_mode','system',false);"

# Grants for the app role on the restored objects (dump restored without privileges).
if [ -z "${DRILL_APP_DATABASE_URL:-}" ]; then
    q_admin "GRANT USAGE ON SCHEMA public TO \"$APP_ROLE\";
             GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"$APP_ROLE\";
             GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO \"$APP_ROLE\";" >/dev/null \
        || die "could not grant drill privileges to $APP_ROLE (does the role exist?)"
fi

# ── De-identify non-production targets (D09) ────────────────────────────────
case "$(printf '%s' "$DRILL_ENVIRONMENT" | tr 'A-Z' 'a-z')" in
    production|prod)
        record "deidentification" true "skipped: drill target declared production (in-region production drill)" ;;
    *)
        if ( cd "$BACKEND_DIR" && ENVIRONMENT="$DRILL_ENVIRONMENT" PAYROLL_DATABASE_URL="$DRILL_DATABASE_URL" \
                python -m scripts.deidentify_database --confirm-nonprod-copy >"$WORKDIR/deid.log" 2>&1 ); then
            STAMP="$(q_admin "$SYS SELECT value FROM platform_settings WHERE key = 'data_deidentified_at';" | tail -n1)"
            if [ -n "$STAMP" ]; then record "deidentification" true "data_deidentified_at=$STAMP"
            else record "deidentification" false "script ran but data_deidentified_at is not set"; fi
        else
            record "deidentification" false "scripts/deidentify_database.py failed (see operator console)"
        fi ;;
esac

# ── Verification ────────────────────────────────────────────────────────────
# V1 policy exists
POLICIES="$(q_admin "SELECT count(*) FROM pg_policies WHERE schemaname='public' AND policyname='zoiko_rls';")"
if [ "${POLICIES:-0}" -gt 0 ]; then record "policy_zoiko_rls_exists" true "$POLICIES tables carry zoiko_rls"
else record "policy_zoiko_rls_exists" false "no zoiko_rls policy after restore"; fi

# V2 RLS enabled + forced on every expected table
if [ -n "${EXPECTED_RLS_TABLES_FILE:-}" ]; then
    [ -f "$EXPECTED_RLS_TABLES_FILE" ] || die "EXPECTED_RLS_TABLES_FILE not found"
    grep -v '^\s*$' "$EXPECTED_RLS_TABLES_FILE" | sort -u > "$WORKDIR/expected.txt"
    EXPECTED_SOURCE="file"
else
    q_admin "SELECT DISTINCT c.table_name FROM information_schema.columns c
             JOIN information_schema.tables t ON t.table_name=c.table_name AND t.table_schema=c.table_schema
             WHERE c.table_schema='public' AND t.table_type='BASE TABLE'
               AND c.column_name IN ('organization_id','employee_id','payroll_employee_id','payslip_item_id')
             ORDER BY 1;" | sort -u > "$WORKDIR/expected.txt"
    EXPECTED_SOURCE="derived"
fi
q_admin "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity AND relkind='r'
         AND relnamespace='public'::regnamespace ORDER BY 1;" | sort -u > "$WORKDIR/rls.txt"
q_admin "SELECT tablename FROM pg_policies WHERE schemaname='public' AND policyname='zoiko_rls' ORDER BY 1;" \
    | sort -u > "$WORKDIR/policy.txt"
MISSING_RLS="$(comm -23 "$WORKDIR/expected.txt" "$WORKDIR/rls.txt" | tr '\n' ' ')"
MISSING_POLICY="$(comm -23 "$WORKDIR/expected.txt" "$WORKDIR/policy.txt" | tr '\n' ' ')"
EXPECTED_N="$(wc -l < "$WORKDIR/expected.txt" | tr -d ' ')"
if [ -z "${MISSING_RLS// }" ]; then record "rls_enabled_and_forced" true "$EXPECTED_N expected tables ($EXPECTED_SOURCE) all ENABLE+FORCE"
else record "rls_enabled_and_forced" false "missing ENABLE/FORCE: $MISSING_RLS"; fi
if [ -z "${MISSING_POLICY// }" ]; then record "rls_policy_on_every_table" true "zoiko_rls on all $EXPECTED_N expected tables"
else record "rls_policy_on_every_table" false "no zoiko_rls on: $MISSING_POLICY"; fi

# V3 app role attributes
ROLE_ROW="$(q_admin "SELECT rolsuper::text || ',' || rolbypassrls::text FROM pg_roles WHERE rolname='$APP_ROLE';")"
if [ "$ROLE_ROW" = "false,false" ]; then record "app_role_nobypassrls" true "$APP_ROLE is NOSUPERUSER NOBYPASSRLS"
else record "app_role_nobypassrls" false "$APP_ROLE attributes (super,bypass)=${ROLE_ROW:-missing}"; fi
OWNED="$(q_admin "SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND pg_get_userbyid(relowner)='$APP_ROLE';")"
if [ "${OWNED:-1}" = "0" ]; then record "app_role_owns_nothing" true "$APP_ROLE owns no relation"
else record "app_role_owns_nothing" false "$APP_ROLE owns $OWNED relations"; fi

# Run SQL as the application role inside one transaction.
as_app() {
    local sql="$1"
    if [ -n "${DRILL_APP_DATABASE_URL:-}" ]; then
        printf 'BEGIN;\n%s\nCOMMIT;\n' "$sql" | "${PSQL[@]}" "$(libpq_url "$DRILL_APP_DATABASE_URL")" -f -
    else
        printf 'BEGIN;\nSET LOCAL ROLE "%s";\n%s\nCOMMIT;\n' "$APP_ROLE" "$sql" | "${PSQL[@]}" "$DRILL_URL" -f -
    fi
}

# V4 no context sees nothing
NOCTX="$(as_app "SELECT count(*) FROM payroll_employees;" | tail -n1)"
if [ "$NOCTX" = "0" ]; then record "no_context_sees_nothing" true "0 worker rows without app.rls_mode"
else record "no_context_sees_nothing" false "$NOCTX worker rows visible without context"; fi

# V5 tenant context sees only its tenant
TOTAL="$(q_admin "$SYS SELECT count(*) FROM payroll_employees;" | tail -n1)"
TENANT_ID="${TENANT_ID:-$(q_admin "$SYS SELECT min(organization_id) FROM payroll_employees;" | tail -n1)}"
if [ -z "$TENANT_ID" ]; then
    record "tenant_segregation" false "no worker rows in the restored backup - cannot prove segregation"
else
    [[ "$TENANT_ID" =~ ^[0-9]+$ ]] || die "TENANT_ID must be an integer"
    OWN_EXPECTED="$(q_admin "$SYS SELECT count(*) FROM payroll_employees WHERE organization_id=$TENANT_ID;" | tail -n1)"
    TENANT_ROW="$(as_app "SELECT set_config('app.rls_mode','tenant',true), set_config('app.tenant_id','$TENANT_ID',true);
        SELECT count(*) FILTER (WHERE organization_id <> $TENANT_ID) || ',' || count(*) FROM payroll_employees;" | tail -n1)"
    FOREIGN="${TENANT_ROW%%,*}"; OWN="${TENANT_ROW##*,}"
    if [ "$FOREIGN" = "0" ] && [ "$OWN" = "$OWN_EXPECTED" ]; then
        record "tenant_segregation" true "tenant $TENANT_ID sees $OWN own rows, 0 foreign (of $TOTAL total)"
    else
        record "tenant_segregation" false "tenant $TENANT_ID saw foreign=$FOREIGN own=$OWN expected_own=$OWN_EXPECTED"
    fi
fi

# V6 platform mode sees no worker rows
PLATFORM="$(as_app "SELECT set_config('app.rls_mode','platform',true); SELECT count(*) FROM payroll_employees;" | tail -n1)"
if [ "$PLATFORM" = "0" ]; then record "platform_mode_sees_no_workers" true "0 worker rows in platform mode"
else record "platform_mode_sees_no_workers" false "$PLATFORM worker rows visible in platform mode"; fi

write_result
exit "$FAILED"
