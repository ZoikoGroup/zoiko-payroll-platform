# Brazil — out-of-scope defects found while tracing

Pre-existing platform issues noticed during Brazil work. They are **not fixed here**; each needs its own decision.

| # | Where | Observation |
|---|---|---|
| O1 | `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md` §7 (on `main`) | Mexico's list already records `NLError` having no exception handler, and NL fallback-registry rows pointing at an undefined `NL_NO_FALLBACK`. Not re-verified on `venu` for Brazil. |
| O2 | `service._normalize_country` | An empty country normalises to `"IN"`. Brazil cannot reach this path with an empty code, but it is still a silent default for every jurisdiction. |

Brazil's own draft defects (BR-K1…K9) are in `BRAZIL_PHASE_0_GAP_ASSESSMENT.md` §7. They are in scope and scheduled.
