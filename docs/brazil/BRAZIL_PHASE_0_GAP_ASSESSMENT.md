# Brazil (BR) — Phase 0 Gap Assessment

Branch `venu` at `d59508c`, plus the uncommitted Brazil draft of 2026-10-15. References use file + symbol rather than line numbers, because lines drift.
The touchpoint list follows `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md` (on `main`).

## 1. Summary

- On 2026-10-15 a Phase 1 + Phase 2 draft was written ahead of any plan. It contains 4 tables, the models, the content, the schemas, the engine and two test files. It was never committed and never run.
- Review found that the draft would fail on Postgres. It also had wrong INSS and IRRF figures, silently defaulted employer rates, and was not connected to employee data.
- Phase 0 keeps the draft but makes it unreachable: every Brazilian calculation BLOCKS.
- Phase 0 also adds the standard scaffolding (13 hooks, registry entries, readiness API) and repairs the migration.

## 2. Touchpoint matrix — backend

| # | Touchpoint | What BR needs | Phase |
|---|---|---|---|
| B1 | `core/jurisdiction.py` `REGISTRATION_COUNTRIES` | **Not added** (same rule as NL/SA/HK/MX) | 11 |
| B2 | `JURISDICTION_TAX_SCHEMAS` | `"BR"`: BRL, `cnpj` (primary, 12 alnum + 2 digits), `cnae` (7 digits) | **0 — done** |
| B3 | `COUNTRY_NAME_TO_CODE` / `CODE_TO_COUNTRY_NAME` | brazil, brasil, república/republica federativa do brasil → BR; BR → Brazil | **0 — done** |
| B4 | `engine/countries/shared.py` `MissingComplianceConfigurationError` | every BR error subclasses it (draft `BrazilCalculationError` removed) | **0 — done** |
| B5 | `jurisdiction_hooks._MODULES` | `"BR": "app.modules.payroll.brazil_service"`, all 13 keys | **0 — done** |
| B6 | `enterprise/service.py` `SUPPORTED_COUNTRY_CODES` | not added | 11 |
| B7 | `main.py` | `brazil_router` mounted before `payroll_router` | **0 — done** |
| B8 | `engine/standard.py` `_COUNTRY_CALC` | `"BR"` → `brazil.calculate`, which BLOCKS at Phase 0 (never `_calc_generic`) | **0 — done** |
| B9 | `engine/base.py` | `brazil_inputs`, `brazil_is_apprentice`, `brazil_*` rows, `brazil_organization_id`; `br_result` + flat `br_*` on the result | **0 — done** (draft fields kept) |
| B10 | `engine/resolver.py` | BR simple-mode block raises the handled error; `brazil_inputs` parameter + splat | **0 — done** |
| B11 | `engine/fallback_registry.py`, `hardcoded_defaults.py` | nothing — Brazil has no hard-coded fallback | — |
| B12 | `service.py` `_NO_TAX_SLAB_COUNTRIES` | **not** BR (INSS/IRRF are bracket tables) | — |
| B13 | `service.py` `_CANONICAL_PACK_ONLY_COUNTRIES`, `shared._VALIDATION_ENABLED_COUNTRIES` | add BR | 1 |
| B14 | `service.py` pack-gate lists (gated names, approver/self-approval/refusal-audit/transition graph, evidence + golden gates, golden dir) | add BR | 2 |
| B15 | `service.py` calc-input sites (preview, `_compute_payslip_values`, `add_payslip_item`) | call the BR `calc_inputs` hook | 6 |
| B16 | `service.py` snapshot write / response | `br_calculation_snapshot` / `brCalculationSnapshot`; flat `br_*` columns | 6 (column added in 0) |
| B17 | `service.py` `_get_currency_symbol` / `_get_currency_code` | `"BR": "R$"` / `"BRL"` | **0 — done** |
| B18 | approval fingerprint (via the `before_run_transition` hook) | `PayrollRun.br_approval_fingerprint` | 6 |
| B19 | `bank_routing.py` | draft: `pix_key`, `bank_compe`, `bank_agency`; needs `bank_account` + masking | 4 |
| B20 | `employee_validation.py` | draft `BREmployeeValidation` (CPF/PIS check digits); needs PIX type checks + sensitive PIX/account | 4 |
| B21 | `organizations/router.py` `delete_organization` | add the BR tables in dependency order | 3 |
| B22 | `retention_service` | inert settings at Phase 0; LGPD decisions | 0 / 11 |
| B23 | `assist/knowledge.py` | BR entry | 11 |

## 3. Touchpoint matrix — frontend

| # | Touchpoint | BR needs | Phase |
|---|---|---|---|
| F1 | `components/jurisdiction/CountryFlag.jsx` | Brazil flag | **0 — done** |
| F2 | `utils/currency.js` | already has BRL / pt-BR — no change | — |
| F3 | `utils/registrationRegions.js` | Brazil states and timezones already present — re-verify in Phase 3 | 3 |
| F4 | `App.jsx` + `pages/JurisdictionCompliance` / `JurisdictionStatutory` / `ReportTemplates` `index.js` maps | BR routes and pages, shipped together (the statutory map derives from the compliance map) | 2 |
| F5 | `config/jurisdictions/brazilComplianceConfig.jsx`, `components/jurisdiction/brazil/*` | Super Admin tabs | 2 |
| F6 | `service/superAdminService.js`, `TestCertificationPage`, `EngineFallbackDefaultsPage` | BR entries | 2 |
| F7 | `Compliances/CompliancePage.jsx` | `BRComplianceCentreTab`, `BRReadinessPanel` | 3 |
| F8 | `Payroll_Employees/countryFieldSpecs.js`, `bankFieldsFor.js`, `EmployeeDetailPanel.jsx` | BR fields, CPF/CNPJ checks, `BrazilStatutoryProfilePanel` | 4 |
| F9 | `PayRollRuns/RunDetailPanel.jsx`, `PaySlips/PayslipStub.jsx`, `utils/jurisdictionLabels.js` | preflight panel, payslip breakdown, labels | 6 |
| F10 | `pages/PolicyModule/index.js` | `BRPolicyPage` | 3 |

## 4. Migration

- `b7a1c9e3d5f2` was rewritten:
  - It is re-parented from `08f0f142574e` to `f4b8d2a6c9e1`. `main` had already put three migrations on `08f0f142574e`, so the draft created a second head. Back to a single head.
  - Boolean defaults now use `sa.false()`. The integer `0` default was rejected by Postgres.
  - Every model CHECK / UNIQUE constraint is now created, with the default `ix_<table>_<column>` index names.
  - `payslip_items.br_calculation_snapshot` was added (JSONB, JSON on SQLite).
  - The downgrade is guarded for partial upgrades.
- **Checked 2026-10-16** (one read-only SELECT): production `alembic_version` is `f4b8d2a6c9e1` and has no `payroll_br_*` tables. The draft migration was never applied, so editing it in place and re-parenting it was safe.

## 5. Errors and HTTP behaviour

`BrazilCalculationBlockedError` → `MissingComplianceConfigurationError` → handled in `main.py` as a 4xx. Block keys introduced at Phase 0:

- `BR_ENGINE_NOT_CERTIFIED` — engine entry point and `calc_inputs`
- `BR_SIMPLE_MODE_UNSUPPORTED`
- `BR_RUN_NOT_SUPPORTED` — approve / authorize / pay

## 6. Risks

- **Merging `main` (Mexico) into `venu`.** Expect conflicts in `base.py`, `resolver.py`, `standard.py`, `jurisdiction_hooks.py`, `jurisdiction.py`, `service.py` (currency) and `CountryFlag.jsx`. They are adjacent additions and straightforward. Mexico's `test_other_hook_modules_unchanged` asserts the exact `_MODULES` dict and must gain `"BR"`.
- The draft engine and content are **unsigned**. Nothing may be activated before Phase 1 fixes BR-K1…K3 and the tax content team signs D1/D2/D6.

## 7. Known defects in the draft (kept unreachable; tracked by tests)

| Key | Defect | Effect if it were live | Fixed in | Test |
|---|---|---|---|---|
| BR-K1 | **FIXED in Phase 1** — `MAX_INSS_CONTRIBUTION = 951.62` contradicts the 2026 brackets (sum at the ceiling = 988.09, D1) | INSS stops growing at ≈ R$8,215; under-deducts up to ≈ R$36/month | 1 | strict xfail (×4) + symptom pin |
| BR-K10 | **FIXED in Phase 1** — INSS rounded per bracket; D1 (2026-10-16) requires the exact progressive total rounded once | Off by R$0.01 on some salaries (F1: 501.52 vs 501.51; 2,902.84: 236.95 vs 236.94) | 1 | strict xfail (×3) |
| BR-K2 | **FIXED in Phase 1** (S3 decides D2) — IRRF 2026 reduction computed from the base after deductions instead of gross taxable income | Under-withholds for gross ≈ R$5,000–8,500 (R$66.57 at 5,500; R$110.59 at 7,350) | 1 | strict xfail (×2) |
| BR-K3 | Seeded rubric incidence codes unverified; likely wrong: INSS `codIncIRRF` 31 (→ 41), INSS `codIncCP` 00 (→ 31), IRRF `codIncIRRF` 00 (→ 31), alimony `codIncIRRF` 33 (→ 51); several nature codes to re-check | Wrong eSocial S-1010 declarations | 1 (needs D6) | — |
| BR-K4 | Missing RAT / FAP / third-party rate silently defaults to 2% / 1.0 / 0% | Wrong employer charges with no warning | 5 | — |
| BR-K5 | One dependants count for IRRF and salário-família; `concurrent_inss_flag` never enforced; alimony lowers the IRRF base but is not deducted from net; gross used as every base; no tax-year guard | Wrong IRRF/SF, missed BR-009 block, overpaid net | 1 / 4 / 5 | — |
| BR-K6 | PIX key not masked (often the CPF); `bank_account` missing from routing; CNPJ check digits not used by the schemas; contact CPF unchecked | LGPD exposure (G7) | 3 / 4 | noted in tests |
| BR-K7 | **FIXED in Phase 1** — Content hash covers 11 scalars, not the tables or rubrics | Hash proves nothing about the brackets | 1 | — |
| BR-K8 | **FIXED (Phases 1–2)** — Rubrics seeded per organisation, no canonical catalogue; content module outside `engine/countries/` | Inconsistent with NL/MX governance | 1 | — |
| BR-K9 | `delete_organization` does not know the BR tables (`RESTRICT` from profiles to establishments) | Org delete can fail once BR rows exist | 3 | — |

Spec errata (to confirm with the tax content team):

- The plan text gave INSS band maxima 174.1704 / 577.0192 and the ceiling contribution 951.62. The bracket arithmetic gives 174.1716 / 576.9792 and ≈ 988.09.
- The spec itself (§24, F2) only says "the 2026 contribution ceiling" and never states 951.62.
- The spec's own wording ("taxable earnings up to R$5,000") supports the gross reading in D2.
