# Mexico (MX) — Production State

Prepared 2026-10-16 from repository state and the public GitHub Actions API (read-only; nothing triggered, re-run or changed). **Merging to `main` deploys to production and runs Alembic migrations** (`.github/workflows/backend-deploy.yml`: test → single-head check → SSH → `git pull` → `pip install` → `scripts/deploy_migrate.sh` → head verification → restart → schema-drift check).

## 1. What reached production, and when

| PR merge to `main` | Commit | Deploy run | Mexico content it carried |
|---|---|---|---|
| #97 (2026-10-15 10:39Z) | aeddba2 | success | Phase 0 scaffolding (`mexico_service.py`, hooks fail closed) |
| #99 (2026-10-16 03:21Z) | 6e865cf | 38845080901 — test ✅ deploy ✅ drift ✅ | + Phase 1 tooling (value-free content module, `seed_mexico_canonical_packs.py`) |
| #100 (2026-10-16 04:09Z) | 9e5c840 | 38849128315 — success | + Phase 2, migration **`5d2c8f1a7b3e`** (mx_foundation_m1) |
| #101 (2026-10-16 06:17Z) | 22e86d3 | **38860348647** — test ✅ (22 min) · deploy ✅ · every step ✅ incl. "Verify single Alembic head", "SSH and deploy backend", "Check for model/schema drift" | + Phase 3, migration **`6e4a1d9c3f27`** (mx_employer_m2) |
| #102 (2026-10-16 07:06Z) | 3851b69 | **38865098800** — test ✅ · deploy ✅ (SSH, drift) | Phase 3 follow-up `878dc00`: streaming-cap tests, S30 in the content source list, readiness message, docs. **No migration** — production stays at `6e4a1d9c3f27`. |
| #103 (2026-10-16 07:56Z) | 7c0fd3e | **38870346791** — test ✅ · deploy ✅ (SSH, drift) — completed | **Phase 4a** `c5b058a`: dormancy gates (`MX_TENANT_ONBOARDING_ENABLED` = False, org-router guard, organisation-country / company-jurisdiction / back-fill gates). **No migration** — production stays at `6e4a1d9c3f27`. Effect: tightening only (§2e). |
| #104 (2026-10-16 09:22Z) | 8b902df | **38879994972** — test ✅ · single-head ✅ · deploy ✅ (SSH incl. `deploy_migrate.sh` + head verification) · drift ✅ | **Phase 4b** `dc4de74`: employee statutory profile, migration **`8b2f6d4e1a93`** (mx_employee_m3: 24 nullable columns + 2 FKs on the shared profile table, INFONAVIT notices table). Dormant: MX employees still refused while the flag is off. Production should be at `8b2f6d4e1a93` (the SSH step's head check would have failed otherwise). |
| #105 (2026-10-16, from `venu`) | 8ae86ee | **38919092609** — success | **Not Mexico**: Brazil Phases 0–2 (ZP-BR-ENG-001), migration **`b7a1c9e3d5f2`** (brazil_statutory_foundation_phase1, parent `8b2f6d4e1a93`). Added `BR` beside `MX` in the shared country tuples. Production should be at `b7a1c9e3d5f2`. |
| #106 (2026-10-17 ~01:50Z) | 5775299 | **38992536267** — test ✅ · single-head ✅ · deploy ✅ (SSH) · drift ✅ | **Phase 5** `1575015`: calculation engine (`engine/jurisdictions/mexico/`, orchestrator MX-ENGINE-2026.1). **No migration** — production stays at `b7a1c9e3d5f2`. Unreachable: `calc_inputs` still raises `MX_ENGINE_NOT_IMPLEMENTED`; `mx_golden` empty. |
| #107 (2026-10-17 04:21Z) | 318aa20 | **39002236064** — test ✅ (24 min) · single-head ✅ · deploy ✅ (SSH incl. `deploy_migrate.sh` + head verification) · drift ✅ — completed 04:46Z; frontend build run 39002236174 ✅ | **Phase 6** `30ff892`: payroll run integration, migration **`c4f7a2d9e6b1`** (mx_run_m4: 7 new Mexico tables, `payroll_mx_labor_policies.salary_days_convention`, `payslip_items.mx_calculation_snapshot`, `payroll_runs.mx_approval_fingerprint` / `mx_run_type` — shared ALTERs last, each its own transaction, `lock_timeout` 5 s). Dormant: `calc_inputs` refuses `MX_DORMANT`. Production should be at **`c4f7a2d9e6b1`** (the SSH step's head check would have failed otherwise) — confirm with `alembic current`. |
| #108 (2026-10-17 ~05:20Z) | 46c7957 | **39005680799** — test ✅ · single-head ✅ · deploy ✅ (SSH) · drift ✅; frontend build 39005680877 ✅ | **Phase 6 follow-up** `8d287f3`: preview takes the run's pay date (Mexico refuses without it), Mexico-only read-only policy in preview (OOS-8), "—" Mexican employer totals, blocked Mexican preview → coded 4xx (OOS-9), master-prompt rule 12. **No migration** — production stays at `c4f7a2d9e6b1`. |
| #109 (2026-10-19 04:42Z) | b041ead | **39200794145** — test ✅ (16 min) · single-head ✅ · deploy ✅ (SSH incl. `deploy_migrate.sh` + head verification) · drift ✅ — completed 05:00Z; frontend build 39200794149 ✅ | **Phase 7** `9e00a20` (commit message reads "phase 6 mexico"; content is Phase 7): CFDI lifecycle + thin PAC seam, migration **`d8b3e5f1a2c7`** (mx_cfdi_m5: three new empty tables, no shared column), same-pay-date month-to-date tie-break. Dormant: routes 403, builder/signer refuse, no PAC adapter. Production should be at **`d8b3e5f1a2c7`** (the SSH step's head check would have failed otherwise) — confirm with `alembic current`. |
| #110 (2026-10-19 07:08Z) | 422d4d2 | **39214061815** — test ✅ (17 min) · single-head ✅ · deploy ✅ (SSH incl. `deploy_migrate.sh` + head verification) · drift ✅ — completed 07:27Z; frontend build 39214061602 ✅ | **Phase 8** `8ee13dd` (commit message reads "phase 7 mexico"; content is Phase 8): authorities — IMSS movements, liability ledger, SUA reconciliation, ISN returns, file-export mode; migration **`e3b9c2d7f4a1`** (mx_authorities_m6: seven new empty tables, no shared column). Dormant: routes 403, nothing transmits. Production should be at **`e3b9c2d7f4a1`** — confirm with `alembic current`. |
| #111 (2026-10-19 08:41Z) | 4adac17 | **39224575881** — test ✅ (22 min) · single-head ✅ · deploy ✅ (SSH incl. `deploy_migrate.sh` + head verification) · drift ✅ — completed 09:05Z; frontend build 39224575888 ✅ | **Phase 9a** `14bf883` (commit message reads "phase 8 mexico"; content is Phase 9a): correction runs, migration **`f5c1a8d3e9b2`** (mx_corrections_m7: one new empty table, no shared column); MX-only guard in `service.delete_payroll_run`. Dormant: routes 403. Production should be at **`f5c1a8d3e9b2`** — confirm with `alembic current`. |
| #112 (2026-10-19 11:35Z) | 9e49df0 | **39245798162** — test ✅ · single-head ✅ · **deploy ❌ (SSH step)** · drift skipped; frontend build 39245797978 ✅ | **Phase 9b** `47455d4`: aguinaldo + vacation, migration `a6d2f9c4b8e1`. **Not applied** — see the incident below. |
| #114 (2026-10-19 12:24Z) | c17da37 | **39251832330** — test ✅ · single-head ✅ · **deploy ❌ (SSH step, 12:48:46–12:49:21Z)** · drift skipped | Deploy-script fix (`drift_pending_filter`) for the PR #112 incident. **Failed again**; the reason awaits the SSH-step log. `a6d2f9c4b8e1` still not applied. |
| #115 (2026-10-21 07:19Z) | e00b66b | **39561229230** — test ✅ (33 min) · single-head ✅ · **deploy ❌ (SSH step: `alembic upgrade head` LockNotAvailable on `ALTER TABLE "users" ENABLE ROW LEVEL SECURITY`)** · drift skipped; frontend build 39561229234 ✅ **deployed** | ZP-PRIV + Mexico 9b–9d. The migration transaction rolled back: production DB still at `e1a3c5e7f9b2`, unchanged; backend not restarted. Cause: Rugvedh's merge revision `c3e5a7b9d1f4` re-ran `apply_rls()` over every table (ACCESS EXCLUSIVE on each) and timed out on `users` (lock_timeout 5 s, set by `a6d2f9c4b8e1` for the transaction). **Fix:** `c3e5a7b9d1f4` corrected (never applied anywhere) to protect only the merged-in table; proved on PostgreSQL 17 with a live reader on `users` (`tests/test_privacy_mexico_merge_migration.py`). **The new frontend is live against the old backend until the next deploy succeeds.** |

Everything committed on `nikhil` up to `14bf883` (Phase 9a) is on `main` (`4adac17`) and deployed (run 39224575881); production database head expected **`f5c1a8d3e9b2`** — confirm with `alembic current`.

**INCIDENT 2026-10-19 — PR #112 deploy failed (Copilot "Explain error" on the SSH step).** The production
`alembic_version` row reads **`e1a3c5e7f9b2`** — a revision that exists in **no branch on GitHub** and nowhere in this
checkout. Someone applied it to production between 09:05Z (PR #111 deploy, `f5c1a8d3e9b2`) and 12:04Z, outside the CI
pipeline. `deploy_migrate.sh` has an orphan self-heal, but it refuses to stamp unless the live schema matches the
models — and the models already included 9b's new `payroll_mx_vacation_records`, the very table the deploy was about to
create, so the self-heal could never succeed for a deploy that brings a new table. Rehearsed exactly on SQLite (old
script: same refusal). The production database was NOT changed by the failed run; the server pulled 9b's code but was
NOT restarted (it still runs 9a). **Fix staged:** the orphan path now finds the stamp point first and ignores only the
objects the pending migrations create (`backend/scripts/drift_pending_filter.py`); any other drift — including DB
columns the models do not know — still refuses. **Open:** who applied `e1a3c5e7f9b2`, and what did it change? If it
added columns to existing tables, the next deploy will refuse again (correctly) and that change must be reconciled first.

**Pending (2026-10-21):** the orphan `e1a3c5e7f9b2` is Rugvedh's ZP-PRIV chain (`origin/rugvedh`, PR #113, open): `f5c1a8d3e9b2` → `a7c3e91f2b60` → `b2f4d6a8c0e1` → `c5e7a9b1d3f4` → `d7f9b1c3e5a6` (row-level security) → `e1a3c5e7f9b2`, applied to production with `scripts/migrate_privacy_rollout.py` (it stores unset mode `system`, so code that sets no `app.rls_mode` keeps seeing rows). Rugvedh's merge revision `c3e5a7b9d1f4` joins it with 9b's `a6d2f9c4b8e1`. `nikhil` now carries that merge (commit `5ff6d17`, **not pushed**) plus PR #114, Phase 9c (`b4d8f2c6a9e3`) and Phase 9d (`c6e1a9d4f2b7`, single head). From production's `e1a3c5e7f9b2`, a normal `alembic upgrade head` runs `a6d2f9c4b8e1` → `c3e5a7b9d1f4` → `b4d8f2c6a9e3` → `c6e1a9d4f2b7` — no self-heal. Merging to `main` also ships ZP-PRIV, so it needs Rugvedh's agreement (PR #113 vs `nikhil`). Do NOT stamp head or add an empty placeholder.

**Migration result (inferred, see §6 to confirm).** The SSH step runs `alembic current --check-heads` and a script that exits non-zero unless the database heads equal the repository head; that step succeeded for run 38860348647, so production should be at **`6e4a1d9c3f27`**. The job logs themselves need repository admin rights (`403 Must have admin rights`), so the exact migration lines were not read.

**What the migrations did.** Both are additive and guarded: `5d2c8f1a7b3e` created three empty tables (earning classifications, CFDI schema releases, catalog entries); `6e4a1d9c3f27` created seven empty tables (employer profiles, IMSS registrations, establishments, risk premiums, ISN registrations, labour policies, credential references). No existing table, column or row was touched.

**What deploy does NOT do.** No seed script runs on deploy, so production has **no** Mexico pack, no MX service-registry row, no MX report templates and no source artifacts **unless someone ran `seed_mexico_canonical_packs.py` / `seed_statutory_report_templates.py` by hand** (the seed scripts require an explicit confirmed target). Frontend deploy is not part of this workflow (GCP_DEPLOYMENT.md: how `frontend/dist` reaches production is not captured in version control), so whether the Mexico UI is live is separate from the backend.

## 2. Mexico routes reachable in production (46)

### 2a. Super Admin — `/api/super-admin/compliance/mexico/...` (25 routes, `get_current_super_admin`: platform Super Admins only)

| Routes | Why fail-closed |
|---|---|
| Reads: `/readiness`, `/organizations`, `/employees`, `/packs`, `/packs/{id}/activation-readiness`, `/isr-tariffs`, `/uma-min-wage`, `/imss-branches`, `/ceav-schedule`, `/infonavit`, `/benefits-workweek`, `/isn-states`, `/employers`, `/employers/{id}`, `/employer-readiness`, `/employer-readiness/summary`, `GET /earning-classifications`, `GET /cfdi-catalogs`, `GET /cfdi-catalogs/{id}/entries` | Read-only. Content views return "awaiting transcription" (no pack unless seeded; content is empty either way). Employer views are masked. G1–G8 all OPEN. |
| `POST /earning-classifications`, `/{id}/approve`, `/{id}/archive` | Creates DRAFT rows; approval needs a second Super Admin; a canonical row cannot be approved without its SAT code in an approved catalog release (S28 not loaded) — so nothing canonical can go live. Org rows have no consumer (no MX calculation exists). |
| `POST /cfdi-catalogs`, `POST /cfdi-catalogs/{id}/entries`, `PUT /cfdi-catalogs/{id}/{action}` | Draft releases only; `activate` is refused until Phase 7. |
| Shared pack lifecycle (`/super-admin/compliance/policies/...`) on an MX pack, if one was seeded | Approval refused by `mx_pack_approval_refusal` (needs QA + exact source-linked content); activation refused by `mx_activation_evidence_refusal` (content empty, no G1 review, no golden PASS). Code never sets anything Active. |

### 2b. Organisation — `/api/payroll/mexico/...` (21 routes; reads `get_current_payroll_operator`, writes `get_current_org_admin`; subscription gate applies)

Reachable by an **org admin / payroll admin (or an assisted-access session) of any organisation with an active subscription or an EVALUATION workspace**: `GET/POST /employers`, `GET /employers/{id}`, `POST /employers/{id}/versions`, `/establishments`, `/imss-registrations`, `/isn-registrations`, `/labor-policies`, `/credentials`, `PUT …/deactivate|close|infonavit|activate|revoke|approve`, `POST /imss-registrations/{id}/risk-premiums`, `POST /credentials/{id}/certificate`, `GET /labor-policies/{id}/floor-check`, `GET /collective-agreements`, `GET /readiness`.

Why every one is still fail-closed:
- **No path to Mexican payroll.** MX is not in `REGISTRATION_COUNTRIES` or `SUPPORTED_COUNTRY_CODES`, and **creating an employee with country `MX` is refused** (`create_employee` → `Unsupported country code 'MX'` — verified on a scratch DB). With no MX employees there is nothing to calculate, run, stamp or file.
- **Calculation and run approval BLOCK** for MX in every mode (`MXBlock` / Phase 0 hooks); a Mexican statutory profile cannot be saved.
- **Registry PLANNED**: moving Mexico to AVAILABLE is refused until G1–G8 are signed (and the row exists only if the seed ran).
- **Nothing an org records can become effective**: risk-premium approval is refused (period rule and legal range not transcribed; four-eyes); labour-policy activation is refused (no Active national pack → BLOCKED_CONTENT); ISN registration only for CDMX and only PENDING_PACK; readiness can never be LIVE-eligible (stamp test, reconciliations, bank, parallel payroll BLOCKED by construction).
- **No secret is stored or resolved**: only `gcp-sm://` references; key material refused and not echoed; the `.cer` is parsed in memory and discarded; nothing resolves a reference before Phase 7.
- Rows written land only in the new `payroll_mx_*` tables, scoped to the caller's organisation (tenant isolation tested).

### 2c. Exposure gaps found (not fixed — recommended follow-up)

1. **The organisation routes do not check that the organisation is Mexican.** Any subscribed org admin can call them directly (the UI shows the tab only to MX orgs). Effect today: Mexico employer rows can be created in that tenant's `payroll_mx_*` tables; nothing consumes them.
2. **An organisation whose jurisdiction is not yet chosen can set its company jurisdiction to `MX`** (`update_company_details` accepted `jurisdictionCountry="MX"` on a scratch DB), which then shows it the Mexico Compliance Centre tab. Once chosen, the jurisdiction lock prevents changing it back through that endpoint.

Recommended (Mexico-only, small): a guard in `mexico_org_router` that refuses unless the caller's organisation is a Mexico organisation, and a Mexico gate in the company-jurisdiction update (refuse `MX` while the service registry is PLANNED, as Singapore's org country-change gate does). Neither is a path to payroll; both keep Mexico dormant rather than merely inert. **Proposed as the first item of Phase 4** (see `MEXICO_PHASE_4_PLAN.md`).

### 2d. Recovery — an organisation locked into MX by mistake

Once a real jurisdiction is chosen, `update_company_details` refuses every change (HTTP 423: "Changing jurisdictions requires a controlled migration process"). **No governed path exists today** to change a locked `payroll_company_compliance.jurisdiction_country`: no Super Admin endpoint writes that column. A Super Admin *can* change `Organization.country` (the organization update, which runs `get_jurisdiction_change_block_reason`), but that does not rewrite an already-set compliance jurisdiction — the back-fill only fills an empty / placeholder value.

So, until a governed "controlled jurisdiction migration" exists (platform item, not built), a mistaken MX organisation is corrected by a Super Admin–approved operator change: record the organisation, old and new value, reason and ticket; check (queries in §6) that it has no MX employees (none can exist) and review/remove its `payroll_mx_*` rows first; then update `payroll_company_compliance.jurisdiction_country` (and `organizations.country` if it was set) in one transaction, and record it in the audit trail. Phase 4a stops new cases (gates on all three paths); it does not alter existing rows.

### 2e. Phase 4a — what changed, and the `tax_resolver.py` change

With `MX_TENANT_ONBOARDING_ENABLED` unset (False) in production, Phase 4a makes the §2b organisation routes refuse (403 *"Mexico is not open for onboarding on this platform yet…"*) and closes the three ways an organisation could become Mexican (§2c), without touching existing rows.

**`engine/tax_resolver.py` — what.** `get_jurisdiction_change_block_reason(db, old_country, new_country)` is the gate that `PUT /organizations/me` and the Super Admin organization update already call before changing `Organization.country` (Singapore Phase 6.10). Phase 4a adds, before its existing logic, one Mexico-only branch:

```python
mx_refusal = entering_mexico_refusal(old_country, new_country)   # mexico_dormancy.py
if mx_refusal:
    return mx_refusal
```

`entering_mexico_refusal` returns a message only when **all three** hold: the new country normalises to `MX` (`app.core.jurisdiction.get_jurisdiction_code`, which never defaults a blank to a country), the old country does not, and the flag is off. Otherwise it returns `None` and the function continues exactly as before.

**Why.** `Organization.country = "Mexico"` was accepted (MX is not in `_REGISTRY_ROW_REQUIRED_COUNTRIES`), and `get_company_details` back-fills the payroll jurisdiction from it — so this was one of the three paths into Mexico (with the company-jurisdiction update and the back-fill, gated in `service.py`).

**It cannot change any other country's resolution.**
- The function is not part of tax resolution at all: it is not called by `resolve_tax_configuration`, rate/slab resolution, calculations or payroll runs — only by the two organization-update endpoints, to decide whether a *country change* is allowed.
- For any change whose new country is not Mexico, the branch returns `None` and the original code runs unchanged; for a change from Mexico to Mexico it also returns `None`.
- Pinned by `tests/test_mexico_dormancy.py::test_jurisdiction_change_gate_is_identical_for_every_non_mexican_pair` (every pair of non-Mexican registration countries — names and codes — plus blank, with the flag off and on: the answer with the branch removed equals the answer with it) and `::test_the_mexico_branch_only_fires_for_a_change_into_mexico`.

## 3. Recommended ops action — nginx limit for the certificate upload

`deploy/nginx/zoiko-payroll.conf` (`location /api/`) sets `client_max_body_size 20m` with request buffering on (default). nginx therefore accepts up to 20 MB on the certificate route and writes any body larger than `client_body_buffer_size` to a temporary file before proxying — the application never writes the `.cer` to disk, but nginx can. Add (not applied — production config):

```nginx
# A regex location wins over the `location /api/` prefix block (nginx matching order); it cannot carry a URI in proxy_pass.
location ~ ^/api/payroll/mexico/credentials/[0-9]+/certificate$ {
    proxy_pass              http://127.0.0.1:8000;
    proxy_set_header        Host              $host;
    proxy_set_header        X-Real-IP         $remote_addr;
    proxy_set_header        X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header        X-Forwarded-Proto $scheme;
    client_max_body_size    16k;     # refuse at the edge (413), matching the app cap
    client_body_buffer_size 16k;     # an accepted body always fits the in-memory buffer — no temp file
}
```

Then `sudo nginx -t && sudo systemctl reload nginx`.

## 4. Infrastructure lead time

Per-employer CSD/PAC credentials need **GCP Secret Manager** live in production before Phase 7 (today application secrets are in the VM `.env`; Secret Manager is the target in GCP_DEPLOYMENT.md).

**Cloud Storage in production is a shared prerequisite.** Mexico Phase 7 D4 (CFDI XML storage) and the HK durable-storage item (G5 finding F-8) both go through `app/core/object_storage.durable_storage_refusal`, which refuses the local `/tmp` fallback in production. Configuring `PAYROLL_GCS_BUCKET` / `PAYROLL_STORAGE_BACKEND=gcs` once unblocks both; until then, both refuse to store anything in production.

**OOS-4 is not a code defect.** The one failing HK test locally (`test_hong_kong_configuration.py::…documented_sourced_consumed_and_exposed`) depends on the untracked HK owner pack (`docs/HONG_KONG_RELEASE_EVIDENCE/`, HK "commit 8"). It fails only where that stale local pack exists. CI and production have no copy, so the deploy test job is unaffected.

## 5. Rule for every future Mexico PR

Merging to `main` deploys to production and runs Alembic migrations. Every phase PR must keep Mexico dormant and fail-closed, and every migration must be additive and guarded.

## 6. How to confirm (GitHub, no admin needed for the first two)

1. **Actions → "Deploy Zoiko Payroll Backend" → run for "Merge pull request #101"** (run 38860348647): jobs `test` and `deploy` are green; in `deploy`, open **"SSH and deploy backend"** and read the blocks *"--- Migration diagnostics ---"* (database `alembic_version` before), *"--- Applying migrations ---"* (`deploy_migrate.sh` output — expect `Running upgrade 5d2c8f1a7b3e -> 6e4a1d9c3f27`), and *"--- Post-migration verification ---"* (expect `database heads: ['6e4a1d9c3f27']` and `Database is at the Alembic head.`). Then **"Check for model/schema drift"** (`scripts.check_schema_drift` output). Viewing logs needs to be signed in with access to the repository.
2. Same for run **38849128315** (PR #100), the first deploy carrying `5d2c8f1a7b3e` (expect `Running upgrade f4b8d2a6c9e1 -> 5d2c8f1a7b3e`).
3. On the VM (read-only): `GET /api/health/version` returns the running commit (expect `8b902df…`); `alembic current` → `8b2f6d4e1a93`. Exposure counts (read-only SQL):
   ```sql
   -- Mexico packs seeded by hand?
   SELECT count(*) FROM payroll_jurisdiction_packs WHERE jurisdiction_country = 'MX';
   -- organisations whose payroll jurisdiction or profile country is Mexico (gap §2c-2 and the back-fill path)
   SELECT o.id, o.organization_name, o.country, c.jurisdiction_country, c.configured_at
     FROM organizations o LEFT JOIN payroll_company_compliance c ON c.organization_id = o.id
    WHERE upper(coalesce(c.jurisdiction_country, '')) IN ('MX', 'MEXICO')
       OR upper(coalesce(o.country, '')) IN ('MX', 'MEXICO');
   -- any Mexico employer onboarding rows (gap §2c-1), per organisation
   SELECT organization_id, count(*) FROM payroll_mx_employer_profiles GROUP BY organization_id;
   SELECT count(*) FROM payroll_mx_credential_refs;   -- references only, never secrets
   ```
