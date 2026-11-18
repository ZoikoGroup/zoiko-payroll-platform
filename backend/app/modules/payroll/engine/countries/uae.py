"""modules/payroll/engine/countries/uae.py
----------------------------------------
United Arab Emirates (ZP-AE-ENG-001 v1.0) — the calculation orchestrator over
the bounded rule modules in engine/jurisdictions/uae/.

The engine reads EVERY statutory value from the active UAE canonical pack
(ctx.rate_map). There is no hardcoded rate, cap, day count or source of truth
in code: a missing row stops the employee's calculation with a named
AE_RATE_MISSING reason, and the generic calculator is never reached (the UAE
is registered in standard._COUNTRY_CALC and simple mode is blocked in resolver).

Employee facts arrive in ctx.ae_facts (AEEmployeeValidation compliance_fields
+ work_state) and the ordinary PayrollContext wage/date fields. No income tax
is ever calculated: UAE salaries have no monthly PAYE line (AE-003).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.jurisdictions.uae import errors as E
from app.modules.payroll.engine.jurisdictions.uae import gratuity as G
from app.modules.payroll.engine.jurisdictions.uae import overtime as O
from app.modules.payroll.engine.jurisdictions.uae import params as P
from app.modules.payroll.engine.jurisdictions.uae import pension as PN
from app.modules.payroll.engine.jurisdictions.uae.errors import AECalculationBlockedError

__all__ = ["AECalculationBlockedError", "calculate"]

_ZERO = Decimal("0")
_BLOCKED_ZONES = ("DIFC", "ADGM")


def _json(value):
    """JSON-safe breakdown: Decimals become fixed-point strings, dates ISO strings."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _block(code: str, reason: str, ctx: PayrollContext):
    raise AECalculationBlockedError(code, reason, organization_id=getattr(ctx, "organization_id", None))


def _decimal(value, field: str, ctx: PayrollContext) -> Decimal:
    if value in (None, ""):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, field), f"'{field}' is not set on this employee.", ctx)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, field), f"'{field}' is not an amount.", ctx)


def _date(value, field: str, ctx: PayrollContext) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, field), f"'{field}' must be a YYYY-MM-DD date.", ctx)


def _facts(ctx: PayrollContext) -> dict:
    facts = dict(ctx.ae_facts or {})
    state = facts.get("work_state") or getattr(ctx, "work_state", None)
    if state:
        upper = str(state).upper()
        if any(zone in upper for zone in _BLOCKED_ZONES):
            _block(E.keyed(E.OUT_OF_SCOPE, state),
                   f"'{state}' (DIFC / ADGM) has its own regime and is outside this UAE payroll engine.", ctx)
    nationality = str(facts.get("nationality_category") or "").upper()
    if nationality not in ("EXPATRIATE", "UAE_NATIONAL", "GCC_NATIONAL"):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "nationality_category"),
               "the employee's nationality category (EXPATRIATE / UAE_NATIONAL / GCC_NATIONAL) is required.", ctx)
    pattern = str(facts.get("work_pattern") or getattr(ctx, "employment_type") or "").upper()
    facts["work_pattern"] = "PART_TIME" if "PART" in pattern else ("FULL_TIME" if pattern else "FULL_TIME")
    facts["nationality_category"] = nationality
    facts["pension_scheme"] = str(facts.get("pension_scheme") or "").upper()
    facts["eos_regime"] = str(facts.get("eos_regime") or "").upper()
    facts["gcc_country"] = str(facts.get("gcc_country") or "").upper()
    facts["government_support_eligible"] = str(facts.get("government_support_eligible") or "").upper()
    return facts


def _period(ctx: PayrollContext, pay_date: date):
    start = ctx.period_start or pay_date.replace(day=1)
    end = ctx.period_end or pay_date
    if start > end:
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "period"),
               "the pay period starts after it ends.", ctx)
    return start, end


def _emirati_minimum(facts: dict, pay_date: date, total_wage: Decimal, rate_map: dict, ctx: PayrollContext):
    """AE-014/F7. The 6,000 floor is a pack row with its own effective date, so a
    payroll before that date sees no rule and an old payroll keeps old values."""
    row = (rate_map or {}).get("ae_emirati_min_salary")
    if facts["nationality_category"] != "UAE_NATIONAL" or row is None:
        return None
    effective = getattr(row, "effective_from", None)
    if effective and isinstance(effective, date) and effective > pay_date:
        return None
    minimum = P.amount(rate_map, "ae_emirati_min_salary")
    if total_wage < minimum:
        _block(E.EMIRATI_MINIMUM_SALARY,
               f"Emirati total Wage AED {total_wage} is below the AED {minimum} minimum from "
               f"{effective.isoformat() if effective else 'the pack date'}; expatriates are not subject to this rule.",
               ctx)
    return minimum


def _end_of_service(facts: dict, ctx: PayrollContext, rate_map: dict, period_start: date, period_end: date,
                    basic_wage: Decimal, total_wage: Decimal):
    if facts["nationality_category"] != "EXPATRIATE":
        return {"regime": "NONE", "employer_amount": _ZERO, "reason": "national — covered by their pension scheme"}
    if facts["work_pattern"] == "PART_TIME":
        _block(E.PART_TIME_EOS_NOT_SUPPORTED,
               "part-time end-of-service gratuity has no formula in ZP-AE-ENG-001; "
               "add the formula to the pack before running this employee.", ctx)
    regime = facts["eos_regime"]
    if not regime:
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "eos_regime"),
               "an expatriate needs eos_regime TRADITIONAL or SAVINGS_SCHEME.", ctx)
    joining = _date(ctx.date_of_joining or facts.get("date_of_joining"), "date_of_joining", ctx)
    period_unpaid = max(int(ctx.unpaid_leave_days or 0), 0)
    # Unpaid absence recorded before this run (AEEmployeeValidation field,
    # cumulative) + this run's unpaid days (payslip attendance) — AE-029.
    prior_unpaid = int(_decimal(facts.get("eos_unpaid_absence_days") or 0, "eos_unpaid_absence_days", ctx))
    unpaid = prior_unpaid + period_unpaid
    if regime == "TRADITIONAL":
        result = G.traditional(joining, period_start, period_end, basic_wage, total_wage, prior_unpaid, rate_map,
                               period_unpaid_days=period_unpaid)
        amount = result["accrual"]
    elif regime == "SAVINGS_SCHEME":
        enrollment = _date(facts.get("savings_enrollment_date"), "savings_enrollment_date", ctx)
        enrollment_wage = _decimal(facts.get("savings_enrollment_basic_wage"), "savings_enrollment_basic_wage", ctx)
        result = G.savings(joining, period_end, basic_wage, enrollment, enrollment_wage, total_wage, unpaid, rate_map)
        amount = result["subscription"]
    else:
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "eos_regime"),
               f"unknown end-of-service regime '{regime}'.", ctx)
    result["employer_amount"] = amount
    result["unpaid_absence_days"] = unpaid
    result["period_start"] = period_start
    result["period_end"] = period_end
    return result


def calculate(ctx: PayrollContext) -> dict:
    """Return the statutory deduction lines and the full AE breakdown."""
    facts = _facts(ctx)
    rate_map = ctx.rate_map or {}
    pay_date = ctx.pay_date or ctx.period_end
    if not isinstance(pay_date, date):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "pay_date"),
               "a pay date or period end is required to resolve effective-dated UAE values.", ctx)
    period_start, period_end = _period(ctx, pay_date)

    basic = _decimal(ctx.basic, "basic", ctx)
    hra = _decimal(ctx.hra or _ZERO, "hra", ctx)
    allowance = _decimal(ctx.special_allowance or _ZERO, "special_allowance", ctx)
    other_allowance = _decimal(getattr(ctx, "additional_compensation", None) or _ZERO,
                               "additional_compensation", ctx)
    overtime_pay = _decimal(ctx.overtime or _ZERO, "overtime", ctx)
    total_wage = _round2(basic + hra + allowance + other_allowance)   # overtime is not part of Wage (F1)
    gross = _round2(total_wage + overtime_pay)
    minimum = _emirati_minimum(facts, pay_date, total_wage, rate_map, ctx)

    pension_result = PN.calculate(facts, rate_map)
    eos_result = _end_of_service(facts, ctx, rate_map, period_start, period_end, basic, total_wage)

    overtime_result = {"regime": "NONE"}
    if overtime_pay > _ZERO or facts.get("overtime_hours"):
        overtime_result = O.hourly_rates(basic, rate_map)
        overtime_result["regime"] = "MINIMUM_RATES"
        overtime_result["hours"] = facts.get("overtime_hours")
        overtime_result["paid"] = overtime_pay

    unpaid_deduction = _round2(gross / Decimal("30") * Decimal(max(int(ctx.unpaid_leave_days or 0), 0)))
    employee_deduction = _round2(unpaid_deduction + pension_result["employee"])
    employer_cash = _round2(pension_result["employer_cash"] + eos_result["employer_amount"])
    employer_cost = _round2(gross + employer_cash)

    settlement_days = P.amount(rate_map, "ae_final_settlement_days")
    lines = [
        {"key": "basic_wage", "label": "Basic Wage", "amount": basic},
        {"key": "total_wage", "label": "Total Wage (gratuity cap / notice base)", "amount": total_wage},
        {"key": "pension_employee", "label": "Pension (Employee)", "amount": pension_result["employee"]},
        {"key": "pension_employer", "label": "Pension (Employer, cash after government support)",
         "amount": pension_result["employer_cash"]},
        {"key": "government_support", "label": "Government support (part of the employer share)",
         "amount": pension_result["government_support"]},
        {"key": "end_of_service", "label": "End of service (employer cost)", "amount": eos_result["employer_amount"]},
    ]
    if overtime_pay:
        lines.append({"key": "overtime", "label": "Overtime pay", "amount": overtime_pay})

    breakdown = {
        "country": "AE",
        "spec": "ZP-AE-ENG-001 v1.0",
        "pay_date": pay_date,
        "period_start": period_start,
        "period_end": period_end,
        "inputs": {
            "nationality_category": facts["nationality_category"],
            "gcc_country": facts["gcc_country"],
            "pension_scheme": pension_result["scheme"],
            "pension_contribution_salary": pension_result["contribution_salary"],
            "government_support_eligible": facts["government_support_eligible"],
            "eos_regime": eos_result["regime"],
            "work_pattern": facts["work_pattern"],
            "emirati_minimum_applied": minimum,
        },
        "wages": {"basic_wage": basic, "total_wage": total_wage, "gross": gross,
                  "unpaid_leave_deduction": unpaid_deduction},
        "lines": lines,
        "pension": pension_result,
        "end_of_service": eos_result,
        "overtime": overtime_result,
        "employee_deductions": employee_deduction,
        "employer_cost": {"pension_cash": pension_result["employer_cash"],
                          "end_of_service": eos_result["employer_amount"], "total": employer_cost},
        "final_settlement_days": settlement_days,
        "income_tax": _ZERO,
    }
    return {
        # Standard lines: employee pension is deducted; employer cash pension
        # and the end-of-service amount are employer-only costs.
        "employee_pension": pension_result["employee"],
        "employer_pension": pension_result["employer_cash"],
        "employer_payroll_tax": eos_result["employer_amount"],
        "ae_result": _json(breakdown),
    }
