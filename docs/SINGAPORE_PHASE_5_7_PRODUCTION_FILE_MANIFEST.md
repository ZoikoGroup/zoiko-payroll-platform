# Singapore Payroll Phase 5.7 Production File Manifest

- **Snapshot date:** 2026-09-25
- **Branch:** `nikhil`
- **Baseline HEAD:** `83601ebc6a9b495eac69a3e36fa2a23031c8ed20`
- **Delivery state:** Working-tree candidate only; uncommitted and unpushed.

## 1. Scope and handling rules

This manifest identifies the Singapore production change set and its verification evidence. It does not authorize deployment, statutory filing, CPF Board, IRAS, MOM, or PDPC certification, or approval of any statutory template.

- Include Singapore implementation, migration, seed, frontend, and test files listed below.
- Review shared files hunk by hunk before staging; paths marked **shared** also support other jurisdictions.
- Do not include any path in the explicit exclusion section.
- Do not regenerate PWM source data. The canonical file contains 6,132 rows and the seed is append-only and idempotent.
- Preserve the report lifecycle: Draft → Review → Approved → Published → Active → Superseded.
- Do not demote or rewrite a promoted template. Refresh only Draft records.
- Keep `officialCertification` false unless a separate, evidenced approval process is completed.

## 2. Phase 5.7 production files

### Documentation

| State | Path | Purpose |
|---|---|---|
| New | `docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md` | This production handoff manifest and deployment-gate record. |

### Backend API, models, generators, and reference data

| State | Path | Purpose |
|---|---|---|
| Modified | `backend/app/modules/payroll/models.py` | Persists Singapore PWM schedules and report metadata; **shared**. |
| Modified | `backend/app/modules/payroll/router.py` | Dedicated Singapore PWM, LQS, and IR21 report routes; **shared**. |
| Modified | `backend/app/modules/payroll/schemas.py` | Singapore report request and response contracts; **shared**. |
| Modified | `backend/app/modules/payroll/service.py` | Super Admin summary, filtered PWM listing, lifecycle checks, and three report generators; **shared**. |
| Modified | `backend/app/modules/super_admin/router.py` | Super Admin-only Singapore summary and PWM schedule endpoints. |
| Modified | `backend/app/modules/super_admin/schemas.py` | PWM pagination/filter and schedule-row response schemas. |
| New | `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory_summary.py` | Eleven-template catalog, production-gate status, and statutory summary layout. |
| Modified | `backend/scripts/seed_statutory_report_templates.py` | Seeds the eleven Singapore templates without demoting promoted versions; **shared**. |
| New | `backend/scripts/seed_singapore_canonical_pack.py` | Seeds the canonical Singapore pack and the 6,132-row PWM schedule idempotently. |
| New | `backend/scripts/sg_pwm_overtime_schedules.json` | Canonical effective-dated PWM reference rows and source traceability. |
| New | `backend/alembic/versions/b8e3d5f2a9c7_create_sgp_pwm_overtime_schedules.py` | Additive, inspector-guarded PWM schedule table migration. |

### Frontend API and views

| State | Path | Purpose |
|---|---|---|
| Modified | `frontend/src/service/superAdminService.js` | Super Admin statutory-summary and PWM-schedule API clients; **shared**. |
| Modified | `frontend/src/App.jsx` | Registers Singapore Super Admin compliance and statutory routes; **shared**. |
| Modified | `frontend/src/components/jurisdiction/CountryFlag.jsx` | Adds the Singapore flag; **shared**. |
| Modified | `frontend/src/pages/JurisdictionCompliance/index.js` | Exports the Singapore compliance page and route slug; **shared**. |
| Modified | `frontend/src/pages/JurisdictionStatutory/index.js` | Exports the Singapore statutory page; **shared**. |
| New | `frontend/src/pages/JurisdictionCompliance/SGCompliancePage.jsx` | Integrates overview, statutory components, summary, PWM, templates, evidence, and golden vectors. |
| New | `frontend/src/pages/JurisdictionStatutory/SGStatutoryPage.jsx` | Singapore statutory-rates route wrapper. |
| New | `frontend/src/components/jurisdiction/singapore/SGStatutorySummaryTab.jsx` | Read-only statutory configuration and production-gate summary. |
| New | `frontend/src/components/jurisdiction/singapore/SGPwmSchedulesTab.jsx` | Read-only, filtered, server-paginated PWM schedule viewer. |
| New | `frontend/src/components/jurisdiction/singapore/SGReportTemplatesTab.jsx` | Eleven-template availability and lifecycle evidence view. |
| New | `frontend/src/components/jurisdiction/singapore/useSgStatutorySummary.js` | Shared loading hook for Singapore summary consumers. |
| New | `frontend/src/components/jurisdiction/singapore/SGStatutoryComponentsTab.jsx` | CPF, SDL, SHG, LQS, FWL, and other statutory component display. |
| New | `frontend/src/components/jurisdiction/singapore/SGOverviewDashboard.jsx` | Singapore country-level compliance overview. |
| New | `frontend/src/components/jurisdiction/singapore/SGBandFormModal.jsx` | Singapore band editing through the existing lifecycle controls. |
| New | `frontend/src/components/jurisdiction/singapore/sgComponentConfig.js` | Frontend-only formatting and component configuration; no statutory calculation. |

### Focused tests

| State | Path | Coverage |
|---|---|---|
| New | `backend/tests/test_singapore_phase56_admin.py` | Super Admin RBAC, summary, PWM filters/pagination, and source evidence. |
| New | `backend/tests/test_singapore_phase57_reports.py` | PWM/LQS/IR21 generators, tenancy, lifecycle, masking, and template preservation. |
| New | `backend/tests/test_singapore.py` | Singapore payroll regression, canonical pack, PWM seed count, and second-run idempotency. |
| New | `backend/tests/test_sg_golden.py` | Exact Singapore golden-vector execution. |
| New | `backend/tests/sg_golden/__init__.py` | Golden harness package marker. |
| New | `backend/tests/sg_golden/runner.py` | Singapore golden-case adapter. |
| New | `backend/tests/fixtures/sg_golden/README.md` | Fixture provenance and limitations. |
| New | `backend/tests/fixtures/sg_golden/*.json` | Thirty-six Singapore golden cases. |

## 3. Required earlier Singapore prerequisites

These files are outside the direct Phase 5.7 API/view list but are part of the deployable Singapore runtime and must travel with it.

### Backend runtime and migrations

- `backend/.env.example`
- `backend/app/config.py`
- `backend/app/core/jurisdiction.py`
- `backend/app/modules/payroll/employee_validation.py`
- `backend/app/modules/payroll/engine/base.py`
- `backend/app/modules/payroll/engine/countries/shared.py`
- `backend/app/modules/payroll/engine/countries/singapore.py`
- `backend/app/modules/payroll/engine/fallback_registry.py`
- `backend/app/modules/payroll/engine/resolver.py`
- `backend/app/modules/payroll/engine/standard.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/__init__.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/compliance.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/labour.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/preflight.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/readiness.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory/__init__.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory/ezpay.py`
- `backend/app/modules/payroll/hmrc_golden_harness.py`
- `backend/scripts/seed_jurisdiction_service_registry.py`
- `backend/alembic/versions/f6a1b4c8d3e5_create_sgp_ir21_cases.py`
- `backend/alembic/versions/e5f9a3b7c2d4_add_singapore_work_pass_validity_dates.py`
- `backend/alembic/versions/d4e8f2a6b9c1_add_payslip_sgp_calculation_trace.py`
- `backend/alembic/versions/c3d9e1f4a7b2_add_singapore_cpf_employee_columns.py`
- `backend/alembic/versions/a7c2e9f4b1d6_add_singapore_work_permit_levy_columns.py`
- `backend/tests/test_alembic_metadata.py`
- `backend/tests/test_engine_jurisdiction_db_integration.py`

All paths in this section are shared integration points unless they are new Singapore-only files. Stage only reviewed Singapore-required hunks where necessary.

### Frontend organization workflow

- `frontend/src/modules/payroll/Compliances/ComplianceForm.jsx`
- `frontend/src/modules/payroll/Compliances/CompliancePage.jsx`
- `frontend/src/modules/payroll/Compliances/SGComplianceCentreTab.jsx`
- `frontend/src/modules/payroll/Compliances/SGIr21CasesTab.jsx`
- `frontend/src/modules/payroll/Compliances/SGOperationsCards.jsx`
- `frontend/src/modules/payroll/PayRollRuns/RunDetailPanel.jsx`
- `frontend/src/modules/payroll/PayRollRuns/SGRunPreflightPanel.jsx`
- `frontend/src/modules/payroll/Payroll_Employees/EmployeeForm.jsx`
- `frontend/src/modules/payroll/Payroll_Employees/countryFieldSpecs.js`
- `frontend/src/service/payrollService.js`

## 4. Eleven-template catalog

The lifecycle and classification remain explicit and un-certified:

1. `SG-IR8A`
2. `SG-SDL-MONTHLY`
3. `SG-CPF-EZPAY`
4. `SG-PAYROLL-REGISTER`
5. `SG-PAYROLL-SUMMARY`
6. `SG-CPF-CONTRIBUTION`
7. `SG-SHG-MONTHLY`
8. `SG-FWL-MONTHLY`
9. `SG-PWM-COMPLIANCE`
10. `SG-IR21-REGISTER`
11. `SG-LQS-COMPLIANCE`

The seed is safe to rerun: it inserts missing Draft templates and preserves any template already promoted beyond Draft.

## 5. Explicit exclusions

Do not include these current working-tree changes in the Singapore production change set:

- `backend/tests/test_germany_report_templates.py`
- `docs/GERMANY_2026_ORG38_LIVE_PAYROLL_UAT_FINAL.md`
- `docs/GERMANY_2026_ORG38_REAL_PAYROLL_ACCURACY_FINAL.md`
- `docs/GERMANY_2026_ORG38_REAL_PAYROLL_ACCURACY_UAT_REPORT.md`
- `docs/GERMANY_2026_REPOSITORY_CONSOLIDATION_FINAL_REPORT.md`
- `docs/GERMANY_PAP_ACTIVATION_RUNBOOK.md`
- `docs/Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx`
- `frontend/src/components/Modal.jsx` — unrelated accessibility changes
- `frontend/src/components/SuperAdminShell.jsx` — unrelated accessibility/text changes
- `frontend/src/modules/payroll/index.jsx` — unrelated accessibility changes
- `backend/tests/test_ytd_posting_lifecycle.py` — unrelated shared lifecycle work

Do not include generated caches, `.pytest_cache`, `__pycache__`, virtual environments, local databases, or `frontend/dist` output.

## 6. Verification evidence

- `python -m pytest -q tests/test_singapore.py` — 476 passed.
- `python -m pytest -q tests/test_singapore_phase56_admin.py tests/test_singapore_phase57_reports.py` — 57 passed.
- `python -m pytest -q tests/test_alembic_metadata.py` — 6 passed.
- Impacted backend regression set — 825 passed, 1 skipped.
- `python -m alembic heads` — one head: `b8e3d5f2a9c7`.
- `git diff --check` — passed; only line-ending conversion warnings were emitted.
- Singapore frontend ESLint target — passed with no findings.
- `npm run build` — passed; Vite emitted only the existing large-chunk warning.
- Repository-wide frontend ESLint — baseline failure with 430 unrelated findings.
- Backend Ruff — not run because Ruff is not installed in the active Python environment (`No module named ruff`).
- Full monolithic backend pytest invocation was interrupted before a final result; the Singapore and impacted regression groups above completed successfully.

## 7. Deployment gates and cautions

1. The migration graph has one repository head, `b8e3d5f2a9c7`, and the PWM migration follows `a7c2e9f4b1d6`.
2. The currently configured database is not at a repository-known Alembic revision: `alembic_version` contains `e7f1a2b3c4d5`, that revision is absent from the repository, and `sgp_pwm_overtime_schedules` is not present. Do not upgrade or stamp it until the environment owner establishes its true migration baseline.
3. Install the repository-standard Ruff version before release, then run `python -m ruff check app/ tests/` and resolve findings without mixing unrelated jurisdictions.
4. Separate the unrelated baseline lint debt from this delivery; the Singapore target files currently pass ESLint.
5. Run the canonical Singapore pack seed and report-template seed in the approved environment. Confirm the PWM count is 6,132 and the second run inserts zero PWM rows.
6. Promote report templates only through the existing maker-checker lifecycle. Do not set `officialCertification` based on this manifest or automated tests.
7. Obtain accountable Singapore statutory and privacy review before production activation or external filing.
