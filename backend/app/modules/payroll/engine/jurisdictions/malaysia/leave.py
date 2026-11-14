"""Leave entitlements by territory (ZP-MY-ENG-001 §9; MY-017 / MY-024).

Annual and sick leave come from the territory's signed tier text
"YEARS:DAYS,YEARS:DAYS" (completed years of service -> days per year);
hospitalisation, maternity and paternity from the territory's signed day
counts. Whole-year entitlements only: proration on joining / leaving, the
eligibility conditions for paternity leave and leave remuneration
(my_leave_pay_rule) are not given by the specification and stay blocked.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, as_date, field

_HALF = Decimal(1) / 2          # tiers may hold half days


def parse_tiers(text: str) -> list:
    """[(years, days)] ascending from 0 years; ValueError on any malformed tier."""
    tiers = []
    for part in [p.strip() for p in str(text or "").split(",") if p.strip()]:
        years, sep, days = part.partition(":")
        try:
            years, days = int(years.strip()), Decimal(days.strip())
        except (ValueError, InvalidOperation):
            raise ValueError("tiers must be YEARS:DAYS pairs separated by commas")
        if not sep or years < 0 or days < 0 or (days / _HALF) != (days / _HALF).to_integral_value():
            raise ValueError("each tier needs whole years and whole or half days")
        tiers.append((years, days))
    if not tiers or tiers[0][0] != 0 or [y for y, _ in tiers] != sorted({y for y, _ in tiers}):
        raise ValueError("tiers must start at 0 years and ascend without repeats")
    return tiers


def completed_years(start: date, on: date) -> int:
    years = on.year - start.year - ((on.month, on.day) < (start.month, start.day))
    return max(years, 0)


def _tier_days(pack: MyPack, base: str, territory: str, years: int) -> Decimal:
    text = pack.text(base, territory=territory)
    try:
        tiers = parse_tiers(text)
    except ValueError as error:
        pack.block(E.keyed(E.POLICY_PENDING, pack.key(base, territory)), str(error))
    return [days for threshold, days in tiers if years >= threshold][-1]


def _days(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def entitlements(pack: MyPack, territory: str, profile, as_of: date) -> dict:
    start = as_date(field(profile, "service_start"))
    if start is None:
        pack.block(E.keyed(E.FACT_MISSING, "service_start"), "the service start date is not recorded")
    years = completed_years(start, as_of)
    return {"territory": territory, "serviceYears": years,
            "annualDays": _days(_tier_days(pack, "my_annual_leave_tiers", territory, years)),
            "sickDays": _days(_tier_days(pack, "my_sick_leave_tiers", territory, years)),
            "hospitalisationDays": _days(pack.amount("my_hospitalisation_days", territory)),
            "maternityDays": _days(pack.amount("my_maternity_days", territory)),
            "paternityDays": _days(pack.amount("my_paternity_days", territory)),
            "notes": ["whole-year entitlement; proration, paternity eligibility and leave pay need signed rules"]}
