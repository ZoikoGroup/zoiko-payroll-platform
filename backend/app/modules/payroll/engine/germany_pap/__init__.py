"""
modules/payroll/engine/germany_pap
------------------------------------
Germany BMF PAP subsystem package (Phase 8E-0A).

The shared `engine/countries/` directory holds exactly one canonical country
calculator per jurisdiction (germany.py for Germany, matching us.py / india.py).
Germany's uniquely complex BMF PAP certification machinery is intentionally
separated here as a sub-package, so it does not pollute the country-folder
convention with multiple `germany_pap_*` modules.

Layering (each module keeps its documented, non-overlapping responsibility):

- `core`          — production statutory support: PAP boundary + executor
                    interface (`resolve_pap_executor`, always fail-closed),
                    the real RV/ALV/GKV/PV social-insurance calculations,
                    GermanyCalculationTrace/errors, and CHURCH_TAX_LAND_RATES.
                    This is what `countries/germany.py` and `service.py` import.
- `interpreter`   — generic BMF PAP XML interpreter core (Phase 8C-1), a
                    pure artifact-agnostic engine; test-only, not wired into
                    production.
- `adapter`       — Zoiko <-> BMF PAP contract bridge (Phase 8C-2); holds
                    `PAP_SOURCE_FINALITY="OPEN"` and the test-only
                    `InterpreterPapExecutor`; not wired into production.
- `golden_vector` — BMF PAP certification data model (Phase 8C-3); test-only.

PAP production safety is unchanged: `resolve_pap_executor()` still returns
`UnavailablePapExecutor`, `PAP_SOURCE_FINALITY="OPEN"`, and
`assert_pap_source_finality_resolved()` still raises.
"""
