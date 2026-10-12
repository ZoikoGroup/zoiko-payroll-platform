# Singapore Payroll — Phase 6.6 Production Gate, Hotfix Governance and Deployment Safety

- **Date:** 2026-09-28
- **Branch / base:** `nikhil` @ `83601eb`. Working tree only: nothing staged, committed, pushed, merged or deployed.
- **Builds on:** `docs/SINGAPORE_PHASE_6_5_HARDENING_AND_GATE_READINESS.md` (the authoritative G1–G8 baseline).
- **Status:**
  - INTERNAL ENGINEERING VALIDATION: **PASS**.
  - OPERATIONAL PRODUCTION READINESS: **BLOCKED** (§8).
  - No CPF Board / IRAS / MOM / PDPC certification exists; `officialCertification` is `false` everywhere.

## 1. Workstream A — hotfix governance

### 1.1 Audit (before this phase)

| Question | Finding |
|---|---|
| Lifecycle | `activate_jurisdiction_pack_hotfix` (shared, all tax packs; not policy packs) → self-approve if unapproved → `set_jurisdiction_pack_status(…, bypass_approver_check=True)` → `PackHotfixActivation` row (`reviewed=false`) → retrospective `review_pack_hotfix_activation` |
| Initiate / activate | Any platform Super Admin (`get_current_super_admin`: org admins, payroll admins and tenant-bound Super Admins are refused). Needs a non-blank incident ID and justification |
| Bypassed | Only the distinct-approver gate and Singapore F2. Singapore evidence gates, downgrade, overlap and inverted-date guards all apply |
| Review | Any platform Super Admin; **including the activator (Gap A)**; a second review **overwrote** reviewer, time and notes |
| Evidence | `PackHotfixActivation` (incident, justification, activator, activated_at, review fields) + a `status_change` audit; refused Singapore hotfixes are audited `refused` with `path: hotfix` (6.5) |
| Transactions | Activation committed inside `set_jurisdiction_pack_status`; then the hotfix row in a **second commit (Gap B)** |
| Failure behaviour | A refused activation rolls back (6.3/6.5). A failure between the two commits left an **Active pack without hotfix evidence** |

**Policy:** the existing architecture already defines it. The `PackHotfixActivation` docstring says the retrospective
review *is* the deferred maker-checker, and hotfix mode exists for single-Super-Admin emergencies. No new policy was
chosen; the Phase 6.5 policy options (keep / prohibit for Singapore / enforced follow-up) remain an owner decision.

### 1.2 Changes (`backend/app/modules/payroll/service.py`)

| Function | Change | Why | Scope | Tests |
|---|---|---|---|---|
| `activate_jurisdiction_pack_hotfix` | The `PackHotfixActivation` row is added **before** the activation, so the one commit inside `set_jurisdiction_pack_status` persists the Active status and its evidence together; any failure rolls both back | Gap B | **All countries.** Transactional correctness with no policy content; successful behaviour identical | `test_failure_writing_the_hotfix_record_never_leaves_an_active_pack_without_evidence[SG, UK]`, `test_successful_hotfix_persists_status_and_record_together`, `test_refused_hotfix_leaves_no_record_and_no_approval` |
| `review_pack_hotfix_activation` + `_HOTFIX_DISTINCT_REVIEWER_COUNTRIES = ("SG",)` | Reviewer must differ from `activated_by_id`; a completed review is final. Both refusals audited (`refused`, `hotfix_review`, `path: hotfix`) | Gap A | **Singapore opt-in** (F2 pattern). Other countries unchanged, because enforcing a second reviewer universally could leave single-Super-Admin hotfixes permanently unreviewable, an owner decision | `test_hotfix_initiator_cannot_review_their_own_sg_hotfix`, `test_distinct_reviewer_succeeds_and_identity_is_recorded`, `test_a_completed_sg_review_cannot_be_replaced`, `test_other_countries_keep_their_existing_review_behaviour` |

**Unchanged and proven:**
- normal maker-checker activation (`test_normal_maker_checker_activation_is_unchanged_and_writes_no_hotfix_record`);
- Super Admin-only, organisation-free hotfix routes (`test_hotfix_routes_are_platform_super_admin_only`);
- the 27 existing hotfix / Super Admin UI tests.

**Directional proof:** against the pre-6.6 code, the self-review, review-replacement and both atomicity tests fail.

## 2. Workstream B — deployment script safety

### 2.1 Where the production script lives
- `scripts/deploy_migrate.sh` on origin/main is **identical** to origin/venu (blob `21929e8`).
- nikhil carries the untouched merge-base version (`a8f8852`), which is not what production runs.
- The fix therefore targets the main/venu version and ships as a **merge-time patch** (like R1). It isn't edited in
  nikhil's tree, where it would only conflict.

### 2.2 Defect map (main/venu version)

| # | Location | Defect | Effect |
|---|---|---|---|
| D1 | `schema_drift()` in the orphan path | The "proof" that the schema matches calls `migrations.sync_schema.sync_schema()`, which runs `ALTER TABLE … ADD COLUMN` (one transaction per table). It also never reports **missing tables** | A deploy that then refuses has already mutated the schema (reproduced: 11 columns added) |
| D2 | `STAMP_REV` ancestor walk | Walks **first parents only**; a pure merge revision at head "creates nothing", so it counts as applied → `stamp --purge <head>` | With tables missing, the DB is marked at head; the drift check then fails with the wrong revision already stamped |
| D3 | Ordering | No explicit preflight before the first mutating step | Relies on Alembic's error text |

**Properties already correct (kept):**
- `alembic upgrade head` is one transaction (`env.py`), so on PostgreSQL a failing migration rolls back completely;
- the happy path verifies the drift check (tables + columns, both directions) and the head before exit 0, so drift
  after a real upgrade exits non-zero.

### 2.3 Fix (merge-time patch; +39 / −110 lines)
1. `schema_drift()` is replaced by `readonly_drift()` → `python -m scripts.check_schema_drift` (read-only, tables and
   columns, both directions).
2. The orphan path: **any drift → refuse, exit 1, database untouched**. **No drift → `alembic stamp --purge` to the
   single head only.** This is the behaviour the script header already promised. The ancestor walk is removed.
3. A preflight (`single_head`) asserts exactly one head before anything runs.

- **Can't be rolled back:** `sync_schema`'s per-table commits (it now runs only after a clean drift check, so it is a
  no-op there) and `alembic stamp` (issued only on a verified exact match).
- **Residual risk:** re-stamping an exact-match orphan skips data-only migrations. None exist in the current pending
  set. A stricter "never auto-stamp" mode is a deploy-owner decision.

### 2.4 Tests
`tests/test_deploy_migrate_safety.py` (merge-time file) runs the real script on throwaway PostgreSQL databases, gated
by `P66_PG_URL`, starting from a structural replica of the shared DB. 9/9 pass against the fixed script:
- success + idempotent rerun;
- orphan + missing tables/columns → refused with **no change**;
- orphan + missing table only → **not stamped**;
- orphan + missing column → refused;
- orphan + exact match → head only;
- failing migration → full rollback, then rerun recovers;
- drift after upgrade → non-zero, no success message;
- DB marked head with a missing table → fails;
- static check that no mutating check and no ancestor stamp remain.

**Against the original script, 5 fail.** The missing-table case gets stamped to head, and the missing-column and
combined cases have columns added.

## 3. Workstream C — database lineage (shared DB read-only; rehearsal on a throwaway restore)

**Evidence:**
- A fresh `pg_dump --schema-only` of the shared DB (read-only snapshot, `default_transaction_read_only`): 145 tables,
  byte-identical to the Phase 6.1 dump.
- It was restored into a throwaway PostgreSQL 17 database, `alembic_version` was set to `5ae06cfda828` on the copy, and
  the fixed deploy script was run from the integration.

| Revision | Down revision | Purpose | Singapore impact | Risk | Result |
|---|---|---|---|---|---|
| `c3d9e1f4a7b2` | `f0b1c2d3e4f5` (R1) | CPF employee columns (5) | Required | Low: guarded, additive, nullable | Applied |
| `d4e8f2a6b9c1` | `c3d9e1f4a7b2` | `payslip_items.sgp_calculation_trace` | Required | Low | Applied |
| `e5f9a3b7c2d4` | `d4e8f2a6b9c1` | Work-pass validity dates (2) | Required | Low | Applied |
| `f6a1b4c8d3e5` | `e5f9a3b7c2d4` | `sgp_ir21_cases` | Required | None: table already present → guard skips | No-op; table/indexes/constraints unchanged |
| `a7c2e9f4b1d6` | `f6a1b4c8d3e5` | WP sector / skill / levy tier (`String(20)`, F1) | Required | Low | Applied (VARCHAR(20)) |
| `b8e3d5f2a9c7` | `a7c2e9f4b1d6` | `sgp_pwm_overtime_schedules` (+2 indexes, unique, FK) | Required | Low: guarded | Applied |
| `4b13831d574b` | `5ae06cfda828` | Re-create `communication_events` if missing (venu) | None | Low: idempotent | Applied (table + 9 indexes) |
| `6247da96d605` | `4b13831d574b`, `b8e3d5f2a9c7` | Merge + P1 ensure `auth_email_events` / `communication_events` | None | None: no-op when present | Applied |

**Path:**
```
CURRENT SHARED DB  5ae06cfda828 (venu lineage; 145 tables)
  → 4b13831d574b → [c3d9e1f4a7b2 → d4e8f2a6b9c1 → e5f9a3b7c2d4 → f6a1b4c8d3e5 → a7c2e9f4b1d6 → b8e3d5f2a9c7]
  → INTEGRATION HEAD 6247da96d605 (147 tables)
```
(`c3d9e1f4a7b2` hangs off `f0b1c2d3e4f5`, which is already an ancestor of `5ae06cfda828`.) There are no data migrations
in the path.

**Rehearsal result (throwaway only):**
- deploy exit 0 through the happy path, with no drift;
- object delta exactly +2 tables, +11 columns, +12 indexes, +4 constraints, with 0 removed and 0 retyped;
- `sgp_ir21_cases` identical;
- the full activation rehearsal on the migrated copy: **172 PASS / 0 FAIL / 0 BLOCKED / 1 INFO**. That covers seeds
  (idempotent), 6,132 PWM rows, 11 Draft templates, golden 36/36, two payroll cycles, 11 generators, and the Germany
  fingerprint unchanged.

**The real shared DB has not been migrated.** The owner procedure is in Phase 6.5 §8. It is now rehearsed against the
current schema, and the §2 patch must be in place before running it.

## 4. Workstream D — G1–G8 evidence readiness (baseline: Phase 6.5 §9)

Categories:
- **EC:** ENGINEERING COMPLETE.
- **EER:** EXTERNAL EVIDENCE REQUIRED.
- **IG:** IMPLEMENTATION GAP.
- **BAR:** BUSINESS APPROVAL REQUIRED.

| Gate | Requirement (spec §18) | Current implementation | Existing evidence | Missing evidence | Evidence owner | External authority | Engineering dependency | Business / statutory dependency | Status | Next action |
|---|---|---|---|---|---|---|---|---|---|---|
| G1 CPF content | 2026 SC/SPR tables, low-wage, OW/AW, ceilings, rounding, 2027 boundary independently certified | CPF engine, 2026 + 2027 packs | Hashed CPF Board sources; 36/36 golden incl. CPF Board worked examples; rehearsals | Independent certification | Statutory compliance owner | Independent reviewer / CPF Board | None | Engage reviewer | EC + **EER** | Commission the independent comparison |
| G2 CPF operations | CSN, EZPay FTP output, SDL/SHG, payment, amendment/reconciliation proven | EZPay builder + maker-checker lifecycle; supplementary advice; SDL/SHG | Spec-sample byte match; rehearsal 14×150-byte file | Accepted CPF submission; payment reconciliation | Employer payroll ops | CPF Board (EZPay / Corppass) | None | Design-partner employer | EC + **EER** | Partner test submission |
| G3 IRAS | AIS YA2027 model validated; AIS-API 2.0 onboarding **or** export-only; amendment + acknowledgement proven | IR8A extract (myTax Portal route) + manual lifecycle | Extract tests; acknowledgement / UNKNOWN handling | IRAS validation; API onboarding or signed export-only decision; **amendment flow** | Product owner | IRAS (APEX, Corppass) | See §5 | Export-only vs API decision | **EC (export) + IG (amendment) + NOT IMPLEMENTED (API) + BAR + EER** | §5 |
| G4 Tax clearance | IR21 trigger, hold, filing, directive, release, exceptions validated with IRAS guidance | Full IR21 lifecycle, distinct-approver release (refusals audited), bank hold, amended-IR21 exception path | Lifecycle tests; register | IRAS guidance validation / real filing | Statutory compliance owner | IRAS | None | Compliance review | EC + **EER** | Review against current IR21 guidance |
| G5 Foreign workforce | Work-pass/CPF distinction, levy billing, LQS/PWM gating, prohibited levy recovery | S Pass / WP handling; levy employer-only; LQS/PWM approval gates | Rehearsal checks; 6,132 PWM cells | MOM levy-bill reconciliation; unpublished MOM values | Statutory compliance owner | MOM | Seed rows once MOM publishes | Scope decision for unpublished values | EC + **EER**; partly BLOCKED | Obtain values or scope out; reconcile a real bill |
| G6 Labour pay | Salary deadlines, payslip, deductions, Part IV OT, leave/PH validated | Employment Act rules; OT; MOM incomplete-month; holidays | Tests + rehearsal | Legal / MOM validation | Legal + compliance owner | MOM / counsel | None | Legal review | EC + **EER** | Legal review |
| G7 Security/privacy | PDPA roles/transfers/retention, NRIC/FIN/SHG protections, credentials, isolation, recovery approved | Masking, isolation, RBAC, refusal auditing, hotfix maker-checker (6.6), retention report | Tests + rehearsals | DPO/PDPA approval; security review; recovery test | DPO + security owner | PDPC framework | Deploy-script patch (§2) for safe recovery | DPO sign-off | EC + **EER + BAR** | DPO + security review |
| G8 Parallel payroll | Two cycles + annual AIS simulation, zero unexplained differences | Two-cycle rehearsals incl. the migrated shared-lineage copy (6.6) | 172-PASS rehearsals | Live partner parallel run + annual AIS simulation | Implementation lead | Design-partner employer | None | Partner agreement | EC (rehearsal) + **EER** | Select partner |

## 5. G3 / AIS classification
- **What AIS needs:** the employer submits employment-income records (IR8A etc.) for YA2027 by 1 Mar 2027. IRAS
  offers two routes: AIS-API 2.0 (system-to-system) or the myTax Portal "Submit Employment Income Records" digital
  service (keyed entry, up to 200 records per submission). There is no TXT/XML file route.
- **Supported today (ENGINEERING COMPLETE for the original submission):**
  - `generate_sg_ir8a` builds the EXPORT_READY extract with IRAS whole-dollar rounding;
  - `transition_sg_ir8a` records EXPORT_READY → SUBMITTED_MANUALLY (distinct operator; refusal audited) →
    ACKNOWLEDGED / REJECTED / UNKNOWN;
  - UNKNOWN is never treated as success, and a new extract is blocked while a submission is open.
- **IMPLEMENTATION GAP:** no IR8A **amendment** flow. There are no transitions from ACKNOWLEDGED, and no amended-record
  type or indicator. A re-extract is possible but isn't an IRAS amendment. It needs a design of IRAS's amendment rules
  (EXTERNAL source review), then implementation.
- **NOT IMPLEMENTED:** AIS-API 2.0. It requires IRAS APEX onboarding, Corppass authorisation and API credentials
  (EXTERNAL credentials). It belongs to a **separate implementation phase**, not 6.6; no speculative integration was
  written.
- **BUSINESS APPROVAL REQUIRED:** "export-only mode" (the spec's allowed alternative) needs a signed product decision.

## 6. Test results
- **Targeted:** Phase 6.6 hotfix 12/12; deploy safety 9/9 (throwaway PostgreSQL).
- **Per suite** (identical in both trees, `test_model_tables_have_migrations.py` in the integration only):

| Suite | Result |
|---|---|
| `test_singapore.py` | 476 |
| Golden | 36 passed, 1 skipped |
| Phase 5.6 / 5.7 / 5.8 | 34 / 23 / 21 |
| Phase 6.0 (PostgreSQL test actually run) | 15 |
| Phase 6.3 / 6.4 / 6.5 / 6.6 | 25 / 3 / 22 / 12 |
| Super Admin UI / hotfix | 27 |
| Report templates | 74 |
| Alembic metadata | 6 |
| `test_model_tables_have_migrations.py` | 5 |

- **Full backend:**
  - Real tree: **3,167 passed, 7 skipped, 0 failed.**
  - Integration (with `P66_PG_URL`): **3,701 passed, 7 skipped, 2 xfailed, 0 failed.** The run's wrapper timeout fired
    during interpreter teardown after pytest printed its summary; that is an environment artefact.
- **PostgreSQL:**
  - lineage rehearsal on the shared-schema restore: delta exact, deploy exit 0;
  - activation rehearsal on the migrated copy: 172 PASS / 0 FAIL;
  - every throwaway database was dropped.
- **Frontend:** Singapore ESLint 0 errors (14 files); build PASS (2,702 modules). No frontend change.

## 7. Files
**Working tree:**
- `backend/app/modules/payroll/service.py`: `activate_jurisdiction_pack_hotfix`, `review_pack_hotfix_activation`,
  `_HOTFIX_DISTINCT_REVIEWER_COUNTRIES`.
- `backend/tests/test_singapore_phase66_hotfix.py` (new).
- `docs/SINGAPORE_PHASE_6_6_PRODUCTION_GATE_READINESS.md` (new).

**Merge-time handover** (`scratchpad/p66_handover`, applied after merging origin/venu, like R1):
- `deploy_migrate_safety.patch` (`scripts/deploy_migrate.sh`);
- `tests/test_deploy_migrate_safety.py`.

**Protected / excluded (unchanged, hash-verified):**
- Germany docs, DOCX, tests and seed hunks.
- The Phase 5.7 manifest.
- `SGPwmSchedulesTab.jsx`, `Modal.jsx`, `payroll/index.jsx`, `SuperAdminShell.jsx`.
- CORS files.

## 8. Production blockers

| Blocker | Why it blocks | Owner | Required action | Kind |
|---|---|---|---|---|
| Shared-DB lineage (`5ae06cfda828`) | The code must reach the DB via the venu lineage | Environment owner | Merge nikhil → venu (R1 + `6247da96d605` + §2 patch); backup; rehearse on a restored copy (done here); migrate in a window | Engineering + owner |
| Deploy-script patch not yet on main/venu | Without it an orphan-revision deploy can mutate or falsely stamp | Deploy-script owner | Apply `deploy_migrate_safety.patch` + its tests at the merge | Engineering |
| Hotfix policy for Singapore (keep / prohibit / enforced follow-up) | Emergency path semantics | Product / compliance owner | Choose; 6.6 already closed the self-review and atomicity gaps | Business |
| Universal scope of 6.5/6.6 opt-ins (refusal audit, Approve-step self-approval, distinct hotfix reviewer) | Consistency across jurisdictions | Product owner | Decide per country | Business |
| G1–G8 external evidence | Statutory acceptance | See §4 | See §4 | External |
| G3 amendment flow; AIS-API 2.0 | IRAS amendment + API route | Product owner / engineering | Design the amendment (IG); API needs IRAS onboarding (external credentials) | Engineering + external |
| Auto-deploy on merge to main | A merge triggers the production migration | Release owner | Hold the main merge until the above are resolved | Operational |
