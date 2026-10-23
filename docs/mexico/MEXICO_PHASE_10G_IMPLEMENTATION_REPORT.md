# Mexico (MX) — Phase 10g Implementation Report: "No new Mexican organisations" switch, named RLS exceptions

Requested 2026-10-22 after the 10f merge. The request had three parts:
1. A four-eyes, audited switch that stops new organisations becoming Mexican. It is a general-availability precondition and is referenced in runbook §6.
2. The two-party RLS predicate of `payroll_mx_master_releases` registered as a named exception, so a re-run of `apply_rls()` cannot narrow it, with a PostgreSQL test proving it.
3. A CODEOWNERS proposal (not created).

> **Review required: Rugvedh, as ZP-PRIV owner, reviews this PR before it is merged.** It adds `backend/app/core/authz/rls_exceptions.py` (§3). His review of **Phase 10f (PR #123), merged before his review, is still pending**. Any change he asks for there must be merged **before any pilot grant is approved** (`PRODUCTION_STATE.md`, release checklist).

**Base.**
- `main` includes PR #123 (Phase 10f, `dbfef67`).
- Deploy run **39768322911** is **green**: tests 11:08:22–11:47:32Z; deploy 11:47:34–11:49:06Z, including `deploy_migrate.sh` and the head verification.
- The frontend build (39768322978) is green. Production should be at **`e5b1d8f3a7c2`** (confirm with `alembic current`).
- Recorded in `PRODUCTION_STATE.md`: the #123 row, plus the note that the ZP-PRIV review is pending after the fact.
- `nikhil` = `21eeca2` (10f).

**Alembic.**
- Before: a single head, `e5b1d8f3a7c2` (219 revisions).
- Now: a single head, **`f6c2a9d1e4b7`** (220 revisions).

**Git.** **Staged on `nikhil`, not committed**, as instructed.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,166 passed**, with the same 4 local-only failures as 10f, none Mexico (§7). |
| 10g tests | `test_mexico_onboarding_pause.py` (4), `test_mexico_onboarding_migrations.py` (6, of which 4 run on PostgreSQL) and `test_rls_named_exceptions.py` (3, of which 1 runs on PostgreSQL). All pass. |
| Migration on PostgreSQL 17 | 6/6, three runs. |
| Named exception, production upgrade path and m15 on PostgreSQL 17 | 12 passed. |
| Browser | **on 10/10** (§6). |
| ESLint / `check:undefined` / `vite build` | The new and changed files are clean. 565 files have no undefined names. The build passes. |
| Route registry | Regenerated. It adds **only the 4 pause routes**, all platform `super_admin`. No other route changed. |
| Manifest | Regenerated. It differs from `HEAD` by the one added m16 line. **`d7f9b1c3e5a6` is untouched.** |

## 2. The "no new Mexican organisations" switch

**Table.** `payroll_mx_onboarding_pauses` is platform configuration (no `organization_id`, so no RLS). Each row is one proposed change:
- `action`: PAUSE or RESUME.
- `status`: PROPOSED, APPROVED or WITHDRAWN.
- `reason`: required.
- Proposer, approver, approval time.

The current state is the **latest APPROVED change**. With no rows, the switch is **not paused**, so production behaviour is unchanged.

**Four-eyes and audit.**
- One Super Admin proposes PAUSE or RESUME with a reason. A **different** Super Admin approves; the proposer gets `MX_FOUR_EYES_REQUIRED`.
- Only one change can be PROPOSED at a time. A no-op (pausing while paused) is refused.
- The proposer or another Super Admin can withdraw a proposal.
- Every step is audited (`entity_type = "mx_onboarding_pause"`).

**What a pause does.**
- **An organisation entering Mexico is refused**, with the pause message. This covers the organisation country change and the company-jurisdiction change: both go through `mexico_dormancy.entering_mexico_refusal`.
- **A pilot grant cannot be approved.** "New Mexican organisations not paused (runbook §6)" is a pilot precondition.
- **General availability cannot be opened.** The same check is a GA precondition: the registry PLANNED → AVAILABLE is refused while paused. This is how "a general-availability precondition" is implemented.
- **Organisations that are already Mexican keep running.** Nothing that does not enter Mexico consults the switch.

The kill switch and the registry are unchanged. The pause only adds a refusal; it never opens anything.

**Screen.** Super Admin → Mexico → Readiness G1–G8 → **New Mexican organisations**:
- the state (OPEN / PAUSED);
- Propose pause / Propose resume, with a reason;
- the change history, with Approve and Withdraw.

Readiness also reports `onboardingPaused`.

**Routes** (Super Admin, platform):
- `GET /api/super-admin/compliance/mexico/onboarding-pause`
- `POST …/onboarding-pause`
- `POST …/onboarding-pause/{id}/approve`
- `POST …/onboarding-pause/{id}/withdraw`

**Runbook §6.**
- Step 3 now uses the switch (two Super Admins; existing organisations keep running). Moving the registry to PLANNED, or using the kill switch, is kept only for when live employers must also stop.
- The "follow-up (not built)" line is replaced by **Resuming** (four-eyes), plus the GA precondition.
- Step 4.4 lists "not paused".
- I also corrected the sentence under the table. It said every Mexico route refuses while paused, which is true only if the registry is also moved to PLANNED.

**Release checklist.** Two items added:
- Exercise the switch once on staging (PAUSE then RESUME).
- Rugvedh reviews 10f and 10g before any pilot grant.

## 3. The two-party RLS predicate as a named exception

**The problem.** `apply_rls()` (in `d7f9b1c3e5a6`) derives one predicate per table from the live schema. Any later migration that re-runs it would replace the 10f predicate on `payroll_mx_master_releases` with the owner-only tenant predicate:
- 10f predicate: USING owner **or** named target; WITH CHECK owner only.
- After a re-run: the target organisation can no longer see the release it must import.

**Your decision.** You chose the guard outside the migration:
- `d7f9b1c3e5a6` is applied in production and the manifest forbids editing it, so the exception is not written into `apply_rls()` itself.
- It is registered **by name next to it**, in `backend/app/core/authz/rls_exceptions.py`.

**What `rls_exceptions.py` contains.**
- `named_exceptions()`: table → `NamedPredicate`, which records:
  - `introduced_by` (`e5b1d8f3a7c2`) and the reason;
  - USING: d7f9's own tenant predicate OR (tenant mode AND `target_organization_id = zoiko_rls_tenant()`);
  - WITH CHECK: d7f9's tenant predicate.
  - It is built from d7f9's `_TENANT_PREDICATE` / `_TENANT_MODE`, so it cannot drift from the generic predicate.
- `reapply_named_exceptions(bind)`: on PostgreSQL only, and for each existing table:
  - ENABLE and FORCE row-level security;
  - drop and recreate the `zoiko_rls` policy with the registered predicate.
  - It returns the tables it did, and does nothing on SQLite.

**Enforcement.**
- **Static (every CI run).** `test_every_apply_rls_rerun_also_reapplies_the_named_exceptions` parses every file under `alembic/versions`, `scripts` and `app` with the AST. Any file that **calls** `apply_rls(` must also call `reapply_named_exceptions(`, or the test fails and names the file.
  - The only exemptions are the two migrations that ran before the exception existed (`d7f9b1c3e5a6`, `e1a3c5e7f9b2`). Neither can run again on an upgraded database.
  - A future migration that re-runs `apply_rls()`, as `c3e5a7b9d1f4` once did, cannot merge without the helper.
- **Registry.** `test_the_registry_names_its_reason_and_origin`: each exception records its origin, its reason and both clauses.
- **PostgreSQL.** `test_pg_a_rerun_of_apply_rls_then_the_helper_preserves_the_two_party_predicate`:
  1. Install d7f9 `apply_rls()`, then m15's two-party policy, and capture it.
  2. Re-run `apply_rls()`: **the policy is narrowed** (the risk is real, not theoretical).
  3. Run `reapply_named_exceptions()`: the policy is **identical to the installed one** (USING and WITH CHECK, as PostgreSQL stores them).
  4. As a non-superuser role, with RLS forced: the owner sees 1 row, the target sees 1, and a third organisation sees 0.

## 4. Data — migration `f6c2a9d1e4b7` (mx_onboarding_m16)

- Creates `payroll_mx_onboarding_pauses` and `ix_payroll_mx_onboarding_pauses_id`, guarded by `_has_table` / `_has_index`.
- `SET LOCAL lock_timeout = '5s'`.
- The foreign keys go to `users`.
- Downgrade drops the table.

**On PostgreSQL 17** (three runs):
- With a live reader on `users`, it takes a brief lock on `users` only (**20–55 ms**). It touches no tenant table and adds no RLS (`classify` sees it as neither).
- With `users` locked exclusively, it fails fast in 5.09–5.20 s.

**Pins.**
- `test_alembic_metadata`: head and 220.
- `test_mexico_migrations`: M16 tables.
- `test_deploy_migrate_script`: pending objects after `e5b1d8f3a7c2`.
- `test_privacy_mexico_merge_migration`: the new table is not yet in production at `e1a3c5e7f9b2`, and is exempt from the RLS assertion as a platform table.

## 5. Documents

- `MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md`: §6 step 3, Resuming, step 4.4, and the corrected sentence (§2).
- `MEXICO_RELEASE_CHECKLIST.md`: the two items (§2).
- `PRODUCTION_STATE.md`: the PR #123 row, and the "ZP-PRIV review pending after the fact" note: any change Rugvedh asks for must be merged before any pilot grant is approved.

## 6. Browser

Real Chrome (headless) against a scratch database. The harness is in `docs/mexico/phase10g-evidence/harness/` and the results are in `RESULTS-on.md`: **10/10 PASS**.

| # | Check |
|---|---|
| on-1 | The switch shows **OPEN**. |
| on-2 | The proposer cannot approve the pause (`MX_FOUR_EYES_REQUIRED`). This is the only 4xx, and the only console error. |
| on-3 | A second Super Admin approves: **PAUSED**. The pilot precondition shows "not paused (runbook §6): paused". |
| on-4 | A newcomer organisation's `PUT /api/organizations/me {"country":"Mexico"}` is refused with the pause message. |
| on-5 | A proposed pilot grant cannot be approved ("not paused"). |
| on-6 | An organisation that is already Mexican: its Compliance Centre still works. |
| on-7 | Resumed by two Super Admins: **OPEN**, with both changes listed. |
| on-8 | The newcomer can now become Mexican (200). |
| on-z1 | The NL compliance page is unchanged. |
| on-z2 | No 5xx responses and no page errors. |

Screenshots, inspected:
- `on_01_paused.png`: PAUSED, change #1 PAUSE APPROVED.
- `on_02_existing_org_runs.png`: the existing organisation's centre.
- `on_03_resumed.png`: OPEN, #2 RESUME and #1 PAUSE, both APPROVED.

## 7. Full suite

Five sequential chunks on scratch SQLite, run alone (not alongside the browser check): **7,166 passed**, 118 skipped, 2 xfailed, and **4 local-only failures**, none Mexico. These are the same four as in 10f.

| Chunk | Result |
|---|---|
| 0 | 853 passed, 15 skipped, 3 failed (route registry) |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed (Hong Kong docs) |
| 2 | 1,335 passed, 35 skipped |
| 3 | 1,641 passed, 61 skipped (includes the three 10g test files) |
| 4 | 1,054 passed, 6 skipped |

**The 4 local-only failures:**
- **3 route-registry tests.** They name only `/health/version`, `/health/ready` and their `/api` twins: the uncommitted routes in `main.py` (see `PRODUCTION_STATE.md` §7). The 4 pause routes are registered.
- **`test_hong_kong_configuration…`.** It reads the uncommitted Hong Kong docs.

## 8. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `f6c2a9d1e4b7` | One new, empty platform table, with no RLS. A brief lock on `users` (about 20–55 ms); fails fast after about 5 s. |
| The switch | Starts **not paused** (no rows). Nothing changes until two Super Admins pause it. |
| 4 Super Admin routes | New; platform only. They never touch tenant or worker data. |
| GA and pilot preconditions | One more condition ("not paused"). It is met by default; it can only make activation stricter. |
| `rls_exceptions.py` | Not called by any migration in this PR. It is a guard plus a CI test; it **does not change any policy** in production. |
| Screens | One panel on the Mexico Readiness tab (Super Admin). |

**Net:** additive. Mexico stays dormant, and no other jurisdiction's behaviour changes.

## 9. CODEOWNERS — proposal (not created)

**`.github/CODEOWNERS` already exists** (ZP-PRIV F07/E06). It already sends these to `@ZoikoGroup/privacy-reviewers`:
- `/backend/app/core/authz/` (which now includes `rls_exceptions.py`)
- `/backend/app/core/redaction.py`
- **all** of `/backend/alembic/versions/`
- `/backend/tests/privacy/`, `/docs/privacy/`, `/.github/workflows/`, `/.github/CODEOWNERS`, and others.

So the paths you asked about are already covered. **The gap is enforcement, not the file.**
- PRs #119, #122 and #123 merged without Rugvedh's review, so either the team does not exist with him in it, or branch protection on `main` does not require code-owner review.
- The file's own header says both are required (human proof **HP-10**).

Suggestions for the lead:

1. **Enforce it** (GitHub settings, not code):
   - Create `@ZoikoGroup/privacy-reviewers` with Rugvedh as a member.
   - On `main`, turn on "Require review from Code Owners" and "Require approval of the most recent reviewable push".
   - If merges before review must stay possible, use an explicit, logged bypass list rather than no rule.
2. **Add the Mexico files that move or expose worker data across tenants**, which are not yet listed:
   ```
   /backend/app/modules/payroll/mexico_transfer_service.py   @ZoikoGroup/privacy-reviewers
   /backend/app/modules/payroll/mexico_transfer_router.py    @ZoikoGroup/privacy-reviewers
   /backend/app/modules/payroll/mexico_pilot_service.py      @ZoikoGroup/privacy-reviewers
   /backend/app/modules/payroll/mexico_dormancy.py           @ZoikoGroup/privacy-reviewers
   /backend/tests/test_rls_named_exceptions.py               @ZoikoGroup/privacy-reviewers
   ```
3. **"Any migration that changes RLS"** cannot be expressed in CODEOWNERS, which matches paths, not contents. Two things already cover it:
   - the existing rule on all of `/backend/alembic/versions/`;
   - the new static test, which fails any migration that re-runs `apply_rls()` without the named-exception helper.

   If the lead wants a content rule, the right place is a CI check that labels or blocks PRs whose migrations contain `ROW LEVEL SECURITY` / `CREATE POLICY` until a privacy reviewer approves. I have not built it.

## 10. Open

- **Rugvedh's review of this PR (10g)** before merging, and **his after-the-fact review of 10f (PR #123)**. Any change he asks for must be merged before any pilot grant is approved.
- The CODEOWNERS enforcement (§9), a decision for the lead.
- Exercise the switch once on staging (release checklist).
