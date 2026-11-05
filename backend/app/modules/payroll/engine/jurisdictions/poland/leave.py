"""Poland annual leave entitlement (ZP-PL-ENG-001 §8).

20 days below the signed service-credit threshold, 26 days at or above it
(spec §8 table), proportional for part-time. Whole-year entitlement only:
mid-year changes of employment or working time and leave remuneration
(reference periods, fixed / variable components) need rules the
specification does not give — leave pay stays blocked by the REVIEW
earning class and pl_leave_pay_reference_rule.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.labour import fte
from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack, dec, field


def annual_entitlement(pack: PlPack, profile) -> dict:
    months = field(profile, "service_credit_months")
    if months in (None, ""):
        pack.block(E.keyed(E.FACT_MISSING, "service_credit_months"), "service credit is not recorded")
    years = int(dec(months)) // 12
    threshold = int(pack.amount("pl_leave_service_years_senior"))
    key = "pl_leave_days_senior" if years >= threshold else "pl_leave_days_base"
    full_days = pack.amount(key)
    numerator, denominator = fte(pack, profile)
    exact = full_days * numerator / denominator
    rounding = None
    days = exact
    if numerator != denominator:
        rounding = pack.text("pl_leave_part_time_rounding", content.LEAVE_PART_TIME_ROUNDING)
        if rounding == "ROUND_UP_FULL_DAY":
            days = exact.quantize(Decimal("1"), rounding=ROUND_CEILING)
    return {"serviceYears": years, "tier": "SENIOR" if years >= threshold else "BASE",
            "fullTimeDays": _days(full_days), "fte": f"{numerator}/{denominator}", "exactDays": _days(exact),
            "rounding": rounding, "days": _days(days)}


def _days(value: Decimal) -> str:
    """A day count without trailing zeros ("26", "19.5") whatever the stored scale."""
    text = format(Decimal(value).normalize(), "f")
    return text
