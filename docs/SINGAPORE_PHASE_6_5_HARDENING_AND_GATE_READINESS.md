# Singapore Payroll — Phase 6.5 Hardening and Production-Gate Readiness

- **Date:** 2026-09-28
- **Branch / base:** `nikhil` @ `83601eb`. Working tree only: nothing staged, committed, pushed, merged or deployed.
- **Builds on:** `docs/SINGAPORE_PHASE_6_4_ACTIVATION_REHEARSAL.md`, `docs/SINGAPORE_PHASE_6_3_HANDOVER_MANIFEST.md`.
- **Production: BLOCKED.** No CPF Board / IRAS / MOM / PDPC certification exists; `officialCertification` is `false`
  everywhere. Internal engineering validation is not regulatory certification.

Status legend: **PASS**, **PASS WITH CONDITION**, **BLOCKED**, **EXTERNAL EVIDENCE REQUIRED**, **NOT IMPLEMENTED**,
**DEFERRED**.

## 1. Executive summary

| Objective | Result |
|---|---|
| A. Audit refused actions | **PASS.** Singapore opt-in: 45 of 49 rehearsal refusals now leave exactly one `refused` audit row. The remaining 4 are operational validations, not audited by design |
| B. Pack self-approval refused at the Approve step | **PASS.** Singapore opt-in; other countries unchanged |
| C. Pack version on IR21 / SDL / IR8A / EZPay reports | **PASS.** Taken from the payslips' pinned pack (the existing generic rule) |
| D. Hotfix policy | **DEFERRED** (owner decision; 3 options, §7). One shared technical gap flagged, not changed |
| E. Shared DB lineage | **BLOCKED** (owner-led). Read-only diff done (§8) |
| F. G1–G8 | **EXTERNAL EVIDENCE REQUIRED** (§9) |
| G. Deployment safety | Reviewed (§10). Shared-infrastructure defects **documented, NOT IMPLEMENTED** |

## 2. Starting Git state
- Branch `nikhil`, HEAD `83601eb`.
- 73 entries (35 modified, 38 untracked), 0 staged, `diff --check` clean.
- 124-file hash baseline identical to the end of Phase 6.4.

## 3. Phase 6.4 baseline
- Rehearsal: 159 PASS / 0 FAIL / 2 INFO.
- Real tree 3,133 passed / 7 skipped; integration 3,658 passed / 7 skipped / 2 xfailed.
- Three findings: refusals unaudited; pack self-approval recorded then refused only at activation; four reports
  missing the pack version.

## 4. Objective A — auditing refused actions
**Architecture:**
- `TaxConfigurationAudit` via `record_tax_audit()` is the one canonical write path. It holds the actor, `created_at`,
  action, entity, pack/version, old/new JSON and reason.
- Before this phase no refusal was audited anywhere, and no `refused` action existed.

**Change:**
- A new `refused` action: old value `{status}`; new value `{attempted, result: "REFUSED", path?}`; the reason is the
  refusal message. It carries only governance text, never payroll or personal data.
- **Singapore opt-in** (`_REFUSAL_AUDIT_COUNTRIES = ("SG",)`), the same per-country pattern as F2.
- Each helper **rolls back first**, so a refused call leaves nothing pending (the Phase 6.3 phantom-approval class) and
  exactly one row.

**Audited:**

| Refused action | Where |
|---|---|
| Pack status change / activation (every gate: evidence, effective date, golden, distinct approver, F2, overlap, downgrade) | `set_jurisdiction_pack_status` (thin wrapper around `_set_jurisdiction_pack_status`) |
| Pack approval by its submitter (Objective B) | `set_jurisdiction_pack_approver` |
| Hotfix activation (gate refusals tagged `path: "hotfix"`; missing incident / justification) | `activate_jurisdiction_pack_hotfix` |
| Report-template transition (incl. Draft/Review→Published, Active→earlier) | `set_report_template_status` (wrapper) |
| Replacing a released template's approval | `set_report_template_approver` |
| Editing a released template in place (template, component, field upsert/delete) | `_require_editable_report_template(…, db, actor_id)` |
| Preparer self-approving IR8A manual submission / IR21 hold release / CPF EZPay approval | `_sg_refuse_self_approval` (Singapore-only functions) |

**Not audited, by design:** operational validations with no governance meaning (EZPay download before APPROVED,
generating from a non-Active template, payslip-correction guards), input/unknown-status validation, and HTTP 401/403
at the auth dependency (shared auth layer, out of scope). Other countries' refusals are unchanged; making them audited
is a one-line owner decision.

## 5. Objective B — pack self-approval
- **Change:** `set_jurisdiction_pack_approver` refuses (and audits) approval by the Super Admin in `updated_by_id`,
  i.e. whoever last edited or submitted the pack. This is a Singapore opt-in (`_SELF_APPROVAL_REFUSED_COUNTRIES`).
- **Workflow:** A submits, B approves, A (or another Super Admin other than B, per F2) activates.
- **Seeded, never-edited pack:** `updated_by_id` is NULL, so any Super Admin may approve; F2 still keeps the approver
  from activating.
- **Unaffected:** hotfix self-approval is a separate, documented path. Other countries keep recording the editor's
  approval (activation still refuses it).
- **Roles:** only existing roles are used.
- **Intentional test updates:** 3 Singapore tests (§11).

## 6. Objective C — pack version on dedicated reports
- **Canonical field:** `GeneratedReport.applicable_tax_pack_id` / `applicable_tax_pack_version`.
- **Canonical rule:** `generate_report_from_template` already derives it from the payslips' pinned
  `tax_policy_pack_id`: one distinct pack means that pack; several means none, listed in
  `rendered_data.metadata.taxPacksUsed`. The new `_sg_pinned_pack()` applies that rule to the payslips each generator
  already reads:
  - **SG-SDL-MONTHLY:** the wage month's payslips.
  - **SG-IR8A:** the income year's payslips.
  - **SG-CPF-EZPAY:** the payslips in the file.
  - **SG-IR21-REGISTER:** each case's `final_payslip_id`. The register calculates nothing itself, so with no
    payslip-linked case it records no pack.
- **Never the current Active pack, a hard-coded value or user input.** A later pack therefore cannot rewrite a
  historical report, and regeneration reproduces the same linkage.

## 7. Hotfix policy analysis (decision required — nothing changed)
**How it works today** (`activate_jurisdiction_pack_hotfix`, shared by every country's tax packs):
1. **Why it exists:** an emergency activation when the second Super Admin needed for maker-checker is unavailable.
2. **When it's allowed:** any tax pack (not policy packs), with a non-blank incident ID and justification.
3. **What can change:** it only **activates an existing pack version**. It cannot edit rates; content changes still go
   through a Draft/new version.
4. **Bypass:** only the distinct-approver gate and Singapore F2. The self-approval is committed only if activation
   succeeds (Phase 6.3 fix).
5. **Evidence still required (Singapore):** source evidence, effective-from date, latest golden run PASS; the overlap and
   inverted-date guards also apply.
6. **Effect on active packs:** it can't overlap an Active pack for the same dates, so the old pack must be superseded
   first.
7. **Calculations:** future payroll runs in the pack's date range use it; existing payslips are pinned and unchanged.
8. **Rollback:** an Active Germany or Singapore pack can't return to Draft/In Review/Approved, only
   Superseded/Deprecated/Retired.
9. **Audit:** a `PackHotfixActivation` row (incident, justification, activator, `reviewed=false`) plus a
   `status_change` audit; refused hotfixes (Singapore) are audited with `path: hotfix`.

**Options:**
1. **Keep as is.** An audited emergency path for Singapore with every evidence gate. Lowest friction; relies on
   retrospective review.
2. **Prohibit for Singapore.** One isolated `jurisdiction_country` check in the hotfix function (pattern as F2), so
   emergencies use the normal two-person path. Strongest control; needs two available Super Admins.
3. **Allow with enforced follow-up.** Keep hotfix, but block further Singapore pack/template activations while an
   unreviewed Singapore hotfix exists, and require the reviewer to differ from the activator. New functionality; needs
   design approval.

**Technical gaps, whichever policy is chosen (shared; NOT IMPLEMENTED, owner approval needed):**
- (a) `review_pack_hotfix_activation` lets the **activator review their own hotfix**, which defeats the deferred
  maker-checker.
- (b) The activation and its `PackHotfixActivation` row are two separate commits, so a failure between them would leave
  an Active pack without its hotfix record.

## 8. Shared database lineage (read-only; `default_transaction_read_only=on`)

| Item | Finding |
|---|---|
| Current revision | `5ae06cfda828` (PostgreSQL 14.24) |
| Repository heads | nikhil `b8e3d5f2a9c7`; origin/venu `4b13831d574b`; origin/main `f0b1c2d3e4f5`; integration `6247da96d605` |
| Is the revision in the repository? | **Not on nikhil.** It is on origin/venu and in the integration (venu's merge `b1c2d3e4f5a6` + `f0b1c2d3e4f5`) |
| Pending from `5ae06cfda828` to integration head | `4b13831d574b`, `c3d9e1f4a7b2`, `d4e8f2a6b9c1`, `e5f9a3b7c2d4`, `f6a1b4c8d3e5` (table exists → skipped by its guard), `a7c2e9f4b1d6`, `b8e3d5f2a9c7`, `6247da96d605` |
| Schema vs integrated models (146 tables) | Missing: `communication_events` (restored by `4b13831d574b`), `sgp_pwm_overtime_schedules`, 11 `sgp_*` columns. **Extra: none.** Orphan `sgp_ir21_cases` column set identical to the model |
| Schema vs nikhil models (131 tables) | The DB has 14 venu tables (France / Ireland / Puerto Rico / auth events) and 14 venu columns nikhil lacks |
| Lineage | **venu deployment lineage.** `communication_events` is absent although its creating revision `e7f1a2b3c4d5` is an ancestor: a stamped, not executed, revision |
| Singapore data | 0 packs, 0 templates, 0 certification runs, 0 organizations |

**Owner-led reconciliation procedure (proposal; nothing executed):**
1. Merge nikhil into venu (R1 + merge `6247da96d605`, per `scratchpad/p64_handover`) so the repository contains
   `5ae06cfda828`. **Never deploy nikhil alone to this DB:** `5ae06cfda828` would be an orphan and trigger the
   mutating orphan path (§10).
2. Take a full backup / PITR point of the shared DB.
3. Restore a copy and run `alembic upgrade head` there (rehearsed as scenario E1: exit 0, drift check clean). Diff the
   schema against the models.
4. In a maintenance window, the environment owner runs the same command on the shared DB. No `stamp`, no manual DDL.
5. Verify `alembic current == 6247da96d605` and a model-drift check with zero differences.
6. Seed Singapore data (Draft) only after that, following the activation workflow.

## 9. G1–G8 evidence readiness (ZP-SG-ENG-001 §18)

| Gate | Engineering evidence available | Evidence missing | Owner | External authority / partner | Required artifact | Acceptance criterion | Status | Blocking reason | Next action |
|---|---|---|---|---|---|---|---|---|---|
| G1 CPF content | Hashed CPF Board tables; 36/36 golden (CPF Board worked examples, 2027 boundary); rehearsal matched golden F1/F2/F4 | Independent certification | Statutory compliance owner | Independent reviewer / CPF Board reference | Signed independent comparison of tables, formulas, rounding | Zero unexplained differences over the agreed case set | EXTERNAL EVIDENCE REQUIRED | No independent sign-off | Commission the independent comparison using the golden set |
| G2 CPF operations | EZPay builder = CPF spec sample; maker-checker lifecycle; supplementary advice; SDL/SHG golden | Real EZPay upload accepted; payment and amendment reconciliation | Employer payroll operations | CPF Board (EZPay / Corppass) | CPF Board acknowledgement + reconciliation record | Accepted file; totals reconcile | EXTERNAL EVIDENCE REQUIRED | Needs a live employer submission | Design-partner test submission |
| G3 IRAS | IR8A EXPORT_READY extract + manual lifecycle | AIS data validation; AIS-API 2.0 onboarding or signed export-only decision; acknowledgement | Product owner | IRAS | IRAS validation/acknowledgement; decision record | Accepted AIS data for a real employer | EXTERNAL EVIDENCE REQUIRED (API: NOT IMPLEMENTED) | No IRAS validation; API not onboarded | Decide export-only vs API; plan IRAS validation |
| G4 Tax clearance | IR21 lifecycle, distinct-approver release (refusals now audited), bank-file hold, register | Validation against current IRAS guidance / a real filing | Statutory compliance owner | IRAS | Guidance review + filing evidence | Workflow matches guidance; filing acknowledged | EXTERNAL EVIDENCE REQUIRED | No external validation | Compliance review against IRAS IR21 guidance |
| G5 Foreign workforce | S Pass no CPF; levy employer-only; LQS / PWM gates block approval; 6,132 PWM cells | Real MOM levy-bill reconciliation; unpublished MOM values (pre-July part-time LQS; WP levy before 24 Sep 2026 outside construction) | Statutory compliance owner | MOM | Levy bill reconciliation; published values | Bill reconciles; no BLOCKED rows in scope | EXTERNAL EVIDENCE REQUIRED; partly BLOCKED | Values not published by MOM | Obtain MOM values or scope them out; reconcile a real bill |
| G6 Labour pay | Employment Act rules; Part IV overtime; MOM incomplete-month table; holidays | Legal / MOM validation | Legal + compliance owner | MOM / legal counsel | Legal review memo | No open legal findings | EXTERNAL EVIDENCE REQUIRED | No legal sign-off | Legal review of the Employment Act controls |
| G7 Security/privacy | PDPC partial NRIC masking; no full NRIC in stored reports; tenant isolation; Super Admin-only RBAC; refusal auditing; retention report | PDPA/DPO approval; security review; recovery test | DPO + security owner | PDPC framework / internal DPO | DPO approval, pen-test / review report, recovery test record | Approvals signed; no critical findings | EXTERNAL EVIDENCE REQUIRED | No approvals yet | Schedule DPO + security review |
| G8 Parallel payroll | Two-cycle rehearsals (5.9, 6.4, 6.5) with golden cross-checks and replay stability | Live design-partner parallel run + annual AIS simulation | Implementation lead | Design-partner employer | Parallel-run reconciliation report | Two cycles + AIS with zero unexplained material differences | EXTERNAL EVIDENCE REQUIRED | No partner run | Select a partner; run two cycles in parallel |

## 10. Deployment safety review (analysis only; nothing changed)
- **Trigger:** `.github/workflows/backend-deploy.yml` (identical on main and venu). A **push to `main`** runs `test`
  (`pytest -q`), then `deploy` (`needs: test`, push only). Deploy SSHes to the server, runs `git pull origin main`,
  `pip install`, read-only diagnostics, then `bash ../scripts/deploy_migrate.sh`, then a head check. Pull requests run
  tests only; pushes to `nikhil` do nothing.
- **When Alembic runs:** first, before any lineage validation. `env.py` runs the whole `upgrade head` in one
  transaction, so on PostgreSQL a failing migration rolls back fully (**fails safely**).
- **Non-atomic steps after or instead of it:**
  1. `check_model_drift` can fail *after* a committed upgrade.
  2. `sync_schema` issues `ALTER TABLE … ADD COLUMN` in separate commits.
  3. On an **unknown (orphan) revision** the script's drift *check* calls `sync_schema()`, which **adds columns**, and
     may then refuse to stamp. That is a partial schema mutation on a refused deploy (reproduced: rehearsal E2 added 11
     columns and exited 1).
  4. If drift is empty, the stamp walk follows **first parents only**, and a pure merge revision at head counts as
     "applied", so it can `stamp --purge` head while tables are still missing. `check_model_drift` then fails with the
     wrong revision already stamped.
- **Is the baseline validated before mutation?** No.
- **Classification:** shared deployment infrastructure, **not Singapore code**. Not changed (outside scope; affects
  every deploy).
- **Proposed fixes for the deploy owner:**
  - make the orphan-path check read-only (`scripts/check_schema_drift.py` instead of `sync_schema()`);
  - refuse to stamp when the head is a merge revision, or walk all parents;
  - add a pre-flight asserting `alembic current` is in the repository's ancestry before `upgrade head`.
- **Operational rule until then:** only deploy a branch whose history contains the DB's revision (the venu-merged
  integration). The rehearsed E1 path then never reaches the orphan branch.

## 11. Test results
**Focused:** Phase 6.5 **22/22**. These tests fail on pre-6.5 code: 15 of the first 19 failed there (verified); the 4
that passed were the "unchanged behaviour" tests.

**Per suite (real tree = integration):**

| Suite | Result |
|---|---|
| `test_singapore.py` | 476 |
| Golden | 36 passed, 1 skipped |
| Phase 5.6 / 5.7 / 5.8 | 34 / 23 / 21 |
| Phase 6.0 (PostgreSQL test actually run) | 15 |
| Phase 6.3 | 25 |
| Phase 6.4 | 3 |
| Phase 6.5 | 22 |
| Alembic metadata | 6 |
| `test_report_templates.py` | 74 |
| `test_super_admin_ui_part11.py` (hotfix) | 27 |
| `test_model_tables_have_migrations.py` | 5 (integration only) |

**Full backend:**
- **Real tree:** 3,155 passed, 7 skipped, 0 failed.
- **Integration:** 3,680 passed, 7 skipped, 2 xfailed, 0 failed.
- **Skips:** the 6 empty "sample" golden parameter sets (AU/CRA/HMRC/IN/US/SG) and the opt-in PostgreSQL test. The
  xfails are venu's.
- Some skip paths print another worktree's name because of copied `__pycache__/*.pyc` files. The executed code is this
  repository's; cosmetic and pre-existing.

**Intentionally updated tests (they encoded the old, weaker behaviour):**
- `test_singapore.py`: the IR21 audit trail now contains the refused self-release, and the IR8A audit count is 4
  (3 + 1 refused).
- `test_singapore_phase60_remediation.py::test_f2e_self_approval_is_still_refused`: refusal now occurs at Approve.

**PostgreSQL re-rehearsal** (throwaway, real chain to `6247da96d605`): **172 PASS / 0 FAIL / 0 BLOCKED / 1 INFO**.
The database was dropped afterwards.

**Frontend:** Singapore ESLint 0 errors (14 files); repo-wide 420 (pre-existing baseline); build PASS (2,702 modules).
No frontend change.

## 12. Cross-jurisdiction regression — PASS
All of these ran in the zero-failure full suite (collected counts): Singapore 656, Germany 684, UK 80, Canada 84,
US 59, Australia 59, India 41, Trinidad & Tobago 18, shared report templates 110, hotfix/Super Admin UI 27. Every
Phase 6.5 behaviour change is Singapore opt-in; the shared functions only gained thin wrappers that change nothing
for other countries (proven by `test_a_other_countries_keep_unaudited_refusals`,
`test_a_non_sg_released_template_refusals_stay_unaudited`, `test_b_other_countries_keep_their_existing_approve_behaviour`).

## 13. Files changed in Phase 6.5
| File | Kind | Hunks |
|---|---|---|
| `backend/app/modules/payroll/service.py` | Shared (Singapore opt-in) | +150 / −21 in: refusal-audit constants/helpers, `set_jurisdiction_pack_status` wrapper, `set_jurisdiction_pack_approver`, `activate_jurisdiction_pack_hotfix`, `set_report_template_status` wrapper, `set_report_template_approver`, `_require_editable_report_template` + its 5 callers, `transition_sg_ir8a`, `transition_sg_ir21_case`, `transition_sg_cpf_ezpay`, `_sg_refuse_self_approval`, `_sg_pinned_pack`, `generate_sg_ir8a`, `generate_sg_sdl_monthly`, `generate_sg_ir21_register`, `generate_sg_cpf_ezpay` |
| `backend/tests/test_singapore.py` | Singapore test | 2 assertions (IR21 trail, IR8A count) |
| `backend/tests/test_singapore_phase60_remediation.py` | Singapore test | `test_f2e…` expects the Approve-step refusal |
| `backend/tests/test_singapore_phase65_hardening.py` | New | 22 tests |
| `docs/SINGAPORE_PHASE_6_5_HARDENING_AND_GATE_READINESS.md` | New | this file |

## 14. Files excluded / protected (unchanged, hash-verified)
- Germany docs, the Germany DOCX, `test_germany_report_templates.py`.
- The Phase 5.7 manifest.
- `Modal.jsx`, `payroll/index.jsx`, `SuperAdminShell.jsx`, `SGPwmSchedulesTab.jsx`.
- CORS files (`backend/.env.example`, `backend/app/config.py`).
- `seed_statutory_report_templates.py` is unchanged this phase; stage it with `git add -p` and leave out its 3 Germany
  hunks.

## 15. Production blockers
1. G1–G8 external evidence (§9).
2. Shared-DB lineage (§8), owner-led.
3. Deploy-pipeline safety defects (§10), deploy-script owner.
4. Hotfix policy + hotfix review gap (§7), owner decisions.
5. Merging to `main` auto-deploys: hold the main merge until 1–4 are resolved.

## 16. Recommended Phase 6.6 (not started)
- Owner decisions: hotfix option (§7) and gaps (a)/(b); whether refusal auditing and Approve-step self-approval should
  extend to all countries; the deploy-script fixes (§10).
- Owner-led shared-DB reconciliation rehearsal on a restored copy (§8, steps 2–3).
- G1–G8 evidence collection starting with a design-partner parallel run (G8) and the independent CPF comparison (G1).

## 17. Git safety state
Nothing staged, committed, pushed, merged or deployed. HEAD `83601eb`. The shared DB was accessed read-only only.
