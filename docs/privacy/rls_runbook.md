# PostgreSQL row-level security runbook (B05, D02; HP-03, HP-02)

Status: awaiting Infrastructure owner proof (HP-03). RLS policies are installed by migration; production
enforcement is NOT in place until the application connects as a NOBYPASSRLS, non-owner role and
`DB_RLS_REQUIRE_ENFORCED=true` (DEV-3, defect PD-004).

## 1. How RLS works here

Migrations: `d7f9b1c3e5a6_postgres_row_level_security.py` (installs) and `e1a3c5e7f9b2_...` (re-applies
to the tables it adds). Both call `apply_rls(bind)`, which derives tables from the live schema:

| Class | Tables | Policy predicate (`zoiko_rls`, USING and WITH CHECK) |
|---|---|---|
| Worker | `payroll_employees`, `payslip_items`, and every table with `employee_id` / `payroll_employee_id` / `payslip_item_id` or an FK to those two | Visible in modes `system`, `platform_aggregate`; otherwise only `tenant` mode and same organization (directly via `organization_id`, or via an `EXISTS` on the RLS-protected parent). Mode `platform` sees no worker row |
| Tenant | Every other table with `organization_id` | Visible in `system`, `platform`, `platform_aggregate`; rows with `organization_id IS NULL` to everyone; otherwise `tenant` mode, own organization |

Both classes have `ENABLE` and `FORCE ROW LEVEL SECURITY` (the table owner is bound too).

Session settings (set per transaction by `core/authz/tenant_context.py`, `set_config(..., true)` in
`after_begin` and on every context change):

| Setting | Values |
|---|---|
| `app.rls_mode` | `tenant`, `platform`, `platform_aggregate`, `system` |
| `app.tenant_id` | organization id in `tenant` mode, else empty |

Helper functions: `zoiko_rls_mode()`, `zoiko_rls_tenant()`.

Mode selection in the app: PDP-allowed tenant request -> `tenant`; platform principal -> `platform`
(or `platform_aggregate` on reviewed aggregate / lifecycle routes); a session with no context (jobs,
schedulers, audit writers, public routes, migrations) -> `system`. A raw connection that sets no mode sees nothing.

Limits you must know:
- `app.rls_mode` is a client-set setting. Anyone holding the application credentials can set `system`.
  RLS is defence in depth against application bugs, not against a credential holder; HP-01 (PAM) covers people.
- The append-only audit triggers honour `zoiko.audit_purge = 'on'` ONLY for members of the
  `zoiko_audit_purger` role (`zoiko_audit_purge_allowed()`, migrations c5e7 / e1a3). The flag alone
  is client-settable and unlocks nothing. Never grant `zoiko_audit_purger` to `zoiko_app`; grant it
  temporarily to the retention operator for an approved purge (AUDIT_PURGE_ON_ORG_HARD_DELETE stays
  off, DEC-7). Superusers count as members of every role - another reason the app is not one.
- Superusers and roles with `BYPASSRLS` skip all policies. A table owner without FORCE would too (FORCE is set),
  but an owner can `ALTER TABLE ... NO FORCE` or `DROP POLICY` - hence the non-owner requirement.
- `apply_rls` only covers tables that exist when it runs. Every future migration that adds a table with
  `organization_id` / employee columns must call `apply_rls` again (as `e1a3c5e7f9b2` does).
- `initialize_database()` runs `create_all` on an empty database; that path installs no policies. Production must be built by Alembic.

## 2. Provision roles

Two roles: a migration owner (owns tables, runs Alembic) and the application role (DML only).
Run as an administrative role. Passwords come from the secret manager; never paste them in tickets.

```sql
-- Migration owner: owns the schema objects. Used only by the deploy/migration step.
CREATE ROLE zoiko_migrator LOGIN PASSWORD :'migrator_password' NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
-- Application role: never owner, never bypasses RLS.
CREATE ROLE zoiko_app LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;

-- Transfer ownership of existing objects to the migrator (run once, as the current owner).
REASSIGN OWNED BY <current_owner_role> TO zoiko_migrator;   -- review first: affects all objects in this database

GRANT CONNECT ON DATABASE <dbname> TO zoiko_app;
GRANT USAGE ON SCHEMA public TO zoiko_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO zoiko_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO zoiko_app;
GRANT EXECUTE ON FUNCTION zoiko_rls_mode(), zoiko_rls_tenant() TO zoiko_app;
-- Future objects created by the migrator:
ALTER DEFAULT PRIVILEGES FOR ROLE zoiko_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO zoiko_app;
ALTER DEFAULT PRIVILEGES FOR ROLE zoiko_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO zoiko_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

Audit purge role (create once; members only during an approved purge):

```sql
CREATE ROLE zoiko_audit_purger NOLOGIN;
-- GRANT zoiko_audit_purger TO <retention_operator>;  -- time-bound, recorded
```

Neon note (to verify with the provider): roles created in the Neon console are members of
`neon_superuser`, which may carry BYPASSRLS. Create `zoiko_app` with SQL as above and confirm
`rolbypassrls = false` and no membership that grants it.

## 3. Wire the application and migrations

| Item | Setting |
|---|---|
| App service (`zoiko-payroll-backend` systemd, `/var/www/zoiko-payroll`) | `PAYROLL_DATABASE_URL` uses `zoiko_app` |
| Migrations | Run Alembic with `PAYROLL_DATABASE_URL` overridden to `zoiko_migrator` in the migration shell only (`alembic/env.py` reuses the app URL resolution) |
| Celery workers and schedulers | Same `zoiko_app` URL |
| Switch on refusal | `DB_RLS_REQUIRE_ENFORCED=true` in the production environment after verification passes |

At startup `app.database.check_row_level_security()` logs CRITICAL and, with `DB_RLS_REQUIRE_ENFORCED=true`,
refuses to start when the role is superuser, has BYPASSRLS, or no `zoiko_rls` policy exists. It does not
check table ownership - verify that separately (query V3).

## 4. Verification queries (run as `zoiko_app` unless noted)

```sql
-- V1 role attributes
SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;   -- expect f, f
-- V2 role memberships (expect none granting bypass)
SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
 WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user);
-- V3 the app role owns nothing
SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = current_user;              -- expect 0
-- V4 every table with organization_id or an employee column has RLS enabled + forced + zoiko_rls
SELECT t.table_name, c.relrowsecurity, c.relforcerowsecurity,
       EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = t.table_name AND p.policyname = 'zoiko_rls') AS has_policy
  FROM (SELECT DISTINCT table_name FROM information_schema.columns
         WHERE table_schema = 'public'
           AND column_name IN ('organization_id','employee_id','payroll_employee_id','payslip_item_id')) t
  JOIN pg_class c ON c.relname = t.table_name AND c.relkind = 'r'
 WHERE NOT (c.relrowsecurity AND c.relforcerowsecurity)
    OR NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = t.table_name AND p.policyname = 'zoiko_rls');
-- expect 0 rows
-- V5 no context sees nothing
SELECT count(*) FROM payroll_employees;                                                   -- expect 0
-- V6 tenant context sees only its tenant
BEGIN;
SELECT set_config('app.rls_mode','tenant',true), set_config('app.tenant_id','<org_id>',true);
SELECT count(*) FILTER (WHERE organization_id <> <org_id>) AS foreign_rows, count(*) AS own_rows FROM payroll_employees;
ROLLBACK;                                                                                 -- foreign_rows = 0
-- V7 platform mode sees no worker rows
BEGIN;
SELECT set_config('app.rls_mode','platform',true);
SELECT count(*) FROM payroll_employees;                                                   -- expect 0
ROLLBACK;
```

Also call the application health/diagnostic that returns `check_row_level_security()` (`enforced: true`).

## 5. Restore-drill verification (HP-02)

Run `deploy/scripts/restore_drill.sh` against an isolated drill database. It restores the backup,
de-identifies a non-production target, and runs the checks above, writing a JSON result with a UTC
timestamp. File the JSON in `docs/privacy/evidence_pack/EP-02/`. A restore of production data into any
non-production environment without `scripts/deidentify_database.py` is forbidden (D09).

## 6. Rollback

| Situation | Action |
|---|---|
| App fails to start after `DB_RLS_REQUIRE_ENFORCED=true` | Set it back to `false`, restart; the app keeps running with a CRITICAL log. Fix the role, re-verify, switch on again |
| App role lacks a grant (permission denied) | Add the missing GRANT (do not switch to the owner role) |
| Business query returns empty rows because a code path has no tenant context | Fix the code path; do not grant BYPASSRLS. Temporary switch of `PAYROLL_DATABASE_URL` back to the previous role is a recorded exception in the defect register with an owner and expiry |
| Policy defect | `alembic downgrade` of the RLS migrations removes policies - only with Security lead approval, recorded as an exception |

## Proof record (HP-03)

| Item | Value |
|---|---|
| Date applied (UTC) | |
| Environment | |
| V1-V7 output attached (EP-02) | |
| `DB_RLS_REQUIRE_ENFORCED` in production | |
| Infrastructure owner signature | |
| Reviewer signature | |
