# Germany Jurisdiction — Production Roadmap

Priority definitions (per the governing phase brief):
- **P0** = prevents Germany payroll from functioning correctly
- **P1** = statutory/compliance production requirement
- **P2** = important production capability
- **P3** = UX/operational enhancement

Each item states whether it is internally implementable now, or blocked on something external/legal/product. Only internally-implementable, safe, testable items are candidates for immediate engineering work; everything else names its exact blocker.

---

## P0 — Prevents Germany Payroll From Functioning Correctly

| # | Item | Internally implementable now? | Blocker | Owner |
|---|---|---|---|---|
| P0-1 | Legal clearance on CC BY-ND 4.0 PAP interpretation | No | Legal review | LEGAL |
| P0-2 | BMF Prüftabellen acquisition | No | External (BMF) | EXTERNAL AUTHORITY |
| P0-3 | Re-acquire and retain the BMF PAP XML (post-legal-clearance) | No (until P0-1 clears) | External + legal | EXTERNAL AUTHORITY / ENGINEERING |
| P0-4 | Ingest a real `PapAlgorithmAsset`, complete all 8 `GermanyPapRelease` gates, wire `production_gate.evaluate()` into `resolve_pap_executor()` | No (until P0-1/P0-2/P0-3 clear) | Sequenced after the above | ENGINEERING (only after external/legal) |

**Status this phase:** none of P0-1 through P0-4 were started — correctly so, since none can be safely done without the external/legal prerequisites, and this phase's own rules forbid beginning external integrations or fabricating legal sign-off.

---

## P1 — Statutory / Compliance Production Requirement

| # | Item | Internally implementable now? | Notes |
|---|---|---|---|
| P1-1 | Add numeric-assertion unit tests for `calculate_minijob()` | **Yes** | Safe, internal, no dependency — **DONE in the Production-Ready engineering phase** |
| P1-2 | Add numeric-assertion unit tests for Midijob transition-zone formulas | **Yes** | Same — **DONE in the Production-Ready engineering phase** |
| P1-3 | Display Kirchensteuer on the payslip UI (`PayslipStub.jsx`) | **Yes** | The field already exists and is populated wherever church-tax calculation runs; purely a display fix — **DONE (UI row + PDF deduction item)** |
| P1-4 | Obtain authoritative Bad Wimpfen (or other) church-tax exception rate data | No | Data acquisition, not engineering — the mechanism itself is now fully functional (G-04 fix) |
| P1-5 | Decide and add a persisted Solidaritätszuschlag field on `PayslipItem` | Partially — the migration itself is safe and internal, but there is no value in adding it before PAP can ever populate it | **Still deferred** — intentionally unchanged; sequence with P0-4 |

**Status (Production-Ready engineering phase):** P1-1/P1-2/P1-3 are now **implemented and test/verification-proven** — 43 numeric Minijob/Midijob tests + 6 E2E payroll scenario tests (all green), Kirchensteuer rendered in both the payslip UI and the generated PDF. P1-4 requires an external data source (unchanged). P1-5 is correctly deferred (a Soli column would be permanently zero until PAP activates).

---

## P2 — Important Production Capability

| # | Item | Internally implementable now? | Notes |
|---|---|---|---|
| P2-1 | Thread `error_code`/`trace` through `api.js` and surface blocked-reason codes in the UI | **Yes** | Safe, internal — **DONE in the Production-Ready engineering phase** (both API clients + `errorClassification.js` + `ErrorBanner` shows `[code]` and "Blocked gates: …") |
| P2-2 | Build a minimal Compliance UI panel for the ELSTER boundary (certificate reference, transmission list/create/validate/transmit) | **Yes** | Backend fully exists (Phase 8BF); UI-only work — **DONE (`ElsterTab`)** |
| P2-3 | Add a per-employee resolved-contribution preview UI (RV/ALV/GKV/PV numbers, not just raw registry config) | **Yes**, but nontrivial | Would reuse `preview_germany_calculation`'s existing backend output — **NOT STARTED** (remaining internally-implementable P2 item) |

**Status (Production-Ready engineering phase):** P2-1 and P2-2 are **implemented**. P2-3 remains — a genuine, safe, internally-implementable enhancement with no external blocker; recommended as the next engineering candidate.

---

## P3 — UX / Operational Enhancement

| # | Item |
|---|---|
| P3-1 | Org-level "operates in Germany" onboarding step (currently per-employee only) — product decision needed first |
| P3-2 | Normalize U2 into a full effective-dated tariff table (matching U1) — not required by spec, current single-column model is functionally correct |
| P3-3 | Dedicated Germany accident-insurance UI panel (currently reuses the generic Employer Tax Profile mechanism, functionally complete but thinner) |
| P3-4 | In-place "edit DRAFT" action on Compliance UI registries (currently: new-draft-version only, by design — effective-dated immutability) — product decision needed |
| P3-5 | Defense-in-depth: tighten `if actor_id is not None and ...` maker-checker guards to an unconditional check (currently unreachable via the real router, not a live risk) |

---

## Work Completed In the Production-Ready Engineering Phase

All items below were safe, internally-implementable, and verification-proven. The protected workflow file was never touched; no external/legal work was begun or fabricated.

1. **P1-1/P1-2 (GAP-2 closed):** new `backend/tests/test_germany_minijob_midijob.py` (43 numeric tests) proving Minijob and Midijob SI amounts with documented EUR values — the previously-untested numeric claims from the Master Audit.
2. **E2E (requirement §26):** new `backend/tests/test_germany_e2e_payroll_scenario.py` (6 tests) exercising the full Employee→Org→Profile→Classification→Gross→Tax→SI→Net→Payslip pipeline; Minijob produces a real payslip (€520 → net €501.28); MIDIJOB/REGULAR fail closed on `GERMANY_PAP_NOT_AVAILABLE` with SI resolved on the trace.
3. **P1-3 (GAP-3a closed):** Kirchensteuer now displayed — UI row in `PayslipStub.jsx` (via new `CHURCH_TAX_LABELS` in `jurisdictionLabels.js`) and a "Kirchensteuer" deduction item in `service.py`'s PDF generator.
4. **P2-1 (GAP-4 closed):** `error_code`/`trace` threaded through `api.js` and `api/client.js`; `describeLoadError` returns both; `ErrorBanner` shows `[code]` and blocked gates.
5. **P2-2 (GAP-5 closed):** ELSTER frontend surface — 6 service functions + `ElsterTab` (certificate reference, transmission list/create/validate/transmit/retry, blocked-reason panel).
6. Frontend production build verified clean; full backend suite now **987 passed / 6 pre-existing stale** (no new failures).

## P0 — Status (unchanged)

P0-1 through P0-4 were not started this phase, correctly so — each is blocked on legal/external prerequisites. P1-5 (Soli column) remains deferred with P0-4. P2-3 (SI preview UI) is the one remaining internally-implementable item.

---

## Recommended Sequencing

1. **P0-1** (legal clearance) — start immediately, in parallel with everything below; it is the only P0 item with no external-authority dependency and gates the largest remaining body of work.
2. **P2-3** — next engineering session (only remaining safe internal item): per-employee SI-contribution preview, reusing `preview_germany_calculation`.
3. **P0-2/P0-3/P0-4** — sequenced strictly after P0-1 clears; cannot be scheduled independently of it.
4. **P1-4** — data acquisition, can run in parallel with anything else; not schedulable as engineering work.
5. **DEÜV** — not schedulable until a specification is obtained; treat as parked, not backlogged.
