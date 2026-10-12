# Singapore Payroll — Phase 6.3 Handover Manifest

- **Date:** 2026-09-28
- **Branch / base:** `nikhil` @ `83601eb`. Working tree only: nothing staged, committed, pushed, merged or deployed.
- **Builds on:** `docs/SINGAPORE_PHASE_5_10_RELEASE_CANDIDATE_MANIFEST.md` (blockers B1–B4, commit split).
  `docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md` is protected and left untouched.
- **Status:** hardening pass complete. **Production remains BLOCKED** (see §10). No CPF Board / IRAS / MOM / PDPC
  certification exists; `officialCertification` is `false` everywhere.

## 1. What Phase 6.3 changed in this working tree

| File | Hunk | Why | Other jurisdictions | Proof |
|---|---|---|---|---|
| `backend/app/modules/payroll/service.py` | `REPORT_TEMPLATE_TRANSITIONS`: `Draft` and `Review` no longer list `Published`; the error message adds an "approve first" hint | **Decision A.** Publishing now requires `Approved` (maker-checker shortcut removed) | **Shared.** It applies to every jurisdiction's report templates. Their normal path (approve, then Published, then Active) is unchanged | `test_singapore_phase63_hardening.py` (lifecycle), `test_report_templates.py`, every `test_*_report_forms.py`, full suite |
| `backend/app/modules/payroll/service.py` | `activate_jurisdiction_pack_hotfix`: the self-approval is no longer committed before activation; a refused activation rolls it back | **Decision B defect.** A refused hotfix used to leave a phantom `approved_by_id` with no approval audit row, and a second Super Admin could then activate on it through the normal path | **Shared.** Only the *refused* path changes; a successful hotfix behaves exactly as before | `test_singapore_phase63_hardening.py` (hotfix section, SG + US), `test_super_admin_ui_part11.py` (existing hotfix tests) |
| `backend/alembic/versions/f6a1b4c8d3e5_create_sgp_ir21_cases.py`, `b8e3d5f2a9c7_create_sgp_pwm_overtime_schedules.py` | `op.create_table(_TABLE, …)` becomes `op.create_table("<literal>", …)`, one line each | **P2.** venu's `tests/test_model_tables_have_migrations.py` only recognises a literal table name | None (Singapore migrations; no schema or semantic change) | Integrated suite: `test_model_tables_have_migrations.py` passes; PostgreSQL scenarios A–E |
| `backend/tests/test_singapore_phase58_lifecycle.py` | `allowedNextStatuses` for Draft is `["Review", "Approved"]`; one refusal now matches the transition message | These two assertions intentionally pinned the old shortcut | None | the file passes |
| `backend/tests/test_singapore_phase63_hardening.py` | new | Focused Decision A and Decision B tests | Includes one IN template and one US pack to prove the shared behaviour | 25 tests pass |
| `docs/SINGAPORE_PHASE_6_3_HANDOVER_MANIFEST.md` | new | This manifest | none | — |

**P1** (migration-lineage resilience) cannot live in `nikhil` on its own. Its merge revision's parent
`4b13831d574b` exists only on `main`/`venu`, so adding it here would break Alembic on this branch. It ships as
a handover file for the owner's merge commit (§11).

## 2. A. Singapore files intentionally included (new, Singapore-only)

| Path | Purpose |
|---|---|
| `backend/app/modules/payroll/engine/countries/singapore.py` | Singapore engine: CPF (OW/AW ceilings, age/SPR bands), SDL, SHG, FWL, incomplete-month (MOM), IRAS classification |
| `backend/app/modules/payroll/engine/jurisdictions/singapore/` (`__init__`, `compliance`, `labour`, `preflight`, `readiness`, `statutory_summary`, `statutory/__init__`, `statutory/ezpay`) | Compliance Centre, EA/PWM/LQS labour checks, run preflight, readiness, Super Admin statutory summary (11-template catalogue), CPF EZPay file builder |
| `backend/scripts/seed_singapore_canonical_pack.py` | Seeds SG-PAYROLL-2026 (ends 2026-12-31, F3) and SG-PAYROLL-2027, always as **Draft** |
| `backend/scripts/sg_pwm_overtime_schedules.json` | 6,132 MOM PWM overtime gross cells (84 schedules × 73 hours), with source hashes |
| `frontend/src/components/jurisdiction/singapore/*` (8 files) | Super Admin Singapore tabs: overview, statutory components, band form, summary, report templates, PWM schedules, config, summary hook |
| `frontend/src/modules/payroll/Compliances/SGComplianceCentreTab.jsx`, `SGIr21CasesTab.jsx`, `SGOperationsCards.jsx` | Org-facing Compliance Centre, IR21 cases, IR8A / EZPay / compliance-report cards |
| `frontend/src/modules/payroll/PayRollRuns/SGRunPreflightPanel.jsx` | Run preflight panel (BLOCK refuses approval) |
| `frontend/src/pages/JurisdictionCompliance/SGCompliancePage.jsx`, `frontend/src/pages/JurisdictionStatutory/SGStatutoryPage.jsx` | Singapore compliance and statutory pages |
| `docs/SINGAPORE_PHASE_5_10_RELEASE_CANDIDATE_MANIFEST.md`, this file | Release manifests |

**`SGPwmSchedulesTab.jsx`: intentionally INCLUDED.** It's a new, Singapore-only file that imports only
Singapore helpers and `getSingaporePwmSchedules`, with no Germany or unrelated content. Its only consumer is
`SGCompliancePage.jsx` (the PWM Schedules tab), so excluding it breaks the frontend build. It carries the
stale-row-clearing fix, lints clean, and builds.

## 3. B. Shared integration files intentionally included

| Path | Singapore purpose | Shared effect (review) |
|---|---|---|
| `backend/app/modules/payroll/service.py` | SG blocks (IR8A/SDL/EZPay/IR21/PWM/LQS/summary/preflight/readiness/corrections), SG pack-activation opt-ins (F2), SG wage-month/joiner plumbing, SG PDF labels | Report-template lifecycle (5.8 + 6.3 Decision A); hotfix phantom-approval fix (6.3); shared YTD posting refactor `_post_payslip_ytd` (5.10 commit 4); shared masking (5.10 commit 5) |
| `backend/app/modules/payroll/schemas.py` | SG request schemas, `ReportTemplateStatusUpdate.reason` | Shared masking of `EmployeeResponse` / `PayslipItemResponse` |
| `backend/app/modules/payroll/employee_validation.py` | `SGEmployeeValidation`, `mask_nric_fin` | `SENSITIVE_FIELDS` masking for other countries |
| `backend/app/modules/payroll/models.py` | `sgp_*` employee columns, `sgp_calculation_trace`, `SgpIr21Case`, `SgpPwmOvertimeSchedule` | Additive only |
| `backend/app/modules/payroll/router.py` | `/api/payroll/singapore/*` routes (payroll-operator RBAC) | Additive only |
| `backend/app/modules/super_admin/router.py`, `schemas.py` | Super Admin SG statutory summary, PWM schedules; `reason` on the template status route | Additive only |
| `backend/app/core/jurisdiction.py`, `engine/base.py`, `engine/resolver.py`, `engine/standard.py`, `engine/countries/shared.py`, `engine/fallback_registry.py` | Registers SG (tax schema, validation, YTD, engine routing) | SG entries only |
| `backend/app/modules/payroll/hmrc_golden_harness.py` | `text_value` / `tax_regime` fixture support for SG golden vectors | Shared harness (additive) |
| `backend/scripts/seed_jurisdiction_service_registry.py` | SG service-registry rows | Additive only |
| `backend/scripts/seed_statutory_report_templates.py` | 8 SG templates, `_seed_template` kwargs, non-Draft skip | **Stage with `git add -p`: exclude the 3 Germany hunks** (§8) |
| `frontend/src/App.jsx`, `CountryFlag.jsx`, `Compliances/ComplianceForm.jsx`, `Compliances/CompliancePage.jsx`, `PayRollRuns/RunDetailPanel.jsx`, `Payroll_Employees/EmployeeForm.jsx`, `Payroll_Employees/countryFieldSpecs.js`, `pages/JurisdictionCompliance/index.js`, `pages/JurisdictionStatutory/index.js`, `service/payrollService.js`, `service/superAdminService.js` | SG routes, flag, options, tabs, employee fields, API calls | Additive; `EmployeeForm` / `countryFieldSpecs` also carry the masked-identifier round-trip |

## 4. C. Migration files

| Path | Purpose |
|---|---|
| `c3d9e1f4a7b2_add_singapore_cpf_employee_columns.py` | CPF employee columns. **R1** (re-parent onto `f0b1c2d3e4f5`) is applied at merge time from the handover patch |
| `d4e8f2a6b9c1_add_payslip_sgp_calculation_trace.py` | `payslip_items.sgp_calculation_trace` |
| `e5f9a3b7c2d4_add_singapore_work_pass_validity_dates.py` | work-pass issue/end dates |
| `f6a1b4c8d3e5_create_sgp_ir21_cases.py` | `sgp_ir21_cases` (**P2** literal applied) |
| `a7c2e9f4b1d6_add_singapore_work_permit_levy_columns.py` | WP sector / skill / levy tier (F1: tier `String(20)`) |
| `b8e3d5f2a9c7_create_sgp_pwm_overtime_schedules.py` | `sgp_pwm_overtime_schedules` (**P2** literal applied) |
| *(handover)* `6247da96d605_merge_venu_main_and_singapore_heads.py` | Merge `(4b13831d574b, b8e3d5f2a9c7)` with **P1**: re-runs `d4e5f6a7c8b9` and `e7f1a2b3c4d5`'s own create-if-missing `upgrade()` (the `4b13831d574b` pattern); no-op downgrade |

All Singapore migrations are inspector-guarded (skip a column or table that already exists).

## 5. D. Tests

- New, Singapore: `test_singapore.py`, `test_sg_golden.py` + `sg_golden/` + `fixtures/sg_golden/` (36),
  `test_singapore_phase56_admin.py`, `test_singapore_phase57_reports.py`, `test_singapore_phase58_lifecycle.py`,
  `test_singapore_phase60_remediation.py`, `test_singapore_phase63_hardening.py`.
- Shared (5.10 commit 4): `test_ytd_posting_lifecycle.py`.
- Modified, SG-only hunks: `test_alembic_metadata.py` (nikhil head `b8e3d5f2a9c7`, 148 revisions; at merge time it is
  replaced by the handover's resolved version: head `6247da96d605`, 158 revisions, branchpoint `f0b1c2d3e4f5`),
  `test_engine_jurisdiction_db_integration.py`.

## 6. E. Frontend files
See §2 (Singapore) and §3 (shared). No frontend file changed in Phase 6.3.

## 7. F. Protected files (not staged by this release)
`frontend/src/components/Modal.jsx`, `frontend/src/modules/payroll/index.jsx` (accessibility),
`docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md`, `backend/tests/test_germany_report_templates.py`.

## 8. G. Germany files explicitly excluded
- The 3 Germany hunks in `backend/scripts/seed_statutory_report_templates.py` (DE-LSTB / DE-PAYROLL-SUMMARY Lohnsteuer
  and Soli labels).
- `backend/tests/test_germany_report_templates.py`.
- `docs/GERMANY_2026_ORG38_LIVE_PAYROLL_UAT_FINAL.md`, `docs/GERMANY_2026_ORG38_REAL_PAYROLL_ACCURACY_FINAL.md`,
  `docs/GERMANY_2026_ORG38_REAL_PAYROLL_ACCURACY_UAT_REPORT.md`, `docs/GERMANY_2026_REPOSITORY_CONSOLIDATION_FINAL_REPORT.md`,
  `docs/GERMANY_PAP_ACTIVATION_RUNBOOK.md`, `docs/Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx`.

## 9. H. Existing unrelated working-tree changes (not part of this release)
- `backend/.env.example`, `backend/app/config.py`: local CORS dev origins.
- `frontend/src/components/SuperAdminShell.jsx`: accessibility (with `Modal.jsx`, `payroll/index.jsx`).

## 10. Remaining blockers — production stays BLOCKED
1. **External statutory evidence (B4):** gates G1–G8, source-artifact review, live-employer validation. The Singapore
   packs and templates are Draft; nothing has been activated.
2. **Shared database (B2):** read-only inspection on 2026-09-28 found:
   - `alembic_version = 5ae06cfda828` (venu's merge) against an expected integrated head of `6247da96d605`;
   - no `sgp_pwm_overtime_schedules`, an orphan empty `sgp_ir21_cases`, 0 `sgp_*` columns;
   - no `communication_events` (`4b13831d574b` restores it), `auth_email_events` present;
   - 0 Singapore packs, templates and organizations.

   It needs **owner-led migration planning**. Never stamp or upgrade it from `nikhil`.
3. **Deploy pipeline:** merging to `main` auto-triggers the production deploy and migration. `scripts/deploy_migrate.sh`'s
   orphan-revision path still adds columns while refusing to stamp (rehearsal E2). That belongs to the deploy-script owner.
4. **Hotfix policy (Decision B release decision):** hotfix activation remains available for Singapore as an audited
   emergency path. A lone Super Admin can activate an **evidenced, golden-PASS** SG pack with an incident ID and
   justification, recorded for mandatory retrospective review. An SG-only prohibition is technically isolatable; it is
   an owner decision, not a defect.

## 11. Handover files (outside the repository)
`scratchpad/p63_handover/`:
- `R1_c3d9_reparent.patch`
- `6247da96d605_merge_venu_main_and_singapore_heads.py` (final, with P1)
- `resolved/` (15 resolved conflict files, including the 6.3 `service.py` changes)
- `resolved_vs_venu.diff`
- `include_paths.txt`
- `include_hunks_only.txt`
