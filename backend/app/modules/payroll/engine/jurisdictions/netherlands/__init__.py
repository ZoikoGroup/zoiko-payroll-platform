"""
engine/jurisdictions/netherlands/__init__.py
--------------------------------------------
Netherlands jurisdiction helpers (ZP-NL-ENG-001) — pure, ORM-free modules
that hold the Dutch shapes the Netherlands engine
(engine/countries/netherlands.py, a later phase) and the payroll workflows
share. Nothing here imports the framework, the ORM or another jurisdiction.

The catalog this package's helpers will consume is
engine/countries/netherlands_content.py (the Draft 2026 content): the scalar
parameters the engine reads from `rate_map` and the structured TaxSlab
families (NL_MIN_WAGE, NL_PERIOD_MAX, NL_WKR_BAND, NL_CAR_ADDITION).

Planned helpers (added in later phases, never before their specification
exists):
  * vcr.py — the voortschrijdend cumulatief rekenen primitive: cumulative
    contribution-base increments against the official time-period maxima
    (NL-012/NL-013), with separate Zvw employer-levy and employee-
    contribution series (NL-020).

No helper exists yet: the Netherlands calculator is not built, so nothing
here may be imported by the engine. This package exists only so the
directory and its doctrine are established from the content phase.
"""
