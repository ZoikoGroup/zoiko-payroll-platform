# Zoiko Payroll — Mexico (MX) Implementation Plan

Spec: ZP-MX-ENG-001 v1.0 (Mexico Engineering Wireframe & Implementation Specification, 22 Sep 2026)
Repo: ZoikoGroup/zoiko-payroll-platform (analysed at commit 6a8f989)
Template jurisdiction: **Netherlands (NL)** — the most complete build (own router/service/schemas, engine subpackage, Super Admin tabs, Statutory + Report Templates pages, jurisdiction hooks, four-eyes opt-in).
State-overlay template: **Australia state payroll tax accordion** (each state = its own JurisdictionPack) → Mexico state ISN.

Line numbers below are from commit 6a8f989; current ones are in `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md`, which wins on any conflict.

**Revision v1.1 (after Phase 0 and the Phase 1 review).** Changes are marked *[v1.1]*. Five points that the Phase 0 gap assessment had already established are restored and marked *[v1.1 carry-over from Phase 0]*. Status: Phase 0 committed (c09f7e8); Phase 1 approved, value-free tooling built, transcription blocked on source downloads.

**Production rule (2026-10-16).** Merging to main deploys to production and runs Alembic migrations. Every phase PR must keep Mexico dormant and fail-closed, and every migration must be additive and guarded. Phases 0–3 are in production (PR #97–#101; migrations `5d2c8f1a7b3e` and `6e4a1d9c3f27`) — see `PRODUCTION_STATE.md`. Each phase plan must include a section on what its migration and routes do in production when merged.

---

## 1. Architecture findings (what Mexico must plug into)

| Concern | Existing mechanism | Mexico usage |
|---|---|---|
| Country registry | `backend/app/core/jurisdiction.py` (`REGISTRATION_COUNTRIES`, `JURISDICTION_TAX_SCHEMAS`, name↔code maps) | `MX` tax schema + name/code maps. *[v1.1]* NOT added to `REGISTRATION_COUNTRIES` or enterprise `SUPPORTED_COUNTRY_CODES` until G1–G8 pass (same as NL/SA/HK) |
| Calculator dispatch | `engine/standard.py` `_COUNTRY_CALC` | `"MX": _calc_mexico` |
| Calc context/result | `engine/base.py` (`france_*`, `nl_*` ctx fields; `*_result` on result) | `mexico_inputs` → `mx_*` ctx fields, `mx_result` |
| Blocking | NL-style `NetherlandsCalculationBlockedError(MissingComplianceConfigurationError)` in the engine | *[v1.1]* `MexicoCalculationBlockedError(MissingComplianceConfigurationError)` in `engine/countries/mexico.py`; blocks every mode. `core/exceptions.py` unchanged |
| Statutory content | `JurisdictionPack` + `ContributionRate` + `TaxSlab` (`rule_type`/`filing_status` discriminators, row-level `effective_from/to`, `source_document_id`) | National pack `MX-PAYROLL-2026`; ISR tariffs, CEAV bands, min wages as TaxSlab rule types; UMA Jan/Feb as dated ContributionRate rows |
| Sub-national packs | `JurisdictionPack.jurisdiction_state` + `parent_pack_id`; `StateLocalProgramReadiness` | One ISN pack per state (`MX-ISN-CDMX-2026`), support status per state |
| Earning taxability | `TaxabilityRule` (single axis); NL built `payroll_nl_earning_classifications` | Mexico needs multi-axis (MX-005) → `payroll_mx_earning_classifications` |
| Pack lifecycle / activation | Draft → In Review → QA → Approved → Active → Deprecated → Retired; `PackHotfixActivation`; `TaxConfigurationAudit`; four-eyes opt-in lists in `service.py` (~L8511–8530); golden PASS required (~L8674/8718) | Add MX to all opt-in lists (same as NL/SA) |
| Report templates | `ReportTemplate` (+Component, +ComponentField), lifecycle Draft → Review → Approved → Published → Active → Superseded; `scripts/seed_statutory_report_templates.py` | MX templates seeded Draft |
| Filing calendar | `StatutoryFilingCalendar`, seeded via `service.upsert_filing_calendar_entry` in `scripts/seed_statutory_report_templates.py` *[v1.1 carry-over from Phase 0]* (`seed_statutory_filings.py` seeds per-organisation filing instances, not the calendar) | ISR 17th, IMSS/INFONAVIT, ISN, aguinaldo, PTU, risk premium |
| Evidence | `SourceArtifact` | S1–S30 (S24–S30 pending spec-owner approval) |
| Golden tests | `TestCertificationRun`, `tests/fixtures/<cc>_golden`, `_GOLDEN_FIXTURES_DIR_BY_COUNTRY` (service.py ~L19268) | `mx_golden` |
| Jurisdiction hooks | `jurisdiction_hooks.py` `_MODULES` (HK, SA, NL) | `"MX": "app.modules.payroll.mexico_service"` |
| Employee statutory data | `EmployeeStatutoryProfile` with prefixed columns (`hk_*`, `sa_*`, `nl_*`), identity tokens not raw IDs | `mx_*` columns |
| Payslip snapshot | `PayslipItem.<cc>_calculation_snapshot` | `mx_calculation_snapshot` |
| Run approval binding | `PayrollRun.sa_approval_fingerprint`, `nl_approval_fingerprint` (computed inside the `before_run_transition` hook) | `mx_approval_fingerprint` (MX-040), computed in the MX `before_run_transition` hook *[v1.1 carry-over from Phase 0]* |
| Bank rails | `bank_routing.py` `ROUTING_COUNTRIES`, field/scheme maps | MX, CLABE, SPEI |
| Seeds safety | `scripts/_local_db_guard.py`, Draft-only, refuse non-Draft rewrite | Same for MX seed |
| Frontend Super Admin | `pages/JurisdictionCompliance/<CC>CompliancePage.jsx` + `config/jurisdictions/<country>ComplianceConfig.jsx` (extra tabs on shared JurisdictionLayout) + `pages/JurisdictionStatutory` + `pages/ReportTemplates`, routes in `App.jsx`, `COUNTRY_CODE_TO_ROUTE` | Same set + `/:jurisdiction` sub-routes for states |
| Shared FE panels | `components/jurisdiction/TaxabilityMatrixTab`, `SourceEvidencePanel`, `TestCertificationPanel` | Reuse `SourceEvidencePanel` + `TestCertificationPanel`. Not `TaxabilityMatrixTab` (CA/US programs only); MX-005 is served by `MXEarningClassificationTab` *[v1.1 carry-over from Phase 0]* |

---

## 2. Phase map

| Phase | Name | Spec coverage | Gate |
|---|---|---|---|
| 0 | Repo gap assessment + registration scaffolding | §1, MX-001/002 | Gap report approved |
| 1 | Statutory content + canonical packs (Draft) | §2, §4, §5, §9, §16, §17, MX-003/004/012/029 | Seed idempotent, resolver boundary tests |
| 2 | Super Admin: compliance config, version activation, report templates, state ISN | §15, §22, MX-045/047 | Draft→Active with four-eyes on a dev DB |
| 3 | Employer onboarding + registrations | §11, MX-002/024/034/035 | Multi-registration, multi-state employer configurable |
| 4 | Employee statutory profile + validation + CLABE | §12, MX-036–038, MX-061 | Identifier mismatches = exceptions |
| 5 | Calculation engine | §3–§10, §15–§17, MX-005–033, 048–053 | F1–F5, F7 golden PASS |
| 6 | Payroll run integration | §13, MX-039–041 | Preview non-mutating; approval fingerprint |
| 7 | CFDI 4.0 + Nómina 1.2 + PAC | §6, MX-015–018, 062 | F6 PASS in PAC sandbox |
| 8 | IMSS/SUA/SIPARE/IDSE, INFONAVIT, ISR remittance, state ISN returns | §8, §10, §14, §15, MX-025/026/030/033/042–046 | SUA reconciliation workflow |
| 9 | Aguinaldo, vacation, PTU, finiquito/severance, annual ISR adjustment | §17–§19, MX-010/054–059 | T7 PASS |
| 10 | Banking, journal, privacy/retention, certification, G1–G8 evidence | §20–§22, MX-060–064 | Evidence register complete |

---

## 3. Phase 0 — Repo gap assessment and scaffolding

Analysis deliverable: `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md` — confirms every touchpoint below (with current line numbers), the NL/AU patterns being cloned, and any deviations.

*[v1.1] Phase 0 is complete (staged on `nikhil`). As built: 13 jurisdiction hooks (same set as NL/SA), all fail closed except `retention_settings`, which returns an inert setting (no categories, decision OPEN, never enables deletion) because report downloads query every country; run blocking covers approve/authorise/pay only; `GET /api/super-admin/compliance/mexico/readiness` shows G1–G8 OPEN. Items below that the gap assessment showed need no change (organizations router, currency.js, registrationRegions.js, errorClassification.js) were left untouched.*

Backend (modify)
- `app/core/jurisdiction.py` — *[v1.1] not added to `REGISTRATION_COUNTRIES`*; `JURISDICTION_TAX_SCHEMAS["MX"]` (label "RFC / Registro Patronal IMSS", currency MXN, RFC persona moral `^[A-ZÑ&]{3}[0-9]{6}[A-Z0-9]{3}$` primary, Registro Patronal 11 chars); name→code (`mexico`, `méxico`) and code→name maps.
- `app/modules/payroll/jurisdiction_hooks.py` — `_MODULES["MX"]`.
- `app/modules/payroll/enterprise/service.py` — *[v1.1] deferred until G1–G8.*
- `app/modules/organizations/router.py` — no change; it is data-driven from `jurisdiction.py` *[v1.1 carry-over from Phase 0]*.

Backend (create, skeleton only)
- `app/modules/payroll/mexico_service.py` (with `JURISDICTION_HOOKS` dict, stub hooks that fail closed)
- `app/modules/payroll/mexico_schemas.py`, `mexico_router.py` (prefix `/super-admin/compliance/mexico`, registered in `main.py`)
- `app/modules/payroll/engine/countries/mexico.py` (calculate() → BLOCKED until Phase 5), `mexico_content.py` (empty constants + SOURCE_REFERENCES S1–S23)
- `app/modules/payroll/engine/jurisdictions/mexico/__init__.py`

Frontend (modify)
- `components/jurisdiction/CountryFlag.jsx` (MX flag). `utils/currency.js` and `utils/registrationRegions.js` already contain MXN / the 32 federal entities / Mexican timezones (naming verified in Phase 3); `service/errorClassification.js` has no country blocked-code registry — unchanged *[v1.1 carry-over from Phase 0]*.

Tests: `tests/test_mexico_scaffolding.py` (registry, hooks fail-closed, calculator blocks).

---

## 4. Phase 1 — Statutory content and canonical packs

*[v1.1] Approved decisions (detail in `docs/mexico/MEXICO_PHASE_1_PLAN.md` §6–§7):*
- Sources first: every value transcribed only from a saved file in `docs/mexico/sources/` listed in `SOURCES_MANIFEST.csv` (SHA-256). Batch A (value sources) blocks transcription; Batch B (evidence-only) is needed before G1.
- Evidence register extended with S24 LISR Art. 93, S25 RLISR Art. 174, S26 Ley Federal del Trabajo, S27 Ley del INFONAVIT Art. 29 (`MEXICO_SPEC_ADDENDUM_SOURCES.md`, pending spec-owner approval). S15/S17/S19/S20 become cross-checks.
- S22: the linked CDMX Fiscal Code is stale (3%, last reform 2022). The current consolidated code (Art. 158 = 4%, reform date December 2025 or later) is required. The stale file stays in the manifest as WRONG_VERSION and is not committed.
- Source wins: an ISR row that fails the quota-arithmetic check but matches S2 exactly is a documented exception, never altered. Spec §4 vs S2 disagreement → stop and ask.
- CEAV: only the 2026 bands are seeded into `MX-PAYROLL-2026`; 2023–2030 stay as dated rows in `mexico_content.py` with a date-selection test (MX-029). The lowest-band minimum-wage reference is a content parameter marked [PENDING G2]; Phase 5 blocks only ZLFN employees whose SBC falls in that band.
- Tests required: MX reads canonical pack rows only (never org-synced copies, which drop row dates); the `_VALIDATION_ENABLED_COUNTRIES` change affects only MX; the test-only Active pack is fixture-inserted and no production path sets MX Active; MX slabs never reach the generic progressive-tax path.
- Transcription log carries an empty "Human G1 reviewer" column per table; the blind AI re-transcription does not count as G1.
- No migrations in Phase 1. Pack activation stays refused until Phase 2.

Backend (create)
- `engine/countries/mexico_content.py` — `MX_2026` pack ids; `MX_PARAMETER_KEYS`; pure `*_in_force(as_of)` helpers with a required date argument; ISR tariffs per period (DAILY, WEEKLY_7, DECENAL_10, QUINCENAL_15, MONTHLY) from Annex 8; subsidy (ceiling 11,492.66; 15.59% Jan on 2025 UMA; 15.02% Feb+; 30.4 divisor); UMA rows (113.14 / 3,439.46 to 31 Jan; 117.31 / 3,566.22 / 42,794.64 from 1 Feb); minimum wages (GENERAL 315.04, ZLFN 440.87, professional table); IMSS branch rates (§8); SBC max 25 UMA; CEAV bands 2023–2030 as dated content (only 2026 seeded); INFONAVIT 5%; benefit floors (aguinaldo 15 days, vacation schedule, 25% premiums); workweek schedule 48/46/44/42/40 with OT limits; special-pay ISR exemption rules; CDMX ISN 4%.
- `scripts/seed_mexico_canonical_packs.py` — clone of `seed_netherlands_canonical_packs.py` (Draft only, `_local_db_guard`, refuses non-Draft rewrite, wholesale replace of Draft rows).
- `scripts/verify_mexico_sources.py` — machine extraction of numbers from the saved PDFs, compared row by row to content.
- `tests/test_mexico_content.py`, `tests/test_mexico_seed.py` — see `MEXICO_PHASE_1_PLAN.md` §4/§6.
- `docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md`, `MEXICO_PHASE_1_IMPLEMENTATION_REPORT.md`.

Backend (modify)
- `engine/fallback_registry.py` — *[v1.1]* one row per required MX key with `attr: "MX_NO_FALLBACK"` (a missing row BLOCKS); `"mexico"` added to `_MODULES`.
- `engine/countries/shared.py` — `"MX"` in `_VALIDATION_ENABLED_COUNTRIES`.
- `hardcoded_defaults.py` — *[v1.1] no MX fallback values.*
- Registry row (PLANNED, NOT_OFFERED) created inside `seed_mexico_canonical_packs.py` (NL pattern), not `seed_jurisdiction_service_registry.py` *[v1.1 carry-over from Phase 0]*.
- MX filing calendar rows *[v1.1: moved to Phase 2]* — via `service.upsert_filing_calendar_entry` in `scripts/seed_statutory_report_templates.py`, not `seed_statutory_filings.py` *[v1.1 carry-over from Phase 0]*.
- `service.py` — add MX to `_CANONICAL_PACK_ONLY_COUNTRIES` (L1508). *[v1.1] MX is NOT added to `_NO_TAX_SLAB_COUNTRIES`* (that list exists only for countries that import tax tables as files).

Data placement (no new tables)

| Content | Table | Discriminator |
|---|---|---|
| ISR tariffs | `payroll_tax_slabs` | `rule_type=MX_ISR_TARIFF`, `filing_status`=period code |
| CEAV employer bands (2026 only) | `payroll_tax_slabs` | `rule_type=MX_CEAV_BAND`, `tax_table_number`=year, band bounds and unit (SM/UMA) in `assessment_basis` |
| CEAV lowest-band min-wage reference | `payroll_contribution_rates` | `mx_ceav_lowest_band_min_wage_ref`, text value, [PENDING G2] |
| Minimum wages | `payroll_tax_slabs` | `rule_type=MX_MIN_WAGE`, `filing_status`=zone or profession code |
| Vacation schedule | `payroll_tax_slabs` | `rule_type=MX_VACATION_DAYS` |
| Workweek limits | `payroll_tax_slabs` | `rule_type=MX_WORKWEEK`, dated rows |
| UMA, subsidy, IMSS branches, INFONAVIT, SBC cap, benefit floors | `payroll_contribution_rates` | `component_key` `mx_*`, row-level `effective_from/to` |
| ISN per state | `payroll_jurisdiction_packs` (`jurisdiction_state`, `parent_pack_id`) + `payroll_contribution_rates` | `MX-ISN-<STATE>-2026`; CDMX only until more states are confirmed |
| State support status | `payroll_state_local_program_readiness` | *[v1.1]* `program=OTHER_STATE_PAYROLL` with a code comment that it is Mexico ISN (not `STATE_PT`, which is India's employee professional tax) |
| Evidence S1–S27 | `payroll_source_artifacts` | per pack and per row; upsert by URL + SHA-256 (HK seed pattern) |

---

## 5. Phase 2 — Super Admin: compliance configuration, version activation, report templates

Version activation: reuse the existing pack lifecycle. *[v1.1] Replace the Phase 0 unconditional activation refusal with the gate-based check (four-eyes + golden PASS + evidence), same as NL.* *[v1.1 Phase 2 Q2]* The Mexico gates are: (1) content present and EXACT against mexico_content (every expected row, 11 ISR brackets per period, no extras); (2) every row linked to a hashed source; (3) G1 human review of every cited source by a Super Admin who is not the activator; (4) a pack-bound golden PASS. A [PENDING G2] parameter is a WARNING, never a block — G2 needs parallel-run output and go-live is already gated by the registry's G1–G8; the engine blocks only the affected ZLFN employees (decision 4). Modify `service.py` opt-in lists (~L8511–8530) to add MX to `_APPROVER_NOT_ACTIVATOR_COUNTRIES`, `_SELF_APPROVAL_REFUSED_COUNTRIES`, `_REFUSAL_AUDIT_COUNTRIES`, `_PACK_TRANSITION_GRAPH_COUNTRIES`, the evidence/golden-PASS gates (~L8674, ~L8718), and `_GOLDEN_FIXTURES_DIR_BY_COUNTRY` (`"MX": "mx_golden"`). Hotfix activation and audit work unchanged.

Report templates: modify `scripts/seed_statutory_report_templates.py` with MX templates (all Draft):

| template_key | report_type | scope |
|---|---|---|
| MX-PAYROLL-REGISTER | REGISTER | AGGREGATE |
| MX-CFDI-NOMINA-RECEIPT | CFDI_RECEIPT | PER_EMPLOYEE |
| MX-CFDI-STATUS | CFDI_STATUS | AGGREGATE |
| MX-ISR-MONTHLY | ISR_WITHHOLDING | AGGREGATE |
| MX-SUBSIDY | SUBSIDY | AGGREGATE |
| MX-IMSS-BRANCH | IMSS | AGGREGATE |
| MX-IDSE-MOVEMENTS | IDSE | AGGREGATE |
| MX-SUA-RECON | SUA | AGGREGATE |
| MX-SIPARE | SIPARE | AGGREGATE |
| MX-INFONAVIT | INFONAVIT | AGGREGATE |
| MX-ISN-RETURN (per state, `jurisdiction_state` set) | ISN | AGGREGATE |
| MX-AGUINALDO | AGUINALDO | PER_EMPLOYEE |
| MX-VACATION-ACCRUAL | VACATION | AGGREGATE |
| MX-PTU-DISTRIBUTION | PTU | AGGREGATE + PER_EMPLOYEE |
| MX-FINIQUITO | FINIQUITO | PER_EMPLOYEE |
| MX-ANNUAL-ISR-ADJ | ANNUAL_ISR | AGGREGATE |
| MX-EMPLOYER-COST | EMPLOYER_COST | AGGREGATE |
| MX-JOURNAL | JOURNAL | AGGREGATE |

Backend (create/modify)
- `mexico_router.py` endpoints: `GET /organizations`, `GET /employees`, `GET /packs`, `GET /packs/{id}/activation-readiness`, `GET /isr-tariffs`, `GET /uma-min-wage`, `GET /imss-branches`, `GET /ceav-schedule`, `GET /infonavit`, `GET /benefits-workweek`, `GET/POST /earning-classifications`, `POST /earning-classifications/{id}/approve`, `POST /earning-classifications/{id}/archive`, `GET/POST /cfdi-catalogs`, `GET/POST /cfdi-catalogs/{id}/entries`, `PUT /cfdi-catalogs/{id}/{action}`, `GET /isn-states`, `GET /readiness`. Content reads take an explicit `on` date; omitted, the pack's effective_from is used — never today. *[v1.1 Phase 2 Q5]*
- *[v1.1 Phase 2 Q1]* `GET/POST /employer-profile`, `GET /employer-profile/readiness` and the Employer tab move to **Phase 3**, with their table (`payroll_mx_employer_profiles`, `mx_employer_m2`).
- `mexico_service.py` — Super Admin reads/writes delegating to the shared pack/rate CRUD (no parallel editor).

Frontend (create)
- `pages/JurisdictionCompliance/MXCompliancePage.jsx`, `pages/JurisdictionStatutory/MXStatutoryPage.jsx`, `pages/ReportTemplates/MXReportTemplatesPage.jsx`
- `config/jurisdictions/mexicoComplianceConfig.jsx` — extra tabs (*Employer moved to Phase 3*): ISR tariffs, Subsidy & UMA, Minimum wages, IMSS & CEAV, INFONAVIT, CFDI catalogs, Benefits & workweek, Earning classification, State ISN, Sources (SourceEvidencePanel), Tests (TestCertificationPanel), Readiness G1–G8
- `components/jurisdiction/mexico/` (*`MXEmployerProfileTab` moved to Phase 3*): `MXIsrTariffsTab`, `MXSubsidyUmaTab`, `MXMinimumWageTab`, `MXImssCeavTab`, `MXInfonavitTab`, `MXCfdiCatalogTab`, `MXBenefitsWorkweekTab`, `MXEarningClassificationTab`, `MXReadinessGatesTab`, `mxShared.jsx`
- `components/jurisdiction/mexico/state/` (clone of AU state accordion): `MXStateAccordionWorkspace`, `MXStateAccordionRow`, `MXStateIsnTab`, `mxStateCodes.js`

Frontend (modify)
- `App.jsx` — routes `/super-admin/compliance/mexico`(+`/:jurisdiction`), `/super-admin/statutory-rates/mexico`(+`/:jurisdiction`), `/super-admin/report-templates/mexico`(+`/:jurisdiction`)
- `pages/JurisdictionCompliance/index.js`, `pages/JurisdictionStatutory/index.js`, `pages/ReportTemplates/index.js` — exports + `MX: "mexico"`
- `service/superAdminService.js` — MX endpoints
- `pages/TestCertificationPage.jsx` — MX option (`backend/tests/fixtures/mx_golden/README.md`)
- `pages/EngineFallbackDefaultsPage.jsx` — MX group

DB (new, migration `mx_foundation_m1`)

| Table | Columns |
|---|---|
| `payroll_mx_earning_classifications` *(as built: + approved_at, sha256; status DRAFT → ACTIVE → SUPERSEDED/ARCHIVED; two partial unique indexes on (code, effective_from) for canonical rows and (org, code, effective_from) for org rows)* | id, organization_id (null=canonical), earning_code, label, version, effective_from, effective_to, isr_treatment (TAXABLE/EXEMPT/PARTIAL), isr_exempt_rule_key, sbc_treatment (FIXED/VARIABLE/EXCLUDED), sbc_exclusion_condition, infonavit_included, isn_default_included, isn_state_overrides (JSON), ptu_wage_base_included, cfdi_node_type (PERCEPCION/DEDUCCION/OTRO_PAGO/SEPARACION), cfdi_concept_code, status, source_document_id, approved_by_id, created_by_id, created_at, updated_at |
| `payroll_mx_cfdi_schema_releases` | id, cfdi_version, complement_version, revision, xsd_checksum, catalog_release, pac_validation_version, source_document_id, status, approved_by_id, created_by_id, created_at, updated_at |
| `payroll_mx_cfdi_catalog_entries` | id, schema_release_id, catalog_name, code, description, valid_from, valid_to, attributes (JSON) |

---

## 6. Phase 3 — Employer onboarding and registrations (§11)

Backend: `mexico_service.py` (profile, establishments, registrations, risk premiums, ISN registrations, labor policy, readiness), `mexico_router.py` endpoints for each, `mexico_schemas.py`. Org-side readiness endpoint `GET /payroll/mexico/readiness` in `router.py` (France pattern). CSD/PAC/IDSE secrets: store only `*_secret_ref` + fingerprint/expiry (MX-035).

DB (migration `mx_employer_m2`)

| Table | Columns |
|---|---|
| `payroll_mx_employer_profiles` | id, organization_id, rfc, legal_name, fiscal_regime_code, fiscal_postal_code, fiscal_address, place_of_issue_postal_code, withholding_obligation_active, csd_certificate_number, csd_fingerprint, csd_valid_from, csd_valid_to, csd_secret_ref, pac_provider, pac_environment, pac_credential_secret_ref, stamp_test_status, stamp_test_uuid, stamp_tested_at, infonavit_operating_model (SUA/SIPARE), readiness_status, readiness_evidence (JSON), created_by_id, created_at, updated_at |
| `payroll_mx_establishments` | id, organization_id, employer_profile_id, name, state_code, municipality_code, postal_code, min_wage_zone, imss_registration_id, is_active, created_by_id, created_at, updated_at |
| `payroll_mx_imss_registrations` | id, organization_id, employer_profile_id, registro_patronal, risk_class, fraction, subdelegation_code, effective_from, effective_to, status, created_by_id, created_at, updated_at |
| `payroll_mx_risk_premiums` | id, registration_id, determination_year, premium_rate_pct, period_from, period_to, source_document_id, status, created_by_id, created_at |
| `payroll_mx_isn_registrations` | id, organization_id, employer_profile_id, state_code, local_account_number, jurisdiction_pack_id, return_frequency, effective_from, effective_to, status, created_by_id, created_at, updated_at |
| `payroll_mx_labor_policies` | id, organization_id, collective_agreement_id (nullable FK), effective_from, effective_to, ordinary_weekly_hours, weekly_schedule (JSON), aguinaldo_days, vacation_policy (JSON), vacation_premium_pct, savings_fund (JSON), food_vouchers (JSON), other_benefits (JSON), floor_check_status, created_by_id, created_at, updated_at |

Frontend: `MXEmployerProfileTab` gains panels A–H; new `MXRegistrationsTab` (IMSS + risk premium), `MXIsnRegistrationsPanel`, `MXLaborPolicyPanel`, `useMexicoOrgData.js`. `pages/PolicyModule/MXPolicyPage.jsx` + `PolicyModule/index.js`.

---


**[As built — Phase 3, commit 45d822a, merged to main by PR #101; plan `MEXICO_PHASE_3_PLAN.md` §19, report `MEXICO_PHASE_3_IMPLEMENTATION_REPORT.md`]**
- Backend: **`mexico_employer_service.py`** (all employer logic — kept out of `mexico_service.py`, the jurisdiction-hook module) and **`mexico_org_router.py`** (`/api/payroll/mexico`, mounted in `router.py` with one `include_router`, NL pattern — not the France-style readiness endpoint in `router.py`). Super Admin employer routes in `mexico_router.py` are read-only and masked.
- Migration **`6e4a1d9c3f27_mx_employer_m2`** (as planned name `mx_employer_m2`): the six planned tables plus **`payroll_mx_credential_refs`**; partial unique indexes on every open/ACTIVE row.
- Secrets: `gcp-sm://` references + public certificate metadata only (`MX_SECRET_REF_SCHEMES`), expiry warning `MX_CREDENTIAL_EXPIRY_WARNING_DAYS = 30`; `.cer` ≤16 KB, DER/PEM, in memory.
- Frontend: Payroll → Compliances → **Mexico Compliance Centre** (the repo's equivalent of the spec's Settings → Countries → Mexico); Super Admin **Employer** tab (read-only). `MXPolicyPage.jsx` not built (Phase 6).
- Column changes against the table above: profiles are versioned (`version`, `previous_version_id`, `effective_from/to`, `taxpayer_type`); `csd_*` / `pac_credential_secret_ref` moved to `payroll_mx_credential_refs`; `infonavit_operating_model` moved to the IMSS registration; `readiness_status` / `readiness_evidence` dropped (computed on read); establishments derive `min_wage_zone` (not stored); risk premiums use `evidence_document_id` → `payroll_compliance_documents`; labour policies gain `employer_profile_id`, `version`, `sunday_premium_pct`, `time_record_dependency`, `status`.
- **Seven deviations** (report §10): (1) service in `mexico_employer_service.py`; (2) ISN registration stores OPEN/CLOSED, PENDING_PACK/ACTIVE computed from the pack on read; (3) IMSS registration status ACTIVE/CLOSED, no DRAFT; (4) credential uniqueness via two partial indexes instead of one expression index; (5) floor check reports dates past the Active content horizon as `notYetCheckable`; (6) Super Admin org picker also lists orgs with an MX employer or MX company jurisdiction; (7) `MXPolicyPage.jsx` deferred to Phase 6 (OOS-6 logged: the shared Policy dispatcher falls back to India's page).

## 7. Phase 4 — Employee statutory profile (§12)

Backend (modify): `models.py` `EmployeeStatutoryProfile` + `employee_validation.py` (RFC persona física 13 chars, CURP 18, NSS 11 with check digit, CLABE 18 with check digit, cross-consistency RFC↔CURP; mismatch = exception, never auto-fix), `bank_routing.py` (`ROUTING_COUNTRIES` + MX, field CLABE, scheme SPEI), `schemas.py`.

DB (migration `mx_employee_m3`)

`payroll_employee_statutory_profiles` new columns: mx_rfc_token, mx_rfc_last4, mx_curp_token, mx_nss_token, mx_fiscal_postal_code, mx_receiver_fiscal_regime, mx_contract_type_code, mx_regime_type_code, mx_workday_type_code, mx_job_risk_code, mx_work_state, mx_work_municipality, mx_establishment_id, mx_min_wage_zone, mx_professional_min_code, mx_pay_frequency_code, mx_daily_salary, mx_salary_type (FIXED/VARIABLE/MIXED), mx_seniority_date, mx_imss_registration_id, mx_subsidy_eligible, mx_annual_adjustment_eligible, mx_annual_adjustment_exclusion, mx_identifier_validation_status, mx_remote_state_exception_ref, mx_termination_date, mx_termination_reason.

New tables

| Table | Columns |
|---|---|
| `payroll_mx_sbc_history` | id, organization_id, employee_id, registration_id, effective_from, sbc_mode, fixed_component, variable_component, integration_factor, sbc_daily, capped_at_max, component_trace (JSON), source (HIRE/SALARY_CHANGE/BIMONTHLY), imss_movement_id, created_by_id, created_at |
| `payroll_mx_variable_accumulators` | id, employee_id, bimester_key, variable_total, days_counted, average_daily_variable, snapshot_hash, committed_run_id, created_at |
| `payroll_mx_infonavit_notices` | id, organization_id, employee_id, credit_number, notice_type (RETENCION/SUSPENSION/MODIFICACION), discount_method (FIXED_AMOUNT/PERCENTAGE/VSM/UMA_FACTOR), discount_value, effective_from, effective_to, authority_reference, source_document_id, status, recorded_by_id, created_at |
| `payroll_mx_benefit_accruals` | id, employee_id, year, aguinaldo_days_statutory, aguinaldo_days_employer, aguinaldo_accrued, vacation_days_statutory, vacation_days_employer, vacation_days_taken, vacation_premium_pct, last_run_id, updated_at |

Frontend (modify): `modules/payroll/Payroll_Employees/countryFieldSpecs.js` (MX block: identity, employment, pay, IMSS, INFONAVIT, ISR, benefits, state), `bankFieldsFor.js` (CLABE). Create `components/jurisdiction/mexico/MXSbcExplainabilityCard.jsx` and `MXInfonavitNoticePanel.jsx`.

---

## 8. Phase 5 — Calculation engine (§3–§10, §15–§17)

Pure functions, no DB access, everything from the pre-resolved context; BLOCK (fail closed) on any missing content. Pay date / contribution period selects law, never server date.

Backend (create) `engine/jurisdictions/mexico/`: `classification.py`, `isr.py`, `isr_special_pay.py`, `subsidy.py`, `sbc.py`, `imss.py`, `ceav.py`, `infonavit.py`, `isn.py`, `labor.py` (minimum wage, workweek/OT, Sunday, holidays), `entitlements.py` (aguinaldo, vacation, premium), `preflight.py`, `rounding.py`, `trace.py`.
Backend (complete) `engine/countries/mexico.py` `calculate(ctx)` orchestrator.

Backend (modify)
- `engine/standard.py` — import and `_COUNTRY_CALC["MX"]` already exist (Phase 0). The calculator returns the generic keys (`tds` = ISR, social-security slots) plus calculator-output keys `mx_employee_total` (added to the employee-deduction sum) and `mx_result`; employer totals live inside `mx_result` (NL pattern).
- `engine/base.py` — ctx fields as built in Phase 0: mx_payroll_date, mx_payment_period, mx_profile, mx_employer, mx_registration, mx_risk_premium, mx_sbc, mx_infonavit_notices, mx_isn_state_pack, mx_classifications, mx_labor_policy, mx_ytd, mx_employee_id, mx_organization_id. Result: a single `PayrollResult.mx_result` dict, with no flat `mx_*` result fields.
- `engine/resolver.py` — block simple mode; accept `mexico_inputs`.

Tests: `tests/fixtures/mx_golden/` (README + F1 UMA boundary, F2 SBC factor, F3 CEAV high band, F4 min-wage geography, F5 subsidy transition, F7 CDMX ISN), `tests/mx_golden/`, `tests/test_mexico_engine.py` (T1, T3, T4, T6).

---

## 9. Phase 6 — Payroll run integration (§13)

Backend (modify) `service.py`: call `jurisdiction_hooks.call("MX", "calc_inputs", ...)` at the three NL sites: preview `preview_payroll_run` (L19959), generate/regenerate `_compute_payslip_values` (L25077 — also the path `regenerate_employee_payslip` uses), and manual add `add_payslip_item` (L31721). Persist `mx_calculation_snapshot` and map it in the payslip response (`_serialize_payslip`, L32550). Currency symbol/code already exist from Phase 0 (`_get_currency_symbol` L32626, `_get_currency_code` L32653). Line numbers are as of HEAD dce5279. `schemas.py`: `mxCalculationSnapshot`.
Backend (create in `mexico_service.py`): `calc_inputs`, `payslip_snapshot`, `before_run_transition` hook (computes/stores `mx_approval_fingerprint` binding content/input hashes at APPROVED, re-verifies at AUTHORIZED/PAID — MX-040, NL pattern; there is no separate `approval_fingerprint` hook) *[v1.1 carry-over from Phase 0]*, `run_preflight` (blocking exceptions), `commit_ledgers` (SBC variable accumulators, accruals, ISN liability rows — only on commit, MX-039).

DB (migration `mx_run_m4`): `payslip_items.mx_calculation_snapshot` (JSON), `payroll_runs.mx_approval_fingerprint`, `payroll_runs.mx_run_type` (ORDINARY/AGUINALDO/PTU/FINIQUITO/CORRECTION); new `payroll_mx_preflight_exceptions` (id, payroll_run_id, employee_id, code, severity, message, resolved_by_id, resolution_note, resolved_at, created_at); `payroll_mx_isn_liabilities` (id, payslip_item_id, organization_id, state_code, base_amount, rate_pct, amount, jurisdiction_pack_id, period_key, created_at); `payroll_mx_imss_branch_lines` (id, payslip_item_id, branch_code, base_amount, contribution_days, employer_rate, employer_amount, employee_rate, employee_amount).

Frontend: Mexico run stages shown inside the existing `modules/payroll/PayRollRuns` flow — create `components/jurisdiction/mexico/MXRunPreflightPanel.jsx`, `MXRunCalculationTrace.jsx`, `MXRunStatusBadges.jsx` (payroll / CFDI / authority / bank separate, MX-041); modify the run detail view to mount them when country = MX; payslip view to render `mxCalculationSnapshot`.

---

## 10. Phase 7 — CFDI 4.0 + Nómina 1.2 + PAC (§6)

Backend (create): `mexico_cfdi_service.py` (builder from committed payslip only, XSD validation against pinned release, CSD signing via secret ref, lifecycle incl. UNKNOWN → status query before retry, cancellation/substitution lineage), `mexico_pac.py` (transport adapter, NL `netherlands_digipoort.py` pattern), `mexico_http.py`. Endpoints in `mexico_router.py` and org-side `router.py` (`/payroll/mexico/cfdi/...`).

DB (migration `mx_cfdi_m5`)

| Table | Columns |
|---|---|
| `payroll_mx_cfdi_documents` | id, organization_id, payroll_run_id, payslip_item_id, employee_id, series, folio, schema_release_id, payload_hash, xml_storage_ref, status (GENERATED/SIGNED/SUBMITTED/STAMPED/REJECTED/UNKNOWN/CANCEL_REQUESTED/CANCELLED/REPLACED), uuid, stamped_at, sat_certificate_number, pac_provider, pac_response_code, pac_message, cancellation_reason_code, cancel_requested_at, cancelled_at, replaces_uuid, replaced_by_uuid, idempotency_key, created_by_id, created_at, updated_at |
| `payroll_mx_cfdi_outbox_items` | id, document_id, action (STAMP/CANCEL/STATUS_QUERY), payload_hash, idempotency_key, status, attempts, last_error, sent_at, acknowledged_at, created_at, updated_at |
| `payroll_mx_cfdi_events` (append-only) | id, document_id, event_type, from_status, to_status, payload_hash, actor_id, occurred_at |

Frontend: `MXCfdiLifecycleTab.jsx` (Super Admin), `MXCfdiStagePanel.jsx`, `MXCfdiDetailDrawer.jsx`, `MXCancelReplaceDialog.jsx`.

---

## 11. Phase 8 — Authorities: IMSS / SUA / SIPARE / IDSE, INFONAVIT, ISR remittance, state ISN

Backend (create): `mexico_imss_service.py` (movements alta/baja/modificación from committed events, 5-business-day due dates, IDSE export, SUA export + reconciliation, SIPARE, annual risk premium), `mexico_filing_service.py` (ISR monthly remittance by the 17th, ISN returns per state, INFONAVIT reconciliation), `mexico_payment_service.py` (authority liabilities). Reuse `StatutoryFiling` for generic filing status where it fits.

DB (migration `mx_authorities_m6`)

| Table | Columns |
|---|---|
| `payroll_mx_imss_movements` | id, organization_id, employee_id, registration_id, movement_type, event_date, due_date, sbc, reason_code, idse_batch_ref, status (PENDING/FILED/ACCEPTED/REJECTED/UNKNOWN), evidence_ref, created_by_id, created_at, updated_at |
| `payroll_mx_sua_periods` | id, organization_id, registration_id, period_month, bimester, sua_version, zoiko_totals (JSON), sua_totals (JSON), difference_total, status (DRAFT/RECONCILED/PAID), reconciled_by_id, reconciled_at, created_at |
| `payroll_mx_sua_differences` | id, sua_period_id, employee_id, branch_code, zoiko_amount, sua_amount, difference, explanation, status |
| `payroll_mx_sipare_payments` | id, sua_period_id, capture_line, amount, due_date, status (READY/RELEASED/SETTLED/FAILED/UNKNOWN), bank_reference, created_at, updated_at |
| `payroll_mx_work_risk_reviews` | id, registration_id, review_year, cases (JSON), computed_premium_pct, filing_date, evidence_ref, status (OPEN/FILED/ACCEPTED) |
| `payroll_mx_authority_liabilities` | id, organization_id, authority (SAT_ISR/IMSS/INFONAVIT/ISN), state_code, period_key, amount, due_date, status (ACCRUED/DUE/PAID/RECONCILED/UNKNOWN), payment_reference, created_at, updated_at |
| `payroll_mx_isn_returns` | id, organization_id, state_code, period_key, base_total, amount, due_date, status, filing_reference, amendment_of_id, created_by_id, created_at |

Frontend: `MXSocialSecurityCenterTab.jsx` (cards: registration, movements, SUA, SIPARE, work-risk, differences), `MXIsrRemittanceTab.jsx`, `MXIsnReturnsTab.jsx`, `MXInfonavitReconTab.jsx`.

---

## 12. Phase 9 — Annual and event modules

Backend (create): `mexico_annual_service.py` (aguinaldo run, vacation accrual by anniversary, PTU cycle and allocation with cap comparison, annual ISR adjustment), `engine/jurisdictions/mexico/ptu.py`, `termination.py`, `annual_adjustment.py`.

DB (migration `mx_annual_m7`)

| Table | Columns |
|---|---|
| `payroll_mx_ptu_cycles` | id, organization_id, fiscal_year, distributable_profit, pool_amount, days_half, salary_half, payment_deadline, status, approved_by_id, created_by_id, created_at |
| `payroll_mx_ptu_allocations` | id, cycle_id, employee_id, eligible, exclusion_reason, qualifying_days, qualifying_salary, days_share, salary_share, cap_three_months, cap_three_year_avg, cap_applied, final_amount, payroll_run_id |
| `payroll_mx_terminations` | id, organization_id, employee_id, termination_date, reason_code, source_document_id, approved_by_id, components (JSON), seniority_premium_applies, payroll_run_id, imss_movement_id, created_at |
| `payroll_mx_annual_isr_adjustments` | id, organization_id, year, employee_id, eligible, exclusion_reason, annual_income, annual_isr, withheld_total, difference, status, created_at |

Frontend: `MXAguinaldoRunPanel.jsx`, `MXPtuCycleWizard.jsx`, `MXTerminationWizard.jsx`, `MXAnnualIsrAdjustmentTab.jsx`.

---

## 13. Phase 10 — Banking, journal, privacy, certification, gates

Backend: `bank_export/` SPEI file generator + returned-payment reconciliation; journal mapping (separate liabilities per §20); `retention_service.py` MX policy; log redaction for RFC/CURP/NSS/CLABE/CFDI XML (MX-061); recovery runbook (UNKNOWN reconciliation, MX-062).
DB (migration `mx_payments_m8`): `payroll_mx_payment_batches` (id, organization_id, payroll_run_id, file_ref, status, maker_id, checker_id, released_at, created_at), `payroll_mx_payment_items` (id, batch_id, employee_id, clabe_last4, amount, status, return_reason), `payroll_mx_idempotency_records` (NL/CH pattern).
Docs: `docs/mx-evidence/G1`…`G8`, `MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md`, `MEXICO_RELEASE_CHECKLIST.md`.
Tests: T2, T5, T7, T8; F6.

---

## 14. Decisions log

| Decision | Outcome |
|---|---|
| NL-style dedicated files vs France-style code in `service.py` | NL style (decided) |
| Registration / enterprise country lists | Excluded until G1–G8 (decided) |
| Blocked exception style | NL style, in the engine (decided) |
| ISN readiness program value | `OTHER_STATE_PAYROLL` (decided) |
| CEAV other years | Content only; 2026 seeded (decided) |
| CEAV lowest band for ZLFN | Content parameter [PENDING G2], resolved by SUA reconciliation |
| Sources S24–S27 | Added, pending spec-owner approval |
| Source S29 — RACERF (work-risk premium validity window / determination) | Added in Phase 3 (Q3), pending spec-owner approval; not yet saved. Premium approval refused until the window (S10/S14/S29) and the LSS Art. 74 range (S10) are transcribed |
| Source S30 — SAT CFDI 4.0 catalog workbook (catCFDI: `c_RegimenFiscal`, `c_CodigoPostal`) | Added in the Phase 3 follow-up, pending spec-owner approval; not yet saved. Employer catalog checks BLOCKED until loaded into an Active CFDI release (Phase 7) |
| Secret store for MX credentials | GCP Secret Manager (`gcp-sm://` only, Phase 3 Q9); must be live in production before Phase 7 (infrastructure lead time) |
| Git workflow | Claude Code stages, you commit; work on `nikhil` |
| Large source PDFs in git vs evidence storage | **Open** (follow the `docs/hk-evidence/` precedent) |
| First ISN states beyond CDMX | **Open**, needed by Phase 2 |
| PAC provider and sandbox credentials | **Open**, needed by Phase 7 |
| IDSE/SUA/SIPARE: file export only at launch, or integrated | **Open**, needed by Phase 8 |
| SPEI bank file formats | **Open**, needed by Phase 10 |
| Hosting / cross-border transfer stance (2025 privacy law) | **Open**, needed by Phase 10 |

Out-of-scope defects found during Mexico work are tracked in `docs/mexico/OUT_OF_SCOPE_DEFECTS.md` (NL simple-mode error handler, NL fallback entries, missing `nl_golden`, HK matrix CSV).
