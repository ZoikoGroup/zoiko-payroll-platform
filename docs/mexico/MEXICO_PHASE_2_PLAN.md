# Mexico (MX) — Phase 2 Plan: Super Admin, Version Activation, Report Templates, State ISN

**Status:** approved and implemented on 2026-10-15, with the answers and changes in §10, which take precedence over §1–§9. See `MEXICO_PHASE_2_IMPLEMENTATION_REPORT.md`.
**Spec:** ZP-MX-ENG-001 v1.0, §6 (CFDI catalogs: schema only), §15, §21 and §22.
**Rules covered:** MX-003, MX-005, MX-006, MX-015 (release pinning, data model only), MX-045 and MX-047.
**Base:** plan v1.1 §5; `nikhil` @ c09f7e8 plus the staged Phase 1 tooling. Line numbers below are current as of that state.
**Working rules:** `nikhil` branch in the main checkout. I stage, the user commits. No behaviour change for any other jurisdiction.

**What Phase 2 cannot do:** nothing that calculates money or activates a pack goes live. §1 shows why activation stays impossible in practice until Phase 1 values, the G1 review and Phase 5 golden vectors all exist.

---

## 1. Version activation: gate-based check replaces the unconditional refusal

### 1a. Governance opt-ins (`backend/app/modules/payroll/service.py`)

| Line | Constant / gate | Change |
|---|---|---|
| L8513 | `_GATED_PACK_COUNTRY_NAMES` | add `"MX": "Mexico"` |
| L8516 | `_APPROVER_NOT_ACTIVATOR_COUNTRIES` | add `"MX"` (four-eyes: the approver cannot activate) |
| L8519 | `_SELF_APPROVAL_REFUSED_COUNTRIES` | add `"MX"` (the editor cannot approve) |
| L8523 | `_REFUSAL_AUDIT_COUNTRIES` | add `"MX"` (every refusal is audited) |
| L8530 | `_PACK_TRANSITION_GRAPH_COUNTRIES` | add `"MX"` (Draft → In Review → QA → Approved → Active only) |
| L8677 | evidence gate (`source_document_id` + `effective_from` required) | add `"MX"` |
| L8721 | strict golden-PASS gate | add `"MX"` |
| L19277 | `_GOLDEN_FIXTURES_DIR_BY_COUNTRY` | add `"MX": "mx_golden"`; create `backend/tests/fixtures/mx_golden/README.md` with **no cases** |

### 1b. `mexico_service.mx_activation_evidence_refusal` becomes a content-and-evidence check

The Phase 0 version refused unconditionally. It is replaced by an ordered check, and the first failing condition refuses:
1. **Content present.**
   - The national pack must carry every required `MX_PARAMETER_KEYS` row (national scope) and at least one `MX_ISR_TARIFF` row for each of the five periods.
   - A state ISN pack must carry `mx_isn_rate_pct`.
   - Empty or partial content is refused.
2. **Evidence linked.** Every row has a `source_document_id`, and its `SourceArtifact` has a URL, a SHA-256 and a `file_path`.
3. **G1 human review recorded.** Every cited `SourceArtifact` has `reviewer_id` / `reviewer_approved_at` set, by a Super Admin who is **not** the activator. The blind AI re-transcription does not count (Phase 1 §6 change 6).
4. **No [PENDING G2] parameter in the pack.** If one is present (the CEAV lowest-band reference), activation is refused until G2 resolves it. **This is also Q2.**
5. **Pack-bound golden PASS** (the HK precedent). The latest MX `TestCertificationRun` must be PASS **and** must have been produced against *this* pack version's rows. The country-wide latest-run gate at L8721 alone could be satisfied by a run against older rows.

### 1c. Why activation stays impossible in practice

The gates are cumulative, and Phase 1 tooling already fails closed on each one:

| Gate | Today | What opens it |
|---|---|---|
| Content present (1b-1) | Every MX content table is empty | Phase 1 transcription |
| Evidence linked (1b-2) | No VERIFIED source in the manifest, so no artifact exists | Batch A files plus `verify_mexico_sources` |
| G1 review (1b-3) | No artifact is reviewer-approved | Human G1 reviewer |
| Golden PASS (L8721 and 1b-5) | `mx_golden/` has no cases (`NO_REAL_CASES` is not PASS), and any case would FAIL because `countries/mexico.py` raises `MX_ENGINE_NOT_IMPLEMENTED` | Phase 5 engine plus golden vectors |
| Four-eyes (L8516/8519) | — | Two different Super Admins |

**Tests prove each gate refuses independently.** One test per gate builds a synthetic pack that satisfies every *other* gate (test-only, fixture-inserted rows and artifacts, as in Phase 1) and asserts the refusal message. A final test shows the real seeded pack is refused today.

### 1c-ii. Hotfix path

The `PackHotfixActivation` path calls the same `pack_activation_refusal` hook (L8795–8798 runs on the hotfix path too). A test covers it.

---

## 2. Super Admin pages and tabs

### 2a. Frontend files to create (`frontend/src/`)

| File | Pattern cloned |
|---|---|
| `pages/JurisdictionCompliance/MXCompliancePage.jsx` | NL org selector (`NLCompliancePage.jsx`) **plus** AU state routing (`useParams` / `onStateChange` → `/super-admin/compliance/mexico/:jurisdiction`, `AUCompliancePage.jsx`) |
| `pages/JurisdictionStatutory/MXStatutoryPage.jsx` | `NLStatutoryPage.jsx` |
| `pages/ReportTemplates/MXReportTemplatesPage.jsx` | `NLReportTemplatesPage.jsx` |
| `config/jurisdictions/mexicoComplianceConfig.jsx` | `netherlandsComplianceConfig.jsx` (tab chain by `after`) and `australiaComplianceConfig.jsx` (`hiddenTabs`, state accordion tab) |
| `components/jurisdiction/mexico/mxShared.jsx` | `nlShared.jsx` (`useLoad`, `useAction`, `Table`, `NeedOrg`, …) |
| `components/jurisdiction/mexico/MXIsrTariffsTab.jsx` | read-only, five period sub-tables |
| `components/jurisdiction/mexico/MXSubsidyUmaTab.jsx` | read-only, January and February columns side by side (MX-004) |
| `components/jurisdiction/mexico/MXMinimumWageTab.jsx` | read-only: zones, professions, ZLFN municipalities |
| `components/jurisdiction/mexico/MXImssCeavTab.jsx` | read-only: IMSS branches, the SBC cap, the 2026 CEAV bands plus the full 2023–2030 schedule (marked content-only) |
| `components/jurisdiction/mexico/MXInfonavitTab.jsx` | read-only |
| `components/jurisdiction/mexico/MXBenefitsWorkweekTab.jsx` | read-only: 2026 → 2030 workweek steps, benefit floors, vacation schedule |
| `components/jurisdiction/mexico/MXEarningClassificationTab.jsx` | `NLEarningClassificationTab.jsx` — **multi-axis (MX-005)**, editable through the governed endpoints (§5) |
| `components/jurisdiction/mexico/MXCfdiCatalogTab.jsx` | schema releases and catalog entries with lifecycle buttons (§5) |
| `components/jurisdiction/mexico/MXReadinessGatesTab.jsx` | `NLReadinessGatesTab.jsx` — G1–G8 from `GET /readiness` |

**Every read-only content tab** shows each row's `[PENDING G1]` marker, its source code and a link to the `SourceArtifact` (URL, SHA-256). While content is empty, a tab shows **"Awaiting transcription"**, never zeros.

**Not in Phase 2:** `MXEmployerProfileTab`. The employer table arrives in Phase 3 (Q1).

### 2b. Tab chain (`mexicoComplianceConfig.jsx`)

The tabs, in order:
1. `overview`
2. ISR tariffs
3. Subsidy & UMA
4. Minimum wages
5. IMSS & CEAV
6. INFONAVIT
7. Benefits & workweek
8. Earning classification
9. CFDI catalogs
10. **State ISN** (§3)
11. Sources (`SourceEvidencePanel`)
12. Tests (`TestCertificationPanel`, with `jurisdiction="MX"` and `fixturesPath="backend/tests/fixtures/mx_golden/README.md"`)
13. Readiness G1–G8

`hiddenTabs: ["rates","slabs"]`, as for AU: generic row editors stay hidden, because MX content changes only through the governed pack lifecycle. **`TaxabilityMatrixTab` is not used** (it only has CA/US programs).

### 2c. Frontend files to modify

| File:line | Change |
|---|---|
| `App.jsx` L29, L38, L44 | import `MXCompliancePage`, `MXStatutoryPage`, `MXReportTemplatesPage` |
| `App.jsx` (after L202, L258, L297) | 6 routes: `/super-admin/compliance/mexico`, `/super-admin/statutory-rates/mexico` and `/super-admin/report-templates/mexico`, each with a `/:jurisdiction` sub-route |
| `pages/JurisdictionCompliance/index.js` L24 / L52 | export, plus `MX: "mexico"` |
| `pages/JurisdictionStatutory/index.js` | export only. Its map is derived from the compliance map (L36), so `MX` appears automatically |
| `pages/ReportTemplates/index.js` L63 | export, plus `MX: "mexico"` |
| `service/superAdminService.js` (after L197) | an `MX_SA` block with every §6 endpoint |
| `pages/TestCertificationPage.jsx` L31 | an MX option with `fixturesPath` pointing to `mx_golden/README.md` |
| `pages/EngineFallbackDefaultsPage.jsx` L37 | `{ code: "MX", name: "Mexico" }` |

---

## 3. State ISN accordion (CDMX only)

- **Clone, don't generalise.** `components/jurisdiction/australia/state/` hard-codes `"AU"` (`AUStateAccordionWorkspace.jsx` L30/L97, `AUStateAccordionRow.jsx` L162). Generalising it would change AU behaviour (rule 8).
- **Create** in `components/jurisdiction/mexico/state/`:
  - `mxStateCodes.js`: `MX_ISN_STATE_CODES = ["CDMX"]` and names. Other states are added only as new Draft packs after you confirm them.
  - `MXStateAccordionWorkspace.jsx`: loads the `MX-ISN-<STATE>-2026` packs with `country:"MX"` and `state`.
  - `MXStateAccordionRow.jsx`: the ISN, source-evidence and version-audit sub-tabs. It reuses `USStateVersionAuditSection` and `USStateSourceEvidenceNote`, as AU does.
  - `MXStateIsnTab.jsx`.
- **Unsupported states are shown, not hidden** (MX-045). The accordion lists all 32 federal entities. Every state without a pack shows **"Not supported — payroll for employees working here is BLOCKED"**, and no "create pack" action is offered except for a state you have confirmed.
- **Backend:** `GET /isn-states` returns, for each of the 32 entities: whether a pack exists, its status, its row count, the readiness row (`OTHER_STATE_PAYROLL`, `legal_status`) and the source status.

---

## 4. Report templates and filing calendar

**Report templates.** `backend/scripts/seed_statutory_report_templates.py` gains `seed_mexico(db)`, called from `run()` (L149). It follows the existing `_seed_template` signature (L64) and AU's per-state pattern (L559–563).
- **Lifecycle:** all templates are Draft. Non-Draft templates are skipped (L86–92), and `template_activation_refusal` stays refused in Phase 2. Templates go live with the outputs they describe, in Phases 6–10.
- **The templates:** the 18 templates of plan v1.1 §5. `MX-ISN-RETURN-CDMX` is the only ISN return template, with `state="CDMX"`.
- **Components:**
  - `REGISTER`, `EMPLOYER-COST` and `JOURNAL` get components whose fields bind to existing payslip columns.
  - Every template whose data does not exist yet (CFDI, IDSE, SUA, SIPARE, PTU, finiquito, annual ISR) is seeded with `components=[]` and a description saying which phase fills it.

**Filing calendar.** Entries are added through `service.upsert_filing_calendar_entry(FilingCalendarUpsert(...))` (service L11178), using the IN L211–225 and HK L2064–2078 pattern.
- **Possible entries:**
  - ISR withholding remittance, monthly, due on the 17th (spec §4, MX-011; S5);
  - IMSS/INFONAVIT bimonthly payment (S12/S16);
  - CDMX ISN monthly (S22);
  - aguinaldo before 20 December (S20/S26);
  - PTU by 30 May for companies (S21);
  - work-risk premium filing in February (S14).
- **The open question is the exact due-date rules** (Q4). The S-codes above name the source for each date.
- **Every due date** is transcribed only from its saved source. Until that source is saved and VERIFIED, the entry is **not seeded**. The calendar only ever shows certified dates, so the seed is partial by design.

---

## 5. Tables and migration

**One migration**, `mx_foundation_m1`. That name goes in the docstring title; the filename follows the autogen-slug convention.
- **Chain:** `down_revision` is the current single head `f4b8d2a6c9e1`. Phases 0 and 1 add no migrations.
- **Idempotent from day one:** every `create_table` / `create_index` sits behind `_has_table` / `_has_index` guards (the `74aeb450aeee_*.py` L49–58 style). NL's migrations had to be repaired afterwards (`08f0f142574e`).

| Table | Columns (plan v1.1 §5) | Additions, following the NL precedent |
|---|---|---|
| `payroll_mx_earning_classifications` | id, organization_id (NULL = canonical), earning_code, label, version, effective_from, effective_to, isr_treatment (TAXABLE/EXEMPT/PARTIAL), isr_exempt_rule_key, sbc_treatment (FIXED/VARIABLE/EXCLUDED), sbc_exclusion_condition, infonavit_included, isn_default_included, isn_state_overrides (JSON), ptu_wage_base_included, cfdi_node_type (PERCEPCION/DEDUCCION/OTRO_PAGO/SEPARACION), cfdi_concept_code, status, source_document_id, approved_by_id, created_by_id, created_at, updated_at | `sha256` (as `PayrollNlEarningClassification`). CheckConstraints on every enum. `UniqueConstraint(organization_id, earning_code, effective_from)`. Index `(organization_id, earning_code, effective_from)`. Status values ACTIVE / SUPERSEDED / ARCHIVED (NL). |
| `payroll_mx_cfdi_schema_releases` | id, cfdi_version, complement_version, revision, xsd_checksum, catalog_release, pac_validation_version, source_document_id, status, approved_by_id, created_by_id, created_at, updated_at | status Draft / Approved / Active / Superseded, with a check constraint |
| `payroll_mx_cfdi_catalog_entries` | id, schema_release_id (FK), catalog_name, code, description, valid_from, valid_to, attributes (JSON) | `UniqueConstraint(schema_release_id, catalog_name, code, valid_from)` |

**Models:** `PayrollMxEarningClassification`, `PayrollMxCfdiSchemaRelease` and `PayrollMxCfdiCatalogEntry` in `models.py`, after the NL block (around L9021).

**Migration tests:**
- **New `tests/test_mexico_migrations.py`** (mirrors `test_netherlands_migrations.py`):
  - the MX chain is linear;
  - every FK target exists;
  - `payroll_mx_*` models and migration tables match in both directions;
  - every op is guarded.
- **`test_migration_idempotency.py`:** `_GUARDED` gains the revision; the migration is applied twice on SQLite.
- **`test_alembic_metadata.py`:** the head string changes in two places (L183, L195), the revision count goes 196 → 197 (L229), plus the comment block.
- **`test_model_tables_have_migrations.py`:** passes unchanged, because every table has a literal `create_table("payroll_mx_…"`.

**Earning-classification governance** (MX-005, MX-006):
- Rows are versioned, never edited in place. A change creates a new row (new `effective_from`) and the old row becomes SUPERSEDED.
- A canonical row (org NULL) needs a second Super Admin to approve it. Org overrides are org-scoped.
- **No canonical classification codes are seeded in Phase 2.** The SAT payroll concept catalogs (Percepción / Deducción / OtroPago codes) need their own source (Q3).

---

## 6. `mexico_router.py` endpoints

All endpoints are Super Admin only. Org-scoped data needs an explicit `org_id` (there is no default organisation). Pack content is read-only.

| Method | Path | Purpose | Notes |
|---|---|---|---|
| GET | `/organizations` | MX organisations | NL L-pattern |
| GET | `/employees?org_id=` | MX employees of one organisation | 422 without `org_id`, 404 for an unknown org |
| GET | `/isr-tariffs?on=` | MX_ISR_TARIFF rows of the pack in force on `on` (default: today **for display only** — the label says which date was used) | read-only, carries `[PENDING G1]` and sources |
| GET | `/uma-min-wage?on=` | UMA, subsidy, minimum wages, ZLFN list | read-only |
| GET | `/imss-branches?on=` | IMSS branches and the SBC cap | read-only |
| GET | `/ceav-schedule` | the 2026 seeded bands, plus the full 2023–2030 content schedule (flagged content-only) | read-only |
| GET / POST | `/earning-classifications` | list (`org_id` optional; canonical when absent), create a new version | four-eyes approve via a POST on `/{id}/approve` |
| POST | `/earning-classifications/{id}/approve` | a second Super Admin approves | refused for the creator |
| GET / POST | `/cfdi-catalogs` | schema releases and entries | releases Draft only |
| PUT | `/cfdi-catalogs/{id}/{action}` | `submit` / `approve` / `activate` / `supersede` | four-eyes. **`activate` is refused in Phase 2**, because pinning a release needs the Phase 7 PAC validation |
| GET | `/isn-states` | the 32 entities with pack and readiness state (§3) | read-only |
| GET | `/readiness` | G1–G8 (existing) | unchanged |
| GET | `/packs/{pack_id}/activation-readiness` | the §1b checklist, every condition with met/unmet and the reason | the UI's "why can't I activate" panel |

**Moved to Phase 3 (Q1):** `GET/POST /employer-profile` and `GET /employer-profile/readiness`. Their table (`payroll_mx_employer_profiles`) is created by `mx_employer_m2` in Phase 3.

`mexico_schemas.py` gains camelCase request and response models for every route.

---

## 7. Files: modify / create

**Backend, modify:**
- `app/modules/payroll/service.py`: the eight lines in §1a.
- `app/modules/payroll/mexico_service.py`:
  - `mx_activation_evidence_refusal` (§1b);
  - classification and catalog services;
  - `statutory_editors` returns the real editors of a pack's rows, as HK and SA do;
  - `template_activation_refusal` stays refused.
- `app/modules/payroll/mexico_router.py` and `mexico_schemas.py`: §6.
- `app/modules/payroll/models.py`: three models (§5).
- `scripts/seed_statutory_report_templates.py`: `seed_mexico` (§4).
- `tests/test_alembic_metadata.py` and `tests/test_migration_idempotency.py`: as in §5.

**Backend, create:**
- `alembic/versions/<rev>_mx_foundation_m1.py`
- `tests/fixtures/mx_golden/README.md` (no cases)
- `tests/test_mexico_activation_gates.py`
- `tests/test_mexico_router.py`
- `tests/test_mexico_classifications.py`
- `tests/test_mexico_report_templates.py`
- `tests/test_mexico_migrations.py`

**Frontend:** §2a, §2c and §3.

**Docs:** `docs/mexico/MEXICO_PHASE_2_IMPLEMENTATION_REPORT.md`.

---

## 8. Tests, and proof that other jurisdictions are unaffected

**Mexico:**
- **Activation gates:** one test per §1b gate, plus the hotfix path, plus "the real seeded pack is refused today".
- **Router:**
  - Super Admin only; explicit `org_id`; read-only content;
  - "Awaiting transcription" while content is empty;
  - `on=` selects the January or February rows of a synthetic fixture pack.
- **Classifications:**
  - versioning (the old row is superseded, never mutated) and four-eyes;
  - the enum constraints;
  - historical lookup by date (MX-006).
- **CFDI catalogs:** lifecycle, four-eyes, and `activate` refused.
- **Report templates:**
  - every MX template is seeded Draft and idempotent;
  - only CDMX has an ISN template;
  - template activation is refused.
- **Filing calendar:** an entry is seeded only when its source is VERIFIED.
- **Migration tests:** the §5 list.

**Other jurisdictions:**
1. **Tuple-literal tests.** Each governance tuple in §1a equals its current value plus `"MX"`, and nothing else changes. These follow the Phase 1 `_VALIDATION_ENABLED_COUNTRIES` test.
2. **The full backend suite** `pytest tests/` (detached run, as before). The pass count must not drop; only the known OOS-4 HK failure is allowed.
3. **Frontend checks:**
   - `npm run build`;
   - `npm run lint`, with no new errors over the current 184 baseline. Lint is what catches a missing `App.jsx` import, which vite build does not (the NL blank-page incident).
4. **Real-browser check** (browser-first lesson):
   - **Mexico screens:** Mexico compliance, statutory and report-template pages (national and `/CDMX`), the State ISN accordion with an unsupported state shown as BLOCKED, and the readiness and activation-readiness panels.
   - **Regression screens:** the NL and AU compliance pages and the AU state accordion still render.
   - Screenshots are inspected and saved to `docs/mexico/phase2-evidence/`.
5. **AU state accordion:** untouched (cloned, not generalised). A `git diff --stat` in the report proves no AU file changed.

---

## 9. Questions

- **Q1. Phase 3 items listed under Phase 2.**
  - **The problem:** plan v1.1 §5 lists `GET/POST /employer-profile`, `GET /employer-profile/readiness` and the Employer tab in Phase 2, but their table (`payroll_mx_employer_profiles`) is created in Phase 3.
  - **Proposal:** move all three to Phase 3 and correct plan v1.1 §5.
  - **Alternative:** stub them in Phase 2 with a "not configured" response.
- **Q2. What the activation gate requires** (§1b), all **on top of** the NL-style generic gates:
  - (a) a G1 human review on every cited `SourceArtifact`, by someone other than the activator;
  - (b) refusing while any `[PENDING G2]` parameter is present;
  - (c) a pack-bound golden PASS (the HK precedent).

  **Decision needed:** confirm all three. Note that (b) means the national pack cannot activate until G2 settles the CEAV lowest-band reference. If you'd rather allow activation and block only the affected ZLFN employees in the engine (decision 4), drop (b).
- **Q3. Source for the earning-classification codes and CFDI catalogs.**
  - **The problem:** the SAT payroll catalogs (c_TipoPercepcion, c_TipoDeduccion, c_TipoOtroPago, and so on) and the Nómina 1.2 XSD are not in S1–S27. S4 is only the CFDI landing page.
  - **The question:** add them as **S28** (the SAT catalog workbook for Complemento de Nómina 1.2, plus its XSD) so the canonical classification codes can be seeded, or keep Phase 2 at the editor and data model only, with no canonical codes?
  - **Recommendation:** add S28. Until it arrives, Phase 2 ships the editor with no canonical rows.
- **Q4. Filing-calendar dates.**
  - **The problem:** each date needs its own saved source. The ISR 17th (S5) and the IMSS/INFONAVIT and work-risk dates (S12/S14/S16) are Batch B sources.
  - **The question:** should those Batch B files move up so the Phase 2 calendar isn't nearly empty, or is a partial calendar acceptable?
- **Q5. Display date on the read-only tabs.**
  - **The problem:** `?on=` needs a default, and today's date would be the only server-date use in Mexico code. It is display-only and labelled.
  - **The question:** acceptable, or should the UI require an explicit date, defaulting to the pack's `effective_from`?
  - **Recommendation:** the explicit default. It removes the only server-date read.


---

## 10. Answers and changes from the user's review (2026-10-15). These take precedence over §1–§9.

**Answers to the §9 questions:**
- **Q1:** the employer-profile endpoints, their readiness view and the Employer tab move to **Phase 3**. Plan v1.1 §5 is corrected.
- **Q2:** gates **(a)** (G1 human review by a non-activator) and **(c)** (pack-bound golden PASS) are kept. **(b) is dropped:** a [PENDING G2] parameter never blocks national activation, because G2 needs parallel-run output and go-live is already gated by the registry's G1–G8. The engine blocks only the affected ZLFN employees (decision 4). The pending parameter shows as a **warning** in the activation-readiness panel.
- **Q3:** **S28** (the SAT Complemento de Nómina 1.2 catalog workbook plus `nomina12.xsd`) is added to the addendum and the fetch list. The classification editor ships with **no canonical rows** until S28 is VERIFIED.
- **Q4:** due-date rules are looked for in the Batch A primary law first: LISR Art. 96 (S24), LSS Arts. 39 and 74 (S10), Ley del INFONAVIT Art. 35 (S27), LFT Arts. 87 and 122 (S26) and the current CDMX Fiscal Code (S22). Each rule must be confirmed from the saved text, and anything not found stays unseeded. Batch B is not pulled forward.
- **Q5:** every content view takes an explicit date, defaulting to the pack's `effective_from` and **never today**. The date is shown prominently with a picker.

**Plan changes:**
1. **Classification lifecycle.** Classifications move DRAFT → ACTIVE, then SUPERSEDED or ARCHIVED. A canonical row is never live until a second Super Admin approves it.
2. **Uniqueness.** `UniqueConstraint(organization_id, earning_code, effective_from)` is replaced by two partial unique indexes: one where `organization_id IS NULL`, one where it `IS NOT NULL`, each with a matching `sqlite_where`, as ContributionRate does. A test proves a duplicate canonical row is refused.
3. **Gate 1b-1 compares exactly.** The pack's content must match the content module exactly: every expected row present, 11 brackets per ISR period, and no extras.
