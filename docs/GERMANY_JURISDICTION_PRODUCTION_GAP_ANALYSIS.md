# Germany Jurisdiction — Production Gap Analysis

Companion to `GERMANY_JURISDICTION_MASTER_COMPLETION_MATRIX.md`. Each gap below follows: **Requirement → Evidence → Root Cause → Exact Blocker → Required Action → Owner Type**. Only gaps with real production impact are detailed here. **Statuses reflect the Production-Ready engineering phase**: GAP-2, GAP-4 and GAP-5 are CLOSED; GAP-3 is PARTIALLY closed (Kirchensteuer display done, Soli deferred with PAP by design); GAP-1, GAP-6, GAP-7 remain externally blocked.

---

## GAP-1: BMF PAP Wage-Tax Engine Cannot Activate (matrix G-10, G-22, G-23, G-26, G-27, G-28, G-29, G-30)

**Requirement:** Lohnsteuer/Soli/Kirchensteuer must be computed via the official BMF Programmablaufplan for Regular and Midijob payroll.

**Evidence:** `resolve_pap_executor()` (`core.py:691-714`) unconditionally returns `UnavailablePapExecutor` regardless of any argument. `production_gate.py` defines exactly 8 gates (`source_identity_verified`, `source_hash_verified`, `source_finality_verified`, `licensing_authorized`, `asset_approved`, `golden_vectors_passed`, `security_certified`, `release_approved`) and is imported by **nothing** in `core.py`, `adapter.py`, `interpreter.py`, or `countries/germany.py` — confirmed by a fresh import-graph search this phase, zero hits. `PAP_SOURCE_FINALITY = "OPEN"` (`adapter.py:80`). No `.xml` file, and no file containing the string "Lohnsteuer2026", exists anywhere in this worktree (fresh whole-repo search, zero hits). `golden_vector.py`'s committed test suite contains exactly one vector, explicitly labeled `source_document="synthetic-test-fixture, not a real BMF publication"` (`test_germany_pap_golden_vector.py:32-42`) — zero vectors in committed code cite an authoritative BMF source. A repo-wide search for "Prüftabelle" finds only documentation *acknowledging its absence*, never actual table data.

**Root Cause:** This is not an engineering defect. The engine (`interpreter.py`) is complete, security-hardened (no eval/exec/network, Decimal-only arithmetic, enforced execution-step and nesting-depth budgets — all re-verified this phase), and correctly wired to fail closed. The blocker is that the two prerequisites for legitimate activation — a legally-cleared, retained copy of the authoritative BMF XML, and authoritative BMF Prüftabellen to certify golden vectors against — do not exist in this project.

**Exact Blocker:**
1. `LEGAL_REVIEW_REQUIRED`: whether faithfully interpreting a CC BY-ND 4.0-licensed BMF XML at runtime (without redistributing a modified copy) constitutes a prohibited "Bearbeitung" (derivative) under the license's NoDerivatives clause.
2. `BLOCKED_EXTERNAL`: the BMF Prüftabellen (official check tables) needed to certify golden vectors do not exist anywhere in this project.
3. `BLOCKED_EXTERNAL` (downstream of #1): even once cleared legally, the XML itself must be re-acquired and retained (previously only hashed transiently and discarded).

**Required Action:** (1) Legal clearance — the single highest-leverage next step, since it is internal (no external counterparty coordination) and gates everything else. (2) BMF Prüftabellen acquisition. (3) Only then: ingest a real `PapAlgorithmAsset` (the insert code path is real and already reachable — `service.py:2300` — it has simply never been exercised outside test transactions), complete all 8 gates on a real `GermanyPapRelease`, wire `production_gate.evaluate()` into `resolve_pap_executor()` (a source change, not a config change), and only then flip `PAP_SOURCE_FINALITY` to `"RESOLVED"`.

**Owner Type:** LEGAL (item 1) + EXTERNAL AUTHORITY (item 2, BMF) + ENGINEERING (item 3, only after 1 and 2).

---

## GAP-2: Minijob and Midijob Numeric Contribution Math Has Zero Unit-Test Coverage (matrix G-20, G-21) — **CLOSED**

**Requirement:** Minijob and Midijob social-insurance contribution amounts must be verified correct, not merely "implemented."

**Evidence:** Direct code read confirms `calculate_minijob()` (`core.py:943-992`) and the Midijob transition-zone functions (`core.py:995-1068`) are internally consistent, use the correct cited statutory constants (`hardcoded_defaults.py:726-759`), and are wired identically to the REGULAR path for effective-dated registry resolution. However, the ONLY tests exercising either path (`test_germany_pap_calculation.py`) are two classification-boundary exception tests (`test_calculate_raises_for_minijob_classification_with_out_of_range_earnings`, `test_calculate_raises_for_midijob_classification_with_out_of_range_earnings`) — neither asserts a single EUR contribution amount. A comment in that same file cites `test_germany_minijob_midijob.py` as the place such coverage lives; that file does not exist anywhere in git history (`git log --all` shows no add/delete commit for it) or on disk.

**Root Cause:** A documentation/comment reference to a test file that was apparently planned but never created (or was created on a different, never-merged branch and the comment survived a merge). This means "Minijob = GO" and "Midijob SI-side = GO" have been true as *code-inspection* claims across multiple phases, but never as *tested* claims — a materially different, weaker form of evidence than the "GO" label implies.

**Exact Blocker:** None external — this is a pure internal testing gap.

**Required Action:** Add numeric-assertion unit tests for `calculate_minijob()` (verify the 13%/15%/0.80%/0.22%/15%/3.60%/2% constants produce correct EUR amounts for representative gross wages) and for `calculate_midijob_branch_contribution()`/the transition-zone formulas (verify the round-then-double sequence, Saxony branch, childless surcharge, at multiple points within and at the boundaries of the €603.01–€2,000.00 corridor).

**Owner Type:** ENGINEERING.

**✅ RESOLVED — Production-Ready engineering phase.** `backend/tests/test_germany_minijob_midijob.py` (new, 772 lines, **43 tests, all pass** in 0.23s) now asserts actual EUR amounts: Minijob at €520/€603/€450/€0/€1, pension-exempt path, accident-insurance contributions, rate constants, classification-boundary thresholds, vocational-trainee exclusion, GKV public/private/missing, Midijob base-formula coefficients (round-then-double preserved), branch contributions, PV childless surcharge (incl. Land-independent equality + differing split), and the 0.6 PV surcharge constant. Additionally `backend/tests/test_germany_e2e_payroll_scenario.py` (new, 404 lines, **6 tests, all pass**) proves Minijob end-to-end (gross €520 → net €501.28, `employer_pf` €78.00, `employer_esi` €73.68, `pf` €18.72, `total_deductions` €18.72) and confirms MIDIJOB/REGULAR fail closed on `GERMANY_PAP_NOT_AVAILABLE` with SI resolved on the trace.

---

## GAP-3: Payslip Does Not Display Kirchensteuer; Solidaritätszuschlag Has No Persisted Field At All (matrix G-11, G-32) — **PARTIALLY CLOSED**

**Requirement:** A German employee's payslip must represent Lohnsteuer, Soli, and Kirchensteuer.

**Evidence:** `PayslipItem.church_tax` (`models.py:1084`) is a real column, but no frontend component (`PayslipStub.jsx`, `jurisdictionLabels.js`) references it — confirmed by direct grep, zero hits for `churchTax`/`church_tax` in the frontend payslip rendering path. Separately, no `solidarity`/`soli` column exists anywhere on `PayslipItem` or any related model — Soli has never been given a place to live once PAP eventually produces a `SOLZLZZ` output.

**Root Cause:** Two independent, smaller gaps that happened to surface together in this audit: (a) a UI oversight — a real backend field was never wired to the payslip view; (b) a genuine, currently-dormant data-model gap — since PAP has been blocked since before this field would ever populate, no prior phase had a concrete reason to add a Soli column, so it was simply never added.

**Exact Blocker:** None — both are internal and safe.

**Required Action:** (a) Add a Kirchensteuer row to `PayslipStub.jsx` reading `church_tax` — small, safe, can be done immediately regardless of PAP's status (the field exists and is populated wherever church-tax calculation already runs). (b) Add a `PayslipItem.solidarity_surcharge` (or equivalent) column via an additive migration, timed to land alongside the eventual PAP activation work (no urgency before then, since it would sit at zero/unpopulated regardless).

**Owner Type:** ENGINEERING.

**✅ (a) RESOLVED — Production-Ready engineering phase.** `frontend/src/utils/jurisdictionLabels.js` adds `CHURCH_TAX_LABELS = { DE: "Kirchensteuer" }` and `getPayrollLabels()` now returns `churchTax`; `frontend/src/modules/payroll/PaySlips/PayslipStub.jsx` (`deductionRows`, ~L70) renders a Kirchensteuer deduction row whenever `labels.churchTax` is set and `payslip.churchTax > 0`; `backend/app/modules/payroll/service.py` `generate_payslip_pdf_bytes` (`:13217-13224`) appends a "Kirchensteuer" deduction item for `country == "DE"` whenever `church_tax > 0`, matching the UI row. No Soli row was added to the UI/PDF because no persisted field exists (a zero/phantom row would be fabricated).

**⏸ (b) DEFERRED — intentionally, unchanged.** Adding a Soli column before PAP can populate it would leave a permanently-zero field with no production value; it is sequenced with PAP activation (GAP-1/P0-4), consistent with the matrix G-11/G-32 note.

---

## GAP-4: Blocked-State UX Discards the Machine-Readable Error Code and Diagnostic Trace (matrix G-33) — **CLOSED**

**Requirement:** When Germany payroll fails closed (e.g. `GERMANY_PAP_NOT_AVAILABLE`, `GERMANY_HEALTH_FUND_NOT_AVAILABLE`), the operator should be able to see exactly why.

**Evidence:** `GermanyCalculationBlockedException` (`backend/app/core/exceptions.py:80-93`) and its global handler (`:116-125`) return a structured `{error, message, detail, trace}` payload. `frontend/src/service/api.js:100-114` reads only `data.detail || data.message` into `err.message` — `error_code` and `trace` are discarded before any component can read them.

**Root Cause:** The frontend API client was written to produce a single human-readable string for the common case, and no Germany-specific caller was ever built to need the structured fields, so nothing surfaced the gap until this audit specifically asked about blocked-state UX.

**Exact Blocker:** None — internal, safe.

**Required Action:** Thread `error_code` and `trace` onto the thrown error object in `api.js` (e.g. `err.errorCode`, `err.trace`), then surface at minimum the code in the existing error banners on the statutory-profile panel and payslip/payroll-run views.

**Owner Type:** ENGINEERING, P2.

**✅ RESOLVED — Production-Ready engineering phase.**
- `frontend/src/service/api.js:99-118` — non-OK responses now capture `errorCode` (`data.error || data.error_code`) and `trace`, passed into `createApiError(detail, status, { errorCode, trace })`.
- `frontend/src/api/client.js:86-87` — sets `err.errorCode` / `err.trace` before throwing (covers the second API client).
- `frontend/src/service/errorClassification.js:49-59` — `describeLoadError` now returns `errorCode` and `trace` alongside `message`/`schemaUnavailable`/`networkError`.
- `frontend/src/pages/JurisdictionCompliance/GermanyStatutoryRegistriesPage.jsx:116-129` — `ErrorBanner` renders the `[errorCode]` in mono and a "Blocked gates: …" line from `trace.failedGates`, so fail-closed outcomes are now machine-readable on screen. (The statutory-profile panel and payroll-run views already surface the human message; the Compliance page is the reference implementation of the code/gates.)

**Verified:** no new backend behavior — the structured payload already existed server-side; only the frontend consumption path changed.

---

## GAP-5: ELSTER Transmission Boundary Has Zero Frontend Surface (matrix G-34) — **CLOSED**

**Requirement:** Operators need a way to configure a certificate reference and view/create/validate/attempt transmissions.

**Evidence:** Phase 8BF built the complete backend boundary (`GermanyElsterCertificateConfig`, `GermanyElsterTransmission`, 5 endpoints) and 9 passing tests. A fresh whole-frontend-tree grep for any ELSTER-prefixed identifier (`ElsterCertificate`, `ElsterTransmission`, `elster-` endpoint paths, `GermanyElster`) returns zero matches.

**Root Cause:** The backend boundary was built in direct response to that phase's own brief; a UI was not in that phase's scope and was correctly not fabricated to "look complete."

**Exact Blocker:** None — internal, safe, but non-trivial (a new tab following the existing `LifecycleRegistryTab`-adjacent patterns).

**Required Action:** Add a Compliance UI tab: certificate-reference form (never accepting/displaying actual key material — matching the backend's own security boundary), a transmission list/create form, and Validate/Transmit buttons that clearly show `BLOCKED_EXTERNAL` outcomes (never implying success).

**Owner Type:** ENGINEERING, P2.

**✅ RESOLVED — Production-Ready engineering phase.**
- `frontend/src/service/payrollService.js:405-455` — 6 new functions mirroring the existing router contract: `get/setGermanyElsterCertificateConfig`, `create/listGermanyElsterTransmissions`, `validate/transmitGermanyElsterTransmission`.
- `frontend/src/pages/JurisdictionCompliance/GermanyStatutoryRegistriesPage.jsx` — new `ELSTER` tab (`TABS` at `:44`, `ElsterTab` at `:1008`, render at `:1474`): certificate-reference form (reference string only, never key material), transmission DRAFT-create form with JSON payload summary, record table with lifecycle actions (DRAFT→Validate→VALIDATED→Transmit→BLOCKED_EXTERNAL→Retry), a "Last blocked reason" panel, and explanatory copy stating that transmission stays `BLOCKED_EXTERNAL` by design. Result objects are the real backend responses — nothing is simulated.
- Frontend production build verified clean after these changes (`npm run build`, 18.28s).

---

## GAP-6: DEÜV Has No Specification Anywhere In This Project (matrix G-35)

See `docs/DEUV_PRODUCTION_REQUIREMENTS.md` for the full analysis. **Owner Type:** EXTERNAL AUTHORITY (specification) + PRODUCT (credential/infrastructure decision) + ENGINEERING (only after both). Not schedulable as an engineering task until a specification exists.

---

## GAP-7: Bad Wimpfen (and Any Other Sub-Land Church-Tax Exception) Has No Authoritative Rate Data (matrix G-12, G-36)

**Requirement:** The documented Baden-Württemberg Bad Wimpfen Roman Catholic exception needs a real, sourced rate to publish.

**Evidence:** The entire mechanism — model, maker-checker lifecycle, resolver, and (as of this phase's GAP-4 fix… no, this phase's G-04 fix) the employee-side denomination/postal-code capture — is now fully implemented and reachable end-to-end, proven by `test_germany_church_tax_exception_resolution.py`. What remains missing is the *actual* rate for Bad Wimpfen (or any other Land-specific exception) from an authoritative source — this project's own documentation has always disclosed this as a data gap, not an engineering one.

**Root Cause:** No authoritative source document containing Land-specific church-tax exception rates was ever supplied to this project.

**Exact Blocker:** `SPECIFICATION_REQUIRED` / data acquisition.

**Required Action:** Obtain the actual Bad Wimpfen rate (and any other genuinely-needed exceptions) from an authoritative German tax-authority source, then have a Super Admin publish it through the now-fully-functional mechanism.

**Owner Type:** EXTERNAL AUTHORITY / PRODUCT (to decide which exceptions are in scope) — pure data acquisition, zero further engineering required once sourced.

---

## Non-Gaps (Explicitly Re-Verified, No Action Needed)

- PAP execution security (Decimal-only, no eval/exec/network, bounded execution) — re-verified clean.
- Alembic chain integrity — single head, no duplicates, no invalid defaults, clean linear history.
- RBAC/tenant isolation — every Germany endpoint has an explicit auth dependency; maker-checker checks are real.
- Overtime subsystem — unchanged, correct, tested.
- U1 tariff registry, contribution ceilings (RV/ALV vs. GKV/PV genuinely distinct), health-fund effective dating — all confirmed correct by direct code read.
