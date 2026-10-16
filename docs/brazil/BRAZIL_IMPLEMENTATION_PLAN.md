# Zoiko Payroll — Brazil (BR) Implementation Plan

Specification: **ZP-BR-ENG-001 v1.0** (22 September 2026), Priority Market #12, ordinary private-sector CLT wedge.
Pattern: the same phase sequence as Netherlands, Saudi Arabia and Mexico (`docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md`).

Every phase ends with: import check, full pytest, `npm run check:undefined`, frontend build. **Every phase starts only on an explicit "go ahead".** Any script that touches a real database needs its own separate go-ahead.

## 1. Architecture rules Brazil follows

- **Engine is pure.** `engine/countries/brazil.py` never queries the database. Every input arrives on `PayrollContext` (`brazil_*` fields), resolved by `brazil_service.calc_inputs`.
- **Fail closed.** A missing statutory fact raises `BrazilCalculationBlockedError` (a `MissingComplianceConfigurationError`, so it is answered as a clean 4xx). Nothing ever defaults silently (BR-001).
- **Hooks, not imports.** The shared service reaches Brazil only through the 13 `jurisdiction_hooks` keys.
- **Registration stays closed.** Brazil is in `JURISDICTION_TAX_SCHEMAS` and the name maps, and stays out of `REGISTRATION_COUNTRIES` until G1–G8 are signed and the registry row leaves PLANNED.
- **Content is governed.** Rates live in Draft canonical packs, dated by tax year, hashed and sourced (S1–S20). Activation needs four-eyes approval plus evidence.
- **Government channels.** eSocial / DCTFWeb / FGTS Digital are prepared, validated and reconciled. No certified-transmitter claim is made, and DARF/GFD guides are imported, never issued.

## Status (2026-10-16)

| Phase | Status |
|---|---|
| 0 | Done (`4f7c145`), merged with `main`/Mexico (`2ded87b`) |
| 1 | Done (2026-10-16): official sources saved and verified, year-dated sourced content, defects BR-K1/K2/K7/K10 fixed, Draft seeder — see `BRAZIL_PHASE_1_IMPLEMENTATION_REPORT.md`. Open: rubric codes (BR-K3), sources S6/S7/S9–S20, G1 sign-off |
| 2 | Done and browser-checked locally. Only the FPAS data (D6) is open — see `BRAZIL_PHASE_2_IMPLEMENTATION_REPORT.md` |
| 3–11 | Not started |

## 2. Phase map

| Phase | Scope | Gates |
|---|---|---|
| 0 | Sync, repair draft, scaffolding (13 fail-closed hooks, registry entries, migration, docs) | — |
| 1 | Statutory content + canonical packs (year-dated, full hash, corrected INSS maximum, IRRF reduction basis, rubric catalogue) | G1 |
| 2 | Super Admin: pack gates, golden fixtures dir, readiness API, compliance/statutory/template pages | G1, G2 |
| 3 | Employer onboarding: employer + establishments API, CNPJ rules, FPAS/RAT/FAP evidence, org delete order | G2, G7 |
| 4 | Employee statutory profile: validation, PIX masking, dependants, concurrent-INSS declarations, alimony orders, VT | G6, G7 |
| 5 | Calculation engine: fail-closed inputs, rubric-incidence bases, payment-date vs competence, labor rules | G1, G2, G6 |
| 6 | Payroll run: real calc_inputs at every call site, snapshot + `br_*` persistence, preflight, approval fingerprint, UI | G1–G2 |
| 7 | 13th salary, vacation, termination (ledgers, TRCT, FGTS fine, D+10) | G5, G6 |
| 8 | Collective agreements (CCT/ACT), state floors, retro deltas as append-only corrections | G6 |
| 9 | eSocial S-1.3 (events table, XML builders, XSD validation, NT 07/2026 isolated) | G3 |
| 10 | DCTFWeb + FGTS Digital reconciliation | G4, G5 |
| 11 | PIX / CNAB 240, holerite + reports, LGPD retention, certification, parallel payroll, then registration | G7, G8 |

## 3. Phase 0 — done (see BRAZIL_PHASE_0_IMPLEMENTATION_REPORT.md)

## 4. Phase 1 — statutory content and canonical packs

- Move `brazil_content.py` to `engine/countries/brazil_content.py`; remove the ORM import; seeding moves to the service / seed script.
- Date every value by tax year. A pay period with no year blocks `BR_CONTENT_YEAR_UNAVAILABLE`. IRRF uses the payment date, INSS/FGTS the competence month (BR-014).
- Calculate the INSS maximum from the brackets, with an import-time check against the official 2026 Portaria (fixes BR-K1).
- IRRF reduction from gross monthly taxable income (fixes BR-K2; needs D2 sign-off).
- Content hash covers the entire rate set, rubrics included (fixes BR-K7).
- Pack rows with rule types `BR_INSS_BAND`, `BR_IRRF_TABLE`, `BR_IRRF_REDUCTION`, `BR_MIN_WAGE`, `BR_SAL_FAMILIA`, `BR_FGTS_RATE`, `BR_CPP_RATE`. Add BR to `_CANONICAL_PACK_ONLY_COUNTRIES` and `_VALIDATION_ENABLED_COUNTRIES`, **not** to `_NO_TAX_SLAB_COUNTRIES`.
- Canonical rubric catalogue, verified against the official Tabela 03 / codInc tables (fixes BR-K3; needs D6).
- `scripts/seed_brazil_canonical_packs.py`: Draft BR-PAYROLL-2026, PLANNED registry row, change-watch. Running it needs its own go-ahead.

## 5. Phase 2 — Super Admin

- Add BR to every pack-gate list in `service.py`:
  - `_GATED_PACK_COUNTRY_NAMES`
  - approver-not-activator, self-approval, refusal-audit
  - the transition graph
  - the evidence gate and the golden-PASS gate
  - `_GOLDEN_FIXTURES_DIR_BY_COUNTRY` → a real `tests/fixtures/br_golden/` folder
- `brazil_router.py` Super Admin endpoints: pack rows, rubric catalogue, FPAS table, gates, golden check.
- Frontend:
  - `BRCompliancePage`, `BRStatutoryPage`, `BRReportTemplatesPage` + the three `index.js` maps + `App.jsx` routes
  - `config/jurisdictions/brazilComplianceConfig.jsx`, `components/jurisdiction/brazil/*` tabs
  - `superAdminService.js` BR block, `TestCertificationPage`, `EngineFallbackDefaultsPage`, `jurisdictionLabels.js`
- Re-check the `JurisdictionLayout` loop regression for other countries.

## 6. Phase 3 — employer onboarding

- `brazil_org_router.py`: employer + establishments.
  - CNPJ check digits; root = first 8 characters of every establishment CNPJ; exactly one headquarters.
  - FPAS / third-party rate looked up from Tabela 04.
  - RAT/FAP with evidence and year; CPRB opt-in with eligibility.
  - Certificate as a vault reference only.
- Organisation rubric adoption (copy canonical → versioned org rows).
- Add the BR tables to `delete_organization` in dependency order (fixes BR-K9).
- Frontend: `BRComplianceCentreTab`, `BREmployerProfileTab`, `BREstablishmentsTab`, `BRReadinessPanel`, `BRPolicyPage`.

## 7. Phase 4 — employee statutory profile

- Finish `BREmployeeValidation`: PIX format by type; `bank_account` in routing; `pix_key` / `bank_account` sensitive; PIX masking everywhere (fixes BR-K6).
- Dated, non-overlapping profiles via the profile hooks.
- Separate IRRF and salário-família dependants, each with evidence.
- New tables: monthly concurrent-INSS declarations (BR-009), alimony orders, VT elections.
- Frontend: `countryFieldSpecs.js`, `bankFieldsFor.js`, `BrazilStatutoryProfilePanel`.

## 8. Phase 5 — calculation engine

- Remove silent defaults; one block key per missing input (fixes BR-K4).
- Bases from rubric incidence; an unmapped earning blocks.
- Alimony deducted from net pay; VT on contracted base salary; apprentice from category 103.
- CPRB on covered payroll only.
- `engine/jurisdictions/brazil/labor.py`: overtime, DSR, 52m30s night hour, minimum-wage floor.
- Golden fixtures F1–F6 in `br_golden/`.

## 9. Phase 6 — payroll run

- Real `calc_inputs` (active profile + establishment + employer, same-tenant check, read-only) at preview, `_compute_payslip_values` and `add_payslip_item`.
- `br_calculation_snapshot` + `br_*` columns + `brCalculationSnapshot` in responses.
- Preflight (CPF/PIS, ACTIVE employer, FAP year, floor, concurrent declared) + approval fingerprint on `PayrollRun`.
- Frontend: `BRRunPreflightPanel`, `BRPayslipBreakdown`, `brPayslipLines.js`, `PayslipStub`, `RunDetailPanel`.

## 10. Phases 7–11

- **7:** 13th-salary ledger and the advance / final / January runs. Vacation events (acquisition and concession, double pay, one-third, cash conversion, D-2). Termination matrix, notice, FGTS fine 40/20%, D+10, prior-month acceleration, TRCT.
- **8:** Collective-agreement table, state floors as pack rows, agreement premiums, data-base back pay as append-only correction runs.
- **9:** eSocial events table (encrypted XML, hashed CPF, idempotency, state machine), builders S-1000…S-1299, XSD validation, NT 07/2026 isolated, transmission behind a flag.
- **10:** DCTFWeb (0561/INSS vs totalizers vs imported DARF) and FGTS Digital (expected vs imported GFD) reconciliation.
- **11:** PIX / CNAB 240 files, holerite + reports, LGPD `retention_settings`, assist knowledge, enterprise country list, G1–G8 evidence + two parallel months. Then `REGISTRATION_COUNTRIES` and pack activation.

## 11. Decisions log

| # | Decision | Status |
|---|---|---|
| D1 | INSS rounding: once (F1 = 501.51) or per bracket (F1 = 501.52) | **Decided 2026-10-16: once.** F1 = 501.51, ceiling maximum = 988.09. The draft's per-bracket rounding is BR-K10. |
| D2 | IRRF reduction on gross taxable income | **Decided 2026-10-16: gross.** The tax-team confirmation is still required as G1 evidence before activation. |
| D3 | Rates as canonical pack rows (`BR_*` rule types) | Open — recommended: yes |
| D4 | Canonical rubric catalogue adopted per organisation | Open — recommended: yes |
| D5 | Government channels: prepare/validate/reconcile only | Open — recommended: yes |
| D6 | Official XSDs and code tables from the tax content team | **Open** — blocks Phase 1 rubrics |
| D7 | Spec `.docx` stored in `docs/brazil/`; `extracted_doc_preview.txt` never committed | Phase 0: preview kept out of git; `.docx` still to be supplied |
| D8 | Establishment CNPJ unique per employer, not platform-wide | Applied in Phase 0 |
| D9 | eSocial categories at launch: 101 and 103 only | Applied in Phase 0 (CHECK constraint) |
