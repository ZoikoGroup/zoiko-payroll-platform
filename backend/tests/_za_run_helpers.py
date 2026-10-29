"""Shared helpers for the South Africa Phase 9 run tests (lifecycle, corrections,
journal). Payslips are calculated by the REAL engine from the golden fixtures
and stored with the real frozen context + snapshot, exactly as
service._generate_single_payslip does. "ZA" is South Africa."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.hmrc_golden_harness import build_context
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "za_golden"
PREPARER, APPROVER, THIRD = 501, 502, 503
AUTHORITIES = {"text_value": "STATUTORY,COURT_ORDER,CONSENT,COLLECTIVE"}


def case(fixture: str, **overrides) -> dict:
    ctx = json.loads((GOLDEN / f"{fixture}.json").read_text(encoding="utf-8"))["context"]
    ctx["rate_map"] = {**ctx["rate_map"], "za_deduction_authority_types": AUTHORITIES}
    ctx.update(overrides)
    return ctx


def calc_frozen(fixture: str, **overrides):
    ctx = build_context(case(fixture, **overrides))
    frozen = svc.za_freeze_context(ctx)
    return calculate_payroll(ctx, "standard"), frozen


def employee(db, organization, code, **kw):
    emp = PayrollEmployee(organization_id=organization.id, employee_code=code, name=f"Employee {code}",
                          date_of_joining=date(2020, 1, 1), basic=Decimal("10000"), country_code="ZA",
                          compliance_fields={"tax_number": "0123456789"}, **kw)
    db.add(emp)
    db.flush()
    return emp


def run(db, organization, pay_date=date(2026, 9, 30), status="Draft", created_by=PREPARER):
    r = PayrollRun(organization_id=organization.id, period_label=pay_date.strftime("%Y-%m"),
                   period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date, status=status,
                   created_by=created_by)
    db.add(r)
    db.flush()
    return r


def payslip(db, organization, payroll_run, emp, fixture="f1_monthly_salary_age_40", **overrides):
    result, frozen = calc_frozen(fixture, **overrides)
    item = PayslipItem(
        payroll_run_id=payroll_run.id, employee_id=emp.id, organization_id=organization.id,
        employee_name=emp.name, country_code="ZA", gross_pay=Decimal(str(result.gross)),
        total_deductions=result.total_deductions, net_pay=result.net_pay, tds=result.tds,
        esi=result.employee_esi, employer_esi=result.employer_esi,
        employer_payroll_tax=result.employer_payroll_tax, employee_pension=result.employee_pension,
        za_calculation_snapshot=svc.za_payslip_snapshot(result, frozen=frozen))
    db.add(item)
    db.flush()
    return item
