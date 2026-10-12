"""
engine/jurisdictions/netherlands/zvw.py
--------------------------------------
Zvw (Zorgverzekeringswet) calculations — two separate routes (NL-020, NL-021).

NL-020: Two separate VCR series
  - ZVW_LEVY (employer levy): income-dependent, paid by employer
  - ZVW_CONTRIB (employee contribution): income-dependent, withheld from net pay

NL-021: Only the employee route reduces net pay.
  - Employer levy is a cost to employer, not deducted from employee.
  - Employee contribution is withheld from gross → net.

Both routes share the same ceiling (max premium wage, NL-019) but have
independent VCR series. Rates and ceiling come from the active NL-PAYROLL-2026 pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .vcr import VcrResult, VcrFamily


def round_eur(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ZvwRates:
    employer_pct: Decimal    # ZVW_LEVY rate (e.g., 6.10%)
    employee_pct: Decimal    # ZVW_CONTRIB rate (e.g., 4.85%)
    ceiling: Decimal         # annual max premium wage (e.g., 79409.00)


def get_zvw_rates_from_pack(rate_map: dict) -> ZvwRates:
    return ZvwRates(
        employer_pct=Decimal(str(rate_map.get("nl_zvw_employer_pct", "6.10"))),
        employee_pct=Decimal(str(rate_map.get("nl_zvw_employee_pct", "4.85"))),
        ceiling=Decimal(str(rate_map.get("nl_zvw_ceiling", "79409.00"))),
    )


@dataclass(frozen=True)
class ZvwPeriodResult:
    """Zvw result for one period, split by route."""
    employer_levy: Decimal      # ZVW_LEVY: employer cost
    employee_contrib: Decimal   # ZVW_CONTRIB: withheld from net
    shared_base_increment: Decimal
    ceiling_applied: bool       # true if ceiling capped this period's base


def calculate_zvw_period(
    vcr_levy_result: VcrResult,
    vcr_contrib_result: VcrResult,
    rates: ZvwRates,
) -> ZvwPeriodResult:
    """
    Calculate Zvw for one period from the two VCR series.

    The VCR already handles ceiling via the cumulative max (period max amounts
    accumulate to the annual ceiling). The base_increment from each series
    already respects the ceiling. We just apply the respective rates.
    """
    employer = round_eur(vcr_levy_result.base_increment * rates.employer_pct / Decimal("100"))
    employee = round_eur(vcr_contrib_result.base_increment * rates.employee_pct / Decimal("100"))

    # Ceiling applied if either series' cumulative base hit the ceiling
    ceiling_applied = (
        vcr_levy_result.new_state.cumulative_base >= rates.ceiling or
        vcr_contrib_result.new_state.cumulative_base >= rates.ceiling
    )

    return ZvwPeriodResult(
        employer_levy=employer,
        employee_contrib=employee,
        shared_base_increment=vcr_levy_result.base_increment,  # both series have same base_increment
        ceiling_applied=ceiling_applied,
    )


@dataclass(frozen=True)
class ZvwAnnualResult:
    """Annual Zvw totals (for reconciliation / reporting)."""
    total_employer_levy: Decimal
    total_employee_contrib: Decimal
    total_premium_wage: Decimal  # cumulative base at year-end


def reconcile_zvw_annual(
    levy_results: list[ZvwPeriodResult],
    contrib_results: list[ZvwPeriodResult],
) -> ZvwAnnualResult:
    """Sum period results for year-end reconciliation."""
    total_employer = sum((r.employer_levy for r in levy_results), Decimal("0"))
    total_employee = sum((r.employee_contrib for r in contrib_results), Decimal("0"))
    total_wage = sum((r.shared_base_increment for r in levy_results), Decimal("0"))

    return ZvwAnnualResult(
        total_employer_levy=round_eur(total_employer),
        total_employee_contrib=round_eur(total_employee),
        total_premium_wage=round_eur(total_wage),
    )