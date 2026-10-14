# Migration review — `8b14824fb575` (HK launch-readiness controls)

**Revises:** `b08f04497195` (production's current revision) · **Target:** PostgreSQL 14 (production `server_version` 14.24) · **Reviewed:** 2026-10-13
**Verdict: ADDITIVE ONLY. No data backfill, no rewrite of existing rows, no long lock expected.** Not a STOP condition. There is one caveat: production row counts were not available (see §3).

## 1. Every DDL statement

Alembic runs the whole migration in **one transaction**, so every lock below is held until the final COMMIT (`env.py` uses transactional DDL; the log shows "Will assume transactional DDL").

| # | Statement | Additive? | Backfill | Locks taken (PostgreSQL 14) | Work done |
|---|---|---|---|---|---|
| 1 | `CREATE TABLE payroll_user_permissions` (PK; FKs to `organizations.id`, `users.id` ×3) | Yes, new table | None | ACCESS EXCLUSIVE on the new (empty) table; **SHARE ROW EXCLUSIVE on `organizations` and `users`** to attach the FK triggers | Catalog only |
| 2–4 | `CREATE INDEX` ×3 on `payroll_user_permissions` | Yes | None | SHARE on the new empty table | Empty-table index build |
| 5 | `CREATE TABLE payroll_hk_contribution_day_disruptions` (unique `disruption_date`; FK to `users.id`) | Yes, new table | None | ACCESS EXCLUSIVE on the new table; SHARE ROW EXCLUSIVE on `users` | Catalog only |
| 6 | `CREATE INDEX ix_payroll_hk_contribution_day_disruptions_id` | Yes | None | SHARE on the new empty table | Empty |
| 7 | `ALTER TABLE assisted_access_sessions ADD COLUMN access_mode varchar(20) NOT NULL DEFAULT 'CONSENT'` | Yes | **None.** PG ≥ 11 stores a constant default in the catalog; no table rewrite | ACCESS EXCLUSIVE on `assisted_access_sessions` | Catalog only |
| 8 | `… ADD COLUMN approval_status varchar(20) NOT NULL DEFAULT 'APPROVED'` | Yes | None (same reason). Existing sessions read as APPROVED, so they behave exactly as before | ACCESS EXCLUSIVE (already held) | Catalog only |
| 9, 10, 12–15 | `… ADD COLUMN requested_minutes / request_expires_at / approved_at / decision_reason / activated_at / tenant_notified_at` (all nullable, no default) | Yes | None | ACCESS EXCLUSIVE (held) | Catalog only |
| 11 | `… ADD COLUMN approved_by_user_id integer REFERENCES users(id)` (nullable) | Yes | None | ACCESS EXCLUSIVE (held) + **SHARE ROW EXCLUSIVE on `users`** | FK validation: one pass over `assisted_access_sessions`; every value is NULL, so it is cheap and proportional to that table's row count |

There is nothing non-additive: no DROP, RENAME, type change, NOT NULL on a populated column without a default, or data UPDATE.

## 2. What is blocked while it runs

* **`assisted_access_sessions`** (ACCESS EXCLUSIVE): every read and write, i.e. support-session token checks and the banner status call, waits until COMMIT.
* **`users` and `organizations`** (SHARE ROW EXCLUSIVE): **writes** wait (login does not write `users`; user and organisation edits do). Reads are not blocked.
* The new tables have no users yet.

## 3. Expected duration

* **Row counts:** not available. The production copy used for rehearsal was `pg_dump --schema-only`, which carries no rows and no statistics, so the size of `assisted_access_sessions` is **unknown**. By design it holds one row per support session, so it is expected to be small, but that is an expectation, not a measurement.
* **Rehearsal on the schema-only copy (empty tables), 2026-10-13T06:41Z:** upgrade, downgrade and upgrade again were each well under a second (exit 0).
* **Expected in production:** catalog changes are milliseconds. The only row-proportional step is the FK validation in #11 (a scan of all-NULL values). Seconds at most, unless the table is unexpectedly large.
* **Recommended before deploy (read-only, by a human):**
  * check the size: run `python -m scripts.hk_production_readonly_verification --out pre_deploy.json` and read the check `pre_deploy_assisted_access_sessions_size`. It reports `exact_rows` (`count(*)`, one read-only scan under ACCESS SHARE), `estimated_rows` (`pg_class.reltuples`, no scan; -1 means the table has never been analysed) and `total_size`;
  * run the migration with `SET lock_timeout = '5s'`, so it fails fast instead of queueing behind a long transaction and blocking `users` writes.

### 3a. Which statement scans, and the measured cost (added 2026-10-14)

* **The statement:** #11, `ALTER TABLE assisted_access_sessions ADD COLUMN approved_by_user_id integer REFERENCES users(id)`.
* **Why it scans:** adding a foreign key makes PostgreSQL validate it against every existing row. The column is brand new, so every value is NULL and none can fail, but PostgreSQL still reads the whole table, and does so while the ACCESS EXCLUSIVE lock from `ADD COLUMN` is held. No other statement scans existing rows. The new tables are empty, and the two `NOT NULL DEFAULT` columns are catalog-only on PostgreSQL 11+.
* **Measured on a local copy of the production schema with 2,000,000 synthetic rows** (`scratchpad/rehearse/scan_test.py`, result `scan_test_2026-10-14.json`, SHA-256 `58d8670fadd6db42e4f54c6d35c77b5f94a04af24fdd39b7277dc27fd1e48d68`):

| Variant | Rows read from `assisted_access_sessions` during the migration | Upgrade wall time (incl. Alembic start-up) | Constraint | Bad user id rejected afterwards |
|---|---|---|---|---|
| As committed | **2,000,000** (one sequential scan) | 2.61 s | validated | yes |
| Patched (`patches/migration_lock_safety.patch`) | **0** | 3.32 s | `NOT VALID` (enforced for new writes) | yes |

  Wall times are dominated by Alembic start-up. A separate `VALIDATE CONSTRAINT` on the patched copy took **0.29 s** for 2,000,000 rows, so the scan in the committed migration costs roughly that much at that size.
* **Verdict:** the scan is real but cheap. A support-session table is expected to hold hundreds or thousands of rows, not millions. **The committed migration is acceptable** if the pre-deploy check shows a modest `exact_rows`. If `exact_rows` exceeds about 1,000,000, apply the patch first: the constraint is added `NOT VALID`, the scan is skipped, and the optional `ALTER TABLE assisted_access_sessions VALIDATE CONSTRAINT assisted_access_sessions_approved_by_user_id_fkey` can be run later under SHARE UPDATE EXCLUSIVE, which does not block reads or writes.
* **Patch evidence (applied temporarily to the working tree, then reverted, 2026-10-14):**
  * upgrade, downgrade and re-upgrade exit 0 on the production schema copy;
  * `tests/test_alembic_metadata.py`, `test_assisted_access.py` and `test_platform_shared_helper_snapshots.py`: 25 passed (03:53Z);
  * SQLite keeps the original path.

  The patch is **not committed**. Applying it is the reviewer's decision.

## 4. Downgrade behaviour (`alembic downgrade b08f04497195`)

* Drops the 9 `assisted_access_sessions` columns, then both new tables and their indexes.
* **Destroys data:**
  * consent / break-glass history columns (who approved, when, mode, notification time) on every session;
  * all `HK_MPF_ACCOUNT_REVEAL` grants;
  * all recorded signal days.

  The assisted-access audit events (`assisted_access_audit_events`) and `TaxConfigurationAudit` rows are **not** dropped, so the trail survives in those tables.
* After a downgrade, the deployed code must also be the pre-`8b14824fb575` code. The new code reads these columns and tables.
* Rehearsed clean on the schema copy (empty data).

## 5. Rollback steps (if the deploy must be undone)

1. Prefer **roll forward**. The migration is additive, and the previous application code does not read the new columns or tables, so the previous code runs fine against the upgraded schema. Redeploying the previous build is enough; leave the schema at `8b14824fb575`.
2. Only if the schema itself must go:
   1. take a backup;
   2. export the three affected data sets if needed: `payroll_user_permissions`, `payroll_hk_contribution_day_disruptions`, and the new `assisted_access_sessions` columns;
   3. deploy the previous code;
   4. run `alembic downgrade b08f04497195` with `lock_timeout` set;
   5. verify that `alembic current` = `b08f04497195`.
3. Re-run `scripts/hk_production_readonly_verification.py`. It expects the alembic revision in its check list. Update `EXPECTED_ALEMBIC_HEAD` in that script to `8b14824fb575` once deployed.

## Sign-off (blank until reviewed)

Engineering reviewer — Name / Role / Date / Signature: ________
DBA / Ops — Name / Role / Date / Signature: ________
