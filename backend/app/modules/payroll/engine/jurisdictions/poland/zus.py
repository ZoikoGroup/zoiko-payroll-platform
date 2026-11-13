"""Poland ZUS social insurance (ZP-PL-ENG-001 §5, PL-009 / PL-010).

Separate employee and employer components on legally distinct bases:
  * pension (emerytalne) and disability (rentowe) are assessed on bases capped
    by the annual 30x limit — each with its OWN year-to-date accumulator
    (ZUS_CAP_PENSION_BASE / ZUS_CAP_DISABILITY_BASE), which already includes
    any approved prior-employer evidence (PL-010, posted by the service);
  * sickness (employee) and accident (employer, rate from the employer
    registration for the contribution year) are NOT stopped by the cap (PL-009).
Rounding: one signed rule for ZUS contributions (pl_rounding_zus, PL-004),
applied per contribution.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import HUNDRED, ZERO, PlPack, dec, money


def _ytd(pack: PlPack, ytd: dict, key: str) -> Decimal:
    if ytd is None or key not in ytd or ytd[key] is None:
        pack.block(E.keyed(E.YTD_MISSING, key), "the year-to-date accumulator is not supplied")
    value = dec(ytd[key])
    if value < ZERO:
        pack.block(E.keyed(E.YTD_MISSING, key), "a year-to-date base cannot be negative")
    return value


def capped(pack: PlPack, base: Decimal, ytd_value: Decimal, cap: Decimal) -> dict:
    remaining = max(cap - ytd_value, ZERO)
    assessed = min(base, remaining)
    return {"base": base, "assessed": assessed, "excluded": base - assessed, "ytdBefore": ytd_value,
            "remainingBefore": remaining, "crossed": ZERO < remaining < base or (remaining == base and base > ZERO),
            "atCap": remaining == ZERO}


def compute(pack: PlPack, bases: dict, applicability: dict, ytd: dict, rnd) -> dict:
    obligations = applicability["obligations"]
    cap = pack.amount("pl_zus_annual_cap")
    out = {"cap": money(cap), "employee": {}, "employer": {}, "bases": {}, "trace": {}}

    pension_ee = pension_er = disability_ee = disability_er = sickness = accident = ZERO
    pension = disability = None
    if obligations["EMERYTALNE"]["applies"]:
        pension = capped(pack, bases["EMERYTALNE"]["base"], _ytd(pack, ytd, "ZUS_CAP_PENSION_BASE"), cap)
        pension_ee = rnd(pension["assessed"] * pack.pct("pl_zus_emerytalne", "employee") / HUNDRED)
        pension_er = rnd(pension["assessed"] * pack.pct("pl_zus_emerytalne", "employer") / HUNDRED)
    if obligations["RENTOWE"]["applies"]:
        disability = capped(pack, bases["RENTOWE"]["base"], _ytd(pack, ytd, "ZUS_CAP_DISABILITY_BASE"), cap)
        disability_ee = rnd(disability["assessed"] * pack.pct("pl_zus_rentowe", "employee") / HUNDRED)
        disability_er = rnd(disability["assessed"] * pack.pct("pl_zus_rentowe", "employer") / HUNDRED)
    if obligations["CHOROBOWE"]["applies"]:
        sickness = rnd(bases["CHOROBOWE"]["base"] * pack.pct("pl_zus_chorobowe", "employee") / HUNDRED)
    if obligations["WYPADKOWE"]["applies"]:
        accident = rnd(bases["WYPADKOWE"]["base"] * dec(applicability["accident"]["ratePct"]) / HUNDRED)

    out["employee"] = {"EMERYTALNE": pension_ee, "RENTOWE": disability_ee, "CHOROBOWE": sickness}
    out["employer"] = {"EMERYTALNE": pension_er, "RENTOWE": disability_er, "WYPADKOWE": accident}
    out["employeeTotal"] = pension_ee + disability_ee + sickness
    out["employerTotal"] = pension_er + disability_er + accident
    out["pension"], out["disability"] = pension, disability
    out["capCrossed"] = any(x is not None and x["crossed"] for x in (pension, disability))

    def cap_trace(x):
        if x is None:
            return None
        return {k: (money(v) if isinstance(v, Decimal) else v) for k, v in x.items()}

    out["trace"] = {
        "cap": money(cap), "pension": cap_trace(pension), "disability": cap_trace(disability),
        "sicknessBase": money(bases["CHOROBOWE"]["base"]) if obligations["CHOROBOWE"]["applies"] else None,
        "accidentBase": money(bases["WYPADKOWE"]["base"]) if obligations["WYPADKOWE"]["applies"] else None,
        "accidentRatePct": applicability["accident"]["ratePct"] if applicability["accident"] else None,
        "employee": {k: money(v) for k, v in out["employee"].items()},
        "employer": {k: money(v) for k, v in out["employer"].items()},
    }
    return out
