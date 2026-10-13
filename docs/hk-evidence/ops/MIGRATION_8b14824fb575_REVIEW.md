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
  * check the size: `SELECT count(*) FROM assisted_access_sessions;`
  * run the migration with `SET lock_timeout = '5s'`, so it fails fast instead of queueing behind a long transaction and blocking `users` writes.

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
