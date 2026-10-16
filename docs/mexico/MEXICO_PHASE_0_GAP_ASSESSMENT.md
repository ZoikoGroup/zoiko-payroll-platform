# Mexico (MX) — Phase 0 Gap Assessment

Spec: ZP-MX-ENG-001 v1.0 (22 Sep 2026), rules MX-001…MX-064, gates G1–G8
Plan: `docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md` (written against commit 6a8f989)
Assessed at: branch `nikhil`, HEAD `dce5279` (23 commits after 6a8f989; 1 ahead / 1 behind `origin/main` 9fc1f32)
Alembic: single head `f4b8d2a6c9e1` (196 revisions)
Date: 2026-10-15
Status: **analysis only — no code changed.** Phase 0 scaffolding waits for approval (§9).

Every line number below was read from the working tree at this HEAD. Several numbers in the plan have moved; corrections are in §2.

---

## 1. Summary

- Mexico plugs into the existing architecture without new framework work. Every shared mechanism the plan relies on exists: `JurisdictionPack.jurisdiction_state`/`parent_pack_id`, `TaxSlab.rule_type`/`filing_status`/`tax_table_number`/`assessment_basis`/`formula_expression`, `ContributionRate.effective_from/to`/`source_document_id`, `StateLocalProgramReadiness`, `ReportTemplate.jurisdiction_state`, `SourceArtifact`, `TestCertificationRun`, and `jurisdiction_hooks`.
- No Mexico code, model or migration exists yet. The only existing MX pieces are:
  - `MXN` currency symbol and code in `service.py`: L32603 and L32637.
  - Frontend `currency.js`: L5, L19, L49 and L174.
  - Frontend `registrationRegions.js`: states at L202–209, timezones at L320.
- **The plan diverges from how NL was actually built in 8 places.** Two of them change Phase 0:
  - **Registration.** NL, SA and HK are deliberately **not** in `REGISTRATION_COUNTRIES`.
  - **The blocked-exception location.** See §6, D1–D8.
- **The spec does not include several statutory tables the plan expects to seed in Phase 1:**
  - the per-period ISR tariffs (daily, 7-day, 10-day and 15-day);
  - the professional minimum-wage table;
  - the CEAV rows for every year except 2026;
  - the parameters for the special-pay exemptions.

  These need an official source decision. See §8, Q3.
- I found 3 pre-existing NL defects while tracing. They are reported only and not fixed, because of master-prompt rule 8 (§7).

---

## 2. Touchpoint matrix — backend

Plan line numbers marked ✗ have moved. The current value is shown.

| # | File:line (current) | What NL / FR does there | What MX needs | Phase |
|---|---|---|---|---|
| B1 | `app/core/jurisdiction.py:27–64` `REGISTRATION_COUNTRIES` | FR is listed at L56. NL, SA and HK are **deliberately absent** ("schema only", L579–585) until G1–G8 pass and the registry row leaves PLANNED. | **Do not add Mexico** (follow NL; see D1). The plan says to add it. | 0 |
| B2 | `jurisdiction.py:72…` `JURISDICTION_TAX_SCHEMAS`: FR at L332–357, NL at L586–597 | label, currency, `fields[]` with key, pattern and primary | Add `"MX"`: label "RFC / Registro Patronal IMSS", currency MXN, fields `rfc` `^[A-ZÑ&]{3}[0-9]{6}[A-Z0-9]{3}$` (primary) and `registro_patronal` (11 chars). Comment says "schema only". | 0 |
| B3 | `jurisdiction.py:603–639` `COUNTRY_NAME_TO_CODE`, `:641–664` `CODE_TO_COUNTRY_NAME` | NL at L636–638 and L663 | Add `mexico`, `méxico`, `estados unidos mexicanos` → MX, and MX → "Mexico". **Required.** `organizations/router.py:61–74` indexes `CODE_TO_COUNTRY_NAME[code]` for every schema code, so a schema without a name is a KeyError on `/jurisdictions/tax-schemas`. | 0 |
| B4 | `jurisdiction.py:682–691` `get_jurisdiction_code` | data-driven | no change | — |
| B5 | `app/core/exceptions.py:122–143` | Germany and France blocked exceptions live here. **NL, SA and HK do not.** Their blocked errors subclass `MissingComplianceConfigurationError` (`engine/countries/shared.py:22`), which `main.py:125/149` maps to clean JSON. | See D2. Recommended: `MexicoCalculationBlockedError(MissingComplianceConfigurationError)` in `engine/countries/mexico.py`. | 0 |
| B6 | `app/modules/payroll/jurisdiction_hooks.py:26–30` `_MODULES` | HK, SA, NL. `get()` raises RuntimeError on a missing hook, so it fails closed. | Add `"MX": "app.modules.payroll.mexico_service"`. All 13 hook keys must exist (table in §2a). | 0 |
| B7 | `enterprise/service.py:30` `SUPPORTED_COUNTRY_CODES`, L37–42 labels | FR and IE are in. **NL, SA and HK are not.** | Do not add in Phase 0 (D1). | 0 → 10 |
| B8 | `organizations/router.py` | No hard-coded names. Uses the L61–74 schema list, L383–386 currency and the L427–436 reverse name lookup. | **No edit.** It is covered by B3. The plan lists this file as modified; that is wrong. | — |
| B9 | `app/main.py:176,190` | `include_router(netherlands_router, prefix="/api")` comes before `payroll_router` (L192). | `mexico_router`, mounted in the same way. **This file has uncommitted, unrelated changes in the working tree** (deployment-verification endpoint, +74 lines). See Q5. | 0 |
| B10 | `engine/standard.py:156–213` `_COUNTRY_CALC` (FR L184, NL L212); imports L70/L78; aliases L145/L153 | NL returns `tds`, pension, `employer_social_security`, `nl_employee_total` and `nl_result` (`netherlands.py:557–564`). The employee total is summed at L253–304 (NL L303). The result is mapped at L572. | `"MX": _calc_mexico`, `mx_employee_total` added to the L253–304 sum, and `mx_result` mapped. Use a **single `mx_result` dict**, as NL does. | 0 (dispatch) / 5 |
| B11 | `engine/base.py`: ctx `nl_*` at L963–983, result `nl_result` at L1594 | NL uses one result dict. FR uses flat `fr_*` (L1386–1403). | ctx `mx_*` fields after L983 and `mx_result` after L1594. Watch the naming trap: `nl_hapset*` (L667, L1200) is Canada/Newfoundland. `mx_` has no such collision. | 0 / 5 |
| B12 | `engine/resolver.py:101–111` (NL simple-mode block); kwargs L228–233, splat L407–423 | NL raises `NLError`, which has **no exception handler** (see §7). FR raises `FranceCalculationBlockedError`. | MX simple-mode block raising `MexicoCalculationBlockedError("MX_SIMPLE_MODE_UNSUPPORTED")`, plus a `mexico_inputs` kwarg and splat. | 0 |
| B13 | `engine/fallback_registry.py:392–420` (NL), L181–236 (FR, `skip_discrepancy_check: True`) | NL rows point at `attr: "NL_NO_FALLBACK"`, **which is undefined** (§7). FR has real `_FR_*` constants in `hardcoded_defaults.py:3780–3889`. | See D3. Recommended: NL no-fallback, but with a sentinel that is actually defined. | 1 |
| B14 | `hardcoded_defaults.py` | No NL constants (no-fallback by design) | No `_MX_*` constants (D3). The plan says to add them. | — |
| B15 | `service.py:1445` `_NO_TAX_SLAB_COUNTRIES = ("CH","NL")` | Lets CH and NL have an empty TaxSlab list without being treated as unconfigured. **It only matters inside `_assert_jurisdiction_ready` (L1448–1465), and only for countries in `shared.py:93` `_VALIDATION_ENABLED_COUNTRIES`.** | **MX stays out.** MX ISR tariffs live in TaxSlab rows (`MX_ISR_TARIFF`), so an empty list *is* unconfigured and must block. See §4. | — |
| B16 | `service.py:1508` `_CANONICAL_PACK_ONLY_COUNTRIES` (used at L503, L1582) | SG, HK, SA, NL | add MX | 1 |
| B17 | `engine/countries/shared.py:93` `_VALIDATION_ENABLED_COUNTRIES` | includes NL | add MX when content lands (not Phase 0, because an empty pack would block nothing new while MX calc is still stubbed) | 1 |
| B18 | `service.py:8510–8511` `_GATED_PACK_COUNTRY_NAMES` | `"NL": "Netherlands"` | `"MX": "Mexico"`. **This list is missing from the plan.** | 2 |
| B19 | `service.py:8513 / 8516 / 8520 / 8527` approver-not-activator / self-approval / refusal-audit / transition-graph | all `("SG","SE","HK","CH","SA","NL")` | add MX to all four | 2 |
| B20 | `service.py:8674` evidence gate; `:8718` golden-PASS gate | `(…,"SA","NL")` | add MX to both | 2 |
| B21 | `service.py:19274` `_GOLDEN_FIXTURES_DIR_BY_COUNTRY` (plan said ~L19268 ✗) | `"NL": "nl_golden"`. **The `tests/fixtures/nl_golden` directory does not exist.** | `"MX": "mx_golden"` plus a real directory with a README | 2 / 5 |
| B22 | calc_inputs sites: preview `19959–19961` (✗ ~19950); `_compute_payslip_values` `25077–25079` (✗ ~25033); `add_payslip_item` `31721–31723` (✗ ~31663; the plan called this "recalc", but recalc/regenerate goes through `_compute_payslip_values`) | `jurisdiction_hooks.call("NL","calc_inputs",…) if emp_country=="NL"` | Three matching MX sites | 6 |
| B23 | snapshot: `25358`, `31905`; response `32550` (✗ ~32491 is the hold view) | `nl_calculation_snapshot` | `mx_calculation_snapshot` / `mxCalculationSnapshot` | 6 |
| B24 | currency: `32603` `"MXN": "MX$"` already exists; `32626` / `32653` country→symbol/code (✗ ~32569) | `"NL": "€"`, `"NL": "EUR"` | add `"MX": "$"`/`"MX$"` and `"MX": "MXN"` | 0 |
| B25 | approval fingerprint | **Not called from service.py.** It runs via the `before_run_transition` hook (loop at L31467). `_nl_before_run_transition` (`netherlands_service.py:1211`) fingerprints and commits ledgers at APPROVED, then re-verifies at AUTHORIZED/PAID. | MX implements this inside `before_run_transition`, not as a separate `approval_fingerprint` hook (D7). | 6 |
| B26 | `bank_routing.py:49` ROUTING_COUNTRIES, `:54–97` fields, `:99` BTF label, `:121` payment-mode label, `:222` combined value | NL: iban+bic, "SEPA" | MX: `clabe`, label "CLABE", mode "SPEI"; single field, so no combined value | 4 |
| B27 | `employee_validation.py:39` base strategy; NL L1398–1442; registry `_STRATEGIES` L1445–1469 | `NLEmployeeValidation` uses the BSN elfproef, `SENSITIVE_FIELDS=('bsn',)` | `MXEmployeeValidation`: RFC/CURP/NSS/CLABE check digits, RFC↔CURP consistency, all sensitive | 4 |
| B28 | `models.py`: `EmployeeStatutoryProfile` nl_* at L1129–1147; `PayrollRun.nl_approval_fingerprint` L1467; `PayslipItem.nl_calculation_snapshot` L1901 | — | Add the `mx_*` equivalents in their phases. All plan column names are free. | 4 / 6 |
| B29 | `models.py:8841` `PayrollNlEarningClassification` | `organization_id` NULL means the canonical row. Seven independent axes, check constraints, a unique key on (org, code, effective_from), `status`, `sha256`. | `PayrollMxEarningClassification` with the same skeleton and the plan's axes. Add `sha256` and a unique constraint, which the plan omits. | 2 |
| B30 | `models.py:5433` `StateLocalProgramReadiness.program` is `STATE_PT \| LOCAL_PT \| LWF \| OTHER_STATE_PAYROLL` | — | The plan's `program=ISN` is **not an allowed value**. Either use `STATE_PT` or add `ISN` to the documented set (the column is String(30); check for constraints in Phase 2). See Q6. | 2 |
| B31 | `models.py:2783` `TaxSlab.rule_type` String(30), free string (no enum validation in schemas or service) | NL uses `NL_*` rule types | `MX_ISR_TARIFF`, `MX_CEAV_BAND`, `MX_MIN_WAGE`, `MX_VACATION_DAYS`, `MX_WORKWEEK` all fit. Period codes such as `QUINCENAL_15` fit `filing_status` String(30). | 1 |

### 2a. Hook contract (`netherlands_service.py:2185–2199`; SA has the same 13 keys, HK adds `evidence_review_refusal`)

Call sites are country-scoped: `has_module(country)` at `service.py` L3353, 8794, 8921, 10968, 20451, 27236, 27511, 32491; `retention_service.py:67`; `super_admin/router.py:953`. The two loops over `countries()` (L31467, L32250) only reach MX when the run has MX payslips. So registering MX in Phase 0 **cannot affect any other country**.

Phase 0 stub behaviour:

| Hook | Phase 0 stub (fail closed, MX-scoped) |
|---|---|
| `pack_activation_refusal` | always returns a refusal: "MX activation blocked — Phase 0 scaffolding, no certified content" |
| `template_activation_refusal` | always refuses |
| `service_registry_transition` | refuses any transition out of PLANNED |
| `calc_inputs` | raises `MexicoCalculationBlockedError("MX_NOT_IMPLEMENTED")` |
| `before_run_transition` | raises a blocked error if the run has MX payslips |
| `statutory_profile_errors` | returns `["Mexico statutory profile not yet supported"]` |
| `statutory_profile_values` | `{}` |
| `payment_treatment` | `{}` (no hold; reached only by MX items, and calc already blocks earlier) |
| `payslip_hold_view` | `None` |
| `pack_holidays` | `[]` |
| `statutory_editors` | `[]` |
| `statutory_summary` | a `{country:"MX", status:"NOT_IMPLEMENTED"}` summary rather than a raise (avoids a 500 in the super-admin summary endpoint) |
| `retention_settings` | **Superseded during implementation:** returns a valid, inert `RetentionJurisdiction` (no categories, matches MX reports only). `retention_service._report_country` calls it for every module on every report download, so raising would break all countries. See Phase 0 implementation report §6.1. |

---

## 3. Touchpoint matrix — frontend

| # | File:line (current) | NL / AU / FR today | MX needs | Phase |
|---|---|---|---|---|
| F1 | `src/App.jsx`: static named imports from each `index.js` (no lazy). Compliance AU L183–184, NL L202 (**no `/:jurisdiction`**); statutory NL L257–258; templates NL L296–297 | — | 6 routes, all with `/:jurisdiction` (needed for state ISN) | 2 |
| F2 | `pages/JurisdictionCompliance/index.js:24` exports, `:29–53` `COUNTRY_CODE_TO_ROUTE` (also consumed by `pages/CompliancePage.jsx`) | NL L52 | `MX: "mexico"` | 2 |
| F3 | `pages/JurisdictionStatutory/index.js:33–37`, derived from the compliance map minus `["FR","CH"]` | IT and SA leak through without pages (pre-existing) | MX appears automatically once F2 is added, so the statutory page must ship in the same phase | 2 |
| F4 | `pages/ReportTemplates/index.js:43–64` (separate map) | NL L63 | `MX: "mexico"` | 2 |
| F5 | `config/jurisdictions/netherlandsComplianceConfig.jsx`: `netherlandsExtraTabs(orgId)` chained by `after`; `JurisdictionLayout.jsx:240` extra tabs need a selected pack; L246–255 handles `hiddenTabs` | NL keeps Rates and Slabs visible | `mexicoExtraTabs(orgId)` with the plan's 13 tabs | 2 |
| F6 | `pages/JurisdictionCompliance/NLCompliancePage.jsx` (org select, no `useParams`) vs `AUCompliancePage.jsx` (`useParams` + `onStateChange`) | — | MX needs **both**: org select + state routing | 2 |
| F7 | `components/jurisdiction/australia/state/`: `AUStateAccordionWorkspace` (hard-codes `"AU"` at L30 and L97), `AUStateAccordionRow` (links to `/compliance/australia` at L162), `AUStatePayrollTaxTab`, `auStateCodes.js` | — | **Clone** into `components/jurisdiction/mexico/state/` rather than generalising the AU code (rule 8: zero AU behaviour change) | 2 |
| F8 | `components/jurisdiction/TaxabilityMatrixTab.jsx:21–35`: only CA/US programs; anything else falls back to **Canada** (AU is affected today) | — | **Do not mount it for MX.** MX-005 multi-axis classification is served by `MXEarningClassificationTab` (D8). | 2 |
| F9 | `SourceEvidencePanel` (no props, not country-filtered); `TestCertificationPanel({jurisdiction,label,fixturesPath})` | AU passes props | Reuse both | 2 |
| F10 | `utils/currency.js` L5, L19, L49, L174 | — | **Already present. No change.** The plan lists it as modified. | — |
| F11 | `utils/registrationRegions.js`: MX states L202–209, timezones L320 already present; `REGISTRATION_COUNTRIES` L3–36 (no NL) | — | **No change in Phase 0.** Verify the 32-entity naming and the 8 timezones in Phase 3. Do not add MX to `REGISTRATION_COUNTRIES` (D1). | 3 |
| F12 | `components/jurisdiction/CountryFlag.jsx:264–279` (SVG 24×16, `FLAGS` map) | NL L278 | Add a `Mexico` flag SVG | 0 |
| F13 | `service/errorClassification.js` | **has no country blocked codes at all** | **Drop it from Phase 0** (the plan lists it). Blocked errors render through the generic error path. | — |
| F14 | `service/superAdminService.js:126–197` NL block (`NL_SA` const) | — | An MX block | 2 |
| F15 | `pages/TestCertificationPage.jsx:12–32` (NL L31); `pages/EngineFallbackDefaultsPage.jsx:16–38` (flat list) | — | MX entries | 2 |
| F16 | Org-side employee: `countryFieldSpecs.js` `COUNTRIES` L8–52 and `COUNTRY_FIELD_SPECS` (no NL; FR at L174); `bankFieldsFor.js` L24/27/49/74; `EmployeeDetailPanel.jsx` mounts per-country panels by `employee.countryCode` (UK L206, HK L272/324, DE L352/373) | **NL has no org-side presence** | Follow **HK/SG/FR**, not NL: an MX block in field specs plus bank (CLABE), and the SBC card and INFONAVIT panel mounted in `EmployeeDetailPanel` | 4 |
| F17 | Org-side run: `PayRollRuns/RunDetailPanel.jsx:464–466` mounts `SGRunPreflightPanel` / HK panels when `items.some(country==="SG")`; `RunDetailPage.jsx:169` `getContributionColumns` (map at `payrollService.js:1399`, no NL) | NL mounts nothing | MX preflight, trace and status badges mounted at L464–466 in the same way, plus an MX contribution-column set | 6 |
| F18 | Payslip: `PaySlips/PayslipStub.jsx` (CH snapshot L86), `utils/jurisdictionLabels.js:105` | — | Render `mxCalculationSnapshot` and add MX labels | 6 |
| F19 | `pages/PolicyModule/index.js:16–28` (no NL) | FR is a thin `PolicyLayout` wrapper | `MXPolicyPage` | 3 |

---

## 4. `_NO_TAX_SLAB_COUNTRIES` vs `_CANONICAL_PACK_ONLY_COUNTRIES` — answer

- **`_NO_TAX_SLAB_COUNTRIES` (L1445)**
  - It only means: an empty TaxSlab list is not "unconfigured", because this country's income tax comes from somewhere else. CH uses QST tariff files and NL uses imported Belastingdienst table files (NL-005).
  - It is read in exactly one place, `_assert_jurisdiction_ready` L1463, and only for countries in `_VALIDATION_ENABLED_COUNTRIES`.
  - It does **not** exclude rows from any calculation path.
- **Where MX ISR lives.** MX ISR is a published 11-bracket fixed-quota + marginal-rate tariff per payment period (Art. 96 / Annex 8). It maps cleanly to TaxSlab rows (`rule_type=MX_ISR_TARIFF`, `filing_status`=period code, `min/max_amount`, `flat_amount`=fixed quota, `rate_pct`=marginal).
  - **So MX must NOT be in `_NO_TAX_SLAB_COUNTRIES`.** An MX pack with no tariff rows must fail readiness.
- **Is there a risk of generic slab misuse?**
  - The generic `_calculate_annual_tax` (`shared.py` ~L1188) treats every non-FORMULA slab as a marginal bracket. It runs only through `_calc_generic`.
  - MX will be in `_COUNTRY_CALC` from Phase 0, so MX slabs never reach `_calc_generic`.
  - The MX calculator filters by `rule_type` prefix `MX_`, as NL does with `NL_`.
  - No exclusion list is needed.
- **`_CANONICAL_PACK_ONLY_COUNTRIES` (L1508):** add MX in Phase 1. It refuses org-level extracted-rate application (L503) and forces canonical pack resolution (L1582), which is what MX-003 requires.
- **Known side-effect:** `check_jurisdiction_readiness` (L1468–1503) ignores `_NO_TAX_SLAB_COUNTRIES`. That makes no difference to MX, which has slabs.

---

## 5. Plan confirmation — files, tables, columns

**Confirmed as written:** every Phase 1–10 table name (`payroll_mx_*`), every `mx_*` column on `EmployeeStatutoryProfile`, `PayslipItem`, `PayrollRun`, the shared tables reused for data placement (plan §4 table), the seed clone approach, and the router prefix `/super-admin/compliance/mexico` (NL: `netherlands_router.py:35`). No name collides with an existing table or column.

**Corrections:**

| Plan item | Correction |
|---|---|
| Phase 0: add Mexico to `REGISTRATION_COUNTRIES` ("safe") | Not added. NL precedent (L579–585) and the spec's §22 approval boundary both say otherwise (D1). |
| Phase 0: `enterprise/service.py` `SUPPORTED_COUNTRY_CODES` | Not added (NL is not there) (D1). |
| Phase 0: `organizations/router.py` | No edit needed (B8). |
| Phase 0: `core/exceptions.py` `MexicoCalculationBlockedException` | See D2 / Q2. |
| Phase 0: `utils/currency.js`, `registrationRegions.js`, `errorClassification.js` | No change. MXN and the MX regions already exist; there is no blocked-code registry. |
| Phase 1: `fallback_registry.py` with `skip_discrepancy_check` "like FR" + `_MX_*` in `hardcoded_defaults.py` | Conflicts with master rules 2 and 3. NL no-fallback pattern recommended (D3). |
| Phase 1: `seed_jurisdiction_service_registry.py` MX row | NL creates its registry row inside its own canonical seed (`seed_netherlands_canonical_packs.py:65–77`, PLANNED, NOT_OFFERED). Do the same (D4). |
| Phase 1: `seed_statutory_filings.py` "MX filing calendar rows" | That script seeds **per-org filing instances**. The **calendar** is seeded through `service.upsert_filing_calendar_entry(FilingCalendarUpsert(...))` inside `seed_statutory_report_templates.py` (IN L211–225, HK L2064–2078) (D4). |
| Phase 1 seed guard | The NL seed does **not** use `assert_local_database`. It uses the stricter `_require_confirmed_target` (L250–278): the override env var, a TTY and a typed `CONFIRM`. Clone that. |
| Phase 2: four-eyes lists | Also add `_GATED_PACK_COUNTRY_NAMES` (L8510) (B18). |
| Phase 2: `StateLocalProgramReadiness program=ISN` | `ISN` is not in the documented program set (B30, Q6). |
| Phase 2: earning classifications table | Add `sha256` plus `UniqueConstraint(org, earning_code, effective_from)` to match NL (B29). |
| Phase 2: reuse `TaxabilityMatrixTab` | Do not; it only knows CA and US (F8). |
| Phase 2: AU accordion "clone" | Confirmed as a clone, not a generalisation (F7). |
| Phase 6: `approval_fingerprint` hook | Implement inside `before_run_transition` (B25). |
| Phase 6: "recalc ~L31663" | That site is `add_payslip_item`. Regenerate goes through `_compute_payslip_values` (B22). |
| Phase 4/6: org-side mounts | NL has none to copy. Use the SG/HK mount points (F16, F17). |
| All migrations ("idempotent") | See D5. NL's 9 migrations were **not** idempotent and needed repair migration `08f0f142574e`. |

---

## 6. Deviations I recommend (need your approval)

- **D1 — Registration exposure.**
  - **What:** do not add Mexico to `REGISTRATION_COUNTRIES` (backend and frontend) or to enterprise `SUPPORTED_COUNTRY_CODES` until G1–G8.
  - **Why:**
    - This is the NL, SA and HK pattern (`jurisdiction.py:579–585`).
    - The spec §22 says approval "does not authorize nationwide live payroll".
    - Super Admin still works for MX through the tax schema and the dedicated router.
- **D2 — Blocked error.**
  - **What:**
    - Use `MexicoCalculationBlockedError(MissingComplianceConfigurationError)` in `engine/countries/mexico.py`, carrying `key` (the coded reason, e.g. `MX_STATE_UNSUPPORTED`), `reason` and `organization_id`.
    - The simple-mode block in `resolver.py` raises it, so it gets `main.py`'s existing JSON handler. Do not copy NL's unhandled `NLError`.
  - **Master prompt:** rule 3 names `MexicoCalculationBlockedException`. Q2 asks whether you want that exact class in `core/exceptions.py` (France style) instead, or as an alias.
- **D3 — No fallbacks.**
  - **What:**
    - No `_MX_*` constants in `hardcoded_defaults.py`.
    - Fallback-registry rows use a sentinel `MX_NO_FALLBACK = None` that is actually defined in `engine/countries/mexico.py`, so NL's undefined-attribute bug is not repeated.
    - No `skip_discrepancy_check`.
  - **Why:** master rules 2 and 3 (no hard-coded law, never silently default).
- **D4 — Seeding.**
  - The registry row is created in `seed_mexico_canonical_packs.py`.
  - The MX report templates and the filing calendar go in `seed_statutory_report_templates.py`, using the AU per-state pattern for ISN (`template_key=f"MX-ISN-RETURN-{state}"`, `state=`).
  - `seed_statutory_filings.py` is untouched.
- **D5 — Migrations.**
  - Every MX migration uses inspector guards from day one: `_has_table`/`_has_column`/`_has_index`, as in `74aeb450aeee_*.py:49–58`.
  - Each is added to `tests/test_migration_idempotency.py` `_GUARDED`.
  - `tests/test_mexico_migrations.py` mirrors `test_netherlands_migrations.py`: linear chain, FK targets exist, and model ↔ migration parity for `payroll_mx_*`.
  - Each MX migration also updates `tests/test_alembic_metadata.py`: the head string at two places (L183, L195) and the revision count at L229 (now 196).
  - Filenames are autogen-slug + rev id; the `mx_*_mN` names go in the docstring title, matching NL.
  - First down_revision: `f4b8d2a6c9e1`.
- **D6 — MX ISR in TaxSlab.** MX is not in `_NO_TAX_SLAB_COUNTRIES`; it is in `_CANONICAL_PACK_ONLY_COUNTRIES` (Phase 1) and `_VALIDATION_ENABLED_COUNTRIES` (Phase 1) (§4).
- **D7 — Approval fingerprint** via the `before_run_transition` hook (B25).
- **D8 — Frontend reuse.** Clone the AU accordion. Do not mount `TaxabilityMatrixTab` for MX.

---

## 7. Pre-existing defects found while tracing (NOT fixed — rule 8)

1. **`NLError` has no exception handler.** `resolver.py:101–111` raises `NLError("NL_SIMPLE_MODE_UNSUPPORTED")`, and `main.py` and `core/exceptions.py` register nothing for it. A Dutch simple-mode call most likely returns a 500 instead of a coded 4xx. *(This was inferred from the absence of a handler; I have not reproduced it.)*
2. **`NL_NO_FALLBACK` is undefined.** All NL rows in `fallback_registry.py:400–419` reference it, and `getattr(…, None)` silently yields null. The page shows null, which happens to be correct, but the registry no longer catches a renamed attribute.
3. **Other notes:**
   - `TaxabilityMatrixTab` falls back to Canada's programs for every country except CA and US, including AU today.
   - `JurisdictionStatutory/index.js` maps IT and SA routes even though they have no statutory page.
   - `tests/fixtures/nl_golden/` is mapped at `service.py:19274` but does not exist.

---

## 8. Questions for you

- **Q1 — D1 registration.**
  - **Recommendation:** keep Mexico out of `REGISTRATION_COUNTRIES` and enterprise `SUPPORTED_COUNTRY_CODES` until G1–G8, as with NL. The plan says to add it.
  - **Decision needed:** confirm or overrule.
- **Q2 — Exception class.**
  - **Recommendation:** `MexicoCalculationBlockedError` in the engine, subclassing `MissingComplianceConfigurationError` (D2).
  - **Decision needed:** confirm that, or ask for the France-style `MexicoCalculationBlockedException` in `core/exceptions.py`.
- **Q3 — Statutory content missing from the spec (needed by Phase 1).** The spec provides the monthly ISR tariff, the UMA values, the general and ZLFN minimum wages, the 2026 CEAV bands, the IMSS rates, the subsidy and the CDMX 4%. It does **not** provide:
  - (a) the RMF 2026 Annex 8 tariffs for daily, 7-day, 10-day and 15-day periods (MX-008 forbids scaling the monthly table);
  - (b) the CONASAMI professional minimum-wage table (S9);
  - (c) CEAV employer rows for 2023–2025 and 2027–2030 (MX-029);
  - (d) the ISR exemption parameters for aguinaldo, vacation premium, PTU, overtime and Sunday premium (MX-009);
  - (e) the ZLFN municipality list;
  - (f) the subsidy decree's exclusions.

  Should I transcribe these from the official sources (S1/S2/S8/S9/S11, DOF) into `mexico_content.py`, each marked `needs_g1=True` with a source code, or will you supply the official documents?
- **Q4 — CEAV lowest band (MX-027/028).**
  - **The ambiguity:** "1.00 minimum wage" — the decree band is anchored to the minimum wage, but a ZLFN worker's minimum (440.87) differs from the general one (315.04).
  - **Decision needed:** should the band boundary use the worker's own zone minimum, or the general minimum? I will not guess this.
- **Q5 — Git workflow.** The master prompt says "commit per phase on `feature/mexico-phase-<N>`". My standing instruction from earlier work on this repo is **stage only; you commit**. The working tree also has unrelated uncommitted changes:
  - `backend/app/main.py` (a deployment-verification endpoint), which Phase 0 must also edit;
  - `.env.example`, `vite.config.js` and Singapore docs.

  Which do you want?
  - (a) Branch `feature/mexico-phase-0` from the current HEAD and commit only MX files, leaving the main.py hunk unstaged with `git add -p`.
  - (b) Stage only, and you commit.

  Also, should the branch be based on `nikhil` (dce5279) or `origin/main` (9fc1f32)? They differ by one commit each way.
- **Q6 — State ISN readiness program code.** Use the existing `STATE_PT` value for Mexico ISN, or add `ISN` as a new program value (a documentation/validation change to a shared column)?
- **Q7 — First ISN states beyond CDMX** (plan §14, needed by Phase 2). The spec only certifies CDMX as an example. Every other state is hard-blocked (MX-045) until a pack is signed.
- **Q8 — Spec path.** The master prompt cites `Juris_doc/…_v1_0.docx`. The file is actually at `../juris_docs/Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx`, outside the repo; I confirmed with `cmp` that it is byte-identical to the copy in the parent folder. Should I copy it into the repo (e.g. `docs/mexico/`) for traceability, or correct the path in the master prompt?

---

## 9. MX-001…MX-064 → phase mapping

| Rule | Topic | Phase(s) |
|---|---|---|
| MX-001 | Eligibility / regime / state / zone resolution; unsupported = BLOCKED | 0 (blocked stubs), 4 (inputs), 5 (preflight) |
| MX-002 | Multi-RFC / registration / state scope | 3 |
| MX-003 | Signed effective-dated content | 1, 2 |
| MX-004 | Feb-1 UMA and 2027 workweek regression; no server-date law | 1, 5 |
| MX-005 | Independent multi-axis earning mappings | 2 (table/editor), 5 |
| MX-006 | Classification versioning; history retains original | 2, 5, 7 |
| MX-007 | Calculation trace per concept | 5 |
| MX-008 | ISR by actual period, Annex 8, no generic divisor | 1, 5 |
| MX-009 | Special-pay withholding methods | 5, 9 |
| MX-010 | Annual ISR adjustment separate | 9 |
| MX-011 | ISR remittance lifecycle (17th) | 8 |
| MX-012 | Subsidy as formula content | 1, 5 |
| MX-013 | Jan/Feb subsidy golden vectors | 5 |
| MX-014 | CFDI subsidy reconciles to applied | 7 |
| MX-015 | CFDI schema/catalog/PAC pinning | 2 (tables), 7 |
| MX-016 | Stamp only committed results | 7 |
| MX-017 | Stamp ≠ payment | 7, 10 |
| MX-018 | Cancellation/substitution lineage | 7 |
| MX-019 | SBC component exposure / factor | 4, 5 |
| MX-020 | Bimonthly variable accumulators + movements | 4, 6, 8 |
| MX-021 | 25-UMA ceiling Jan/Feb | 1, 5 |
| MX-022 | Concept-specific SBC exclusions | 2, 5 |
| MX-023 | Independent IMSS branches | 5, 6 |
| MX-024 | Risk premium per registration/period | 3 |
| MX-025 | IMSS movements, 5 business days | 8 |
| MX-026 | Annual risk-premium workflow | 8 |
| MX-027 | CEAV mixed minimum-wage/UMA thresholds | 1, 5 |
| MX-028 | CEAV Jan/Feb boundary tests | 1, 5 |
| MX-029 | CEAV 2023–2030 rows; only current year active | 1, 2 |
| MX-030 | SUA as reconciliation reference | 8 |
| MX-031 | INFONAVIT credit only from notice | 4, 5 |
| MX-032 | Credit vs 5% contribution distinct | 5, 10 |
| MX-033 | SUA/INFONAVIT reconciliation before SETTLED | 8 |
| MX-034 | Employer LIVE readiness gate | 3, 10 |
| MX-035 | Secrets as refs/fingerprints only | 3, 7 |
| MX-036 | Identifier mismatch = preflight exception | 4, 6 |
| MX-037 | SBC vs compensation displayed separately | 4 |
| MX-038 | Work state statutory, not HQ | 4, 5 |
| MX-039 | Preview non-mutating; ledgers only on COMMIT | 6 |
| MX-040 | Approval invalidated by content/input change | 6 |
| MX-041 | Separate payroll / CFDI / authority / bank statuses | 6 |
| MX-042 | Branch reconciliation to SUA pre-launch | 8, 10 |
| MX-043 | UNKNOWN ≠ failed for IDSE/SIPARE | 8 |
| MX-044 | Preserve risk-premium history/evidence | 8 |
| MX-045 | Unsupported states blocked | 2, 5 |
| MX-046 | ISN reconciles employee → return → ledger | 6, 8 |
| MX-047 | State content separate cadence | 2 |
| MX-048 | 48 h in 2026, staged reductions | 1, 5 |
| MX-049 | OT from approved time data | 5 |
| MX-050 | No salary reduction across 2026→2027 | 5 |
| MX-051 | Statutory vs employer accruals; floor | 3, 4, 5 |
| MX-052 | Entitlement ≠ tax/SBC base | 5 |
| MX-053 | Seniority to exact anniversary | 4, 5, 9 |
| MX-054 | PTU from employer-provided profit | 9 |
| MX-055 | PTU audit trail | 9 |
| MX-056 | PTU payment own ISR/CFDI | 9 |
| MX-057 | Termination reason as approved legal input | 9 |
| MX-058 | Finiquito decomposition | 9 |
| MX-059 | Termination lifecycles separate | 9 |
| MX-060 | Fiscal / social-security / bank separation | 6, 10 |
| MX-061 | No full identifiers/XML/keys in logs | 4, 10 |
| MX-062 | UNKNOWN after timeout/restore; no blind replay | 7, 8, 10 |
| MX-063 | Golden vector contents | 5, 10 |
| MX-064 | No promotion with unexplained differences | 10 |

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Phase 1 content transcription errors (ISR period tables, CEAV) | Every row is `needs_g1`, Draft-only, with a source code and boundary/continuity tests. Activation still requires four-eyes plus golden PASS (B19/B20). |
| An MX migration breaks the single-head and revision-count tests | Update `test_alembic_metadata.py` in the same change (D5). |
| A shared-file edit changes another country's behaviour | Every MX edit is either an additive dict/tuple entry or MX-gated. The full `pytest tests/` suite (SQLite in-memory, per `conftest.py:196–248`) plus `npm run build` and lint run before each phase is declared done. |
| Collision with uncommitted main.py work | Q5. |
| The CFDI / PAC / IDSE / SPEI externals are undecided | They are Phase 7/8/10 decisions (plan §14) and do not block Phases 0–6. |

---

## 11. Phase 0 scaffolding change list (awaiting "go ahead")

**Backend — modify**
- `app/core/jurisdiction.py`:
  - `JURISDICTION_TAX_SCHEMAS["MX"]` (schema only, with a comment);
  - name→code entries `mexico`, `méxico`, `estados unidos mexicanos`;
  - code→name `MX: "Mexico"`.
  - **Not** `REGISTRATION_COUNTRIES` (pending Q1).
- `app/modules/payroll/jurisdiction_hooks.py`: `_MODULES["MX"]`.
- `app/modules/payroll/engine/standard.py`: import, `_calc_mexico`, `_COUNTRY_CALC["MX"]`, `mx_employee_total` in the employee-total sum, and `mx_result` mapping.
- `app/modules/payroll/engine/base.py`:
  - ctx `mexico_*`/`mx_*` placeholders (`mx_payroll_date`, `mx_payment_period`, `mx_profile`, `mx_employer`, `mx_registration`, `mx_risk_premium`, `mx_sbc`, `mx_infonavit_notices`, `mx_isn_state_pack`, `mx_classifications`, `mx_labor_policy`, `mx_ytd`, `mx_employee_id`, `mx_organization_id`), all default None;
  - result `mx_result: dict = None`.
- `app/modules/payroll/engine/resolver.py`: MX simple-mode block, plus the `mexico_inputs` kwarg and splat.
- `app/modules/payroll/service.py`: `"MX"` in the country→currency-symbol and country→ISO-code maps (L32626/L32653). Nothing else in Phase 0.
- `app/main.py`: import and `include_router(mexico_router, prefix="/api")` (pending Q5 on the dirty file).
- `app/core/exceptions.py`: only if Q2 asks for the France-style class.

**Backend — create (skeleton, fail closed)**
- `app/modules/payroll/mexico_service.py`: the 13-hook `JURISDICTION_HOOKS` with the §2a stub semantics.
- `app/modules/payroll/mexico_schemas.py`: `MXReadinessResponse`.
- `app/modules/payroll/mexico_router.py`: prefix `/super-admin/compliance/mexico`, super-admin auth like NL, with `GET /readiness` returning every gate G1–G8 as `NOT_STARTED`.
- `app/modules/payroll/engine/countries/mexico.py`:
  - `ENGINE_VERSION = "MX-ENGINE-2026.0"`;
  - `MexicoCalculationBlockedError`;
  - `MX_NO_FALLBACK = None`;
  - `calculate(ctx)` returns `{}` for a non-MX ctx and otherwise raises `MX_ENGINE_NOT_IMPLEMENTED`.
- `app/modules/payroll/engine/countries/mexico_content.py`: `PACK_STATUS="Draft"`, pack-id tuples `MX_2026`, `SOURCE_REFERENCES` S1–S23 (verbatim from spec §22), `SOURCE_CODES`, an empty `MX_PARAMETER_KEYS`, and rule-type constants.
- `app/modules/payroll/engine/jurisdictions/mexico/__init__.py`.

**Frontend — modify**
- `src/components/jurisdiction/CountryFlag.jsx`: a Mexico SVG and `FLAGS.MX`.

**Tests — create**
- `backend/tests/test_mexico_scaffolding.py`. It imports `app.*` lazily inside the tests (collection-order hazard). It asserts:
  - the MX schema, its name maps and the `/jurisdictions/tax-schemas` KeyError guard;
  - MX is **not** in `REGISTRATION_COUNTRIES`;
  - `jurisdiction_hooks` has MX with all 13 hooks callable;
  - activation, template and registry-transition refusals;
  - `calc_inputs`, `before_run_transition` and the engine raise `MexicoCalculationBlockedError`;
  - simple mode is blocked;
  - `standard` dispatches MX to the MX calculator, not `_calc_generic`;
  - S1–S23 are present;
  - the router is mounted and requires super admin;
  - no other country's `_COUNTRY_CALC`, hook map or currency entry changed.

**Verification before reporting Phase 0 done:**
- full `pytest tests/` (not a subset);
- `npm run build` plus `npm run lint`;
- `docs/mexico/MEXICO_PHASE_0_IMPLEMENTATION_REPORT.md`.

**No migrations in Phase 0.**

---

## 12. Phase 0 decisions (user, 2026-10-15)

| # | Question | Decision |
|---|---|---|
| 1 | Registration | MX stays out of `REGISTRATION_COUNTRIES` and enterprise `SUPPORTED_COUNTRY_CODES` until G1–G8 (NL/SA/HK pattern). The plan has been updated. |
| 2 | Exception | NL style: `MexicoCalculationBlockedError(MissingComplianceConfigurationError)` in `engine/countries/mexico.py`. No change to `core/exceptions.py`. |
| 3 | Missing statutory tables | Transcribed from official sources in Phase 1. The source PDFs are saved first to `docs/mexico/sources/`. If sat.gob.mx or dof.gob.mx is unreachable, the user downloads them. Every row is flagged [PENDING G1] and linked to a SourceArtifact (URL + SHA-256), with bracket-continuity tests. No invented values. If a source is unclear, stop and ask. |
| 4 | CEAV lowest band | The minimum-wage reference for the 1.00 band is a content parameter marked [PENDING G2]. Until SUA reconciliation confirms it, BLOCK only ZLFN employees whose SBC falls in that band; everyone else is calculated normally. |
| 5 | Git | Stage only; the user commits. **Superseded during Phase 0:** the user then asked for no worktree and no feature branch, so all work happens on `nikhil` in the main checkout. Only my own files and hunks are staged. |
| 6 | ISN readiness program | `program = OTHER_STATE_PAYROLL`, with a code comment saying it is Mexico ISN. No new enum value. |
| 7 | First ISN states | CDMX only. The user will confirm more before Phase 2. |
| 8 | Spec location | Copied to `docs/mexico/Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx`. The paths in the master prompt and the plan are fixed. |
| 9 | NL defects (§7) | Not touched on this branch. Listed in `docs/mexico/OUT_OF_SCOPE_DEFECTS.md` for ticketing. |
