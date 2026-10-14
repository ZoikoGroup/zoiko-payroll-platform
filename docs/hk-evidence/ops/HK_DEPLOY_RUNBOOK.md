# Hong Kong deploy runbook (nikhil → main → production)

**Prepared:** 2026-10-14 by engineering. **Nothing in this runbook has been run against staging or production.** Every rehearsal result quoted here comes from local copies.
**Scope:** deploying the HK launch-readiness code and migration `8b14824fb575`. It does **not** activate HK. The service stays PLANNED and the packs stay Draft until G1–G7 are accepted (`../SIGNOFF_PACKETS/`).

## 0. How code reaches production here

The `backend-deploy.yml` workflow deploys on a push to `main` (or `rugvedh`). It runs the full test suite and **refuses more than one Alembic head**. It then runs `scripts/deploy_migrate.sh` on the server (`alembic upgrade head`) and restarts the service.

So deploying means merging `nikhil` into `main`. As of 2026-10-14, `origin/main` has its own migrations after `b08f04497195`:
* `c7d3e8f1a2b4` (Saudi approval fingerprint);
* 8 Netherlands migrations, ending at `2f905bb1c296`.

`8b14824fb575` also hangs off `b08f04497195`, so the merge would create **two heads**, and CI would refuse it. The merge must therefore re-parent `8b14824fb575` onto `main`'s head: `patches/reparent_8b14824fb575_onto_main_head.patch`, a two-line change.

**Proven locally on 2026-10-14** on a fresh copy of the production schema at `b08f04497195` (`scratchpad/rehearse/rehearsal_2026-10-14.json`, SHA-256 `3b1b8d3d7a66e89d2e4165f1afac7e25edd51345f1cfe4c0c5ea8e1ee74a8219`):
* a single head;
* `upgrade head` ran `c7d3e8f1a2b4` → … → `2f905bb1c296` → `8b14824fb575`, exit 0;
* `downgrade 2f905bb1c296` exit 0;
* re-upgrade exit 0;
* both new tables and all 9 new columns present after each upgrade and absent after the downgrade.

If `main` gains more migrations before the merge, re-parent onto the new head and re-run that rehearsal.

**Update 2026-10-14:** `main` was merged into `nikhil` on GitHub (`02070f8`), and that merge left two heads, which failed the PR's CI test job. The re-parent patch is now **applied on `nikhil`**, together with the fixed pins in `test_alembic_metadata.py` (a single head `8b14824fb575`, 190 revisions) and the restored snapshot fixture. P-3 now holds on `nikhil` itself.

## 1. Pre-checks (all must pass; a human runs each)

| # | Check | How | Pass when |
|---|---|---|---|
| P-1 | Production revision and HK state | `cd backend && python -m scripts.hk_production_readonly_verification --out pre_deploy.json` (read-only session, SELECT-only; `../ops/HK_production_readonly_verification_instructions.md`) | `alembic_version` is a revision on `main`'s chain (expected `b08f04497195` or later); HK registry PLANNED; no HK pack Active |
| P-2 | Row count for the migration's only scan | the same report, check `pre_deploy_assisted_access_sessions_size` | `exact_rows` is modest. Measured locally: 2,000,000 rows validate in about 0.3 s. Above about 1,000,000 rows, stop: engineering writes a **new** migration (constraint `NOT VALID`, `VALIDATE` later). `8b14824fb575` itself must not be edited, and the old lock-safety patch is OBSOLETE |
| P-3 | Exactly one Alembic head on the merge commit | `cd backend && alembic heads` | one line: `8b14824fb575 (head)` |
| P-4 | Backup | Take a provider snapshot / branch or a point-in-time restore marker of the production database, and **test that it can be restored** (to a scratch instance) | restore point recorded (time + id) |
| P-5 | Identity key | `HK_IDENTITY_TOKEN_KEY` provisioned as a separate secret in production (`HK_IDENTITY_TOKEN_KEY_provisioning.md`, decision D-5) | present in the production environment; never in the repository |
| P-6 | Environment flag (F-10) | the production environment sets `ENVIRONMENT=production`. Check what `GET /api/health/version` reports for `environment` | `production`. **If it says `unset` and `DEBUG` is not `false`, the new outbound guard treats the server as local and blocks all email.** Set `ENVIRONMENT=production` first |
| P-7 | Real mail only in production | the production environment has the real `SMTP_*` settings; **no** developer `backend/.env` holds real SMTP credentials (`INCIDENT_F10_test_emails.md` §6d) | confirmed by Ops / Security |
| P-8 | Durable storage (F-8) | `PAYROLL_GCS_BUCKET` set (with `PAYROLL_STORAGE_BACKEND` `auto` or `gcs`), and the service account can write to it | set. Otherwise evidence and HK document uploads are refused in production, by design |
| P-9 | Full test suite on the merge commit | CI `test` job, or locally `python -m pytest tests/ -q` | 0 failed |
| P-10 | Staging rehearsal | §6 below | done, with timings recorded |

## 2. Migration

1. Merge `nikhil` into `main` through a reviewed PR, with the re-parent patch applied in the merge, and confirm P-3 on the merge commit.
2. Optional: set a lock timeout for the deploy's migration step, so it fails fast instead of queueing behind a long transaction. Set `PGOPTIONS="-c lock_timeout=5s"` in the deploy environment (a deploy-workflow change, owned by whoever runs CI/CD).
3. The deploy job runs `scripts/deploy_migrate.sh`, which runs `alembic upgrade head` and checks for drift. Expected:
   * `c7d3e8f1a2b4` and the NL migrations, if production is still at `b08f04497195`. These are other teams' migrations, and their size and locks are **not** reviewed here;
   * then `8b14824fb575`.

## 3. Deploy and HK seed

1. The deploy job restarts the backend. Watch the job to the end: earlier deploys failed at the SSH / restart step.
2. Re-run the canonical HK seed **on the Draft packs only**, so the governed row `mpf_contribution_day_deferral` exists in production: `cd backend && python -m scripts.seed_hong_kong_canonical_pack`. The seed refuses non-Draft packs and keeps `HK_GENERAL_HOLIDAY` rows.
3. Do **not** load general holidays until the specialist has supplied the official files (packet 01).

## 4. Smoke checks (after deploy)

| # | Check | Pass when |
|---|---|---|
| S-1 | `GET /api/health/version` | `commit` = the merge commit; `environment` = `production` |
| S-2 | `alembic current` on the server | `8b14824fb575 (head)` |
| S-3 | Read-only verification again (`hk_production_readonly_verification`) | HK registry PLANNED; packs Draft; `alembic_version` = `8b14824fb575` |
| S-4 | Super Admin → Jurisdictions → Hong Kong | the Statutory Summary & Gates page loads; each gate shows **Evidence (n)**; Contribution-day disruptions is visible |
| S-5 | Super Admin → Alerts | the page loads; no unexpected Security alerts |
| S-6 | Email | one routine notification to an internal mailbox. The server log shows `[email] Sent to …`, **not** `[outbound] BLOCKED` |
| S-7 | Upload storage | a test evidence upload on a scratch tag is stored in GCS. Remove it afterwards through supersession, not deletion |

**S-8 (after a successful deploy):** a Super Admin runs Test Certification for HK (Hong Kong → Test Certification → Run Now). Expect **PASS 11/11**, then the blocker list in `../ACTIVATION_READINESS.md` (30 items on 2026-10-14) under Statutory Summary & Gates.

**Deploy blocked (2026-10-14):** production is at an unknown revision `4c5d6e7f8a9b`. Do not deploy, restart or migrate until `DEPLOY_FAILURE_4c5d6e7f8a9b.md` is resolved.

## 5. Upload kit

Super Admin A uploads the 32 drafts and B reviews them later (`../SIGNOFF_PACKETS/09_SuperAdmin_upload_and_review.md`, `../UPLOAD_KIT/UPLOAD_GUIDE.md`). Then run `python -m scripts.hk_verify_evidence_upload ../docs/hk-evidence/UPLOAD_KIT/manifest.csv --out hk_upload_check.json` and upload its output under `HK-PRODUCTION-VERIFICATION`.

## 6. Rollback

| Situation | Action |
|---|---|
| The migration fails | `deploy_migrate.sh` stops before the restart and the old code keeps running. Fix and redeploy. Nothing to undo: Alembic runs the migration in one transaction |
| The new code misbehaves; the schema is fine | Revert the merge on `main` (new revert commit) → CI redeploys the previous code. The extra tables and columns are harmless to the old code (additive) |
| The schema must go back | With a lock timeout set: `alembic downgrade 2f905bb1c296` (the parent in the merged chain). This **drops** `payroll_user_permissions` (including all HK_MPF_ACCOUNT_REVEAL grants), `payroll_hk_contribution_day_disruptions`, and the 9 consent / break-glass columns. Audit events survive (`MIGRATION_8b14824fb575_REVIEW.md` §4) |
| Data damaged | Restore from the P-4 restore point (owner + Ops decision) |

## 7. Staging rehearsal checklist (before P-10 is ticked)

There is no provisioned staging environment (`backend-deploy-staging.yml` is a proposal), so use a scratch database.

- [ ] A human takes a **read-only, schema-only** dump of production (`MIGRATION_ALIGNMENT_NOTE.md` shows the commands) on the day of the deploy, and restores it into a scratch PostgreSQL 14 database.
- [ ] Optionally load representative row counts into `assisted_access_sessions` (synthetic), up to the P-2 figure.
- [ ] Check out the merge commit. `alembic heads` shows one head.
- [ ] `alembic upgrade head`, `alembic downgrade <main head>`, `alembic upgrade head`, each with exit 0. Record the timings.
- [ ] Start the backend against the scratch database with `ENVIRONMENT=development` and **no** real SMTP settings. Mail must log `BLOCKED`. Run smoke checks S-3 to S-5.
- [ ] Rehearse the upload kit: verify → 32 MISSING; register all items; verify → 32 MATCH; tamper with one digest → DIGEST_MISMATCH.
- [ ] Record the results, with command, time and output digest, and attach them to the deploy PR.

## Sign-off (leave blank)

| Role | Name | Date | Signature |
|---|---|---|---|
| Deploy owner | | | |
| Engineering lead | | | |
