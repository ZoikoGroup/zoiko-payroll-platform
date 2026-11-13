"""Belgium holiday pay (ZP-BE-ENG-001 §8, BE-024 .. BE-028; Block B2). Pure.

Two SEPARATE strategies (BE-025), chosen by the worker category:

* White-collar (EMPLOYEE): simple holiday pay is the employer's continued
  salary (be_hol_wc_simple_rule, signed acknowledgement); double holiday pay is
  be_hol_wc_double_pct of the reference salary, pro rata the months worked in
  the SERVICE year, minus what a prior employer already paid for that service
  year (approved IN holiday certificates) and minus the additional-holiday
  advance to offset (BE-026); additional holidays (be_hol_additional_rule) are
  advanced and recorded for that offset; departure pay (be_hol_departure_rule)
  on exit.
* Manual (MANUAL): the holiday-fund regime — the employer pays NO simple or
  double holiday pay (the fund does); paying one is an exception. The quarterly
  contribution is an obligation delta (onss.py); the annual debit
  (be_hol_manual_annual_debit) on the prior service year's base is reconciled
  here when requested.

The service year (the year the remuneration was earned) is kept separate from
the taking year (BE-024); the holiday base is the HOLIDAY_BASE obligation of the
service year — never the sector minimum or the RMMMG (BE-028). A worker-category
change inside the service year is an explicit transition exception. Holiday pay
is VERIFIED, never topped up: due > paid is an exception.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec, field, upper

_PERCENT = Decimal("100")
_MONTHS_PER_YEAR = Decimal("12")           # calendar fact


def _category_changes(history, service_year: int) -> list:
    seen = []
    for row in sorted(history or [], key=lambda r: str(field(r, "effective_from"))):
        start, end = as_date(field(row, "effective_from")), as_date(field(row, "effective_to"))
        if upper(field(row, "status")) not in ("ACTIVE", "SUPERSEDED"):
            continue
        if start.year > service_year or (end is not None and end.year < service_year):
            continue
        category = upper(field(row, "worker_category"))
        if not seen or seen[-1] != category:
            seen.append(category)
    return seen


def compute_be_holiday(pack: BePack, worker: dict, pay: dict, holiday: Optional[dict], certificates, history,
                       pay_date) -> dict:
    """{"strategy", "due", "exceptions", "deltas", "obligations", "trace"}."""
    holiday = holiday or {}
    category = worker.get("workerCategory")
    service_year = int(holiday.get("serviceYear") or (pay_date.year - 1))
    trace = {"serviceYear": service_year, "takingYear": pay_date.year, "category": category}
    exceptions, deltas, obligations = [], {}, {}
    changes = _category_changes(history, service_year)
    if len(changes) > 1:
        exceptions.append({"code": E.HOLIDAY_CATEGORY_TRANSITION,
                           "detail": f"the worker category changed in service year {service_year} "
                                     f"({' -> '.join(changes)}); holiday pay needs the transition handled explicitly"})
    simple_paid = pay.get("HOLIDAY_PAY_SIMPLE", ZERO)
    double_paid = pay.get("HOLIDAY_PAY_DOUBLE", ZERO)
    departure_paid = pay.get("DEPARTURE_HOLIDAY_PAY", ZERO)
    rnd = None
    if category == "MANUAL":
        trace["strategy"] = "MANUAL_FUND"
        if simple_paid != ZERO or double_paid != ZERO:
            exceptions.append({"code": E.HOLIDAY_PAID_BY_FUND,
                               "detail": "a manual worker's holiday pay is paid by the holiday fund, not the employer"})
        if holiday.get("reconcileFund"):
            rnd = pack.rounder("be_rounding_holiday")
            base = dec(holiday.get("priorYearBase"))
            obligations["HOLIDAY_FUND_ANNUAL_DEBIT"] = rnd(base * pack.pct("be_hol_manual_annual_debit", "employer")
                                                           / _PERCENT)
            trace["fundReconciliation"] = {"priorYearBase": str(base),
                                           "annualDebit": str(obligations["HOLIDAY_FUND_ANNUAL_DEBIT"]),
                                           "declared": holiday.get("fundDeclared")}
            declared = holiday.get("fundDeclared")
            if declared is not None and dec(declared) != obligations["HOLIDAY_FUND_ANNUAL_DEBIT"]:
                exceptions.append({"code": E.HOLIDAY_FUND_MISMATCH,
                                   "detail": "the holiday-fund debit declared differs from the debit due"})
        return {"strategy": "MANUAL_FUND", "due": {}, "exceptions": exceptions, "deltas": deltas,
                "obligations": obligations, "trace": trace}

    trace["strategy"] = "WHITE_COLLAR_EMPLOYER"
    due = {}
    if simple_paid != ZERO:
        trace["simpleRule"] = pack.text("be_hol_wc_simple_rule")        # simple pay = continued salary (ack)
        deltas["HOLIDAY_SIMPLE_PAID"] = simple_paid
    if double_paid != ZERO or holiday.get("payDouble"):
        rnd = pack.rounder("be_rounding_holiday")
        reference = dec(holiday.get("referenceSalary"))
        if reference == ZERO:
            pack.block(E.FACT_MISSING, "holiday_reference_salary",
                       "double holiday pay needs the reference salary of the service year (HOLIDAY_BASE)")
        months = dec(holiday.get("monthsWorked") if holiday.get("monthsWorked") is not None else _MONTHS_PER_YEAR)
        gross_due = reference * pack.pct("be_hol_wc_double_pct", "employee") / _PERCENT * months / _MONTHS_PER_YEAR
        prior = sum((dec(field(c, "double_pay_amount")) for c in certificates or ()
                     if upper(field(c, "direction")) == "IN" and upper(field(c, "status")) == "APPROVED"
                     and int(field(c, "service_year") or 0) == service_year), ZERO)
        advance = dec(holiday.get("advanceOutstanding"))
        double_due = rnd(max(ZERO, gross_due - prior - advance))
        trace["contributionRule"] = pack.text("be_hol_wc_double_contribution_rule")
        trace["double"] = {"reference": str(reference), "monthsWorked": str(months), "gross": str(gross_due),
                           "priorEmployer": str(prior), "advanceOffset": str(advance), "due": str(double_due)}
        due["HOLIDAY_PAY_DOUBLE"] = double_due
        if advance != ZERO:
            deltas["ADDITIONAL_HOLIDAY_ADVANCE"] = -min(advance, gross_due)       # the offset consumes the advance
        if double_paid < double_due:
            exceptions.append({"code": E.HOLIDAY_PAY_SHORT, "detail": "double holiday pay below the amount due"})
        deltas["HOLIDAY_DOUBLE_PAID"] = double_paid
    if holiday.get("additionalDays"):
        rnd = rnd or pack.rounder("be_rounding_holiday")
        additional = rnd(max(ZERO, pack.formula("be_hol_additional_rule", days=dec(holiday["additionalDays"]),
                                                reference=dec(holiday.get("referenceSalary")))))
        due["ADDITIONAL_HOLIDAY"] = additional
        deltas["ADDITIONAL_HOLIDAY_ADVANCE"] = deltas.get("ADDITIONAL_HOLIDAY_ADVANCE", ZERO) + additional
        trace["additional"] = {"days": str(holiday["additionalDays"]), "advance": str(additional)}
    if holiday.get("departure") or departure_paid != ZERO:
        rnd = rnd or pack.rounder("be_rounding_holiday")
        departure = holiday.get("departure") or {}
        departure_due = rnd(max(ZERO, pack.formula(
            "be_hol_departure_rule", reference=dec(departure.get("reference") or holiday.get("referenceSalary")),
            months=dec(departure.get("monthsWorked")), prior_months=dec(departure.get("priorYearMonths")))))
        due["DEPARTURE_HOLIDAY_PAY"] = departure_due
        trace["departure"] = {"due": str(departure_due)}
        if departure_paid < departure_due:
            exceptions.append({"code": E.HOLIDAY_PAY_SHORT, "detail": "departure holiday pay below the amount due"})
    return {"strategy": "WHITE_COLLAR_EMPLOYER", "due": due, "exceptions": exceptions, "deltas": deltas,
            "obligations": obligations, "trace": trace}
