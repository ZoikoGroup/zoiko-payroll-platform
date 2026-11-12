"""Belgium wage floors and wage rules (ZP-BE-ENG-001 §4 "Sector-first wage
rule", BE-020 / BE-021; Block B1). Pure.

* Sector minimum first: the employee's classification -> its ACTIVE Joint
  Committee agreement -> modules["wage_scales"] (rows by function class,
  seniority and schedule regime; written by the Belgium-only Super Admin route
  on Draft agreements, user decision 2026-11-12). The row with the highest
  seniorityFromMonths not above the employee's seniority wins.
* The interprofessional guaranteed minimum (RMMMG, be_wage_rmmmg) is a fallback
  ONLY when no sector minimum applies (the agreement has no wage_scales
  module); the reason is in the trace. With a committee but no agreement
  linked, there is no fallback (spec §2).
* Any breach is a run EXCEPTION — the engine never tops up pay.
* Index-centime limitation and sector indexation: only when an indexation input
  is supplied, from signed content (pending blocks).
* Wage norm (be_wage_norm_margin): a WARNING only.
The minimum is compared with the SECTOR_MIN_WAGE base (signed earning-class
matrix, BE-006), never with gross.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec, field, in_window, upper

_PERCENT = Decimal("100")


def _age(birth: Optional[date], on: date) -> Optional[int]:
    if birth is None:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _scale_rows(agreement) -> Optional[list]:
    modules = field(agreement, "modules")
    if not isinstance(modules, dict) or "wage_scales" not in modules:
        return None
    return list(modules.get("wage_scales") or [])


def select_scale_row(rows: list, function_class, seniority_months, regime, on: date):
    """The scale row for this function class / seniority / regime on `on`."""
    fit = []
    for row in rows:
        if upper(row.get("functionClass")) != upper(function_class):
            continue
        if row.get("scheduleRegime") and upper(row.get("scheduleRegime")) != upper(regime):
            continue
        if not in_window(row.get("effectiveFrom"), row.get("effectiveTo"), on):
            continue
        if int(row.get("seniorityFromMonths") or 0) > int(seniority_months or 0):
            continue
        fit.append(row)
    if not fit:
        return None
    return max(fit, key=lambda r: (int(r.get("seniorityFromMonths") or 0), bool(r.get("scheduleRegime"))))


def compute_be_wage_floor(pack: BePack, line: dict, agreement, schedule: Optional[dict], pay_basis: str,
                          paid_base: Decimal, hours_paid, date_of_birth, pay_date: date) -> dict:
    """{"source", "required", "paid", "exception", "trace"} — never blocks on a
    breach; blocks only on pending content that the check needs."""
    weekly = dec((schedule or {}).get("weeklyHours")) if schedule and schedule.get("weeklyHours") else None
    trace = {"paid": str(paid_base), "payBasis": pay_basis}
    exception = None

    def unverified(reason: str) -> dict:
        return {"source": trace.get("source"), "required": None, "paid": paid_base,
                "exception": {"code": E.SECTOR_MINIMUM_UNVERIFIED, "detail": reason}, "trace": {**trace,
                                                                                             "unverified": reason}}

    rows = _scale_rows(agreement) if agreement is not None else None
    if agreement is None:
        trace["source"] = "NONE"
        trace["reason"] = ("no Joint Committee agreement is linked; there is no fallback to the interprofessional "
                           "minimum while a committee applies (spec §2)")
        return {"source": "NONE", "required": None, "paid": paid_base, "exception": None, "trace": trace}
    if rows is not None:
        trace["source"] = "SECTOR"
        row = select_scale_row(rows, line.get("functionClass"), line.get("seniorityMonths"),
                               (schedule or {}).get("regime"), pay_date)
        if row is None:
            return {"source": "SECTOR", "required": None, "paid": paid_base,
                    "exception": {"code": E.SCALE_ROW_MISSING,
                                  "detail": "the agreement has wage scales but none for this function class / "
                                            "seniority / schedule"}, "trace": trace}
        trace["scaleRow"] = row
        if pay_basis == "HOURLY":
            if row.get("hourlyMinimum") in (None, ""):
                return unverified("the scale row has no hourly minimum for an hourly-paid worker")
            if hours_paid is None:
                return unverified("the hours paid are not known, so the hourly minimum cannot be checked")
            required = dec(row["hourlyMinimum"]) * dec(hours_paid)
        else:
            if row.get("monthlyMinimum") in (None, ""):
                return unverified("the scale row has no monthly minimum for a salaried worker")
            required = dec(row["monthlyMinimum"])
            full_time = dec(row.get("fullTimeWeeklyHours"))
            if weekly is not None and full_time > ZERO and weekly < full_time:
                required = required * weekly / full_time                   # part-time pro rata
    else:
        # No sector minimum applies (the agreement carries no wage_scales): the
        # RMMMG fallback, with the reason (spec §4, BE-021).
        trace["source"] = "RMMMG"
        trace["reason"] = "the Joint Committee agreement defines no wage scale; the interprofessional minimum applies"
        minimum_age = pack.amount("be_wage_rmmmg_min_age")
        age = _age(as_date(date_of_birth), pay_date)
        if age is None:
            return unverified("the date of birth is not known, so the minimum-age condition cannot be checked")
        if dec(age) < minimum_age:
            return unverified("the worker is below the minimum age of the interprofessional minimum; the youth "
                              "rules are not certified")
        required = pack.amount("be_wage_rmmmg")
        full_time = pack.amount("be_wt_weekly_limit_hours")
        if weekly is not None and full_time > ZERO and weekly < full_time:
            required = required * weekly / full_time
    trace["required"] = str(required)
    if paid_base < required:
        exception = {"code": E.MINIMUM_WAGE_BREACH,
                     "detail": f"pay below the {trace['source'].lower()} minimum (paid {paid_base}, required "
                               f"{required}); never topped up automatically"}
    return {"source": trace["source"], "required": required, "paid": paid_base, "exception": exception,
            "trace": trace}


def compute_be_indexation(pack: BePack, indexation: Optional[dict], reference_salary: Decimal) -> dict:
    """Index-centime limitation (only when an indexation input is supplied):
    the signed formula be_wage_index_centime_rule caps the indexation increase
    above be_wage_index_centime_threshold. Pending content blocks."""
    if not indexation:
        return {"applied": False, "exception": None, "warning": None, "trace": {"applied": False}}
    increase = dec(indexation.get("increase"))
    threshold = pack.amount("be_wage_index_centime_threshold")
    capped = pack.formula("be_wage_index_centime_rule", reference=reference_salary, threshold=threshold,
                          increase=increase)
    exception = None
    if increase > capped:
        exception = {"code": E.INDEXATION_ABOVE_LIMIT,
                     "detail": "the indexation increase exceeds the index-centime limitation"}
    warning = None
    margin_input = indexation.get("increasePct")
    if margin_input is not None:
        margin = pack.pct("be_wage_norm_margin", "employer")
        if dec(margin_input) > margin:
            warning = {"code": E.WAGE_NORM_WARNING, "detail": "the wage increase exceeds the wage-norm margin "
                                                             "(warning only)"}
    return {"applied": True, "exception": exception, "warning": warning,
            "trace": {"applied": True, "increase": str(increase), "cappedIncrease": str(capped),
                      "threshold": str(threshold)}}
