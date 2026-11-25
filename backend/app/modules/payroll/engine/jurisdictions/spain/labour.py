"""Labour checks — ZP-ES-ENG-001 §2, §15, ES-010, ES-044, F4 (docs/spain D9, D11).

  smi_check            full-time minimum interprofessional wage (SMI): the
                       employee's ANNUAL equivalent (12 monthly salaries plus
                       the annual extra-pay total when the extras are paid
                       separately) must reach es_smi_annual — the spec's
                       "€17,094/year for full-time annual comparison". A
                       collective-agreement minimum can be higher and is not
                       modelled here (ES-044).
  short_contract_surcharge
                       a TEMPORARY contract shorter than es_short_contract_days
                       that ends in this pay period costs the employer
                       es_short_contract_surcharge, unless the employee is
                       marked as a statutory exception (ES-010). Employer cost,
                       never deducted from the worker.
"""
from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain import params as P
from app.modules.payroll.engine.jurisdictions.spain.params import ZERO, round2


def smi_check(*, monthly_salary, extra_pay_policy, extra_pay_annual_amount, rate_map: dict) -> dict:
    monthly = Decimal(str(monthly_salary or 0))
    extras = Decimal(str(extra_pay_annual_amount or 0)) if (extra_pay_policy or "").upper() == "SEPARATE_14" else ZERO
    annual = round2(monthly * 12 + extras)
    minimum = P.amount(rate_map, "es_smi_annual")
    if annual < minimum:
        raise E.ESCalculationBlockedError(
            E.BELOW_SMI,
            f"the annual equivalent salary {annual} is below the minimum interprofessional wage (SMI) {minimum} "
            "for a full-time employee (ZP-ES-ENG-001 §2, §15).")
    return {"annual_equivalent": annual, "smi_annual": minimum}


def short_contract_surcharge(*, contract_type, date_of_joining, date_of_leaving, period_start: date,
                             period_end: date, exception, rate_map: dict) -> dict:
    result = {"applies": False, "amount": ZERO}
    if (contract_type or "").upper() != "TEMPORARY" or not isinstance(date_of_leaving, date):
        return result
    if not period_start <= date_of_leaving <= period_end:
        return result                                                 # the contract does not end in this run
    if not isinstance(date_of_joining, date):
        raise E.ESCalculationBlockedError(E.keyed(E.EMPLOYEE_FACT_MISSING, "date_of_joining"),
                                          "a temporary contract ending this period needs its start date (ES-010).")
    length_days = (date_of_leaving - date_of_joining).days + 1
    threshold = P.amount(rate_map, "es_short_contract_days")
    result["contract_days"] = length_days
    if Decimal(length_days) >= threshold:
        return result
    if (str(exception or "").upper()) in ("YES", "TRUE", "1"):
        result["exception"] = True
        return result
    result.update(applies=True, amount=round2(P.amount(rate_map, "es_short_contract_surcharge")))
    return result
