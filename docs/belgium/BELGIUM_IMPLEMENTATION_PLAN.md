# Belgium (BE) Implementation Plan — ZP-BE-ENG-001 v1.0

Spec: docs/belgium/Zoiko_Payroll_Belgium_Engineering_Implementation_Wireframe_v1.0.docx
Plan baseline commit: 1512855 (re-verified against 1af3d44 in Phase 0). Alembic head at planning: efc56f3235e2.
Status: live Belgian payroll remains disabled until release gates G1–G7 pass (spec §17).

## 1. Architecture decision
Belgium follows the Poland (ZP-PL-ENG-001) "generation 2" pattern:
- fail-closed orchestrator engine/countries/belgium.py over bounded modules in engine/jurisdictions/belgium/
- pay-date-scoped pack reader that blocks on "[PENDING G1]"
- dedicated payroll_be_* tables (versioned, four-eyes, org + legal_entity scoped)
- encrypted identifier vault
- append-only accumulator ledger
- filing / obligation state machines
- jurisdiction_hooks with all 13 hooks
- dormancy flag + canary
- registry row PLANNED

Australia and Canada (generation 1: employee columns, ungoverned generic rate editors, not fail-closed) are references only for the shared UI shell and the pack/assignment flow. No statutory values are taken from any other country.

## 2. Current-state facts (verified at baseline)
- Belgium is absent from the backend.
- get_jurisdiction_code("Belgium") returns None, so onboarding is refused today.
- is_supported_employee_country("BE") is False.
- Countries missing from engine/standard.py _COUNTRY_CALC fall through to _calc_generic. Phase 1 must register BE as fail-closed.
- Risk: adding BE to JURISDICTION_TAX_SCHEMAS without adding it to engine/tax_resolver._REGISTRY_ROW_REQUIRED_COUNTRIES would let an Active pack open onboarding. Both changes must go in the same commit.
- The only existing literal "BE" is the Swiss canton list (SwitzerlandStatutoryProfilePanel.jsx). There is no attendance-code collision.
- payroll.service._normalize_country resolves "Belgium" to "BE" only by [:2] truncation, so explicit aliases are required.

## 3. Payroll execution flow (integration map)
create_payroll_run → generate_payslips_for_run → _compute_payslip_values → _resolve_effective_rate_inputs (canonical pack only for listed countries) → jurisdiction_hooks calc_inputs → build_context_from_employee(**belgium_inputs) → engine/resolver.calculate_payroll (simple-mode block) → StandardStrategy → _COUNTRY_CALC["BE"] → result keys mapped onto PayrollResult → payslip_items.be_calculation_snapshot → advance_payroll_run_status (before_run_transition hook) → payment_treatment hook → filings built after PAID.
The preview path is preview_payroll_run; manual items go through add_payslip_item.

## 4. Integration points in shared code (all additive)
Backend:
- app/core/jurisdiction.py: JURISDICTION_TAX_SCHEMAS, COUNTRY_NAME_TO_CODE, CODE_TO_COUNTRY_NAME (NOT REGISTRATION_COUNTRIES until release)
- engine/tax_resolver.py: _REGISTRY_ROW_REQUIRED_COUNTRIES
- engine/resolver.py: simple-mode block; build_context_from_employee belgium_inputs
- engine/standard.py: _COUNTRY_CALC; be_employee_total summed at the same point as pl_employee_total; be_result mapping
- engine/base.py: PayrollContext be_* fields (default None); PayrollResult.be_result
- modules/payroll/service.py:
  - _CANONICAL_PACK_ONLY_COUNTRIES
  - _APPROVER_NOT_ACTIVATOR_COUNTRIES, _SELF_APPROVAL_REFUSED_COUNTRIES, _REFUSAL_AUDIT_COUNTRIES, _PACK_TRANSITION_GRAPH_COUNTRIES
  - generic statutory edit refusal (PL equivalent near _refuse_nz_generic_statutory_edit)
  - country label map
  - calc sites in preview_payroll_run, _compute_payslip_values, add_payslip_item
  - _serialize_payslip
- modules/payroll/jurisdiction_hooks.py: _MODULES["BE"]
- modules/payroll/employee_validation.py: _DORMANT_STRATEGIES + _dormant_strategy() branch
- modules/payroll/bank_routing.py: ROUTING_COUNTRIES, ROUTING_FIELDS, labels
- modules/payroll/router.py: mount be_org_router
- modules/super_admin/router.py: /compliance/belgium routes
- app/config.py: BE_TENANT_ONBOARDING_ENABLED, BE_CANARY_ORG_IDS, BE_IDENTIFIER_KEYRING, BE_IDENTIFIER_FINGERPRINT_KEY

Frontend:
- App.jsx routes
- pages/JurisdictionCompliance/index.js (export + COUNTRY_CODE_TO_ROUTE BE:"belgium")
- modules/payroll/Compliances/CompliancePage.jsx (Belgium Compliance Centre tab)
- Payroll_Employees/EmployeeDetailPanel.jsx, countryFieldSpecs.js, bankFieldsFor.js
- PayRollRuns/RunDetailPanel.jsx
- PaySlips/PayslipStub.jsx (BE branch)
- utils/currency.js (code map BE:"EUR"), utils/jurisdictionLabels.js, utils/jurisdictionTax.js
- components/jurisdiction/CountryFlag.jsx
- service/payrollService.js, service/superAdminService.js

## 5. Reused tables (no schema change unless stated)
- payroll_jurisdiction_packs (BERulePack)
- payroll_contribution_rates and payroll_tax_slabs (pack rows, row-level effective dates; Annex III via rule_type + formula_expression)
- payroll_source_artifacts (evidence S1–S24, hashes)
- payroll_tax_configuration_audit
- payroll_pack_hotfix_activations
- payroll_company_compliance (active_pack_id; assign_pack_to_organizations reused unchanged)
- payroll_collective_agreements (Joint Committee / sub-committee CBA packs, BE-021)
- payroll_statutory_filing_calendar (authority calendar, BE-035)
- payroll_holidays (via pack_holidays hook; employer substitutes as category "Substitute", audited)
- payroll_report_templates / payroll_generated_reports (281.10 employee copy, individual account, holiday certificate)
- jurisdiction_service_registry (BE row PLANNED)
- legal_entities
- payroll_employees (country_code, legal_entity_id, pay_frequency, compliance_fields)
- payroll_runs: + be_approval_fingerprint JSON
- payslip_items: + be_calculation_snapshot JSON
Shared code reused unchanged: bank_export/sepa_pain001.py.

## 6. New tables (payroll_be_*)
Foundation:
- identifier_vault, identifier_access_events
- employer_registrations, establishment_units
- worker_profiles, work_schedules, employment_classifications
- declarations, accumulator_entries
Absence / holiday:
- absence_episodes, holiday_certificates
Payment (D13):
- payment_batches, payment_items
Filing:
- filings, obligations, reconciliation_variances
Parallel:
- parallel_imports, parallel_differences

## 7. New modules
Backend:
- engine/countries/belgium.py, belgium_content.py (keys/vocabularies only)
- engine/jurisdictions/belgium/{errors, pack, applicability, bases, onss, withholding, wages, working_time, holiday, absence, declarations}.py
- modules/payroll/{belgium_service, belgium_dormancy, belgium_readiness, be_identifiers, be_org_router, be_super_admin, belgium_filing, belgium_settlement, belgium_payment_service, belgium_parallel, belgium_golden}.py
- scripts/seed_belgium_registry.py, scripts/seed_belgium_canonical_packs.py
Frontend:
- pages/JurisdictionCompliance/BECompliancePage.jsx
- config/jurisdictions/belgiumComplianceConfig.jsx
- components/jurisdiction/belgium/* (thin; imports the shared japan/ and new_zealand/ helpers that Poland uses; no Poland file changes)
- Compliances/BEComplianceCentreTab.jsx, BEFilingSettlementPanel.jsx, BEParallelCyclesSection.jsx
- Payroll_Employees/BelgiumStatutoryProfilePanel.jsx, BEIdentifierField.jsx
- PayRollRuns/BERunPreflightPanel.jsx, BEPayslipBreakdown.jsx, BEPaymentPanel.jsx

## 8. Derived calculation order (G-01: needs specialist confirmation)
1. Pay/payment date, quarter and pack set
2. Applicability resolver (§2, fail closed)
3. Earning classification (BE-006)
4. Independent bases (BE-007)
5. Sector minimum / RMMMG check (exception, never auto-pay)
6. Overtime and premiums
7. ONSS employee (108% base for manual / assimilated workers only)
8. Social work bonus
9. Withholding taxable basis (Annex III)
10. Regular withholding → family/reduction layer → fiscal work bonus
11. Exceptional-remuneration withholding (separate strategy)
12. Employer ONSS: base / special / holiday / reductions kept separate
13. Net, employer cost, obligation deltas, exceptions, hashes
Rounding only through signed pack rows (be_rounding_*).
Platform key mapping:
- tds = withholding
- be_employee_total = employee ONSS after reductions
- employer_esi = employer ONSS base + special
- employer_pension = occupational pension contribution
- be_result = everything
- Manual-worker holiday contributions go only to obligation deltas.

## 9. Roadmap
- P1 Fail-closed scaffold and registration
- P2 Database foundation
- P3 Content model and Super Admin governed console
- P4 Employer / worker / classification setup and resolver endpoint
- P5 Core engine (bases, ONSS, withholding) and payroll-flow integration
- P6 Sector wages, indexation, working time, public holidays
- P7 Holiday pay and absence engines
- P8 Run lifecycle, payslip, corrections, SEPA payment (G-18 acceptance)
- P9 Dimona / DmfA / withholding / Belcotax builders, obligations, calendar, settlement (transmission stubbed behind G3)
- P10 Parallel run, golden checks, readiness gates G1–G7, canary runbook
Alembic sequence from the current head: be_foundation (P2) → be_absence_holiday (P7) → be_payment (P8) → be_filing_obligations (P9) → be_parallel (P10).

## 10. Decisions (all DECIDED)
- D1 Poland Gen-2 pattern
- D2 dedicated payroll_be_* tables
- D3 CBA packs in payroll_collective_agreements
- D4 routes /api/payroll/belgium and /api/super-admin/compliance/belgium; simulate/commit map onto preview_payroll_run and the run lifecycle
- D5 thin BE frontend files using the shared JP/NZ helpers
- D6 first scope = private-sector ordinary payroll; special regimes and termination block
- D7 BSSC not implemented; pending key + exception
- D8 rounding as signed pack rows
- D9 transmission adapters stubbed behind G3
- D10 English operator payslip first; nl/fr/de as content keys
- D11 roadmap P1–P10
- D12 external content supplied by a Belgian specialist
- D13 payroll_be_payment_batches/_items mirroring NL, using sepa_pain001 unchanged
- D14 be_identifiers.py with its own keyring settings
- D15 substitute holidays in payroll_holidays, audited

## 11. Gaps
- G-01 calculation order not consolidated
- G-02 no rounding rules
- G-03 Annex III tables / formulas absent
- G-04 work-bonus parameters absent
- G-05 wage moderation / 1.60% threshold / fund rates absent
- G-06 BSSC not mentioned
- G-07 manual-worker guaranteed-salary day bands absent
- G-08 ONSS rate-file and authority schemas external
- G-09 public holiday dates / substitution rules absent
- G-10 index-centime mechanics unspecified
- G-11 pay-frequency scope
- G-12 definition of "high-risk" for four-eyes
- G-13 legal language rules
- G-14 spec /be/ API paths vs repo convention
- G-15 BIK / meal voucher / ecocheque values absent
- G-16 KBO/BCE, ONSS and NISS format / check-digit rules unverified
- G-17..G-20 as recorded in BELGIUM_GAPS_AND_DECISIONS.md

## 12. Regression rules
- Every shared change is additive and guarded by country == "BE".
- No other country's calculation changes.
- Each phase runs its new tests plus test_registration_jurisdiction_gate.py, test_multi_country_payroll_e2e.py, all test_poland_*.py, and the full backend suite from Phase 5 onward.
- Single Alembic head after every migration phase.

## Appendix A — Errata and verified locations (Phase 0, commit 1af3d44)
Path convention: "engine/..." = backend/app/modules/payroll/engine/...; "bank_export/..." = backend/app/modules/payroll/bank_export/...; "service.py", "jurisdiction_hooks.py", "employee_validation.py", "bank_routing.py", "router.py" = backend/app/modules/payroll/...; "core/..." and "config.py" = backend/app/...
Corrections:
- Poland's generic-edit refusal is a PL branch inside service._refuse_nz_generic_statutory_edit (no separate function); Belgium adds a BE branch there.
- _calc_generic is a module variable (standard.py:141); fall-through is _COUNTRY_CALC.get(..., _calc_generic) (standard.py:281).
- _normalize_country (service.py:142–161) tries core.jurisdiction.get_jurisdiction_code first, then [:2]; "Belgium" currently reaches "BE" only via the [:2] fallback.
- is_supported_employee_country is in employee_validation.py:2137.
- Other existing Belgium literals (no collision): frontend utils/currency.js:17 (name map) and :193 (country list), utils/registrationRegions.js:149 and :311. The currency CODE map (lines 1–12) has no BE.
- Config: Phase 1 mirrors only PL_TENANT_ONBOARDING_ENABLED / PL_CANARY_ORG_IDS; the identifier keyring pair is Phase 4.

Verified line map at 1af3d44:

Backend (paths relative to backend/app/; engine/ = modules/payroll/engine/)

| Point | Location |
|---|---|
| `JURISDICTION_TAX_SCHEMAS` | `core/jurisdiction.py:83` |
| `COUNTRY_NAME_TO_CODE` | `core/jurisdiction.py:718` |
| `CODE_TO_COUNTRY_NAME` | `core/jurisdiction.py:787` |
| `REGISTRATION_COUNTRIES` (not to be touched until release) | `core/jurisdiction.py:27` |
| `_REGISTRY_ROW_REQUIRED_COUNTRIES` | `engine/tax_resolver.py:318` |
| Simple-mode block (Poland's) | `engine/resolver.py:167` |
| `build_context_from_employee` | `engine/resolver.py:191`; `poland_inputs` at 304 and 515 |
| `_COUNTRY_CALC` | `engine/standard.py:168`; `"PL"` at 251 |
| `pl_employee_total` sum | `engine/standard.py:369` |
| `pl_result` mapping | `engine/standard.py:659` |
| `PayrollContext` | `engine/base.py:35`; `pl_*` fields from 1018 |
| `PayrollResult` | `engine/base.py:1175`; `pl_result` at 1800 |
| `_CANONICAL_PACK_ONLY_COUNTRIES` | `service.py:1548` |
| The four governance tuples | `service.py:8622`, `8625`, `8629`, `8636` |
| Country label map (`_GATED_PACK_COUNTRY_NAMES`) | `service.py:8618` |
| `preview_payroll_run` calc sites | `service.py:20631`, `20676` |
| `_compute_payslip_values` calc sites | `service.py:25813`, `25888` |
| `add_payslip_item` calc sites | `service.py:32940`, `33008` |
| `_serialize_payslip` | `service.py:33562` |
| `_MODULES` | `jurisdiction_hooks.py:27` |
| `_DORMANT_STRATEGIES` | `employee_validation.py:2091` |
| `_dormant_strategy` | `employee_validation.py:2104` |
| `ROUTING_COUNTRIES` / `ROUTING_FIELDS` | `bank_routing.py:53` / `59` |
| Routing labels | `bank_routing.py:128` and `156` |
| `pl_org_router` mount | `payroll/router.py:79` and `210` |
| `/compliance/poland` routes | `super_admin/router.py:4757` |
| `PL_*` config settings to mirror | `config.py:92`, `95`, `101`, `104` |

The other 11 `calculate_payroll`/`build_context` calls in `service.py` are country-specific (France, Germany, UK, Ireland, Sweden, Singapore, Australia) or a comment. None of them need Belgium changes.

Frontend (paths relative to frontend/src/)

| Point | Location |
|---|---|
| Poland routes to mirror | `App.jsx:246–247` |
| `COUNTRY_CODE_TO_ROUTE` | `pages/JurisdictionCompliance/index.js:35` (`PL` at 64) |
| Poland Compliance Centre tab | `modules/payroll/Compliances/CompliancePage.jsx:172`, `441` |
| Employee panel / field specs / bank fields | `modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx`, `countryFieldSpecs.js`, `bankFieldsFor.js` |
| Run detail | `modules/payroll/PayRollRuns/RunDetailPanel.jsx` |
| Payslip stub | `modules/payroll/PaySlips/PayslipStub.jsx` |
| Currency code map | `utils/currency.js:1–12` |
| Labels / tax schemas | `utils/jurisdictionLabels.js`, `utils/jurisdictionTax.js` |
| Flag | `components/jurisdiction/CountryFlag.jsx` |
| Services | `service/payrollService.js`, `service/superAdminService.js` |
| Shared helpers | `components/jurisdiction/japan/jpFormat.js`, `jpShared.jsx`; `components/jurisdiction/new_zealand/nzShared.jsx`, `nzForm.js`, `NZPackRowsTab.jsx`; `components/jurisdiction/EarningClassMatrix.jsx` |

Line numbers drift; re-verify by symbol name before each edit.
