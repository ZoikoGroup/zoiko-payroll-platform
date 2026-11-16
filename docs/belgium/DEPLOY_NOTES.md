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
| 2 | Single Alembic head = `b7e4c2a9d5f1` (Belgium Block K, on main's merge `cf348b09db2b`) | `cd backend && alembic heads` → exactly one line, `b7e4c2a9d5f1 (head)`. If `main` gained another migration since the PR was opened, there are two heads: stop and re-chain before merging (see `MERGE_PLAN.md`) |
| 3 | `main` has not moved past the PR base | GitHub shows "This branch has no conflicts"; otherwise merge `main` into `nikhil` again and re-run CI |
| 4 | Database backup | Take a production backup with the standard procedure **immediately before** merging, and note its name and time. Example: `pg_dump -Fc -f zoiko_pre_be_$(date +%Y%m%d%H%M).dump "$DATABASE_URL"`, then confirm the file size is non-zero |
| 5 | Deploy window | Low-traffic window; someone who can SSH to the backend host is available for 30 min after the merge |
| 6 | Environment unchanged | Production must **not** set `BE_TENANT_ONBOARDING_ENABLED`, `BE_CANARY_ORG_IDS`, `BE_DEMO_PACKS_ENABLED`, `BE_DEMO_ORG_IDS`. `BE_IDENTIFIER_KEYRING` / `BE_IDENTIFIER_FINGERPRINT_KEY` stay unset until activation (`tests/test_belgium_production_startup.py` proves the app starts and Belgium stays dormant with none of them set) |

## 2. What the deploy changes

Three additive migrations, applied in order by `alembic upgrade head` (`f3a9c1d7e2b4` → `1d76678ef1a1` →
`2943a0490b5b` → `8a1f5ef9fa5d`):

Block K adds a fourth, `b7e4c2a9d5f1` (after main's merge revision `cf348b09db2b`), with **2 platform tables**:
`payroll_be_gate_evidence` and `payroll_be_decisions` (Super Admin records, no organisation, so no RLS policy —
like `payroll_source_artifacts`).

- **19 new tenant / worker tables**, all empty, each with row-level security ENABLED + FORCED and the tenant policy:
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
SELECT version_num FROM alembic_version;                       -- expect exactly: b7e4c2a9d5f1

-- 3.2 The 21 Belgian tables exist (19 tenant / worker + 2 platform)
SELECT count(*) FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name LIKE 'payroll\_be\_%';                   -- expect 21

-- 3.3 Row-level security is enabled AND forced on every one, each with a policy
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
       (SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) AS policies
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname LIKE 'payroll\_be\_%'
 ORDER BY c.relname;     -- expect t | t | >= 1 on the 19 tenant / worker tables; payroll_be_gate_evidence and
                         -- payroll_be_decisions are platform tables: f | f | 0 (no organisation, by design)

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

**Owner decision (2026-11-16): rollback = dormancy + fix-forward. The Belgian schema is permanent.**

Main's migration chain now **builds on the Belgian head**. The merge revision `cf348b09db2b` joins
`8a1f5ef9fa5d` (Belgium) with the Malaysian chain, so the three Belgian revisions can never be removed from the
history again. Main also keeps changing files that Belgium touched. A "revert all Belgian code" rollback cannot
stay deployable, as the recorded evidence below shows. Rolling back therefore never removes code or schema.

### 4.1 Switch Belgium off (no deploy, no database change)

1. Unset `BE_TENANT_ONBOARDING_ENABLED`, empty `BE_CANARY_ORG_IDS` and restart the backend. Every
   `/api/payroll/belgium` route then answers 404 for every organisation; this is the state proven by
   `tests/test_belgium_production_startup.py`.
2. Keep or return the registry row to **PLANNED**, through the governed transition; see
   `BELGIUM_ACTIVATION_RUNBOOK.md` §3. Organisations cannot onboard Belgium while it is PLANNED.
3. If a Belgian pack is Active, retire it through the governed pack workflow. That is a Super Admin action and is
   audited; it is never done by script.

Nothing else is needed. The Belgian tables and the two nullable columns stay, as they are additive and read only by
Belgian code. Existing Belgian data stays intact and auditable.

### 4.2 Fix forward

A Belgian defect is fixed by a normal change on top: a targeted fix, CI, merge, deploy. Belgian behaviour is behind
`country == "BE"` branches and the Belgian hooks (`BELGIUM_SECURITY_REVIEW.md` §3), so a fix stays local to
Belgium. If a shared (non-Belgian) path misbehaves because of a Belgian hunk, the fix removes or guards that hunk;
that is a code change, not a schema change.

### 4.3 Superseded: the code-only revert with a schema shim (Blocks I1 / J1, kept for the record)

- **I1** (2026-11-13) proved the pre-Belgium code works unchanged against a database with the Belgian schema
  (`scripts/be_rollback_orm_check.py`). It also proved that a plain `git revert` of the Belgium merge cannot be
  deployed, and added `scripts/belgium_rollback_shim.py` to make it deployable. **J1** ran that proof in CI.
- **2026-11-16:** after merging main (Malaysia, merge revision `cf348b09db2b`), the proof failed:
  - revert plus shim then fails the drift check (`payroll_runs.my_approval_fingerprint` is a Malaysian column that
    the pre-Belgium code does not know);
  - 13 pin tests fail, because the shim restores whole files that main has since changed.
  The CI step was removed (it would have blocked main's deploy for a scenario that is no longer the strategy) and
  the proof test deleted. The two scripts remain as tools; they are not part of the rollback procedure.
- **Schema removal is no longer possible:** the Belgian revisions are ancestors of other countries' migrations.
  The database backup in §1 remains the last resort for a failed deploy.

## 5. First manual steps after a good deploy (owner's decision; none is automatic)

Nothing Belgian is seeded by the deploy or by app startup (`docs/belgium/PROGRESS.md`, Block H2c). When the owner
decides to start content work:

1. **Run the post-deploy setup** on the backend host, from `backend/` with the venv active:

   ```bash
   python -m scripts.belgium_post_deploy_setup --environment production --dry-run    # plan + checks, writes nothing
   python -m scripts.belgium_post_deploy_setup --environment production --confirm    # do it (idempotent)
   ```

   It is create-only:
   - it ensures the BE registry row is **PLANNED** (an existing row is never changed);
   - it seeds the Draft `BE-PAYROLL-2026`, every row `[PENDING G1]`, if no Belgian pack exists;
   - it registers the S1–S24 sources;
   - it then prints the §3 checks as `PASS` / `FAIL`. Exit 0 means all passed; exit 2 means it refused.

   It never signs, approves, activates or assigns anything, sets no setting, never creates the DEMO pack (it refuses
   if `BE_DEMO_PACKS_ENABLED` is set in production) and touches no other country. `--environment` must match the
   process's `ENVIRONMENT`. Writes need `--confirm`.

   Console alternative (same result, inside the app): Super Admin → Belgium → **Overview** → "No Belgium pack yet"
   → reason → **Create the Draft pack**. This one does not register the sources separately; the pack seed does.
2. **Verify:** the setup's own output (§3.5 `PLANNED`, §3.6 no Active pack). Re-running it is safe and reports
   "nothing to do".
3. **Import the AI-drafted content, unsigned.** Console → Belgium → **Signing status** tab → "Content workbook (specialist intake)" → choose
   `docs/belgium/content/BE_2026_AI_DRAFT.xlsx` → **Dry run** → review the report → **Confirm import**. Rows
   arrive UNSIGNED with their sources. Signing is the Belgian specialist's job (four-eyes, per row,
   `BELGIUM_REVIEWER_GUIDE.md`). Nothing becomes Active.

Never on production: `scripts/seed_belgium_demo.py`, `BE_DEMO_PACKS_ENABLED` or `BE_DEMO_ORG_IDS`. The demo is
refused in a production environment anyway (`STAGING_REHEARSAL.md`).
