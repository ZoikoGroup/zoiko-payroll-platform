# Deployment Alembic Migration Fix

## Current Workspace

```
D:\zoiko_payroll_platform\zpp-nikhil-extract
```

## Branch

```
nikhil
```

## Incident

The GitHub Actions job **"Deploy Zoiko Payroll Backend"** (repository
`ZoikoGroup/zoiko-payroll-platform`, workflow `.github/workflows/backend-deploy.yml`)
fails during `alembic upgrade head` on the production server.

## Exact Error

```
alembic.util.exc.CommandError: Can't locate revision identified by 'f61cb4b650f4'
FAILED: Can't locate revision identified by 'f61cb4b650f4'
```

Alembic could not resolve the revision recorded in the production database's
`alembic_version` table because no migration file with revision
`f61cb4b650f4` exists in this repository.

## Root Cause

The production PostgreSQL database's `alembic_version` table records
`f61cb4b650f4` as its current revision, but **no migration with that revision
id has ever existed in this repository** (any branch, any tag, any reflog, any
unreachable object). The value is an **orphaned revision** left over from an
un-tracked and no-longer-present migration lineage that was used to build the
production database.

A read-only structural audit of the live production database shows that its
actual schema content corresponds to the migration chain state
`c7d8e9f0a1b2` (the pre-Germany head of `origin/main`; the comparison stands
regardless of later merges):

* Every object (table/column/index) created by every migration from the chain
  base `0b624a4a7481` through `c7d8e9f0a1b2` already exists in production.
* Every object created by `d3e4f5a6b7c8` (the unique constraint
  `uq_germany_elstam_change_list_batch_org_ref`) or any later migration
  (`e4f5a6b7c8d9` ELSTER tables, `f5a6b7c8d9e0` minijob/midijob table,
  `1a2b3c4d5e6f` payslip `soli` column, `2b3c4d5e6f70` overtime wage-tax delta
  columns) is absent from production.

So the recorded revision is an orphan, while the real schema state is exactly
`c7d8e9f0a1b2`. Without a migration file named `f61cb4b650f4`, every alembic
command fails and the deployment cannot proceed.

## Evidence

| # | Evidence | Result |
|---|---|---|
| 1 | `git grep f61cb4b650f4` across the whole working tree | no match |
| 2 | `git grep f61cb4b` across all tracked files | no match |
| 3 | `git log --all -S/-G f61cb4b650f4` (and reflogs) | no commit ever introduced/removed it |
| 4 | `git fsck --unreachable` + blob content scan for `f61cb4b` | no unreachable object contains it |
| 5 | Alembic `ScriptDirectory` parse of every migration's `revision`/`down_revision` | only 72 distinct ids ever existed; `f61cb4b650f4` never one of them |
| 6 | Version-dir collation (pre-fix) `origin/main` vs `origin/nikhil` | main lacked the 5 head-chain migrations; nikhil carried them |
| 6b | Version-dir collation (fix time) `origin/main` = `e47fc7e` vs `origin/nikhil` = `a2d8fa5` | both contain 73 identical migration files — PR #34 already merged nikhil's Germany chain onto main (`5b38499`); neither contains the graft `f61cb4b650f4` |
| 7 | `alembic current` (read-only) against production | error `Can't locate revision identified by 'f61cb4b650f4'` before the fix; prints `f61cb4b650f4` after the fix |
| 8 | Read-only production schema audit (105 tables) mapping every migration's created objects to the DB | DB matches chain-state `c7d8e9f0a1b2` exactly; `d3e4f5a6b7c8`..`2b3c4d5e6f70` objects absent |
| 9 | Read-only check `payroll_germany_elstam_change_list_batches` | 0 rows (so the `d3e4f5a6b7c8` unique constraint can be created cleanly) |

## Missing Migration Investigation

`f61cb4b650f4` is not a migration that was deleted, renamed, or moved; it is
not present in another branch, an older commit, or the object store. It is a
**bookkeeping value written by an external/older lineage** that was never part
of this repository. Because the original file is permanently unavailable (it
never existed here), it cannot be "restored". The only correct resolution is a
**graft** — a no-op revision that re-attaches the orphaned version onto the
real chain at the point where the production schema provably sits.

## Migration Graph Before Fix

As deployed (from `origin/main`):

```
base 0b624a4a7481
heads (single): c7d8e9f0a1b2
revisions: 68
revision f61cb4b650f4:  NOT PRESENT
→ database current version f61cb4b650f4 cannot be resolved
```

## Migration Graph After Fix

On `nikhil` (the graft, the re-parent and the workflow edit must land on
`main` together — see "Remote Repository State" below):

```
base 0b624a4a7481
heads (single): 2b3c4d5e6f70
revisions: 74
...
c7d8e9f0a1b2  (mergepoint, no-op)
  └─ f61cb4b650f4  (NEW graft, no-op — re-attaches production version)
       └─ d3e4f5a6b7c8  (unique constraint)
            └─ e4f5a6b7c8d9  (ELSTER tables)
                 └─ f5a6b7c8d9e0  (minijob/midijob table)
                      └─ 1a2b3c4d5e6f  (payslip_items.soli)
                           └─ 2b3c4d5e6f70  (head — overtime tax deltas)
```

`alembic heads` → `2b3c4d5e6f70 (head)` (single head, no new branches).
The upgrade path from the production version is now exactly:

```
f61cb4b650f4 -> d3e4f5a6b7c8 -> e4f5a6b7c8d9 -> f5a6b7c8d9e0 -> 1a2b3c4d5e6f -> 2b3c4d5e6f70
```

All five migrations create objects that are currently absent from production;
none conflicts with an existing object.

## Remote Repository State at Fix Time

* `origin/main` = `e47fc7e` (merge of PR #35, "billing module"). PR #34
  (nikhil → main, merge `5b38499`) already merged the five Germany head-chain
  migrations onto `main`, so `main` and `nikhil` now have an identical set of
  73 migration files (single head `2b3c4d5e6f70`).
* `main` is internally consistent but does **not** contain the graft
  `f61cb4b650f4` nor the re-parented `d3e4f5a6b7c8`, so a deploy from current
  `main` still fails with `Can't locate revision identified by 'f61cb4b650f4'`.
* The graft, the `d3e4f5a6b7c8` re-parent and the workflow edit must land on
  `main` as a single unit (delivered here as one commit on `nikhil`):
  graft-without-re-parent would create a second head, and re-parent-without-
  graft would reference a non-existent revision.
* `.github/workflows/backend-deploy.yml` triggers **only** on `push` to
  `main` (paths `backend/**`) and the server deploys `git pull origin main`.
  Pushing `nikhil` therefore does not by itself trigger the deployment; the
  next `main` push/PR (with this commit) triggers the run that executes
  `alembic upgrade head` against production.

## GitHub Actions Evidence (public API, at fix time)

| Run # | head_sha | Event | Conclusion |
|---|---|---|---|
| 13 | `e47fc7e` (`main`, merge PR #35) | push | **failure** |
| 12 | `5b38499` (`main`, merge PR #34) | push | **failure** |
| 11 | `0c57e3b` (`main`, pre-Germany-chain) | push | success |
| 10 | `0501303` (`main`) | push | **failure** |

The two most recent `main` deployments fail exactly as documented (run with
the pre-fix workflow against a `main` that contains the Germany chain but not
the graft; production `alembic_version = f61cb4b650f4` cannot be resolved).
Pushing `nikhil` (commit `f8174a5`) created **no** workflow run, confirming
the trigger is `main`-only. Final deployment success therefore requires the
user to merge this `nikhil` commit onto `main` (this repository's normal
PR flow — see PRs #31/#34); that is an external action deliberately not
performed here (branch `main` is off-limits for this task).

## Files Changed

The changes for this fix are limited to the migration/deployment problem:

| File | Change |
|---|---|
| `backend/alembic/versions/f61cb4b650f4_germany_production_chain_recovery.py` | **NEW** graft revision `f61cb4b650f4` (no-op), `down_revision = c7d8e9f0a1b2` |
| `backend/alembic/versions/d3e4f5a6b7c8_add_germany_elstam_change_list_batch_uniqueness.py` | `down_revision` re-pointed from `c7d8e9f0a1b2` to `f61cb4b650f4` (keeps chain linear, single head) |
| `.github/workflows/backend-deploy.yml` | Added migration diagnostics, post-upgrade head verification, fail-closed restart behaviour |
| `docs/DEPLOYMENT_ALEMBIC_MIGRATION_FIX_REPORT.md` | This incident report |

No Germany payroll business logic was modified. All other working-tree
changes (engine, service, tests, frontend, docs) were left untouched.

## Deployment Workflow Changes

The workflow now follows the required principle and adds diagnostics:

1. pull deployable source (`origin main`)
2. install dependencies
3. inspect Alembic state: `git rev-parse HEAD`, `alembic heads`, `alembic branches`,
   `alembic history`, `alembic current` (read-only)
4. `alembic upgrade head`
5. verify final revision: post-upgrade `alembic current` must match `alembic heads`
   — otherwise the job fails **before** restarting the backend
6. restart backend only after a successful, verified migration

`set -euo pipefail` keeps the job fail-closed: if `alembic upgrade head` fails,
the deployment stops and the backend is **not** restarted. No secrets are
written to logs.

## Validation Results

Run from `backend/` (worktree = this repository, branch `nikhil`, alembic
1.13.1, SQLAlchemy 2.0.50):

| Check | Result |
|---|---|
| `alembic heads` | `2b3c4d5e6f70 (head)` — single head |
| `alembic branches` | 3 pre-existing branchpoints fully merged (no new branches) |
| `alembic history` | complete, terminates at `2b3c4d5e6f70` |
| Upgrade path from `f61cb4b650f4` | `d3e4f5a6b7c8 → e4f5a6b7c8d9 → f5a6b7c8d9e0 → 1a2b3c4d5e6f → 2b3c4d5e6f70` |
| `alembic current` (read-only, live DB) | resolves and prints `f61cb4b650f4` (was a hard failure before the fix) |
| `alembic check` (read-only, live DB) | runs; reports pre-existing model↔DB drift (DB not yet upgraded to head + historic create_all-era drift) — no writes performed |
| `alembic upgrade head` | NOT executed against production (requires operator authorization); safe-by-audit: all five pending migrations create only currently-absent objects; `payroll_germany_elstam_change_list_batches` has 0 rows so the `d3e4f5a6b7c8` unique constraint will be created cleanly |
| Tests (offline/hermetic, no prod DB touched) | `test_engine_standard.py`, `test_germany_elster.py`, `test_germany_minijob_midijob_parameters.py`, `test_germany_overtime_tax_delta.py` → **462 passed**, 6 pre-existing failures unrelated to this change |
| `git diff --check` | no whitespace errors |

Pre-existing test failures (not caused by this change; `GermanyStatutoryProfileMissingError`
and Germany church-tax default assertions in the modified working-tree tests):
`test_engine_standard.py` (3), `test_engine_jurisdiction_upgrade.py` (3).

## Production Database Verification

**VERIFIED (read-only inspection only).** The live production PostgreSQL
database (GCP host configured via `PAYROLL_DATABASE_URL`) was inspected in a
strictly read-only manner — no table was created/dropped/altered, no row was
written, `alembic_version` was not modified, and no `alembic upgrade`/`stamp`
was executed:

* `alembic_version` = `f61cb4b650f4` (the orphan confirmed live).
* 105 tables present; schema content matches chain-state `c7d8e9f0a1b2`.
* The five pending migrations' objects are absent (ELSTER tables, minijob
  table, `payslip_items.soli`, three overtime delta columns, and the
  `d3e4f5a6b7c8` unique constraint).

Because the database has NOT been modified, the deployment will repair it
automatically on the next successful run once this fix is merged to `main`:
`alembic upgrade head` will resolve `f61cb4b650f4`, apply the five additive
migrations, and only then will the workflow restart the backend.

**At the time of writing the production migration has NOT been executed** —
neither locally nor by a deployment (no `main` push carrying this commit has
occurred; the workflow triggers only on `main`). This statement will be
updated only when a GitHub Actions run actually applies the migrations.

No credentials, connection strings, or secrets are reproduced in this report
or in any log produced during the investigation.

## Recovery / Rollback

Recovery (executed by the deployment itself after this fix lands on `main`);
the same steps can be run manually by an authorized operator on the server:

```bash
cd /var/www/zoiko-payroll/backend/backend
source venv/bin/activate
alembic current        # expected: f61cb4b650f4 (resolves, no error)
alembic heads          # expected: 2b3c4d5e6f70 (head)
alembic upgrade head   # applies the 5 additive migrations
alembic current        # expected: 2b3c4d5e6f70
deactivate
```

Rollback of the *code* change: revert the merge/commit that introduced the
graft, `d3e4f5a6b7c8` re-parent and the workflow edit. Rollback of the
*schema* is not affected by this change — `alembic downgrade` remains the
mechanism for any future migration and the database state at head is simply
the current chain head.

## Prevention

* Never rewrite/rebase an Alembic revision id after a database has recorded it.
* Never re-initialize the Alembic chain for an existing database; reconcile
  schema state with the existing chain (e.g. `alembic stamp` against a
  provably-equivalent real revision, not hand-written ids).
* Keep the migration files under `backend/alembic/versions` that represent
  applied-production schema in sync with every deployment branch (`main`).
* The deploy workflow now fails fast with read-only diagnostics and refuses to
  restart the backend after a migration failure, avoiding silent drift.
* Follow-up (out of scope here, pre-existing): reconcile the remaining
  model↔DB drift (baseline-only tables such as `payroll_inbound_*` /
  `platform_statutory_rates`, and model-only columns) through explicit
  additive migrations; keep `create_all` for fresh databases only.