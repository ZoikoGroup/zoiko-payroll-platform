# Belgium (ZP-BE-ENG-001) — production deploy notes

For: the engineer who merges `nikhil` into `main` and watches the deploy. Merging `main` deploys to production
automatically (backend-deploy.yml: pull → `scripts/deploy_migrate.sh` → restart → drift check), so this page is
the merge checklist.

Belgium is **dormant** after this deploy. No customer sees or uses it until the activation runbook
(`BELGIUM_ACTIVATION_RUNBOOK.md`) is completed, which needs signed content and the G1–G7 release gates.

---

## 1. Pre-merge checklist

| # | Check | How |
|---|-------|-----|
| 1 | CI green on the PR | `test` (full suite, Python 3.12), `privacy-isolation` (PostgreSQL 15: RLS + the 3 Belgian migration round trips, last step), frontend build |
| 2 | Single Alembic head = `8a1f5ef9fa5d` | `cd backend && alembic heads` → exactly one line, `8a1f5ef9fa5d (head)`. If `main` gained another migration since the PR was opened, there are two heads: stop and re-chain before merging (see `MERGE_PLAN.md`) |
| 3 | `main` has not moved past the PR base | GitHub shows "This branch has no conflicts"; otherwise merge `main` into `nikhil` again and re-run CI |
| 4 | Database backup | Take a production backup with the standard procedure **immediately before** merging, and note its name and time. Example: `pg_dump -Fc -f zoiko_pre_be_$(date +%Y%m%d%H%M).dump "$DATABASE_URL"`, then confirm the file size is non-zero |
| 5 | Deploy window | Low-traffic window; someone who can SSH to the backend host is available for 30 min after the merge |
| 6 | Environment unchanged | Production must **not** set `BE_TENANT_ONBOARDING_ENABLED`, `BE_CANARY_ORG_IDS`, `BE_DEMO_PACKS_ENABLED`, `BE_DEMO_ORG_IDS`. `BE_IDENTIFIER_KEYRING` / `BE_IDENTIFIER_FINGERPRINT_KEY` stay unset until activation (`tests/test_belgium_production_startup.py` proves the app starts and Belgium stays dormant with none of them set) |

## 2. What the deploy changes

Three additive migrations, applied in order by `alembic upgrade head` (`f3a9c1d7e2b4` → `1d76678ef1a1` →
`2943a0490b5b` → `8a1f5ef9fa5d`):

- **19 new tables**, all empty, each with row-level security ENABLED + FORCED and the tenant policy:
  `payroll_be_identifier_vault`, `payroll_be_identifier_access_events`, `payroll_be_employer_registrations`,
  `payroll_be_establishment_units`, `payroll_be_worker_profiles`, `payroll_be_work_schedules`,
  `payroll_be_employment_classifications`, `payroll_be_declarations`, `payroll_be_accumulator_entries`,
  `payroll_be_absence_episodes`, `payroll_be_holiday_certificates`, `payroll_be_payment_batches`,
  `payroll_be_payment_items`, `payroll_be_component_mappings`, `payroll_be_filings`, `payroll_be_obligations`,
  `payroll_be_reconciliation_variances`, `payroll_be_parallel_imports`, `payroll_be_parallel_differences`.
- **2 nullable columns** on existing tables: `payslip_items.be_calculation_snapshot` (JSON),
  `payroll_runs.be_approval_fingerprint` (JSON). No default, no backfill, no lock-heavy rewrite
  (`SET LOCAL lock_timeout = '5s'`).
- No data is inserted. No existing column, index, policy or row is changed.

Behaviour for existing customers: unchanged. The shared code changes are keyed to `country == "BE"` (reviewed in
`BELGIUM_SECURITY_REVIEW.md` §3). A Belgian payslip PDF is only ever the Belgian §11 layout, and organisation
payslip templates refuse a BE scope (Block H1).

Rehearsed locally: `python -m scripts.be_deploy_rehearsal /tmp/be_rehearsal.db` (from `backend/`) replays the
deploy from `f3a9c1d7e2b4` on a throwaway SQLite file:
- the drift filter explains all 21 Belgian objects;
- a second upgrade is a no-op;
- the orphan-path stamp walk never skips pending migrations;
- the three downgrades work on empty tables.

## 3. Post-deploy verification (read-only SQL)

Run as a read-only role (or in a transaction you roll back). Every query only reads.

```sql
-- 3.1 Alembic is at the single head
SELECT version_num FROM alembic_version;                       -- expect exactly: 8a1f5ef9fa5d

-- 3.2 The 19 Belgian tables exist
SELECT count(*) FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name LIKE 'payroll\_be\_%';                   -- expect 19

-- 3.3 Row-level security is enabled AND forced on every one, each with a policy
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
       (SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) AS policies
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname LIKE 'payroll\_be\_%'
 ORDER BY c.relname;                                      -- expect 19 rows: t | t | >= 1

-- 3.4 The two shared columns exist and are unused
SELECT table_name, column_name, is_nullable FROM information_schema.columns
 WHERE (table_name, column_name) IN (('payslip_items', 'be_calculation_snapshot'),
                                     ('payroll_runs', 'be_approval_fingerprint'));       -- expect 2 rows, YES
SELECT count(*) FROM payslip_items WHERE be_calculation_snapshot IS NOT NULL;            -- expect 0
SELECT count(*) FROM payroll_runs  WHERE be_approval_fingerprint IS NOT NULL;            -- expect 0

-- 3.5 Belgium is not available: no registry row, or PLANNED
SELECT country, availability FROM jurisdiction_service_registry WHERE country = 'BE';   -- expect 0 rows or PLANNED

-- 3.6 No Belgian pack is Active
SELECT pack_id, version, status FROM payroll_jurisdiction_packs
 WHERE jurisdiction_country = 'BE';                     -- expect 0 rows now; later only Draft rows

-- 3.7 No Belgian data (generates one UNION query; run its output)
SELECT string_agg(format('SELECT %L AS t, count(*) FROM %I', table_name, table_name), ' UNION ALL ')
  FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name LIKE 'payroll\_be\_%';                   -- every count 0
```

Also: `GET /api/payroll/belgium/employer-registrations` as any org admin returns **404**. The Super Admin console
(Belgium → Overview) loads with "No Belgium pack yet" and the **Create the Draft pack** form.

## 4. Rollback

Belgium is dormant, so a Belgian problem affects no customer. Rolling back means removing the Belgian **code**.
Start with 4.1. Removing the schema (4.3) is only done when someone explicitly requires it.

### 4.0 Behaviour only (no deploy)

Belgium is already closed. Keep `BE_TENANT_ONBOARDING_ENABLED` unset, `BE_CANARY_ORG_IDS` empty and the registry
row PLANNED (`BELGIUM_ACTIVATION_RUNBOOK.md` §3). If a shared, non-Belgian path misbehaves, a targeted fix is
smaller than a revert.

### 4.1 Default: revert the code, keep the Belgian schema (no database operation)

The schema is additive: 19 empty tables and 2 nullable columns. The pre-Belgium code works against it unchanged.
`python -m scripts.be_rollback_orm_check --workdir <scratch dir>` runs main's pre-Belgium code (6081174) against
a database at 8a1f5ef9fa5d that holds the Belgian schema and the Draft pack. Organisation, employees, a run,
payslip generation, status change, payslip read / list / PDF and updates for an existing country (IN) behave
**identically** to a database built by the pre-Belgium code itself.

**A plain `git revert` is not enough.** The deploy pipeline rejects it, and the same check proves why. With the
pre-Belgium code against the Belgian database:
- `alembic upgrade head` fails with "Can't locate revision identified by '8a1f5ef9fa5d'";
- `scripts/deploy_migrate.sh` then refuses to stamp: "payslip_items: DB has columns not on the model:
  ['be_calculation_snapshot']" (and `payroll_runs` … `be_approval_fingerprint`);
- the script exits 1 **before the restart**: nothing changes, but the rollback never takes effect.

So the revert carries a small **schema shim**, `backend/scripts/belgium_rollback_shim.py`. It restores only:
- the three Belgian revision files and their manifest lines, so the alembic head stays `8a1f5ef9fa5d` and
  `upgrade head` is a no-op;
- the two nullable column declarations, so there is no drift. The 19 tables need no model, because extra tables
  are not drift;
- the alembic / drift-set pin tests as re-pinned for Belgium, so CI agrees.

No Belgian route, service, engine, setting or screen remains. Proven by the same check: revert plus shim gives
`deploy_migrate.sh` exit 0, drift clean, identical payroll operations, and 135/135 pin tests passing in the
shim tree.

Exact commands (repository root):

```bash
git checkout main && git pull
git checkout -b revert-belgium                       # owner's branch for the revert PR
git revert -m 1 <Belgium merge commit>               # main's pre-merge parent is parent 1
python backend/scripts/belgium_rollback_shim.py --merge <Belgium merge commit> --dry-run   # review the plan
python backend/scripts/belgium_rollback_shim.py --merge <Belgium merge commit>
cd backend && alembic heads && cd ..                 # expect exactly: 8a1f5ef9fa5d (head)
git add -A backend/alembic backend/app/modules/payroll/models.py backend/tests
git commit -m "revert(belgium): remove Belgian code, keep the additive schema (rollback shim)"
git push -u origin revert-belgium                    # open the PR; CI green; merge -> normal deploy
```

The shim refuses if a file it would restore was changed on `main` after the merge; restore that file by hand.
After the deploy, verify with §3.1 (`8a1f5ef9fa5d`), §3.2 (19 tables, unused) and
`python -m scripts.check_schema_drift` (clean). Re-introducing Belgium later is a normal merge on top: its revision
files are already there.

### 4.2 What stays behind after 4.1

The 19 empty `payroll_be_*` tables (RLS on), two always-NULL columns, the three revision files, and any Draft
Belgian pack rows in the shared pack tables. No code reads or writes any of them.

### 4.3 Schema removal (only if explicitly required)

Run it **while the Belgian migration files are still present**: before the revert (the current deploy), or from a
checkout of the Belgian merge commit. After a revert, alembic cannot downgrade revisions whose files are gone.

1. **Read-only "tables empty" checks.** Every count must be 0. If any is not, STOP: that is real data.

   ```sql
   -- the generated query from 3.7 (every payroll_be_* table), plus:
   SELECT count(*) FROM payslip_items WHERE be_calculation_snapshot IS NOT NULL;
   SELECT count(*) FROM payroll_runs  WHERE be_approval_fingerprint IS NOT NULL;
   ```

2. **Downgrade on the backend host**, from the deployed Belgian checkout, with the remote-migration
   acknowledgement the deploy pipeline uses (`scripts/deploy_migrate.sh`):

   ```bash
   cd /var/www/zoiko-payroll/backend/backend
   source venv/bin/activate
   export ZOIKO_ALLOW_REMOTE_MIGRATIONS=I_UNDERSTAND
   alembic current                      # expect 8a1f5ef9fa5d
   alembic downgrade 2943a0490b5b       # drops the 5 Block C tables
   alembic downgrade 1d76678ef1a1       # drops the 5 Block B tables + the Block B decision columns
   alembic downgrade f3a9c1d7e2b4       # drops the 9 foundation tables + the 2 shared columns
   alembic current                      # expect f3a9c1d7e2b4
   unset ZOIKO_ALLOW_REMOTE_MIGRATIONS
   ```

   If the code was already reverted with the shim (4.1), use the shim tree. It has the revision files, so the
   same commands work there. Then remove the shim in the next step.

3. **Revert the code without the shim.** Use `git revert -m 1 <merge>` alone (or, after 4.1, revert the shim
   commit). The deploy then finds the database at `f3a9c1d7e2b4` = head: the upgrade is a no-op and the drift
   check is clean.

Downgrades were rehearsed on empty tables (`python -m scripts.be_deploy_rehearsal`, Block H2a). The §1 database
backup is the last resort.

## 5. First manual steps after a good deploy (owner's decision; none is automatic)

Nothing Belgian is seeded by the deploy or by app startup (`docs/belgium/PROGRESS.md`, Block H2c). When the owner
decides to start content work:

1. **Registry row PLANNED and Draft pack.** Preferred: Super Admin console → Belgium → Overview → "No Belgium pack yet" → enter a reason
   → **Create the Draft pack** (`POST /api/super-admin/compliance/belgium/seed-draft`; audited). It runs inside the deployed app and creates both the Draft `BE-PAYROLL-2026`, with
   every row `[PENDING G1]`, and the PLANNED registry row, only while no Belgian pack exists. The scripts do the same
   on a host whose database is local:
   - `python -m scripts.seed_belgium_registry` (PLANNED row only);
   - `python -m scripts.seed_belgium_canonical_packs` (Draft pack and PLANNED row).

   Both refuse a non-local database (`scripts/_local_db_guard.py`).
2. **Verify:** re-run §3.5 and §3.6. Expect `PLANNED` and one `Draft` pack.
3. **Import the AI-drafted content, unsigned.** Console → Belgium → **Signing status** tab → "Content workbook (specialist intake)" → choose
   `docs/belgium/content/BE_2026_AI_DRAFT.xlsx` → **Dry run** (the default) → review the report → **Import**. Rows
   arrive UNSIGNED with their sources. Signing is the Belgian specialist's job (four-eyes, per row,
   `BELGIUM_REVIEWER_GUIDE.md`). Nothing becomes Active.

Never on production: `scripts/seed_belgium_demo.py`, `BE_DEMO_PACKS_ENABLED` or `BE_DEMO_ORG_IDS`. The demo is
refused in a production environment anyway (`STAGING_REHEARSAL.md`).
