"""
modules/payroll/engine/germany_pap
------------------------------------
Germany BMF PAP subsystem package (Phase 8E-0A / 8BC).

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
                    pure artifact-agnostic engine. Restored to nikhil branch
                    in Phase 8BC for production-capability assessment.
- `adapter`       — Zoiko <-> BMF PAP contract bridge (Phase 8C-2); holds
                    `PAP_SOURCE_FINALITY="OPEN"` and the
                    `InterpreterPapExecutor`. Restored to nikhil branch in
                    Phase 8BC.
- `golden_vector` — BMF PAP certification data model (Phase 8C-3).
                    Restored to nikhil branch in Phase 8BC.
- `elstam`        — ELStAM retrieval boundary (Phase 8K); fail-closed
                    `UnavailableElstamProvider`. No live connector.
- `production_gate` — Eight-gate production release governance (Phase 8G-1).
                    Pure evaluation, not yet wired to resolve_pap_executor().

PAP PRODUCTION SAFETY (Phase 8BC): `resolve_pap_executor()` STILL returns
`UnavailablePapExecutor` and `PAP_SOURCE_FINALITY="OPEN"`. The BMF PAP XML
artifact (`Lohnsteuer2026.xml`) does not exist in the repository. No PAP
asset has been ingested into `PapAlgorithmAsset`. Activation of a real
executor requires: (1) ingestion of the verified BMF XML, (2) all eight
production gates satisfied, (3) wiring of production_gate to
resolve_pap_executor, and (4) resolution of PAP_SOURCE_FINALITY.
"""
