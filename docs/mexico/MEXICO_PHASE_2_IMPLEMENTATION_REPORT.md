# Mexico (MX) — Phase 2 Implementation Report

**Scope:** Super Admin (compliance configuration, version activation, report templates, state ISN)
**Spec:** ZP-MX-ENG-001 v1.0
**Plan:** `MEXICO_PHASE_2_PLAN.md`; §10 holds the user's answers and changes, which take precedence.
**Branch:** `nikhil`. The work is staged only; the user commits.
**Date:** 2026-10-15

Nothing that calculates money or activates a pack goes live in this phase:
- Every Mexico content table is still empty, and no statutory value was transcribed.
- Both Mexico packs remain Draft.
- Activation is now a gate-based check. It cannot succeed until Phase 1 values, the human G1 review and the Phase 5 golden vectors exist.

---

## 1. Version activation

### Shared opt-ins (`backend/app/modules/payroll/service.py`)

| Line | Constant / gate | Change |
|---|---|---|
| L8513 | `_GATED_PACK_COUNTRY_NAMES` | adds `"MX": "Mexico"` |
| L8516 | `_APPROVER_NOT_ACTIVATOR_COUNTRIES` | adds `"MX"` |
| L8519 | `_SELF_APPROVAL_REFUSED_COUNTRIES` | adds `"MX"` |
| L8523 | `_REFUSAL_AUDIT_COUNTRIES` | adds `"MX"` |
| L8530 | `_PACK_TRANSITION_GRAPH_COUNTRIES` | adds `"MX"` |
| L8677 | evidence gate | adds `"MX"` |
| L8721 | strict golden-PASS gate | adds `"MX"` |
| L19292 `_GOLDEN_FIXTURES_DIR_BY_COUNTRY` | golden fixtures map | adds `"MX": "mx_golden"` |
| `_REPORT_COMPONENTS_BY_TYPE` | report component allow-list | adds `MX_REGISTER`, `MX_EMPLOYER_COST` and `MX_JOURNAL` |

**Hook call site (L8797–8807).** The `pack_activation_refusal` hook now receives `actor_id`, but **only when the hook function declares that parameter**. The Mexico hook needs it to refuse an activator who was also the G1 reviewer. The HK, SA and NL hooks keep their exact `(db, pack)` call, and a test pins this.

### The Mexico gates (`mexico_service.activation_checks`)

They run in order on the normal and the hotfix path. The first unmet gate refuses.

1. **Content present and exact** (review change 3):
   - The pack's rows, as value signatures, must equal the rows `mexico_content` defines for the pack window, as a multiset. No row may be missing and no extra row may be present.
   - Every required national parameter must exist, and there must be exactly **11** Art. 96 brackets for each of the 5 periods.
   - A state ISN pack must carry `mx_isn_rate_pct`.
2. **Every row linked to a hashed source:** each row has a `source_document_id`, and its `SourceArtifact` has a URL, a SHA-256 and a saved file.
3. **G1 human review by a non-activator:** every cited artifact must be reviewer-approved, and the reviewer may not be the activator.
4. **Pack-bound golden PASS:** every `mx_golden` vector inside the pack window must reproduce with **this pack's own rows** (the shared `run_pack_golden_vectors`, the SG/HK precedent).

**[PENDING G2] is a warning only (Q2 b dropped).** `activation_readiness` shows it under `warnings`, and it never blocks.

### Why activation is impossible in practice today

| Gate | State now |
|---|---|
| 1 | Every content table is empty. |
| 2 | No VERIFIED source exists, so no artifact is linked. |
| 3 | No artifact has been reviewed. |
| 4 | `tests/fixtures/mx_golden/` has no cases. Any case would FAIL anyway, because the engine blocks. |
| Shared gates | The transition graph refuses Draft → Active, and the latest MX certification run is not PASS. |

The real seeded packs report **4 / 4 checks unmet**, as both the browser and the tests show.

### Seed change
- `seed_mexico_canonical_packs.py` links each pack's primary source: S2 for the national pack, S22 for CDMX.
- That link exists only once the source is VERIFIED and cited; today it is None. The shared evidence gate requires it.

---

## 2. Data model and migration

**Models:** `models.py` gains three classes at the end of the file:
- `PayrollMxEarningClassification`, whose status runs DRAFT → ACTIVE → SUPERSEDED/ARCHIVED, with check constraints on every enum and on the effective window. Review change 2: **two partial unique indexes**:
  - `uq_mx_earn_canonical_code_eff` on (code, effective_from) WHERE `organization_id IS NULL`;
  - `uq_mx_earn_org_code_eff` on (org, code, effective_from) WHERE `organization_id IS NOT NULL`;
  - each with a matching `postgresql_where` and `sqlite_where`.
- `PayrollMxCfdiSchemaRelease`.
- `PayrollMxCfdiCatalogEntry`.

**Migration:** `alembic/versions/5d2c8f1a7b3e_mx_foundation_m1.py`, with `down_revision` `f4b8d2a6c9e1`, which leaves a single head `5d2c8f1a7b3e`.
- Every create is guarded by `_has_table` / `_has_index`, and every drop by `_has_table`.
- It is additive only.

**Migration test updates:**
- `test_alembic_metadata.py`: head `5d2c8f1a7b3e` in two places, and the revision count 196 → 197.
- `test_migration_idempotency.py`: added to `_GUARDED` and to the literal-`create_table` check.
- New `test_mexico_migrations.py`:
  - a linear chain, and every create guarded;
  - model and migration tables are the same;
  - upgrade twice, then downgrade, restores the exact table set;
  - the migrated partial index refuses a duplicate canonical row.

---

## 3. Services and API

### `mexico_service.py`

**Activation:** `activation_checks` and `activation_readiness`.

**Content and packs:**
- `pack_golden_check`.
- `content_view(family, on, pack_row_id)`, read-only. `on` is explicit; when it is omitted the pack's `effective_from` is used, **never today** (Q5).
- `list_packs`.
- `isn_states`: all 32 federal entities with their pack, readiness and SUPPORTED/BLOCKED state (MX-045).

**Classifications** (create / approve / archive / list / `classification_in_force`):
- **A new row is DRAFT and never live** (review change 1). A second Super Admin approves it.
- A canonical approval also needs its SAT concept code in an approved catalog release. **That means S28, so no canonical row can go live today** (Q3).
- An approved newer version SUPERSEDES the previous one. Its window closes the day before, and historical lookups still return it (MX-006).
- Every axis is validated explicitly:
  - an EXEMPT or PARTIAL ISR treatment needs a named rule (MX-009);
  - an EXCLUDED SBC treatment needs its condition (MX-022);
  - the INFONAVIT, ISN and PTU axes are booleans with no default (MX-005);
  - ISN state overrides must use known entity codes.

**CFDI releases:** Draft → In Review → Approved, with four-eyes. Entries are frozen once a release leaves Draft. **Activate is refused** until the Phase 7 PAC validation.

**Other hooks:**
- `statutory_editors` now returns the real editors from the audit trail.
- The template-activation refusal stays in place.
- Every refusal is audited.

### `mexico_router.py`

Every route is Super Admin only:
- `GET /readiness`
- `GET /organizations`, `GET /employees?org_id=` (explicit organisation)
- `GET /packs`, `GET /packs/{id}/activation-readiness`
- `GET /isr-tariffs`, `/uma-min-wage`, `/imss-branches`, `/ceav-schedule`, `/infonavit`, `/benefits-workweek` (each takes `?on=&pack_id=`)
- `GET /isn-states`
- `GET/POST /earning-classifications`, `POST /earning-classifications/{id}/approve`, `POST /earning-classifications/{id}/archive`
- `GET/POST /cfdi-catalogs`, `GET/POST /cfdi-catalogs/{id}/entries`, `PUT /cfdi-catalogs/{id}/{action}`

**Moved to Phase 3 (Q1):** the employer-profile routes and the Employer tab.

### `mexico_schemas.py`
- camelCase request models.
- The classification create model has **no defaults on any axis**, so a missing axis is a 422.

---

## 4. Report templates and filing calendar

**Templates.** `scripts/seed_statutory_report_templates.py` gains `seed_mexico`, called from `run()` after HK.
- It seeds **18 Draft templates**, matching plan v1.1 §5: 17 national plus `MX-ISN-RETURN-CDMX` (`jurisdiction_state="CDMX"`).
- Only REGISTER, EMPLOYER-COST and JOURNAL have components today, bound to existing payslip columns. Every other template is a component-less shell whose description names the phase that fills it.
- Template activation stays refused.

**Filing calendar.** Entries come only from `mexico_content.MX_FILING_CALENDAR`, through `upsert_filing_calendar_entry`.
- That content holds `FilingRule` rows, each citing its source and article.
- An entry is seeded **only when the rule's source is VERIFIED**.
- **Q4 result:**
  - The primary-law sources to search are LISR Art. 96 (S24), LSS Arts. 39 and 74 (S10), Ley del INFONAVIT Art. 35 (S27), LFT Arts. 87 and 122 (S26) and the current CDMX Fiscal Code (S22).
  - **None of them is in `docs/mexico/sources/` yet**, so no due-date rule could be confirmed from saved text.
  - `MX_FILING_CALENDAR` is therefore empty and **0 calendar entries** are seeded. Batch B was not pulled forward.

---

## 5. Frontend

**Created:**
- `pages/JurisdictionCompliance/MXCompliancePage.jsx`: organisation picker (NL pattern) plus state routing (AU pattern).
- `pages/JurisdictionStatutory/MXStatutoryPage.jsx`
- `pages/ReportTemplates/MXReportTemplatesPage.jsx`
- `config/jurisdictions/mexicoComplianceConfig.jsx`: 12 extra tabs. `hiddenTabs: ["rates","slabs"]`, and no TaxabilityMatrix tab.
- `components/jurisdiction/mexico/`:
  - `mxShared.jsx`, which contains `OnDateBar` (a prominent "Law in force on …" bar with a picker; with no date chosen it uses the pack's effective-from, and it says the server date is never used), `AwaitingTranscription`, `[PENDING G1/G2]` flags and source cells;
  - `MXIsrTariffsTab`, `MXSubsidyUmaTab`, `MXMinimumWageTab`, `MXImssCeavTab`, `MXInfonavitTab`, `MXBenefitsWorkweekTab`;
  - `MXEarningClassificationTab` (multi-axis, DRAFT plus a second-admin approval);
  - `MXCfdiCatalogTab`;
  - `MXReadinessGatesTab` (G1–G8 plus a per-pack activation checklist and warnings).
- `components/jurisdiction/mexico/state/MXStateAccordionWorkspace.jsx`, `MXStateAccordionRow.jsx` and `MXStateIsnTab.jsx`, **cloned from AU, not generalised**.
  - All 32 entities are listed. CDMX has its pack; every other state shows "Not supported — payroll BLOCKED" with no create action.

**Modified:**
- `App.jsx`: 3 imports and 6 routes (each page plus its `/:jurisdiction` sub-route).
- `pages/JurisdictionCompliance/index.js` and `pages/ReportTemplates/index.js`: export plus `MX: "mexico"`.
- `pages/JurisdictionStatutory/index.js`: export only (its map is derived from the compliance map).
- `service/superAdminService.js`: the `MX_SA` block.
- `pages/TestCertificationPage.jsx` and `pages/EngineFallbackDefaultsPage.jsx`: a Mexico entry each.

---

## 6. Tests and results

### Mexico backend tests

| File | Tests | Covers |
|---|---|---|
| `test_mexico_activation_gates.py` | 19 | Each gate refuses on its own (missing row, extra row, 10 brackets, empty content, unlinked row, artifact without file, unreviewed source, reviewer = activator, no vector, failing vector). A pack meeting every gate is accepted, and **the governed path activates it with four-eyes; the approver cannot**. G2 is a warning. The real seeded packs are refused (4/4 unmet). The hotfix path runs the same gates. The actor reaches only hooks that declare it. The governance tuples equal their previous value plus "MX". |
| `test_mexico_classifications.py` | 23 | Draft is never live; maker-checker; a canonical row needs a catalog code; supersede and history; date-ordered approval; an org row overrides the catalogue; 7 axis-validation cases; archive rules; **a duplicate canonical row is refused by the database**; org/canonical scope independence; 5 check constraints; CFDI release lifecycle. |
| `test_mexico_router.py` | 21 | Super Admin only (7 routes); explicit organisation; **the default date is the pack's effective-from**; an explicit date selects the January or February row; awaiting transcription; 32 ISN entities; activation readiness; four-eyes over HTTP; no axis defaults (422); CFDI activation refused over HTTP. |
| `test_mexico_report_templates.py` | 6 | 18 Draft templates, CDMX-only ISN, components only on the three templates with data, idempotent, activation refused; no calendar entry without a VERIFIED rule; a VERIFIED rule gives 12 monthly or 6 bimonthly entries. |
| `test_mexico_migrations.py` | 5 | Section 2. |

| `test_mexico_approval.py` | 7 | **Approval gate** (open item 5). An empty Draft pack can no longer reach Approved, and the refusal is audited. A Draft pack is refused even with exact content. A QA pack with empty content is refused by gate 1, and one with an unlinked row by gate 2. A QA pack with exact, linked content is approved, with no auto-advance. The hook is declared for MX only, takes a named `actor_id` and no `**kwargs`. **OOS-5 is pinned:** an NL Draft pack still auto-advances to Approved. |

**Exact refusal reasons.** The relaxed Phase 1 test (`test_mexico_seed.py::test_governed_activation_of_a_seeded_pack_is_refused`) only asserts *some* refusal, because the shared transition graph now refuses Draft → Active first. **Mexico's exact refusal reasons are asserted by the per-gate tests**: `test_mexico_activation_gates.py` matches each gate's exact wording, and `test_mexico_approval.py` matches the approval gate's.

Phase 1 tests changed to match Phase 2:
- The activation-refused test now accepts any refusal, because the transition graph refuses first.
- The AST check now forbids only **writes** of `"Active"`.
- S1–S28.
- The `phase` field is now 2.

**Mexico total:** 149 tests (9 value tests skipped pending transcription).

**Full backend suite** (`pytest tests/`, detached run, after the fixes below): **1 failed, 6013 passed, 48 skipped, 2 xfailed** (54 min).

**Final run, on the merged tree** (`e77ff16`, after `origin/main` was merged in, plus the approval gate): **1 failed, 6074 passed, 48 skipped, 2 xfailed** (23 min, system Python 3.11). The single failure is the known OOS-4. The +61 tests over the earlier run are the 7 Mexico approval tests plus the NL Phase 13 tests that came in with `main`.
- *Note:* in a new shell session, `python` resolved to `D:\zoiko_payroll_platform\.venv`, which has no `celery`, so 3 files failed at collection. The suite was re-run with the system interpreter used by every earlier run.
- **After the merge:** the frontend undefined-name check passes (485 files), lint is unchanged (184 errors), the build passes, and the browser acceptance gives 37/37 plus the approve re-check 3/3.
- Against Phase 1 tooling (5939 passed): +74 new Mexico tests.
- The single failure is the known, pre-existing **OOS-4** (HK matrix CSV, the same 10 findings).

**First full run: 4 failed / 6010 passed.**
- **OOS-4 (known):** the HK matrix failure, as before.
- **Three failures caused by this phase's shared changes.** Each was fixed, and the suite was re-run:
  1. **`test_alembic_migration_manifest`.** The new migration must be registered. I ran `python -m scripts.update_migration_manifest`; `alembic/MIGRATIONS_MANIFEST.txt` gains exactly one line, for `5d2c8f1a7b3e`.
  2. **`test_singapore_phase60_remediation::test_f2_opt_in_is_singapore_only`.** It pins `_APPROVER_NOT_ACTIVATOR_COUNTRIES` to the previous tuple. I updated it to the tuple plus `"MX"`, and its docstring names Mexico. This is the same pattern NL, SA and CH followed when they opted in.
  3. **`test_platform_shared_helper_snapshots::test_sg_statutory_summary`.** Singapore's statutory summary derives two strings from shared state: the D3 opt-in list, which is the union of the governance tuples, and the code-head evidence. I re-recorded that one key (`PLATFORM_SNAPSHOT_RECORD=1`, throwaway SQLite). The diff is exactly:
     - `"SG_ONLY (plus per-country opt-ins: CH, HK, NL, SA, SE)"` → `"… CH, HK, MX, NL, SA, SE)"`;
     - `code ['4c5d6e7f8a9b']` → `code ['5d2c8f1a7b3e']` (two lines);
     - the key's recorded date.

     No other key changed.

**Frontend:**
- `npm run build` passes.
- `npm run lint` across the repo: **184 errors, unchanged from the baseline**. Warnings go from 184 to 195; the 11 new ones are all react-refresh/only-export-components on `mxShared.jsx`, the same pattern as `nlShared.jsx`.
- Two `set-state-in-effect` errors that the AU originals also have were **not** copied into the Mexico clones; both were fixed before commit.

### Real-browser check: 37 / 37

**Setup:**
- Installed Chrome (Playwright, headless) against the `vite build` bundle served by `vite preview`.
- The backend ran on a **throwaway SQLite** database (the URL was forced and the setup refuses anything else).
- It was seeded with the **real, empty** Mexico Draft packs, the 18 templates, the NL packs for regression, and two Super Admins.

**What the checks prove:**
- Every check asserts positive on-screen content.
- The only failed requests are the **four intended refusals**, all HTTP 400:
  - the creator approving their own classification;
  - the registrant approving their own CFDI release;
  - CFDI activation before Phase 7;
  - a canonical approval without S28.
- There are no page errors and no other console errors.
- Every Mexico pack is still Draft at the end.

**Where to find it:**
- `docs/mexico/phase2-evidence/RESULTS.md` (the table) and 25 full-page screenshots, inspected by eye.
- `docs/mexico/phase2-evidence/harness/` (the scripts).

| Screenshot | Shows |
|---|---|
| 01 | Compliance landing with Mexico |
| 02 | Mexico workspace and its 12 tabs |
| 03–08 | The six read-only families: "Law in force on 2026-01-01 · Date from the pack's effective-from · The server date is never used" and **Awaiting transcription** |
| 09 | The picker set to 2026-02-01 ("the date you chose") |
| 10–11 | The multi-axis classification form; draft saved; **"You created this classification — a different Super Admin must approve it"** |
| 12 | CFDI release In Review; the registrant's approval refused |
| 13–14 | State ISN: **"32 federal entities · 1 with an ISN pack · 31 unsupported (payroll BLOCKED)"**; the CDMX Draft pack is awaiting transcription; Jalisco is not supported |
| 15 | Tests tab (`mx_golden`) |
| 16 | Readiness: G1–G8 OPEN, and both packs **"Cannot be activated yet."** with all four reasons |
| 17–18 | The second Super Admin approves the release, but activation is refused (Phase 7); a canonical approval is refused (S28 not VERIFIED) |
| 19–23 | The `/compliance/mexico/CDMX` route, statutory rates, the report-template list (17 Drafts) and `/CDMX` (the ISN return), engine defaults |
| 24–25 | **Regression:** NL workspace with its tabs and AU workspace render unchanged |
| 26 | **Re-check after the approval gate (2026-10-16), 3/3:** the pack-header **Approve** on the empty MX Draft pack is refused ("…move it through In Review to QA first…"); the pack stays Draft with no approver; the only failed request is that `PUT /policies/1/approve` 400. Script: `harness/approve_check.py`. |

**Finding from the browser pass:**
- **What happened.** In the first run my script clicked the pack-header **Approve** button by mistake, and the shared `set_jurisdiction_pack_approver` moved the empty MX Draft pack straight to **Approved**.
- **Why.** That function auto-advances Draft → Approved for any Super Admin who did not edit the pack. This is existing behaviour for every country, NL included; it is not new code.
- **Impact.** It is harmless here: an Approved empty pack still fails all four Mexico gates and the golden-run gate.
- **What I did.** I noted it rather than changing shared behaviour. The check that had passed for the wrong reason was rewritten: clicks are scoped to the table row, and each refusal is asserted by its exact wording. The run then re-ran from a fresh database.

---

## 7. Proof other jurisdictions are unaffected

- `git diff --stat` shows no change to `components/jurisdiction/australia/`, `hong_kong_service.py`, `netherlands_service.py` or `saudi_arabia_service.py`.
- **Tuple-literal tests:** each governance tuple is its previous value plus `"MX"`, there are 12 golden directories, and `_CANONICAL_PACK_ONLY_COUNTRIES` is as expected.
- **Hook call compatibility:** HK, SA and NL hook signatures are pinned without `actor_id`.
- **Shared report seed:** the SG full-seed tests (`seed.run()`) pass with the Mexico templates included.
- **Browser regression:** NL and AU pages render with their own tabs.
- **Full backend suite:** 6013 passed; the only failure is the pre-existing OOS-4 (section 6).

---

## 8. Deviations and open items

1. **Text parameters and readiness.** The CEAV G2 reference is text, so it is not a readiness requirement (carried over from Phase 1). Gate 1b-1 still requires every non-text national key.
2. **The `actor_id`-aware hook call** is a small shared change. It is signature-gated, so no other jurisdiction is affected.
3. **`mxStateCodes.js` was not created**, because the in-scope flag comes from `/isn-states`. Plan §3 listed it.
4. **Filing calendar:** no entries, because no Batch A source is saved (Q4).
5. **Draft → Approved auto-advance. Resolved for Mexico only** (user decision, 2026-10-16). This is a new optional, signature-gated hook, `pack_approval_refusal`:
   - **Where it runs:** it is called from `set_jurisdiction_pack_approver` only when the country module declares it (`jurisdiction_hooks.declares`).
   - **What Mexico requires:** its hook refuses approval unless the pack is in **QA** and gates 1 and 2 already hold. A Mexico pack can therefore never be auto-advanced from Draft.
   - **Other countries:** their approver path is unchanged and pinned. The shared defect is logged as **OOS-5**.
   - **Code comment:** the `actor_id` dispatch sites (activation and approval) now explain the signature gating, and that a hook must declare `actor_id` by name and never rely on `**kwargs`.
6. **Large source PDFs in git versus evidence storage:** still open (plan §14).
