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
  `payroll_runs.be_approval_fingerprint` (string). No default, no backfill, no lock-heavy rewrite
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

Rollback is rarely needed. Belgium is dormant, so a Belgian problem affects no customer. Start from the smallest
step that works.

### 4.1 Behaviour only (no code or schema change)

Belgium is already closed. Keep `BE_TENANT_ONBOARDING_ENABLED` unset, `BE_CANARY_ORG_IDS` empty and the registry row
PLANNED (`BELGIUM_ACTIVATION_RUNBOOK.md` §3). If a shared (non-Belgian) code path misbehaves, ship a targeted fix.

### 4.2 Full rollback (code and schema)

**Order matters.** Downgrade the schema while the Belgian code (and its three revision files) is still on the
server, then revert the code. The other order fails twice:
- after a code revert the revision files are gone, so `alembic downgrade` cannot run them;
- the next deploy's drift check (`scripts/check_schema_drift.py`) refuses, because `payslip_items` and
  `payroll_runs` still carry columns that the reverted models do not declare. The deploy stops before the restart.

1. **Verify the Belgian tables are empty** (all must be 0; if any is not, STOP: that is real data and a downgrade
   would destroy it):

   ```sql
   -- run the generated query from 3.7, plus:
   SELECT count(*) FROM payslip_items WHERE be_calculation_snapshot IS NOT NULL;
   SELECT count(*) FROM payroll_runs  WHERE be_approval_fingerprint IS NOT NULL;
   ```

2. **Downgrade the schema on the backend host**, newest first. Run it from the deployed (Belgian) checkout, with the
   same remote-migration acknowledgement the deploy pipeline uses (`scripts/deploy_migrate.sh`):

   ```bash
   cd /var/www/zoiko-payroll/backend/backend
   source venv/bin/activate
   export ZOIKO_ALLOW_REMOTE_MIGRATIONS=I_UNDERSTAND
   alembic current                      # expect 8a1f5ef9fa5d
   alembic downgrade 2943a0490b5b       # drops the 5 Block C tables (filings, obligations, variances, parallel)
   alembic downgrade 1d76678ef1a1       # drops the 5 Block B tables + the Block B decision columns
   alembic downgrade f3a9c1d7e2b4       # drops the 9 foundation tables + the 2 shared columns
   alembic current                      # expect f3a9c1d7e2b4
   python -m scripts.check_schema_drift # expect drift ONLY for the Belgian model objects (code not yet reverted)
   unset ZOIKO_ALLOW_REMOTE_MIGRATIONS
   ```

3. **Revert the code** on `main` through a PR, then merge it. That deploys:

   ```bash
   git checkout main && git pull
   git checkout -b revert-belgium                 # the only branch in this procedure; owner's call
   git revert -m 1 <merge commit of the Belgium PR>
   git push -u origin revert-belgium               # open the PR, wait for CI, merge
   ```

   The deploy then finds the database at `f3a9c1d7e2b4` = head: the upgrade is a no-op and the drift check is clean.

**If the code was already reverted first:** the deploy reports `alembic_version` `8a1f5ef9fa5d` as an unknown
revision, and the drift check refuses on the two shared columns. Nothing is changed (the script refuses before it
stamps). To finish:
- export the Belgian revision files from the pre-revert commit:
  `git archive <merge commit> backend/alembic/versions | tar -x -C /tmp/be_rollback`;
- copy only `1d76678ef1a1_*.py`, `2943a0490b5b_*.py` and `8a1f5ef9fa5d_*.py` into `backend/alembic/versions/`
  temporarily;
- run step 1, then step 2;
- delete the three copied files and re-run the deploy.

The database backup from §1 is the last resort if any step above does not behave as described.

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
