# Incident 2026-10-19 — orphan alembic revision `e1a3c5e7f9b2` in production (closure note)

**Status:** closed on 2026-10-21 (PR #116 deployed). Process questions for the lead are open (§5).

**Basis:** repository history, GitHub Actions run records (public API), `docs/mexico/PRODUCTION_STATE.md`, and the deploy-step log text the team pasted from the Actions UI. **Facts only.** Where something is not known, this note says so.

## 1. What happened

| Time (UTC) | Fact |
|---|---|
| 2026-10-19 09:05 | PR #111 deploy (Mexico 9a): production `alembic_version` = `f5c1a8d3e9b2`. |
| 2026-10-19, between 09:05 and 12:04 | Production `alembic_version` became **`e1a3c5e7f9b2`**, outside the CI pipeline. The `rugvedh` branch had **no workflow run that day before 12:15:25**, and `main` had none that applied it. |
| 2026-10-19 12:04 | The PR #112 deploy (run `39245798162`, Mexico 9b) found `e1a3c5e7f9b2` and failed at the SSH step. |
| 2026-10-19 12:11:28 | Commit **`3c85325`** (author and committer time; Rugvedh, "ZP-PRIV-VERIFY-001: default-deny tenant privacy, JIT support access, security plane") added the five ZP-PRIV revisions `a7c3e91f2b60` → `b2f4d6a8c0e1` → `c5e7a9b1d3f4` → **`d7f9b1c3e5a6`** (row-level security) → **`e1a3c5e7f9b2`** (the tip), and `scripts/migrate_privacy_rollout.py`, the script that applies exactly `f5c1a8d3e9b2 .. e1a3c5e7f9b2`. **The schema write came before the commit.** |
| 2026-10-19 12:15 and 12:59 | The first pushes to `rugvedh` that day (`530badd`, `84156a6`). Their backend deploy runs (`39250633751`, `39256323315`) **failed**; their frontend build runs succeeded. |
| 2026-10-19 12:24 | PR #114 (deploy-script fix, run `39251832330`) failed at the SSH step. |
| 2026-10-21 07:19 | PR #115 (ZP-PRIV + Mexico 9b–9d, run `39561229230`): the backend deploy failed; the frontend build `39561229234` succeeded and **was deployed**. |
| 2026-10-21 08:18 | PR #116 (run `39568307882`) deployed the corrected merge revision. Production went from `e1a3c5e7f9b2` to `c6e1a9d4f2b7`. **Closed.** |

**What `e1a3c5e7f9b2` was.** It was the tip of the ZP-PRIV privacy chain, not a single migration. Moving production to it also applied `d7f9b1c3e5a6`, which runs `ENABLE` + `FORCE ROW LEVEL SECURITY` with a `zoiko_rls` policy on the tenant and worker tables, as well as new columns on existing tables (`users`, `payroll_employees`, `organizations`).

**How it was applied.** It is not known who ran it. `PRODUCTION_STATE.md` records it as applied with `scripts/migrate_privacy_rollout.py`. That script runs `alembic upgrade head` in a subprocess with the caller's environment plus `ZP_RLS_UNSET_MODE=system`.

## 2. Why the safeguards did not see it

- **The drift check cannot see row-level security.** `scripts/check_schema_drift.py` compares **tables and columns** with the models. It does not read `relrowsecurity`, `relforcerowsecurity` or `pg_policies`, so RLS enabled outside the pipeline produces no drift. The extra columns on existing tables *were* visible to it.
- **The orphan self-heal in `scripts/deploy_migrate.sh`** stamps a revision that is not in `alembic/versions` back to the last revision whose objects exist, and only after a read-only drift check passes. Here it refused, correctly, because the schema did not match the models.

## 3. Consequences

| Run | Consequence |
|---|---|
| PR #112 (`39245798162`) | Backend deploy failed: orphan revision. The self-heal refused, because the drift check also counted the deploy's own new table (`payroll_mx_vacation_records`). Production database unchanged; the server pulled the 9b code but was not restarted. |
| PR #114 (`39251832330`) | Backend deploy failed again. The fixed self-heal (`drift_pending_filter.py`) ignored the deploy's own objects but still refused, **correctly**, on the ZP-PRIV columns the models did not know. |
| PR #115 (`39561229230`) | Backend deploy failed: `LockNotAvailable` on `ALTER TABLE "users" ENABLE ROW LEVEL SECURITY`. The merge revision `c3e5a7b9d1f4` re-ran `apply_rls()` over every table (taking an ACCESS EXCLUSIVE lock on each) and hit the 5 s `lock_timeout` on `users`. The migration transaction rolled back; production stayed at `e1a3c5e7f9b2`. **The frontend was deployed anyway**, so the new frontend ran against the old backend from 07:22 to 08:59. |
| PR #116 (`39568307882`) | Fixed: `c3e5a7b9d1f4` corrected to protect only the one table merged in (`payroll_mx_vacation_records`) with a fixed predicate. This was proved on PostgreSQL 17 with a live reader on `users` (`tests/test_privacy_mexico_merge_migration.py`) and then deployed. Production went from `e1a3c5e7f9b2` through 9b and the merge revision to 9c and 9d (`c6e1a9d4f2b7`). |

No data loss is recorded. Every failed migration ran in one transaction and rolled back.

## 4. What changed afterwards

- `scripts/drift_pending_filter.py`: the orphan self-heal ignores only objects the pending migrations create (PR #114).
- Merge revision `c3e5a7b9d1f4`: RLS is applied to new tables only, with fixed predicates. Later Mexico migrations follow the same rule (`a1d5e8c2f7b4`, `b3f7c1e9d5a2`).
- A PostgreSQL 17 test of the upgrade path from production's revision, with a live reader on `users`.

## 5. Open process questions for the lead

1. **How was a schema write from outside the pipeline possible?** `alembic/env.py` refuses `upgrade`, `downgrade` and `stamp` against a non-local database unless `ZOIKO_ALLOW_REMOTE_MIGRATIONS=I_UNDERSTAND` is set (`scripts/_local_db_guard.py`, in place since 2026-10-15, commit `d59508c`). The guard also lets the write through when the database URL's host is a **loopback** address. So either the override was set, or the command ran where production's database is reachable on a loopback address (for example, on the server or through a tunnel). Which one applied is not known.
2. **The automatic self-heal policy.** `deploy_migrate.sh` will re-stamp `alembic_version` on its own when a revision is not in the repository and the column-level drift check passes. Since that check cannot see RLS, policies, indexes or constraints, should an orphan revision **stop** the deploy for a human decision instead of being healed automatically?
3. **Frontend deployed while the backend failed (PR #115).** `frontend-build.yml` runs independently of `backend-deploy.yml`, so a failed backend deploy does not hold the frontend back. Should the frontend deploy depend on a successful backend deploy?
4. **Deploys from `rugvedh`.** `backend-deploy.yml` and `frontend-build.yml` also trigger on pushes to `rugvedh`, not only `main`.
5. **The remote-migration guard trusts a loopback host.** `is_local_database()` treats any `127.0.0.1` / `localhost` URL as local, and an SSH tunnel (for example `ssh -L 5432:<db-host>:5432 …`) makes the production database look exactly like `127.0.0.1`. The guard therefore cannot tell a developer's local database from production reached through a tunnel. **Proposal, not built:** a database-side environment marker — a one-row table (for example `zoiko_environment(name)`) written once per environment by the platform team, reading `production` there. `alembic/env.py` reads it on the opened connection **before** any write command; when it reads `production` it refuses `upgrade` / `downgrade` / `stamp` unless the pipeline override `ZOIKO_ALLOW_REMOTE_MIGRATIONS=I_UNDERSTAND` is set, whatever the host looks like. A database with no marker behaves as today. Writing the marker, and who may change it, is the lead's decision.
