"""Contribution bases — ZP-ES-ENG-001 §3, ES-005, ES-006, ES-007, F1, F5.

  remuneration      = ordinary contributable pay + extra-pay prorrata
                      (the cash extra pay itself is never passed in — F5)
  common base (CC)  = remuneration, clamped to [group minimum, maximum]
                      (overtime is EXCLUDED from the common base)
  AT/EP base        = remuneration + overtime, clamped to [group minimum, maximum]
                      (feeds unemployment, FOGASA, training and AT/EP)
  excess            = (remuneration + overtime) - maximum, never negative:
                      the ordinary bases stay capped and the excess feeds the
                      solidarity contribution (ES-011)

Minimum and maximum are monthly pack values multiplied by the period factor
(days in alta / 30; 1 for a whole month) — the docs/spain D6 rule for a partial
month. Groups 1-3 read es_base_min_group_<n> (gap G-02: blocks until a Super
Admin adds it); groups 4-7 read es_base_min_group_4_7; daily groups 8-11 are
blocked (gap G-05).
"""
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain import params as P
from app.modules.payroll.engine.jurisdictions.spain.params import ZERO, round2

MONTH_DAYS = Decimal(30)


def period_factor(days_in_alta: int, days_in_period: int) -> Decimal:
    """1 for a whole period; otherwise days in alta / 30 (never above 1)."""
    days_in_alta, days_in_period = int(days_in_alta), int(days_in_period)
    if days_in_alta <= 0:
        raise E.ESCalculationBlockedError(E.keyed(E.EMPLOYEE_FACT_MISSING, "days_in_alta"),
                                          "the employee has no day in alta in this pay period.")
    if days_in_alta >= days_in_period:
        return Decimal(1)
    return min(Decimal(days_in_alta) / MONTH_DAYS, Decimal(1))


def contribution_group(value) -> int:
    try:
        group = int(str(value).strip())
    except Exception:  # noqa: BLE001
        group = None
    if group is None or not 1 <= group <= 11:
        raise E.ESCalculationBlockedError(E.keyed(E.EMPLOYEE_FACT_MISSING, "contribution_group"),
                                          "the employee needs a contribution group 1-11 (ES-007, ES-038).")
    if group >= 8:
        raise E.ESCalculationBlockedError(
            E.keyed(E.DAILY_GROUP_NOT_SUPPORTED, group),
            f"contribution group {group} is a daily-contribution group; daily bases and the daily solidarity "
            "rule are not configured yet (docs/spain G-05).")
    return group


def minimum_monthly(group: int, rate_map: dict) -> Decimal:
    key = f"es_base_min_group_{group}" if group <= 3 else "es_base_min_group_4_7"
    return P.amount(rate_map, key)


def compute(*, ordinary_pay, overtime_pay, extra_prorrata, group: int, factor: Decimal, rate_map: dict) -> dict:
    ordinary = Decimal(str(ordinary_pay or 0))
    overtime = Decimal(str(overtime_pay or 0))
    prorrata = Decimal(str(extra_prorrata or 0))
    minimum = round2(minimum_monthly(group, rate_map) * factor)
    maximum = round2(P.amount(rate_map, "es_base_max_monthly") * factor)

    remuneration = round2(ordinary + prorrata)
    with_overtime = round2(remuneration + overtime)
    common = min(max(remuneration, minimum), maximum)
    at_ep = min(max(with_overtime, minimum), maximum)
    return {
        "group": group,
        "factor": factor,
        "minimum": minimum,
        "maximum": maximum,
        "ordinary_pay": round2(ordinary),
        "extra_prorrata": round2(prorrata),
        "overtime_pay": round2(overtime),
        "remuneration": remuneration,
        "remuneration_with_overtime": with_overtime,
        "common": common,
        "at_ep": at_ep,
        "excess_over_maximum": max(round2(with_overtime - maximum), ZERO),
        "raised_to_minimum": remuneration < minimum,
    }
