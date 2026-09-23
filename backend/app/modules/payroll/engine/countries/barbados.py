"""
modules/payroll/engine/countries/barbados.py
------------------------------------------------
Barbados (BB) — Phase 1 statutory build (ZP-BB-ENG-001).

Two independent statutory obligations, computed on independent bases —
never folded into one number (per BB-011):
  1. PAYE — non-cumulative, period-by-period (BB-005/BB-009): personal
     allowance (BBD 25,000/year) then 11.5% up to the BBD 50,000/year
     taxable band, 27.5% above it. Reused field: `tds`.
  2. NIS code-R bundle — employee 11.00% / employer 12.75% of insurable
     earnings, capped at the current weekly/monthly ceiling (BB-010/BB-011).
     Reused fields: `social_security` (employee) / `employer_social_security`
     (employer) — same generic "primary social-insurance contribution"
     slot US/UK/AU already use for their own equivalents.
  3. Resilience & Regeneration levy — 0.25% employee + 0.25% employer on
     UNCAPPED gross earnings, a genuinely separate base from NIS (BB-011:
     "Never cap R&R merely because the main NIS bundle is capped"). Reused
     fields: `employee_pension` / `employer_pension` — the closest
     existing generic "second mandatory contribution" slot; this is NOT a
     literal pension and is labelled as R&R everywhere it is displayed.

Secondary-employment/Table-X treatment (BB-007) and the Protection of
Wages Act 2026-15 effective-date gate (BB-016) are deliberately NOT
implemented here — the spec itself gates both behind signed 2026 content
that has not been acquired yet; this module never guesses a legacy rate.

PAYE bands come from `ctx.slabs` (canonical TaxSlab rows for country="BB",
seeded by scripts/seed_caribbean_canonical_packs.py with the exact
11.5%/27.5% bands from ZP-BB-ENG-001 §2) via the same generic
`_calculate_annual_tax` bracket engine every other country's PAYE/ISR/tax
uses — NOT a Python-hardcoded band table, matching engine/countries/
uk.py:_calculate_annual_tax_uk's exact pattern. Only the personal
allowance (a single scalar) has a Python fallback constant, via
resolve_jurisdiction_parameter, same convention as every existing country.

Validated against ZP-BB-ENG-001 §12 fixtures F1 (5,000/mo) and F2
(10,000/mo) — see tests/test_barbados.py.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year,
    resolve_jurisdiction_parameter,
    _calculate_annual_tax,
)

_BB_ANNUAL_ALLOWANCE = Decimal("25000")

_BB_NIS_EMPLOYEE_RATE = Decimal("0.1100")
_BB_NIS_EMPLOYER_RATE = Decimal("0.1275")
_BB_NIS_WEEKLY_CEILING = Decimal("1238")
_BB_NIS_MONTHLY_CEILING = Decimal("5360")

_BB_RR_EMPLOYEE_RATE = Decimal("0.0025")
_BB_RR_EMPLOYER_RATE = Decimal("0.0025")


def _resolve_nis_ceiling(rate_map: dict, pay_frequency: str | None) -> Decimal:
    frequency = (pay_frequency or "Monthly")
    if frequency == "Weekly":
        return resolve_jurisdiction_parameter(rate_map, "bb_nis_ceiling_weekly", _BB_NIS_WEEKLY_CEILING, country="BB")
    return resolve_jurisdiction_parameter(rate_map, "bb_nis_ceiling_monthly", _BB_NIS_MONTHLY_CEILING, country="BB")


def calculate(ctx: PayrollContext) -> dict:
    """Barbados: non-cumulative PAYE + NIS code-R (capped) + R&R levy
    (uncapped). Frequency-aware via ctx.pay_frequency/resolve_periods_per_year
    (defaults to Monthly)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    period_gross = ctx.gross

    # ── PAYE (non-cumulative: this period's own equivalent-annual figure,
    # never a cumulative YTD run) ─────────────────────────────────────────
    allowance_annual = resolve_jurisdiction_parameter(rate_map, "bb_personal_allowance", _BB_ANNUAL_ALLOWANCE, country="BB")
    period_allowance = allowance_annual / periods_per_year
    taxable_period = max(period_gross - period_allowance, Decimal("0"))
    taxable_annualized = taxable_period * periods_per_year
    annual_tax = _calculate_annual_tax(taxable_annualized, ctx.slabs)
    tds = _round2(annual_tax / periods_per_year)

    # ── NIS code-R bundle (capped) ────────────────────────────────────────
    nis_ceiling = _resolve_nis_ceiling(rate_map, ctx.pay_frequency)
    nis_base = min(period_gross, nis_ceiling)
    nis_employee_rate = resolve_jurisdiction_parameter(rate_map, "bb_nis", _BB_NIS_EMPLOYEE_RATE, side="employee", country="BB")
    nis_employer_rate = resolve_jurisdiction_parameter(rate_map, "bb_nis", _BB_NIS_EMPLOYER_RATE, side="employer", country="BB")
    social_security = _round2(nis_base * nis_employee_rate)
    employer_social_security = _round2(nis_base * nis_employer_rate)

    # ── Resilience & Regeneration levy (uncapped gross) ──────────────────
    rr_employee_rate = resolve_jurisdiction_parameter(rate_map, "bb_resilience_regeneration", _BB_RR_EMPLOYEE_RATE, side="employee", country="BB")
    rr_employer_rate = resolve_jurisdiction_parameter(rate_map, "bb_resilience_regeneration", _BB_RR_EMPLOYER_RATE, side="employer", country="BB")
    employee_pension = _round2(period_gross * rr_employee_rate)  # R&R employee — see module docstring
    employer_pension = _round2(period_gross * rr_employer_rate)  # R&R employer — see module docstring

    return dict(
        tds=tds,
        social_security=social_security,
        employer_social_security=employer_social_security,
        employee_pension=employee_pension,
        employer_pension=employer_pension,
    )
