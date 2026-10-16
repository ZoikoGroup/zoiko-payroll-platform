# Mexico Phase 2 — browser acceptance results

Real Chrome (Playwright, headless) against the `vite build` bundle served by `vite preview`, backed by a
throwaway SQLite database seeded with the REAL (empty) Mexico Draft packs and templates.

**37/37 checks passed.**

| # | Check | Result |
|---|---|---|
| 1 | landing: Mexico card | PASS |
| 2 | workspace: every Mexico tab present | PASS |
| 3 | workspace: generic Rates/Slabs editors hidden | PASS |
| 4 | workspace: no TaxabilityMatrix tab | PASS |
| 5 | ISR tariffs: date bar = pack effective-from, awaiting transcription | PASS |
| 6 | Subsidy & UMA: date bar = pack effective-from, awaiting transcription | PASS |
| 7 | Minimum wages: date bar = pack effective-from, awaiting transcription | PASS |
| 8 | IMSS & CEAV: date bar = pack effective-from, awaiting transcription | PASS |
| 9 | INFONAVIT: date bar = pack effective-from, awaiting transcription | PASS |
| 10 | Benefits & workweek: date bar = pack effective-from, awaiting transcription | PASS |
| 11 | ISR tariffs: picker selects 2026-02-01 | PASS |
| 12 | classification: every axis shown, S28 note | PASS |
| 13 | classification: draft recorded | PASS |
| 14 | classification: creator's approval refused (four-eyes) | PASS |
| 15 | cfdi: release In Review, creator's approval refused | PASS |
| 16 | isn: 32 entities summary | PASS |
| 17 | isn: CDMX pack, awaiting transcription | PASS |
| 18 | isn: Jalisco unsupported and BLOCKED | PASS |
| 19 | tests tab: MX fixtures path | PASS |
| 20 | readiness: gates + activation checklist for both packs | PASS |
| 21 | readiness: two packs not activatable | PASS |
| 22 | cfdi: second Super Admin approves | PASS |
| 23 | cfdi: activation refused until Phase 7 PAC validation | PASS |
| 24 | classification: canonical approval refused without S28 catalog code | PASS |
| 25 | route /compliance/mexico/CDMX: CDMX pack listed | PASS |
| 26 | statutory-rates/mexico renders | PASS |
| 27 | report-templates/mexico lists Draft templates | PASS |
| 28 | report-templates/mexico/CDMX: ISN return | PASS |
| 29 | test-certification lists Mexico | PASS |
| 30 | engine-defaults lists Mexico | PASS |
| 31 | regression: NL workspace + its tabs | PASS |
| 32 | regression: AU workspace | PASS |
| 33 | regression: NL statutory rates | PASS |
| 34 | regression: NL report templates | PASS |
| 35 | final state: every MX pack still Draft | PASS |
| 36 | the only failed requests are the four intended refusals (all 400) | PASS |
| 37 | no page errors and no console errors other than those refusals | PASS |

Errors:
- sa-a@mxbrowsercheck.io console.error: Failed to load resource: the server responded with a status of 400 (Bad Request)
- sa-a@mxbrowsercheck.io console.error: Failed to load resource: the server responded with a status of 400 (Bad Request)
- sa-b@mxbrowsercheck.io console.error: Failed to load resource: the server responded with a status of 400 (Bad Request)
- sa-b@mxbrowsercheck.io console.error: Failed to load resource: the server responded with a status of 400 (Bad Request)

## Re-check after the Mexico approval gate (2026-10-16)

| Check | Result |
|---|---|
| pack-header Approve is refused with the Mexico reason | PASS |
| pack stays Draft with no approver | PASS |
| the only failed request is that approval refusal (400) | PASS |
