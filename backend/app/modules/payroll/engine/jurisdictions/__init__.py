"""
engine/jurisdictions
--------------------
Jurisdiction subsystem packages (Phase 5 — Jurisdiction Architecture
Normalization).

The shared `engine/` namespace holds only genuinely shared engine concerns
(base, standard, simple, enterprise, resolver, tax_resolver,
fallback_registry, __init__). Each jurisdiction's entry-point calculator
lives in `engine/countries/` (one calculator per jurisdiction). Larger
jurisdiction-specific subsystems that exceed a single calculator file live
under `engine/jurisdictions/<country>/` so they are clearly grouped at the
jurisdiction boundary instead of appearing to be generic engine components.

Germany (the first jurisdiction with a subsystem package) groups its
statutory support under `engine/jurisdictions/germany/`:

- `tax.py`              - INTERNAL functional wage-tax calculator (§32a/39b EStG).
- `overtime/`           - Germany overtime/shift-premium subsystem (§3b EStG,
                          §1 SvEV): classifier, wage tax, social insurance,
                          premium component (grouped, not merged).
- `statutory/`          - Statutory reporting boundaries: DEÜV (deuv.py) and
                          ELSTER (elster.py).
- `pap/`                - Germany BMF PAP subsystem: production statutory
                          support core, XML interpreter, adapter, golden
                          vectors, production gate, ELStAM boundary.

`engine/countries/germany.py` remains the canonical country calculator /
entry point and re-exports everything the generic engine path needs.
"""