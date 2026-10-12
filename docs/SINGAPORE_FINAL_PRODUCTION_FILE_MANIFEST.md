# Singapore — Final Production File Manifest

Status date: 2026-09-29 · Branch `nikhil` over `264c585` · Alembic head `445abd6a9083` (single head, 153 revisions).
Nothing is staged, committed, pushed, merged or deployed. The release owner performs those steps.

**Safe to stage: 65 files** (sections A–E). **Excluded: 14 files** (section F).

## A. Singapore-owned production files (16)

- `backend/app/modules/payroll/engine/countries/singapore.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory/ezpay.py`
- `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory_summary.py`
- `backend/scripts/seed_singapore_canonical_pack.py`
- `frontend/src/components/jurisdiction/singapore/SGBandFormModal.jsx`
- `frontend/src/components/jurisdiction/singapore/SGOverviewDashboard.jsx`
- `frontend/src/components/jurisdiction/singapore/SGPwmSchedulesTab.jsx`
- `frontend/src/components/jurisdiction/singapore/SGReportTemplatesTab.jsx`
- `frontend/src/components/jurisdiction/singapore/SGStatutoryComponentsTab.jsx`
- `frontend/src/components/jurisdiction/singapore/SGStatutorySummaryTab.jsx`
- `frontend/src/components/jurisdiction/singapore/sgComponentConfig.js`
- `frontend/src/components/jurisdiction/singapore/useSgStatutorySummary.js`
- `frontend/src/modules/payroll/Compliances/SGOperationsCards.jsx`
- `frontend/src/pages/JurisdictionCompliance/SGCompliancePage.jsx`
- `frontend/src/components/jurisdiction/singapore/SGReadinessTab.jsx`
- `frontend/src/pages/ReportTemplates/SGReportTemplatesPage.jsx`

## B. Shared production files requiring hunk review (18)

- `backend/app/modules/payroll/employee_validation.py` — SG field validation (work_pass_end_reason)
- `backend/app/modules/payroll/engine/base.py` — SG context fields
- `backend/app/modules/payroll/engine/resolver.py` — SG wiring
- `backend/app/modules/payroll/engine/tax_resolver.py` — SG opt-in: a missing registry row blocks onboarding
- `backend/app/modules/payroll/hmrc_golden_harness.py` — SG golden harness support
- `backend/app/modules/payroll/router.py` — org pack-route tax guard (all countries); SG routes
- `backend/app/modules/payroll/schemas.py` — optional `errors` on SG transition requests
- `backend/app/modules/payroll/service.py` — SG services; plus cross-jurisdiction: `_clone_pack_rates` copies every column (new pack versions), `taxPacksUsed` sorted, pack upsert target / pack-type immutability, optional status `reason`, template list tie-breaker
- `backend/app/modules/super_admin/router.py` — SG evidence / decision / supersede routes; `reason`, `actor_id` (additive)
- `backend/app/modules/super_admin/schemas.py` — SgEvidenceReview, SgDecisionCreate, SourceArtifactSupersede (additive)
- `frontend/src/App.jsx` — two /super-admin/report-templates/singapore routes (additive)
- `frontend/src/components/jurisdiction/JurisdictionLayout.jsx` — opt-in `autoSelectPack` prop (unset for other countries)
- `frontend/src/components/reportTemplates/ReportTemplateLayout.jsx` — `embedded` prop (hides page header only)
- `frontend/src/modules/payroll/Payroll_Employees/countryFieldSpecs.js` — SG employee field specs
- `frontend/src/pages/ReportTemplates/index.js` — SG export + map entry
- `frontend/src/service/payrollService.js` — generateSgIr8a, createSgIr8aModification only
- `frontend/src/service/superAdminService.js` — SG summary / PWM / evidence / decision calls
- `scripts/deploy_migrate.sh` — main's version + the refuse-before-mutate safety fix (deploy infrastructure)

## C. Migrations (6)

- `backend/alembic/versions/c3d9e1f4a7b2_add_singapore_cpf_employee_columns.py`
- `backend/alembic/versions/445abd6a9083_create_sgp_ir8a_modifications.py`
- `backend/alembic/versions/998877665544_drop_orphan_ie_fr_columns.py`
- `backend/alembic/versions/d4e5f6a7c8b9_create_auth_email_events_table.py`
- `backend/alembic/versions/e7f1a2b3c4d5_create_communication_events_table.py`
- `backend/alembic/versions/f0b1c2d3e4f5_drop_orphan_sgp_columns.py`
- Notes: `c3d9e1f4a7b2` is re-parented onto `998877665544`. The four migrations `d4e5f6a7c8b9`, `e7f1a2b3c4d5`, `f0b1c2d3e4f5` and `998877665544` are carried byte-identically from `origin/main`. No migration was added in the final closure passes.

## D. Tests (18)

- `backend/tests/fixtures/sg_golden/README.md`
- `backend/tests/test_alembic_metadata.py`
- `backend/tests/test_singapore_phase56_admin.py`
- `backend/tests/test_singapore_phase58_lifecycle.py`
- `backend/tests/test_singapore_phase63_hardening.py`
- `backend/tests/test_singapore_phase64_activation.py`
- `backend/tests/fixtures/sg_golden/wp_services_tier2_cancelled_mid_month.json`
- `backend/tests/test_deploy_migrate_script.py`
- `backend/tests/test_singapore_completion_programme.py`
- `backend/tests/test_singapore_evidence_lifecycle.py`
- `backend/tests/test_singapore_evidence_registry.py`
- `backend/tests/test_singapore_final_closure.py`
- `backend/tests/test_singapore_model_migrations.py`
- `backend/tests/test_singapore_multi_pack_reports.py`
- `backend/tests/test_singapore_pack_version_clone.py`
- `backend/tests/test_singapore_pass_cancellation.py`
- `backend/tests/test_singapore_pwm_retail_averaging.py`
- `backend/tests/test_singapore_seed_idempotency.py`

## E. Documentation (7)

- `docs/SINGAPORE_EXTERNAL_EVIDENCE_HANDOFF.md`
- `docs/SINGAPORE_FINAL_CLOSURE_REPORT.md`
- `docs/SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md`
- `docs/SINGAPORE_FINAL_PRODUCTION_FILE_MANIFEST.md`
- `docs/SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md`
- `docs/SINGAPORE_REAL_ORGANIZATION_VALIDATION.md`
- `docs/SINGAPORE_RELEASE_CHECKLIST.md`

## F. Files explicitly excluded — DO NOT STAGE (14)

- `backend/.env.example` — unrelated CORS change
- `backend/app/config.py` — unrelated CORS change
- `backend/scripts/seed_statutory_report_templates.py` — Germany hunks (Lohnsteuer labels)
- `backend/tests/test_germany_report_templates.py` — Germany work
- `frontend/src/components/Modal.jsx` — unrelated accessibility work
- `frontend/src/components/SuperAdminShell.jsx` — unrelated accessibility work
- `frontend/src/modules/payroll/index.jsx` — unrelated accessibility work
- `docs/GERMANY_2026_ORG38_LIVE_PAYROLL_UAT_FINAL.md` — Germany work
- `docs/GERMANY_2026_ORG38_REAL_PAYROLL_ACCURACY_FINAL.md` — Germany work
- `docs/GERMANY_2026_ORG38_REAL_PAYROLL_ACCURACY_UAT_REPORT.md` — Germany work
- `docs/GERMANY_2026_REPOSITORY_CONSOLIDATION_FINAL_REPORT.md` — Germany work
- `docs/GERMANY_PAP_ACTIVATION_RUNBOOK.md` — Germany work
- `docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md` — pre-existing Phase 5.7 manifest (superseded by this file)
- `docs/Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx` — Germany work

Never staged: scratch harnesses, disposable databases, screenshots, `.env` files, secrets. Everything generated lives in the release owner's scratchpad, outside the repository.

## Staging

```
git add --pathspec-from-file=<scratchpad>/stage_list.txt
git diff --cached --stat     # expect 65 files, none from section F
git commit -m "feat(payroll): complete Singapore jurisdiction production readiness"
```
