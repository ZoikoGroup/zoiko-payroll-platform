"""
engine/jurisdictions/brazil/__init__.py
----------------------------------------
Brazil jurisdiction helpers (ZP-BR-ENG-001) — pure, ORM-free modules the
Brazil engine (engine/countries/brazil.py) will compose. Nothing here imports
the framework, the ORM or another jurisdiction.

Phase 5: labor (overtime, DSR, night hour, vale-transporte).
Planned (never before their content exists): thirteenth / vacation /
termination (Phase 7), cct_engine (collective floors and premiums — Phase 8),
esocial_xml (Phase 9).
"""

from .labor import (
    calculate_overtime,
    calculate_night_premium,
    calculate_dsr,
    calculate_dsr_from_total,
    OVERTIME_50_PCT,
    OVERTIME_100_PCT,
    NIGHT_PREMIUM_PCT,
    NIGHT_HOUR_MINUTES,
    LaborRates,
    resolve_labor_rates,
)

__all__ = [
    "calculate_overtime",
    "calculate_night_premium",
    "calculate_dsr",
    "calculate_dsr_from_total",
    "OVERTIME_50_PCT",
    "OVERTIME_100_PCT",
    "NIGHT_PREMIUM_PCT",
    "NIGHT_HOUR_MINUTES",
    "LaborRates",
    "resolve_labor_rates",
]
