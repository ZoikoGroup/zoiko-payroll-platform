# Mexico (MX) — Phase 1 Plan: Statutory Content and Draft Canonical Packs

**Status:** approved 2026-10-15, with the revisions in §6, which take precedence over §0–§5. Step 1 (downloads) is done; I am waiting for the user to supply the files.
**Spec:** ZP-MX-ENG-001 v1.0, §2, §4, §5, §8, §9, §15, §16 and §17.
**Rules covered:** MX-003, MX-004, MX-008, MX-012, MX-013, MX-021, MX-027, MX-028, MX-029 and MX-048, all at content level. The engine is Phase 5.
**Working rules:** branch `nikhil` in the main checkout; I stage, the user commits.

---

## 0. Step 1 — save sources first (condition 1)

The evidence register has 27 sources: S1–S23 from spec §22, whose URLs come from the `.docx` hyperlinks, and S24–S27 from `MEXICO_SPEC_ADDENDUM_SOURCES.md`, pending spec-owner approval.
- Each source is saved byte-for-byte to `docs/mexico/sources/`, under the filename in the user's fetch checklist.
- Its SHA-256 and retrieval time go into `docs/mexico/sources/SOURCES_MANIFEST.csv`. The columns are code, title, url, file, sha256, bytes, retrieved_at, content_type, status and note, plus the document's header version, recorded at step 1.
- For an HTML page, a browser "Save as PDF" is acceptable. The SHA-256 is computed from whatever file is saved.

**Batches:**
- **Batch A** (needed for transcription): S2, S3, S6, S7, S9, S10, S11, S18, the current S22, S24, S25, S26 and S27. Cross-checks: S8, S15, S17, S19 and S20.
- **Batch B** (evidence only, needed before G1): S1, S4, S5, S12, S13, S14, S16, S21 and S23.
- **S28** (Phase 2 dependency, added 2026-10-15): the SAT Complemento de Nómina 1.2 catalog workbook plus `nomina12.xsd`. Files: `S28_SAT_catNomina12.xlsx` (or `.xls` as published) and `S28_SAT_nomina12.xsd`. It gates canonical earning-classification codes only, never a Phase 1 value.

**Download results** (2026-10-15) are in §7. Only S22 could be fetched from this machine, and it is the wrong version. The user supplies the rest.

**Step 1, once files arrive, covers only the files present:**
- hash each one into the manifest;
- verify its title, issuer and reform/publication date from the header;
- S22: confirm the last reform is December 2025 or later and that Art. 158 reads 4%;
- S9: confirm it has the professional minimum-wage table and the ZLFN municipality list;
- S24/S25: record the last-reform dates and confirm they are current for 2026.

**Then stop.** Transcription starts only on the user's "start transcription", possibly for a partial batch.

---

## 1. What is transcribed, and from which saved file

Every value below must be found in a saved source file. **If a value is not in its source, I stop and ask; I never infer it.**

| Content | Source | Placement (no new tables) |
|---|---|---|
| ISR tariffs: 1-day, 7-day, 10-day, 15-day and monthly (Art. 96), 11 brackets each, so 55 rows | **S2** | `TaxSlab`, `rule_type=MX_ISR_TARIFF`, `filing_status`=`DAILY` / `WEEKLY_7` / `DECENAL_10` / `QUINCENAL_15` / `MONTHLY`. Columns: `min_amount`/`max_amount`, `flat_amount`=fixed quota, `rate_pct`=marginal %. |
| Employment subsidy: income ceiling 11,492.66; January 15.59% on the 2025 monthly UMA; February onward 15.02% on the monthly UMA in force; the 30.4 divisor for periods under a month; the multi-month rule; and exclusions | **S3** | `ContributionRate` `mx_subsidy_*`, using row-level `effective_from/to` (Jan 1–31 and Feb 1–Dec 31). Exclusions are stored as text/flag rows only if S3 enumerates them; otherwise I stop and ask. |
| UMA 2025 (daily 113.14, monthly 3,439.46), in force until 31 Jan 2026 | **S7** | `ContributionRate` `mx_uma_daily` / `mx_uma_monthly`, dated 2026-01-01 → 2026-01-31 |
| UMA 2026 (daily 117.31, monthly 3,566.22, annual 42,794.64), from 1 Feb 2026 | **S6** | Same keys plus `mx_uma_annual`, dated 2026-02-01 → 2026-12-31 |
| Minimum wages: general 315.04, ZLFN 440.87, professional table, ZLFN municipality list | **S9** (S8 as a cross-check) | `TaxSlab` `rule_type=MX_MIN_WAGE`, `filing_status`=`GENERAL` / `ZLFN` / professional code. ZLFN municipalities go in a content tuple, and in the seed only if S9 lists them. |
| IMSS branch rates (§8) and the SBC cap of 25 UMA | **S10** (LSS) | `ContributionRate` `mx_imss_*` (each employer/employee split as its own row) and `mx_sbc_max_uma` |
| CEAV employer bands: 2026 seeded, full 2023–2030 schedule in content; employee rate 1.125% | **S11** (+ S10) | **Seeded:** only the 2026 bands go into `MX-PAYROLL-2026`, as `TaxSlab` `rule_type=MX_CEAV_BAND` with `tax_table_number`=2026 and band bounds as multiples plus their unit (SM or UMA) in `assessment_basis`. **Content only:** the full 2023–2030 schedule is kept as dated rows in `mexico_content.py`, and a content test proves year selection by date (MX-029). Later years' packs are seeded from that content when needed. |
| **CEAV lowest-band minimum-wage reference** | decision 4 | `ContributionRate` `mx_ceav_lowest_band_min_wage_ref`, a text value marked **[PENDING G2]**. The content flags it, and the Phase 5 engine blocks only ZLFN employees whose SBC falls in that band. |
| INFONAVIT employer contribution, 5% | **S27** (Ley del INFONAVIT Art. 29; S15 as a cross-check) | `ContributionRate` `mx_infonavit_er` |
| Workweek: 48 h (2026), 46 (2027), 44 (2028), 42 (2029), 40 (2030), and the overtime limits per year | **S18** (S17 as a cross-check) | `TaxSlab` `rule_type=MX_WORKWEEK`, one dated row per year |
| Benefit floors: aguinaldo 15 days, the vacation schedule (12/14/16/18/20 days, then +2 per 5 years), vacation premium 25%, Sunday premium 25% | **S26** (Ley Federal del Trabajo; S19 and S20 as cross-checks) | `ContributionRate` `mx_aguinaldo_min_days`, `mx_vacation_premium_min_pct`, `mx_sunday_premium_min_pct`; `TaxSlab` `rule_type=MX_VACATION_DAYS` |
| CDMX ISN: 4% | **S22** | Separate Draft pack `MX-ISN-CDMX-2026` (`jurisdiction_state="CDMX"`, `parent_pack_id` → national pack) with `ContributionRate` `mx_isn_rate_pct`. `StateLocalProgramReadiness` row `program="OTHER_STATE_PAYROLL"`, with a comment saying it is Mexico ISN (decision 6). |
| S1, S4, S5, S12–S14, S16, S21, S23 | evidence only | `SourceArtifact` rows. No value is transcribed in Phase 1. |

**Every row:**
- carries `source_document_id` → its `SourceArtifact` (URL + SHA-256 of the saved file + `file_path`);
- has `[PENDING G1]` in its label;
- is `needs_g1=True` in `mexico_content.py`;
- lives in a Draft pack.

The `SourceArtifact` upsert is matched by URL + hash, cloned from `seed_hong_kong_canonical_pack.py` L499–510. A changed file therefore creates a new artifact rather than silently rewriting the old one.

---

## 2. Files

**Modify:**
- `backend/app/modules/payroll/engine/countries/mexico_content.py`:
  - pure-data tuples for everything in §1, each row carrying its source code and `needs_g1`;
  - `MX_PARAMETER_KEYS` filled in;
  - pure `*_in_force(as_of)` helpers (NL pattern), each taking an explicit date argument with no default.
- `backend/app/modules/payroll/service.py`: add `"MX"` to `_CANONICAL_PACK_ONLY_COUNTRIES` (L1508).
- `backend/app/modules/payroll/engine/countries/shared.py`: add `"MX"` to `_VALIDATION_ENABLED_COUNTRIES` (L93). This is safe because the MX calculation is blocked anyway, and it makes an empty or partial MX pack fail closed.
- `backend/app/modules/payroll/engine/fallback_registry.py`: one row per required MX key, `attr: "MX_NO_FALLBACK"` (the sentinel defined in `mexico.py`), "NO FALLBACK — a missing row BLOCKS". Also add `"mexico"` to `_MODULES`.
- `backend/tests/test_mexico_scaffolding.py`: update the assertions that pinned the Phase 0 empty `MX_PARAMETER_KEYS`.

**Create:**
- `backend/scripts/seed_mexico_canonical_packs.py`, cloned from `seed_netherlands_canonical_packs.py`:
  - **Draft only.** It refuses to rewrite any pack that is not Draft, with SystemExit.
  - It wholesale-replaces Draft rows, upserts the SourceArtifacts, and creates the registry row once (PLANNED, NOT_OFFERED).
  - It writes an `audit seed` entry.
  - It uses NL's `_require_confirmed_target` guard: the override env var, a TTY and a typed `CONFIRM`.
  - It never sets anything Active.
- `backend/scripts/verify_mexico_sources.py`: the independent automated check (§3). It runs `pdftotext -layout` (or pypdf) over the saved files and compares every transcribed number to the content row by row.
- `docs/mexico/sources/` (the source files plus `SOURCES_MANIFEST.csv`).
- `backend/tests/test_mexico_content.py` (§4).
- `backend/tests/test_mexico_seed.py` (§4).
- `docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md`: for each table, the source file, its SHA-256, the page/article, a transcription and verification sign-off, and any discrepancy found.
- `docs/mexico/MEXICO_PHASE_1_IMPLEMENTATION_REPORT.md`.

**Unchanged:**
- Pack activation stays refused by the Phase 0 hook (condition 7). Phase 2 replaces it with the gate-based check.
- No migrations: everything fits existing tables.

---

## 3. ISR double check (condition 3)

Each of the five Art. 96 tables goes through three independent controls:

1. **Blind second transcription.** A separate agent transcribes the table again from the **saved S2 file**, without seeing my values. A machine diff must be empty. Any disagreement is resolved by re-reading the source page and recorded in the transcription log. If it can't be resolved, I stop and ask.
2. **Machine extraction.** `verify_mexico_sources.py` extracts the numbers from the S2 text layer and compares every bracket (lower, upper, quota, rate) to the content.
   - If the PDF has no usable text layer, I report that and controls 1 and 3 still apply.
3. **Arithmetic tests** in `test_mexico_content.py`, per table:
   - The first lower limit is 0.01.
   - `lower[i] == upper[i-1] + 0.01`. Brackets are contiguous, with no gaps or overlaps.
   - The last bracket is open-ended (`max_amount` NULL, "en adelante").
   - The rates are strictly increasing.
   - `quota[i] == round(quota[i-1] + (upper[i-1] − lower[i-1]) × rate[i-1], 2)`, within ±0.01.
     - Example: **bracket 3's** quota is bracket 2's quota 16.22 + (bracket 2 upper 7,168.51 − bracket 2 lower 844.60) × bracket 2 rate 6.40% = 420.95. *(The original draft mislabelled this as bracket 2; corrected per review change 2.)*
   - The **monthly table equals the spec §4 table** exactly, as a third-source cross-check.

---

## 4. Tests

**`test_mexico_content.py`** (pure, no DB):
- **Condition 3:** bracket continuity and quota consistency for all five ISR tables; monthly ISR equals spec §4.
- **Condition 4, pay date selects law, never server date:**
  - UMA: `uma_in_force(2026-01-31)` gives 113.14 / 3,439.46; `uma_in_force(2026-02-01)` gives 117.31 / 3,566.22 / 42,794.64.
  - Subsidy: January gives 15.59% × the 2025 monthly UMA (= 536.21, *computed from the transcribed values, not hard-coded*); February gives 15.02% × the 2026 monthly UMA.
  - The 25-UMA SBC cap differs between January and February (MX-021).
  - Workweek: `workweek_in_force(2026-12-31)` is 48 h and `workweek_in_force(2027-01-01)` is 46 h.
  - **The helpers have no date default:** `inspect.signature` shows the `as_of` parameter is required.
  - **A guard test** monkeypatches the content module's `date` so that "today" is a different year, and shows the results are unchanged.
- **Condition 5:** `mx_ceav_lowest_band_min_wage_ref` exists, is marked `[PENDING G2]`, and is the only G2-pending parameter.
- **CEAV / MX-029:**
  - 2026 has 8 bands matching spec §9 (3.150 … 7.513%).
  - 2023–2030 are all present.
  - Only the 2026 rows fall inside the 2026 pack window.
- **Provenance:** every row has a source code present in `SOURCES_MANIFEST.csv` and `needs_g1=True`. Every manifest SHA-256 matches the file on disk.

**`test_mexico_seed.py`** (in-memory SQLite):
- **Seeding:**
  - The seed creates the MX national pack and the CDMX ISN pack, both Draft.
  - Every row has a `source_document_id`, and its SourceArtifact has the URL, the SHA-256 and a `file_path`.
  - Every label contains `[PENDING G1]`.
- **Condition 7 — idempotence and safety:**
  - A re-run produces the same row set and counts, with no duplicate SourceArtifacts and one registry row (PLANNED).
  - The seed refuses to touch a non-Draft pack.
  - The guard refuses without the override and confirmation.
  - **Activation is still refused** through the governed path (the Phase 0 hook).
- **Condition 4 through the real resolver:**
  - A test-only Active copy of the seeded pack, existing only in the in-memory DB, goes through `tax_resolver.resolve_tax_configuration`.
  - Calls with `payroll_date` 2026-01-31 and 2026-02-01 return the January and February UMA, subsidy and SBC-cap rows respectively.
  - **No code path sets Active.**
- **Condition 6 — MX slabs never reach the generic progressive-tax path:**
  - `_COUNTRY_CALC["MX"]` is the MX calculator (Phase 0 test, kept).
  - A spy test monkeypatches `shared._calculate_annual_tax` (the generic progressive path) to fail if called. It runs a full `StandardStrategy` calculation with `country="MX"` and the real seeded `MX_*` slabs, and asserts the MX block is raised **and the spy was never called**.
  - Every seeded MX slab `rule_type` starts with `MX_`.

The full `pytest tests/` suite runs before Phase 1 is reported done (detached process, as in Phase 0). The frontend is untouched.

---

## 5. Questions before "go ahead"

- **Q1. Special-pay ISR exemptions (MX-009) have no source in S1–S23.**
  - **The problem:** the exempt limits for aguinaldo, vacation premium, PTU, overtime, Sunday premium and separation pay are in the **Ley del ISR, Art. 93**. The special withholding method is in the **RLISR, Art. 174**. Neither is in the register.
  - **Option A:** add them as **S24 (LISR)** and **S25 (RLISR)**; you'd fetch them with the rest.
  - **Option B:** leave special-pay parameters out of Phase 1 and do them in Phase 5 or 9.
  - **Recommendation:** A.
- **Q2. The labour-law floors rest on PROFEDET explainer pages, not the law.**
  - **The problem:** S19 and S20 (vacations, aguinaldo) are explainers. The primary source is the **Ley Federal del Trabajo** (Arts. 69–71 Sunday premium, 74–75 holidays, 76–80 vacations and premium, 87 aguinaldo, 66–68 overtime).
  - **The question:** add it as **S26**, or transcribe from S19/S20 as the spec's register lists them?
  - **Recommendation:** add the LFT, and keep S19/S20 as cross-checks.
- **Q3. INFONAVIT 5%: same issue.**
  - **The problem:** S15 is a portal page. The primary source is the **Ley del INFONAVIT, Art. 29**.
  - **The question:** add it as **S27**, or accept S15?
- **Q4. Where the CEAV rows for other years live.** Seed only the 2026 bands into `MX-PAYROLL-2026`, and keep the full 2023–2030 schedule as dated rows in `mexico_content.py`, or seed every year into the 2026 pack? (Answered in §6: only 2026 is seeded.)



---

## 6. Revisions from the user's review (2026-10-15). These supersede §0–§5 where they differ.

**Answers to the §5 questions:**
- **Q1–Q3:** add **S24** (LISR Art. 93), **S25** (RLISR Art. 174), **S26** (Ley Federal del Trabajo) and **S27** (Ley del INFONAVIT Art. 29). They are recorded in `docs/mexico/MEXICO_SPEC_ADDENDUM_SOURCES.md` as an extension of the §22 register, pending spec-owner approval. S15, S19 and S20 remain cross-checks only; the primary source wins.
- **Q4:** seed **only the 2026 CEAV bands** into `MX-PAYROLL-2026`. The full 2023–2030 schedule lives as dated rows in `mexico_content.py`, and a content test proves year selection by date (MX-029). Later years' packs are seeded from that content when needed.

**Plan changes:**
1. **Source wins.**
   - If an ISR row fails the quota-arithmetic check but matches S2 exactly, it is recorded as a **documented exception** in the transcription log, and the value is not altered. The quota test carries an explicit exception list, keyed by (period, bracket), whose entries cite the log.
   - **If spec §4 and S2 disagree, stop and ask.** The same rule applies to any spec figure versus its source. *Applied already: S22 vs spec §15, see §7.*
2. **Quota indexing.** The quota test is written as: for bracket `i ≥ 2`, `quota[i] == round(quota[i-1] + (upper[i-1] − lower[i-1]) × rate[i-1], 2)` ±0.01. The worked example above is now correctly labelled bracket 3. A directional test covers bracket 2 explicitly: `quota[2] = round(0 + (844.59 − 0.01) × 1.92%, 2) = 16.22`.
3. **Canonical rows only.** A new test proves that an MX calculation reads only canonical pack rows, never org-synced copies.
   - **Why:** `sync_org_rates_from_canonical` drops row-level dates, which would merge the January and February UMA rows.
   - **How:** an org is given synced/org-scoped MX rows with deliberately wrong values, and the test asserts the resolver returns the canonical rows only (`_CANONICAL_PACK_ONLY_COUNTRIES` path, `service.py` L1582). A second assertion shows that applying extracted rates to an MX org is refused (L503).
4. **Validation-switch blast radius.** A test asserts that adding MX to `shared._VALIDATION_ENABLED_COUNTRIES` changes nothing else: the set equals the previous set plus `{"MX"}` exactly. For each other country it shows `_assert_jurisdiction_ready` behaves exactly as before.
5. **The test-only Active pack** is inserted directly by a fixture (ORM object, `status="Active"`, `db.add`), never through a service function.
   - A test asserts that no production code path sets an MX pack Active: the seed, `mexico_service` and the router never write `status="Active"`.
   - The governed transition path still refuses MX activation (Phase 0 hook), and an AST/grep check over `mexico_*` modules and the seed finds no `"Active"` assignment.
6. **Transcription log** (`MEXICO_PHASE_1_TRANSCRIPTION_LOG.md`): every table gets an empty **"Human G1 reviewer (name / date / verdict)"** column. The blind second transcription is recorded as an engineering control and **does not count as G1**.

---

## 7. Step 1 result — downloads (2026-10-15)

I attempted all 27 sources from this machine (IPv4, 60-second timeout, one retry). Only content that validated was kept: a `%PDF` header, or an HTML page with an expected value marker.

- **Saved (1 of 27):** S22. **It is the wrong version for the 2026 rate:**
  - The URL the spec links serves the CDMX Fiscal Code "texto vigente, última reforma G.O.C.D.M.X. 27-12-2022".
  - Its **Art. 158 sets ISN at 3%**, while spec §15 says 4% for 2026.
  - Source and spec disagree, so per change 1 **I stop on CDMX ISN**. The current consolidated 2025/2026 text is needed.
  - The file is kept as evidence of what the spec URL serves, and is flagged `WRONG_VERSION` in `SOURCES_MANIFEST.csv`. It is 49 MB, so consider before committing.
- **Not obtainable from here (26):**
  - SAT: timeouts and HTTP 504.
  - DOF, INEGI and congreso.gob.mx: no DNS resolution.
  - IMSS and INFONAVIT: HTTP 403 (bot block).
  - gob.mx (CONASAMI, STPS, PROFEDET): HTTP 200, but every one is the same 1,910-byte bot-challenge shell with no content.
  - diputados.gob.mx: resolves, but times out.

The user's fetch checklist is in the chat reply for this step. Transcription starts only after the user confirms the files are in `docs/mexico/sources/`.
