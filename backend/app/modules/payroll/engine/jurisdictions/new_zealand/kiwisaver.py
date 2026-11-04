"""KiwiSaver employee deduction and employer contribution (spec §4).

Rates are selected by the payday (NZ-008). A temporary rate reduction and a
savings suspension apply only with evidence and inside their dates; a zero
deduction is never inferred (NZ-009). Gross employer contribution, ESCT and
net contribution are kept separate, with the settlement destination (NZ-007).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from typing import Optional

from . import errors as E
from . import esct as _esct
from .pack import HUNDRED, ZERO, NzPack, as_date, dec, field, in_window, money, upper

CONTRIBUTING = "CONTRIBUTING"
NOT_CONTRIBUTING = ("NOT_MEMBER", "OPTED_OUT", "NOT_ELIGIBLE")


@dataclass
class KsResult:
    status: str
    employee_rate: Optional[Decimal] = None
    employee: Decimal = ZERO
    employer_rate: Optional[Decimal] = None
    employer_gross: Decimal = ZERO
    esct_rate: Optional[Decimal] = None
    esct: Decimal = ZERO
    employer_net: Decimal = ZERO
    destination: Optional[str] = None
    complying_fund_ref: Optional[str] = None
    compulsory_employer: bool = False
    reduction_applied: bool = False
    age: Optional[int] = None
    steps: list = dc_field(default_factory=list)


def age_on(dob, on: date) -> int:
    dob = as_date(dob)
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def calculate_kiwisaver(base: Decimal, election, dob, pay_date: date, pack: NzPack) -> KsResult:
    if election is None:
        return KsResult("NOT_MEMBER", steps=[{"step": "election", "value": "none", "note": None}])
    if upper(field(election, "status")) != "ACTIVE" \
            or not in_window(field(election, "effective_from"), field(election, "effective_to"), pay_date):
        pack.block(E.keyed(E.PROFILE_NOT_ACTIVE, "kiwisaver"), "no ACTIVE KiwiSaver election covers the payday")
    if upper(field(election, "employer_contribution_treatment")) == "PAYE_ALTERNATIVE":
        pack.block(E.KS_PAYE_ALTERNATIVE_UNSUPPORTED,
                   "employer contributions taxed under PAYE instead of ESCT are outside the first release")
    destination, fund = upper(field(election, "settlement_destination")) or None, field(election, "complying_fund_ref")
    state = upper(field(election, "membership_state"))
    if state in NOT_CONTRIBUTING:
        return KsResult(state, destination=destination, complying_fund_ref=fund,
                        steps=[{"step": "state", "value": state, "note": None}])
    if state == "SAVINGS_SUSPENSION":
        if not field(election, "suspension_ref") or field(election, "suspension_from") is None:
            pack.block(E.KS_SUSPENSION_UNEVIDENCED, "a savings suspension needs its Inland Revenue reference and dates")
        if in_window(field(election, "suspension_from"), field(election, "suspension_to"), pay_date):
            return KsResult("SUSPENDED", destination=destination, complying_fund_ref=fund,
                            steps=[{"step": "state", "value": "SUSPENDED", "note": None}])
    elif state != CONTRIBUTING:
        pack.block(E.KS_RATE_UNSUPPORTED, f"KiwiSaver membership state {state or 'missing'!r} is not recognised")

    rnd = pack.rounder("nz_ks_rounding")
    reduction = bool(field(election, "reduction_ref")) and field(election, "reduction_from") is not None \
        and in_window(field(election, "reduction_from"), field(election, "reduction_to"), pay_date)
    allowed = [dec(rate) for rate in pack.text_list("nz_ks_employee_rates")]
    if reduction:
        employee_rate = pack.pct("nz_ks_temporary_reduction_rate")
    elif field(election, "employee_rate_pct") is None:
        employee_rate = pack.pct("nz_ks_default_rate")
    else:
        employee_rate = dec(field(election, "employee_rate_pct"))
        if employee_rate not in allowed:
            pack.block(E.KS_RATE_UNSUPPORTED, f"employee rate {employee_rate}% is not a standard KiwiSaver rate")
    employee = rnd(base * employee_rate / HUNDRED)

    if dob is None:
        pack.block(E.KS_AGE_UNKNOWN, "the member's date of birth is needed for employer contributions")
    age = age_on(dob, pay_date)
    compulsory = pack.amount("nz_ks_employer_min_age") <= age < pack.amount("nz_ks_employer_max_age")
    minimum = pack.pct("nz_ks_employer_min_rate")
    if reduction and field(election, "employer_matches_reduction"):
        minimum = pack.pct("nz_ks_temporary_reduction_rate")
    stated = field(election, "employer_rate_pct")
    if compulsory:
        employer_rate = dec(stated) if stated is not None else minimum
        if employer_rate < minimum:
            pack.block(E.KS_EMPLOYER_RATE_BELOW_MINIMUM,
                       f"employer rate {employer_rate}% is below the compulsory minimum {minimum}%")
    else:
        employer_rate = dec(stated) if stated is not None else ZERO
    employer_gross = rnd(base * employer_rate / HUNDRED)
    esct_rate, esct = None, ZERO
    if employer_gross > ZERO:
        esct_rate = _esct.resolve_esct_rate(election, pack)["rate"]
        esct = _esct.calculate_esct(employer_gross, esct_rate, pack)
    steps = [{"step": "employeeRate", "value": str(employee_rate), "note": "reduction" if reduction else None},
             {"step": "employee", "value": money(employee), "note": None},
             {"step": "employerRate", "value": str(employer_rate),
              "note": "compulsory" if compulsory else "voluntary"},
             {"step": "employerGross", "value": money(employer_gross), "note": None},
             {"step": "esct", "value": money(esct), "note": f"{esct_rate}%" if esct_rate is not None else None}]
    return KsResult(CONTRIBUTING, employee_rate, employee, employer_rate, employer_gross, esct_rate, esct,
                    employer_gross - esct, destination, fund, compulsory, reduction, age, steps)
