"""Ordinary Social Security contributions — ZP-ES-ENG-001 §2, §4, ES-008, ES-009, ES-042.

Per family, employee and employer amounts on the correct base, each rounded
half-up to the cent:

  es_cc                      common base         (contingencias comunes)
  es_mei                     common base         (intergenerational equity)
  es_unemployment_general /  AT/EP base          chosen by contract_type (D8)
  es_unemployment_temporary
  es_fogasa                  AT/EP base          employer only
  es_training                AT/EP base
  overtime additional        overtime pay        es_overtime_other or
                                                 es_overtime_force_majeure
  AT/EP                      AT/EP base          employer only, the EMPLOYER's
                                                 own premium rate (ES-008, G-03)

Employer amounts are employer cost; they never reduce net pay (ES-042).
"""
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain import params as P
from app.modules.payroll.engine.jurisdictions.spain.params import ZERO, round2

CONTRACT_TYPES = ("INDEFINITE", "TEMPORARY")
OVERTIME_KINDS = ("OTHER", "FORCE_MAJEURE")


def unemployment_key(contract_type) -> str:
    contract_type = (contract_type or "").upper()
    if contract_type not in CONTRACT_TYPES:
        raise E.ESCalculationBlockedError(E.keyed(E.EMPLOYEE_FACT_MISSING, "contract_type"),
                                          "the employee needs contract_type INDEFINITE or TEMPORARY (ES-009).")
    return "es_unemployment_general" if contract_type == "INDEFINITE" else "es_unemployment_temporary"


def at_ep_rate(value) -> Decimal:
    """The employer's AT/EP premium as a fraction (0.015 = 1.50%). There is no
    universal Spanish rate (ES-008), so a missing or invalid one blocks."""
    try:
        rate = Decimal(str(value).strip()) if value is not None and str(value).strip() != "" else None
    except Exception:  # noqa: BLE001
        rate = None
    if rate is None or rate < ZERO or rate >= Decimal(1):
        raise E.ESCalculationBlockedError(
            E.AT_EP_RATE_MISSING,
            "the employer's AT/EP premium rate (es_at_ep_rate, a fraction such as 0.015) is not set; it comes from "
            "the employer's own premium tariff (ES-008) — add it in Compliance → Company details.")
    return rate


def _line(family, key, base, employee_rate, employer_rate):
    return {"family": family, "key": key, "base": base, "employee_rate": employee_rate, "employer_rate": employer_rate,
            "employee": round2(base * employee_rate), "employer": round2(base * employer_rate)}


def compute(*, bases: dict, contract_type, overtime_kind, employer_at_ep_rate, rate_map: dict) -> dict:
    common, at_ep = bases["common"], bases["at_ep"]
    unemployment = unemployment_key(contract_type)
    lines = []
    for family, key, base in (("common_contingencies", "es_cc", common), ("mei", "es_mei", common),
                              ("unemployment", unemployment, at_ep), ("fogasa", "es_fogasa", at_ep),
                              ("training", "es_training", at_ep)):
        lines.append(_line(family, key, base, P.pct_or_zero(rate_map, key, "employee"),
                           P.pct_or_zero(rate_map, key, "employer")))

    overtime = bases["overtime_pay"]
    if overtime > ZERO:
        kind = (overtime_kind or "OTHER").upper()
        if kind not in OVERTIME_KINDS:
            raise E.ESCalculationBlockedError(E.keyed(E.EMPLOYEE_FACT_MISSING, "overtime_kind"),
                                              "overtime_kind must be OTHER or FORCE_MAJEURE (ZP-ES-ENG-001 §4).")
        key = "es_overtime_force_majeure" if kind == "FORCE_MAJEURE" else "es_overtime_other"
        lines.append(_line("overtime", key, overtime, P.pct(rate_map, key, "employee"),
                           P.pct(rate_map, key, "employer")))

    rate = at_ep_rate(employer_at_ep_rate)
    lines.append(_line("at_ep", "es_at_ep_rate", at_ep, ZERO, rate))

    return {
        "lines": lines,
        "unemployment_key": unemployment,
        "employee_total": round2(sum((l["employee"] for l in lines), ZERO)),
        "employer_total": round2(sum((l["employer"] for l in lines if l["family"] != "at_ep"), ZERO)),
        "at_ep_employer": next(l["employer"] for l in lines if l["family"] == "at_ep"),
    }
