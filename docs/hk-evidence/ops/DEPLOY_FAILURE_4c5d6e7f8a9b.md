# Deploy failure: production database at unknown revision `4c5d6e7f8a9b`

**Status:** OPEN. **Do not restart the backend service on the production server until this is resolved** (§4).
**Prepared:** 2026-10-14 by engineering (Claude), with no production access of any kind. Everything below comes from the repository, the deploy workflow, and local copies.

## 1. What happened

1. PR #91 (`nikhil`) was merged into `main` (`2be8802`). `main` has 190 migrations and one head, `8b14824fb575`.
2. The push to `main` triggered `.github/workflows/backend-deploy.yml` (job 115732289310). The `test` job passed. The `deploy` job connected to the server over SSH and ran:
   * `git fetch` / `git checkout` / `git pull` (the server's working tree moved to `main`);
   * then `scripts/deploy_migrate.sh`.
3. Production's `alembic_version` row is **`4c5d6e7f8a9b`**. That revision exists in no migration file in `main`, so `deploy_migrate.sh` treated it as an orphan. It then checked, read-only, whether the live schema matches the models, found it does not, and **refused to stamp** (exit 1). That is correct behaviour: production really is behind `main` (it lacks `main`'s Netherlands, Saudi and HK tables), so stamping would have hidden migrations that never ran.
4. `set -euo pipefail` stopped the script **before** `sudo systemctl restart zoiko-payroll-backend`. The **running process is still the old code**, but the **files on disk are now `main`** (§4).

## 2. Where `4c5d6e7f8a9b` came from: what is known

Searched on 2026-10-14; **not found anywhere reachable**:

| Place | Result |
|---|---|
| Every branch tip on GitHub (`main`, `nikhil`, `venu`, `ravi_changes`, `rugvedh` and the rest) and every local branch | not present |
| Full history of every ref, reflogs and the stash (`git log --all --reflog -S 4c5d6e7f8a9b`) | not present |
| 552 unreachable / dangling git objects in this clone | not present |
| Deleted or renamed migration files anywhere in history (`--diff-filter=DR`) | none with this id (the only renames are older France / Germany ids and two stubs) |
| Other repositories on this machine: `D:\project Zoiko\zoiko-payroll-platform` (older clone, last commit 2026-09-01), `Zoiko-one_Billing`, `zoiko-one-backend`, `Nk` | not present |
| Every file under `D:\zoiko_payroll_platform`, `D:\project Zoiko` and the Claude scratch folders | not present |
| All 168 Claude Code session logs for this machine | The id first appears in the user's message of 2026-10-14 07:26 UTC; every later occurrence is a search. **Claude never authored a migration, file or command that created `4c5d6e7f8a9b`** |

So the migration was applied to production **from code that was never pushed to GitHub**, on some other machine.

## 3. How code and migrations reach production

**Through the deploy workflow (as written on `main` today):**
* The `deploy` job runs only for `push` events (`if: github.event_name == 'push'`) on `main` or `rugvedh`, and only when `backend/**`, `.github/workflows/**` or `scripts/**` changed. A pull request runs only the tests. **A `workflow_dispatch` run cannot deploy**, because its event is not `push`.
* On the server, the script picks the branch with `TARGET_BRANCH="${GITHUB_REF_NAME:-main}"`. That script runs on the remote host, and `appleboy/ssh-action` passes no runner variables unless `envs:` is set (it is not). So `GITHUB_REF_NAME` is empty there and **the server always deploys `main`, even for a push to `rugvedh`**. The deploy log's `git rev-parse HEAD` line confirms which commit was deployed. Please check it for the 2026-10 runs (§5.3).

**Outside the workflow (the likely route for `4c5d6e7f8a9b`, and earlier for `b08f04497195`):** any machine whose `backend/.env` holds the production `PAYROLL_DATABASE_URL` migrates production when someone runs `alembic upgrade head` (or the app's own startup / seed scripts) there. This machine's `backend/.env` does point at production. That is how the 2026-10-13 schema copy could be taken from here, and why every local test run in this project overrides the URL. A developer running Alembic on an unpushed branch with such a `.env` would produce exactly this state.

## 4. What NOT to do on the server

* **Do not restart `zoiko-payroll-backend`, and do not reboot the VM.** The files on disk are `main`, the database is not, and a restart would start the new code on the old schema (missing tables, failing requests).
* **Do not run** `alembic stamp`, `alembic upgrade`, `deploy_migrate.sh`, or any seed script against production.
* **Do not create a placeholder migration** called `4c5d6e7f8a9b` with a guessed parent.
* Do not re-run the failed deploy job until this is resolved. It would pull and refuse again, which is harmless but noisy.
* If the server must be stabilised before the fix: `git -C /var/www/zoiko-payroll/backend checkout <previous deployed commit>` puts the files back to match the running process. Find that commit in the previous successful deploy's log (`git rev-parse HEAD` line). **Read-only first: confirm it with the team before running it.**

## 5. Read-only steps for a human (in this order)

1. **Schema inventory.** From a machine with production read access (credentials never in the repository):
   ```bash
   PGOPTIONS="-c default_transaction_read_only=on" \
   psql "$PROD_READONLY_URL" -X -A -t -F '|' -f backend/scripts/hk_prod_migration_forensics.sql -o prod_schema_inventory.txt
   LC_ALL=C sort -o prod_schema_inventory.txt prod_schema_inventory.txt
   diff docs/hk-evidence/ops/forensics/reference_prod_2026-10-13_b08f04497195.txt prod_schema_inventory.txt > changed_since_2026-10-13.diff
   diff docs/hk-evidence/ops/forensics/reference_main_head_8b14824fb575.txt prod_schema_inventory.txt > prod_vs_main.diff
   ```
   The SQL reads only system catalogs and the one-row `alembic_version`, never personal data. Keep all three files.
2. **Drift report on the server** (read-only; it prints what the models expect and the database lacks): `cd /var/www/zoiko-payroll/backend/backend && source venv/bin/activate && python -m scripts.check_schema_drift > drift_2026-10-14.txt 2>&1`. Keep the file.
3. **Actions history** (`gh` is not installed on the engineering machine, so a person runs this): `gh run list --repo ZoikoGroup/zoiko-payroll-platform --workflow backend-deploy.yml --limit 100 --json databaseId,headBranch,headSha,event,displayTitle,actor,conclusion,createdAt`. Alternatively, in GitHub → Actions → "Deploy Zoiko Payroll Backend", filter to runs since 2026-10-10. For each run, note the id, branch, commit, actor, trigger and result. For each deploy run, also note the `git rev-parse HEAD` and "Database alembic_version" lines from its log.
4. **Ask the team** (venu, ravi, rugvedh, and anyone else with production database access):
   * Does anyone have a migration file containing `4c5d6e7f8a9b`, committed or not, including stashes and other clones? Search with `git log --all --reflog -S 4c5d6e7f8a9b` and `grep -r 4c5d6e7f8a9b backend/alembic`.
   * Did anyone run `alembic upgrade`, a seed script or the app against production from their own machine since 2026-10-13?
   * Does anyone's local `backend/.env` point `PAYROLL_DATABASE_URL` at production? It should not (`INCIDENT_F10_test_emails.md` §6d covers the same file).
5. Send `prod_schema_inventory.txt`, both diffs, `drift_2026-10-14.txt` and the run list to engineering.

## 6. How it will be fixed

* **If the file is found:** engineering adds it **byte-identical** (same revision id, original parent), then adds an Alembic **merge** revision joining it to `main`'s head, so there is exactly one head. Before any production step, this is proven on a local database rebuilt along the original chain: up to `4c5d6e7f8a9b`, then `upgrade head`, downgrade one step, re-upgrade, and `check_schema_drift`.
* **If it is not found:** no migration is written until the inventory diff (step 5.1) shows exactly what production has that `main`'s chain does not. Reconstruction then needs from that output:
  * the exact objects `4c5d6e7f8a9b` created or changed (tables, columns with types, nullability and defaults, indexes, constraints, enums, triggers);
  * whether production applied any of `main`'s own post-`b08f04497195` migrations (for example `c7d3e8f1a2b4` or Netherlands M1–M7) under a different id;
  * the parent the author used (from the author, or inferred from which objects exist).

  Only then can a migration with id `4c5d6e7f8a9b` and a parent consistent with the real history be written, rehearsed on a schema-only copy built from that inventory, and reviewed. That copy is created by a human, as before.

## 7. Prevention

`patches/deploy_guard.patch` (proposed, not applied) and the CI check in `backend/tests/test_alembic_metadata.py` (committed). The single most effective control is outside the repository: **no developer machine should hold production database credentials.**
