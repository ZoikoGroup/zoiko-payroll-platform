"""
engine/jurisdictions/germany
----------------------------
Germany jurisdiction subsystem package (Phase 5 — Jurisdiction Architecture
Normalization).

The canonical Germany country calculator is `engine/countries/germany.py`;
this package holds the Germany-specific subsystems that grew too large for
a single calculator file:

- `tax.py`              - INTERNAL functional wage-tax calculator (§32a/39b EStG)
                          (formerly `engine/germany_internal_tax.py`).
- `overtime/`           - overtime/shift-premium subsystem (§3b EStG, §1 SvEV).
- `statutory/`          - statutory reporting boundaries (DEÜV, ELSTER).
- `pap/`                - Germany BMF PAP subsystem (production support core,
                          interpreter, adapter, golden vector, gate, ELStAM).

This package makes the dependency direction explicit: generic engine ->
`countries/germany.py` -> this package. Nothing in this package is imported
by `_COUNTRY_CALC` or the generic strategy/registry layer except transitively
through `countries/germany.py`.
"""