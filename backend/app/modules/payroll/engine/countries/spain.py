"""modules/payroll/engine/countries/spain.py
------------------------------------------
Spain (ZP-ES-ENG-001 v1.0, docs/spain) — the calculation orchestrator over the
bounded rule modules in engine/jurisdictions/spain/.

The engine reads EVERY statutory value from the active Spanish canonical pack
(ctx.rate_map). There is no hardcoded rate, base, threshold or tranche: a
missing row stops the employee's calculation with a named ES_RATE_MISSING
reason, and the generic calculator is never reached (Spain is registered in
standard._COUNTRY_CALC and simple mode is blocked in resolver).

Employee facts arrive in ctx.es_facts (ESEmployeeValidation compliance_fields +
work_state) and the ordinary PayrollContext wage/date fields:

  ordinary pay      basic + hra + special_allowance (the monthly salary), less
                    this run's unpaid days; plus additional_compensation as
                    ordinary variable pay — EXCEPT in an extra-pay month of a
                    SEPARATE_14 employee (es_facts.extra_pay_months), where
                    additional_compensation is the cash extra pay: gross pay,
                    but never in the bases again (F5, D15)
  overtime          ctx.overtime (outside the common base, own contribution)

Payslip lines (docs/spain D14): tds = IRPF; social_security = employee Social
Security incl. solidarity; employer_social_security = employer Social Security
incl. solidarity; employer_occupational_hazard = AT/EP; employer_payroll_tax =
short-contract surcharge; es_result = the JSON-safe breakdown.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.jurisdictions.spain import bases as B
from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain import extra_pay as X
from app.modules.payroll.engine.jurisdictions.spain import irpf as IRPF
from app.modules.payroll.engine.jurisdictions.spain import labour as L
from app.modules.payroll.engine.jurisdictions.spain import social_security as SS
from app.modules.payroll.engine.jurisdictions.spain import solidarity as SOL
from app.modules.payroll.engine.jurisdictions.spain.errors import ESCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.spain.params import ZERO, round2

__all__ = ["ESCalculationBlockedError", "calculate"]


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
    raise ESCalculationBlockedError(code, reason, organization_id=getattr(ctx, "organization_id", None))


def _decimal(value, field: str, ctx: PayrollContext) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError, TypeError):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, field), f"'{field}' is not an amount.", ctx)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _facts(ctx: PayrollContext) -> dict:
    facts = dict(ctx.es_facts or {})
    pattern = str(facts.get("work_pattern") or getattr(ctx, "employment_type", None) or "FULL_TIME").upper()
    if "PART" in pattern:
        _block(E.PART_TIME_NOT_SUPPORTED,
               "part-time employees need the hourly minimum contribution bases, which are not configured yet "
               "(docs/spain G-04).", ctx)
    facts["work_pattern"] = "FULL_TIME"
    facts["contract_type"] = str(facts.get("contract_type") or "").upper()
    facts["extra_pay_policy"] = str(facts.get("extra_pay_policy") or "").upper()
    facts["overtime_kind"] = str(facts.get("overtime_kind") or "OTHER").upper()
    months = facts.get("extra_pay_months") or []
    if isinstance(months, str):
        months = [m for m in months.replace(";", ",").split(",") if m.strip()]
    try:
        facts["extra_pay_months"] = sorted({int(str(m).strip()) for m in months})
    except ValueError:
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "extra_pay_months"),
               "extra_pay_months must be month numbers such as 6,12.", ctx)
    return facts


def _period(ctx: PayrollContext, pay_date: date):
    start = ctx.period_start or pay_date.replace(day=1)
    end = ctx.period_end or pay_date
    if start > end:
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "period"), "the pay period starts after it ends.", ctx)
    return start, end


def _days_in_alta(ctx: PayrollContext, start: date, end: date) -> tuple[int, int]:
    joining = _as_date(ctx.date_of_joining)
    leaving = _as_date(ctx.date_of_leaving)
    first = max(start, joining) if joining else start
    last = min(end, leaving) if leaving else end
    return max((last - first).days + 1, 0), (end - start).days + 1


def calculate(ctx: PayrollContext) -> dict:
    """Return the statutory deduction lines and the full Spanish breakdown."""
    facts = _facts(ctx)
    rate_map = ctx.rate_map or {}
    pay_date = ctx.pay_date or ctx.period_end
    if not isinstance(pay_date, date):
        _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "pay_date"),
               "a pay date or period end is required to resolve effective-dated Spanish values.", ctx)
    period_start, period_end = _period(ctx, pay_date)

    group = B.contribution_group(facts.get("contribution_group"))
    unemployment_key = SS.unemployment_key(facts["contract_type"])          # validates contract_type early
    salary = round2(_decimal(ctx.basic, "basic", ctx) + _decimal(ctx.hra, "hra", ctx)
                    + _decimal(ctx.special_allowance, "special_allowance", ctx))
    additional = round2(_decimal(getattr(ctx, "additional_compensation", None), "additional_compensation", ctx))
    overtime = round2(_decimal(ctx.overtime, "overtime", ctx))
    payroll_days = Decimal(ctx.payroll_days or 30)
    unpaid_days = max(int(ctx.unpaid_leave_days or 0), 0)
    unpaid_deduction = min(round2(salary / payroll_days * unpaid_days), salary) if payroll_days else ZERO

    prorrata = X.monthly_prorrata(facts["extra_pay_policy"], facts.get("extra_pay_annual_amount"))
    extra_pay_month = facts["extra_pay_policy"] == "SEPARATE_14" and pay_date.month in facts["extra_pay_months"]
    extra_pay_cash = additional if extra_pay_month else ZERO
    variable_pay = ZERO if extra_pay_month else additional
    smi = L.smi_check(monthly_salary=salary, extra_pay_policy=facts["extra_pay_policy"],
                      extra_pay_annual_amount=facts.get("extra_pay_annual_amount"), rate_map=rate_map)

    days_in_alta, period_days = _days_in_alta(ctx, period_start, period_end)
    factor = B.period_factor(days_in_alta, period_days)
    bases = B.compute(ordinary_pay=salary - unpaid_deduction + variable_pay, overtime_pay=overtime,
                      extra_prorrata=round2(prorrata * factor), group=group, factor=factor, rate_map=rate_map)
    social = SS.compute(bases=bases, contract_type=facts["contract_type"], overtime_kind=facts["overtime_kind"],
                        employer_at_ep_rate=facts.get("at_ep_rate"), rate_map=rate_map)
    solidarity = SOL.compute(remuneration_with_overtime=bases["remuneration_with_overtime"], factor=factor,
                             rate_map=rate_map)
    surcharge = L.short_contract_surcharge(
        contract_type=facts["contract_type"], date_of_joining=_as_date(ctx.date_of_joining),
        date_of_leaving=_as_date(ctx.date_of_leaving), period_start=period_start, period_end=period_end,
        exception=facts.get("short_contract_exception"), rate_map=rate_map)

    employee_ss = round2(social["employee_total"] + solidarity["employee_total"])
    employer_ss = round2(social["employer_total"] + solidarity["employer_total"])
    gross = round2(Decimal(str(ctx.gross or 0)))
    irpf = IRPF.compute(pay_date=pay_date, monthly_gross=gross, monthly_ss_employee=employee_ss, facts=facts,
                        rate_map=rate_map)
    irpf_amount = round2(irpf["amount"])
    employer_cost = round2(employer_ss + social["at_ep_employer"] + surcharge["amount"])

    breakdown = {
        "country": "ES",
        "spec": "ZP-ES-ENG-001 v1.0",
        "pay_date": pay_date,
        "period_start": period_start,
        "period_end": period_end,
        "inputs": {
            "contract_type": facts["contract_type"],
            "contribution_group": group,
            "work_pattern": facts["work_pattern"],
            "extra_pay_policy": facts["extra_pay_policy"],
            "extra_pay_month": extra_pay_month,
            "overtime_kind": facts["overtime_kind"],
            "days_in_alta": days_in_alta,
            "period_days": period_days,
            "unemployment_key": unemployment_key,
        },
        "pay": {"monthly_salary": salary, "unpaid_days": unpaid_days, "unpaid_deduction": unpaid_deduction,
                "variable_pay": variable_pay, "extra_pay_cash": extra_pay_cash, "overtime": overtime,
                "gross": gross},
        "smi": smi,
        "bases": bases,
        "social_security": social,
        "solidarity": solidarity,
        "short_contract_surcharge": surcharge,
        "irpf": irpf,
        "employee_deductions": {"social_security": employee_ss, "irpf": irpf_amount,
                                "total": round2(employee_ss + irpf_amount)},
        "employer_cost": {"social_security": employer_ss, "at_ep": social["at_ep_employer"],
                          "short_contract_surcharge": surcharge["amount"], "total": employer_cost},
    }
    return {
        # Employee-side: IRPF + employee Social Security (incl. solidarity) are
        # deducted. Employer-side lines are employer cost only (ES-042).
        "tds": irpf_amount,
        "social_security": employee_ss,
        "employer_social_security": employer_ss,
        "employer_occupational_hazard": social["at_ep_employer"],
        "employer_payroll_tax": surcharge["amount"],
        "es_result": _json(breakdown),
    }
