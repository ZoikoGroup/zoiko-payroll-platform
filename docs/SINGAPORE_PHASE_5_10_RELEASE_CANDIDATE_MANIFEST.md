# Singapore Payroll — Phase 5.10 Release Candidate Manifest

- **Date:** 2026-09-28
- **Branch / base:** `nikhil` @ `83601eb` (origin/nikhil identical). Working tree only — nothing staged, committed or pushed.
- **Status:** release candidate for **manual, hunk-reviewed** staging. Not deployed. Not activated. No CPF Board / IRAS / MOM / PDPC certification exists (`officialCertification: false` everywhere).
- **Supersedes nothing:** `docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md` is left untouched (protected).

## 1. Blockers that must be resolved BEFORE this is merged or deployed

### B1 — `main` drops the Singapore columns this release adds (merge blocker)
`origin/main` (head `f0b1c2d3e4f5`, commit `75caa48`, 2026-09-25) contains
`alembic/versions/f0b1c2d3e4f5_drop_orphan_sgp_columns.py`, which drops, if present:

- `payroll_employees`: `sgp_cpf_contribution_arrangement`, `sgp_cpf_residency_status`, `sgp_shg_funds`,
  `sgp_spr_effective_date`, `sgp_work_pass_end_date`, `sgp_work_pass_issue_date`, `sgp_work_pass_type`,
  `sgp_wp_levy_tier`, `sgp_wp_sector`, `sgp_wp_skill_level`
- `payslip_items`: `sgp_calculation_trace`

Its premise ("none of these columns are referenced by any current model") is true on `main` today and
**false once this release merges** — these are exactly the columns this release's models declare and its
migrations `c3d9e1f4a7b2`, `d4e8f2a6b9c1`, `e5f9a3b7c2d4`, `a7c2e9f4b1d6` add. After a merge the two
chains form two heads; depending on the order the merge revision applies them, `f0b1c2d3e4f5` can drop
live Singapore data. **Owner action (main / deploy owner):** agree how `f0b1c2d3e4f5` is neutralised for
the Singapore columns (e.g. made conditional on the columns not being declared by the models, or
superseded by a merge revision that runs it before the Singapore migrations) before the Singapore
migrations are merged. Not changed here — it is `main`'s migration.

### B1 resolution evidence (Phase 6.1 rehearsal, 2026-09-28, throwaway PostgreSQL only)
- A merge revision alone is **unsafe**: with `c3d9e1f4a7b2` still parented on `a5f6e7d8c9b0`, `alembic upgrade head`
  from the fork point ran `f0b1c2d3e4f5` after the Singapore migrations and left **0/10** `sgp_*` columns — silently.
- **Proposed:** re-parent `c3d9e1f4a7b2` onto `f0b1c2d3e4f5` (the six Singapore migrations are uncommitted and on
  no branch, so this is safe) and add one merge revision `(4b13831d574b, b8e3d5f2a9c7)` in the branch that merges
  second. Rehearsed from the fork point, from a `main`-style DB with orphan columns, a round trip, and `main`'s
  `deploy_migrate.sh` on a schema copy of the shared DB: 10/10 `sgp_*` columns, `sgp_wp_levy_tier` 20, one head.
- Deploy needs the **code** merged with `venu` too: on the schema copy the drift check fails until the models carry
  venu's `ie_*` / `fr_calculation_snapshot` columns.

### B2 — shared database migration lineage
The configured shared database (read-only inspection, 2026-09-28) records `alembic_version = 5ae06cfda828`.
That revision is **`origin/venu`'s** merge migration `5ae06cfda828_merge_venu_france_ireland_and_main_communications`
(parents `b1c2d3e4f5a6` + `f0b1c2d3e4f5`). The earlier value `e7f1a2b3c4d5` is `origin/main`'s
`create_communication_events_table`. Neither is in `nikhil`. `main`'s `scripts/deploy_migrate.sh`
re-stamps an "orphan" revision when a deploying branch does not know it, so the recorded revision follows
whichever branch deployed last. The database currently has no `sgp_*` columns (the drop ran), keeps an
empty `sgp_ir21_cases` table, has no `sgp_pwm_overtime_schedules`, no Singapore packs/templates, and no
`communication_events` table although `e7f1a2b3c4d5` is an ancestor of the recorded revision (a stamped,
not executed, revision). **Owner action:** the environment owner decides which branch owns this database,
reconciles `venu` + `main` + `nikhil` into one chain, and only then migrates. Never stamp from `nikhil`.

### B3 — empty-database migration (pre-existing, not Singapore)
`alembic upgrade head` from an empty database fails in `71d815f06d78` (US), which drops
`uq_contribution_rate_canonical_country_state_component` that the baseline `0b624a4a7481` never creates.
Present on `main` as well. Fresh databases use `python -m migrations.create_all.create_all` (documented).

### B4 — external evidence
Production gates G1–G8 (ZP-SG-ENG-001 §18), source-artifact review, live-employer validation.

## 2. INCLUDE — Singapore release files

**New (untracked) — Singapore only**
- `backend/alembic/versions/c3d9e1f4a7b2_add_singapore_cpf_employee_columns.py`
- `backend/alembic/versions/d4e8f2a6b9c1_add_payslip_sgp_calculation_trace.py`
- `backend/alembic/versions/e5f9a3b7c2d4_add_singapore_work_pass_validity_dates.py`
- `backend/alembic/versions/f6a1b4c8d3e5_create_sgp_ir21_cases.py`
- `backend/alembic/versions/a7c2e9f4b1d6_add_singapore_work_permit_levy_columns.py`
- `backend/alembic/versions/b8e3d5f2a9c7_create_sgp_pwm_overtime_schedules.py`
- `backend/app/modules/payroll/engine/countries/singapore.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/` (`__init__`, `compliance`, `labour`, `preflight`,
  `readiness`, `statutory_summary`, `statutory/__init__`, `statutory/ezpay`)
- `backend/scripts/seed_singapore_canonical_pack.py`, `backend/scripts/sg_pwm_overtime_schedules.json`
- `backend/tests/fixtures/sg_golden/` (36 fixtures + README), `backend/tests/sg_golden/`, `backend/tests/test_sg_golden.py`
- `backend/tests/test_singapore.py`, `test_singapore_phase56_admin.py`, `test_singapore_phase57_reports.py`,
  `test_singapore_phase58_lifecycle.py`, `test_singapore_phase60_remediation.py` (Phase 6.0 F1/F2/F3; its PostgreSQL
  test runs only when `P60_PG_URL` names a throwaway `p60_*` database)
- `frontend/src/components/jurisdiction/singapore/` except `SGPwmSchedulesTab.jsx` (see §4)
- `frontend/src/modules/payroll/Compliances/SGComplianceCentreTab.jsx`, `SGIr21CasesTab.jsx`, `SGOperationsCards.jsx`
- `frontend/src/modules/payroll/PayRollRuns/SGRunPreflightPanel.jsx`
- `frontend/src/pages/JurisdictionCompliance/SGCompliancePage.jsx`, `frontend/src/pages/JurisdictionStatutory/SGStatutoryPage.jsx`
- `docs/SINGAPORE_PHASE_5_10_RELEASE_CANDIDATE_MANIFEST.md` (this file)

**Modified — Singapore-only hunks (whole file)**
`backend/app/core/jurisdiction.py`, `engine/base.py`, `engine/countries/shared.py`, `engine/fallback_registry.py`,
`engine/resolver.py`, `engine/standard.py`, `payroll/models.py`, `payroll/router.py`, `super_admin/router.py`,
`super_admin/schemas.py`, `scripts/seed_jurisdiction_service_registry.py`, `tests/test_alembic_metadata.py`,
`tests/test_engine_jurisdiction_db_integration.py`, `frontend/src/App.jsx`, `CountryFlag.jsx`,
`Compliances/ComplianceForm.jsx`, `Compliances/CompliancePage.jsx`, `PayRollRuns/RunDetailPanel.jsx`,
`pages/JurisdictionCompliance/index.js`, `pages/JurisdictionStatutory/index.js`, `service/payrollService.js`,
`service/superAdminService.js`.

## 3. INCLUDE after hunk-level review (shared files)

| File | Include | Review / decide |
|---|---|---|
| `backend/app/modules/payroll/service.py` (107 hunks) | Singapore blocks (IR8A/SDL/EZPay/IR21/PWM/LQS/summary/preflight/readiness/corrections), SG pack-activation opt-in, SG wage-month / joiner plumbing, IR21 bank hold, SG PDF labels, **Phase 5.8 report-template lifecycle** (`REPORT_TEMPLATE_TRANSITIONS`, upsert lifecycle-field lock, approval invalidation, released-approval lock, `reason`) | **Cross-jurisdiction:** shared YTD posting refactor `_post_payslip_ytd` / `_ytd_record_postings` / `_refresh_ytd_after_correction` (corrections now re-post YTD for CA/US/AU/KY/GY/UK/JM), shared masking round-trip in `update_employee` / `bulk_update_employees`, `assessment_basis` snapshot replay fix (also fixes IN Chennai PT), US SSN last-4 on payslip PDFs (`_ssn_last_four`, `_payslip_identity_rows`) |
| `backend/app/modules/payroll/schemas.py` (8 hunks) | SG request schemas, `ReportTemplateStatusUpdate.reason` (5.8) | Shared masking of `EmployeeResponse` / `PayslipItemResponse` (all countries) |
| `backend/app/modules/payroll/employee_validation.py` (17 hunks) | `mask_nric_fin`, SG validation | `SENSITIVE_FIELDS` masking added for IN/US/UK/AU/CA/DE/Caribbean |
| `backend/app/modules/payroll/hmrc_golden_harness.py` | `text_value` / `tax_regime` fixture support used by SG golden vectors | shared harness |
| `backend/scripts/seed_statutory_report_templates.py` (10 hunks) | 5 hunks: SG templates, `_seed_template` description kwargs, non-Draft skip | **Exclude 3 Germany hunks** (DE-LSTB / DE-PAYROLL-SUMMARY Lohnsteuer + Soli labels, around L818, L838, L1325) |
| `frontend/src/modules/payroll/Payroll_Employees/EmployeeForm.jsx`, `countryFieldSpecs.js` | SG employee fields | masked-identifier round-trip (shared) |

## 4. EXCLUDE

- Germany: the 3 Germany hunks in `seed_statutory_report_templates.py`; `backend/tests/test_germany_report_templates.py`;
  all `docs/GERMANY_*`; `docs/Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx`.
- `docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md` (protected; authored outside these phases).
- `frontend/src/components/jurisdiction/singapore/SGPwmSchedulesTab.jsx` — **protected by instruction, but
  `SGCompliancePage.jsx` imports it (PWM Schedules tab); excluding it alone breaks the frontend build.**
  Decide: include it (its only post-5.6 change clears stale rows on error — reviewed) or exclude it together
  with its tab entry in `SGCompliancePage.jsx`.
- Unrelated: `backend/.env.example`, `backend/app/config.py` (local CORS dev ports);
  accessibility changes in `frontend/src/components/Modal.jsx`, `SuperAdminShell.jsx`, `frontend/src/modules/payroll/index.jsx`.
- Local stash `stash@{0}` (billing guard, "superseded by main") — not part of this release.
- Scratchpad rehearsal artifacts (`p59_*`, `p510_*`) — outside the repository.

## 5. Suggested commit split

1. `feat(sg): Singapore payroll jurisdiction — engine, statutory pack seed, PWM reference data, migrations`
2. `feat(sg): Singapore compliance, IR21/IR8A/EZPay/SDL/PWM/LQS reports, Super Admin configuration UI`
3. `fix(report-templates): enforce lifecycle transitions and maker-checker on template edits` (shared)
4. `feat(payroll): YTD posting reversal/re-post on delete and correction` (shared — separate review)
5. `feat(payroll): mask national identifiers in responses and PDFs` (shared — separate review)

## 6. Phase 6.0 remediation (2026-09-28)

- F1 `sgp_wp_levy_tier` String(20) (model + migration `a7c2e9f4b1d6`, edited in place: never committed or deployed).
- F2 Singapore packs: approver can never activate (`_APPROVER_NOT_ACTIVATOR_COUNTRIES = ("SG",)`; other countries unchanged).
- F3 `SG-PAYROLL-2026` seeded 2026-01-01 → 2026-12-31 so `SG-PAYROLL-2027` can follow it.

## 7. Verification evidence (2026-09-28)

Full backend and Singapore suites, golden vectors (36/36), Phase 5.6/5.7/5.8 tests, Alembic metadata,
seed idempotency, Singapore ESLint and the production build — see the Phase 5.10 audit report. The
Phase 5.9 activation rehearsal ran on disposable PostgreSQL 17 databases only (all dropped).
