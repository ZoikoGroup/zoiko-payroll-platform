"""Poland PPK contributions (ZP-PL-ENG-001 §7, PL-013 / PL-014).

Only for an ENROLLED participant (state decided in applicability). Base = the
PPK earning-class base, which mirrors the pension base WITHOUT the 30x cap
(PL-014). Rates:
  * employee basic: the signed default, or an approved PPK_REDUCED_RATE
    statement — used only while this month's income passes the income test
    (income <= the signed % of the minimum wage). A failed test reverts to the
    default rate for the month and raises a PPK anomaly (PL-013); the
    statement must carry the income from the other relevant sources;
  * employee additional: an approved PPK_ADDITIONAL statement, within the
    signed maximum;
  * employer basic: signed; employer additional: from the employer
    registration, within the signed maximum.
The PIT treatment of the employer contribution is a signed policy
(pl_ppk_employer_pit_treatment) — not stated by the specification.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import declarations as D
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import HUNDRED, ZERO, PlPack, dec, field, money


def _rate(pack: PlPack, raw, key: str, low: Decimal, high: Decimal, code: str) -> Decimal:
    try:
        rate = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        pack.block(E.keyed(code, key), "the PPK rate is not a number")
    if rate < low or rate > high:
        pack.block(E.keyed(code, key), "the PPK rate is outside the signed limits")
    return rate


def compute(pack: PlPack, bases: dict, applicability: dict, declarations, pay_date: date, rnd) -> dict:
    zero = {"employee": {"BASIC": ZERO, "ADDITIONAL": ZERO}, "employer": {"BASIC": ZERO, "ADDITIONAL": ZERO},
            "employeeTotal": ZERO, "employerTotal": ZERO, "employerPitTreatment": None, "exceptions": [],
            "trace": {"applies": False, "reason": applicability["obligations"]["PPK"]["reason"]}}
    if not applicability["obligations"]["PPK"]["applies"]:
        return zero

    base = bases["PPK"]["base"]
    basic = pack.pct("pl_ppk_employee_basic", "employee")
    reduced_min = pack.pct("pl_ppk_employee_reduced_min", "employee")
    ee_additional_max = pack.pct("pl_ppk_employee_additional_max", "employee")
    er_basic = pack.pct("pl_ppk_employer_basic", "employer")
    er_additional_max = pack.pct("pl_ppk_employer_additional_max", "employer")
    treatment = pack.text("pl_ppk_employer_pit_treatment", content.PPK_EMPLOYER_PIT_TREATMENTS)
    exceptions = []

    ee_rate, reduced_trace = basic, None
    reduced = D.in_force(pack, declarations, "PPK_REDUCED_RATE", pay_date)
    if reduced is not None:
        requested = _rate(pack, D.value(reduced, "ratePct"), "PPK_REDUCED_RATE", reduced_min, basic,
                          E.PPK_DECLARATION_INVALID)
        other = D.value(reduced, "otherSourcesIncome")
        if other is None or dec(other) < ZERO:
            pack.block(E.keyed(E.PPK_DECLARATION_INVALID, "otherSourcesIncome"),
                       "the reduced-rate statement must state income from other relevant sources")
        income = base + dec(other)
        limit = pack.amount("pl_min_wage_monthly") * pack.pct("pl_ppk_reduced_income_pct_min_wage",
                                                              "employee") / HUNDRED
        passed = income <= limit
        if passed:
            ee_rate = requested
        else:
            exceptions.append({"code": E.EXC_PPK_REDUCED_RATE_LAPSED,
                               "detail": "reduced PPK rate not applied: income test failed this month"})
        reduced_trace = {"declaration": D.describe(reduced), "requestedPct": str(requested),
                         "income": money(income), "limit": money(limit), "passed": passed}

    ee_additional = ZERO
    additional = D.in_force(pack, declarations, "PPK_ADDITIONAL", pay_date)
    if additional is not None:
        ee_additional = _rate(pack, D.value(additional, "ratePct"), "PPK_ADDITIONAL", ZERO, ee_additional_max,
                              E.PPK_DECLARATION_INVALID)
    registration = applicability["registration"]
    raw_er_additional = field(registration, "ppk_employer_additional_pct")
    er_additional = ZERO if raw_er_additional in (None, "") else _rate(
        pack, raw_er_additional, "ppk_employer_additional_pct", ZERO, er_additional_max, E.PPK_RATE_INVALID)

    employee = {"BASIC": rnd(base * ee_rate / HUNDRED), "ADDITIONAL": rnd(base * ee_additional / HUNDRED)}
    employer = {"BASIC": rnd(base * er_basic / HUNDRED), "ADDITIONAL": rnd(base * er_additional / HUNDRED)}
    out = {"employee": employee, "employer": employer,
           "employeeTotal": employee["BASIC"] + employee["ADDITIONAL"],
           "employerTotal": employer["BASIC"] + employer["ADDITIONAL"],
           "employerPitTreatment": treatment, "exceptions": exceptions}
    out["trace"] = {"applies": True, "base": money(base), "capped": False,
                    "employeeBasicPct": str(ee_rate), "employeeAdditionalPct": str(ee_additional),
                    "employerBasicPct": str(er_basic), "employerAdditionalPct": str(er_additional),
                    "reducedRate": reduced_trace, "employerPitTreatment": treatment,
                    "employee": {k: money(v) for k, v in employee.items()},
                    "employer": {k: money(v) for k, v in employer.items()}}
    return out
