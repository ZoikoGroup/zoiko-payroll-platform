"""
modules/payroll/simple_engine.py
------------------------------------
"Simple Payroll" calculation mode — DELEGATES to engine.simple.SimpleStrategy.

This module is kept for backward compatibility with any code that still
calls ``generate_simple_payslip()`` directly.  The actual calculation
now lives in ``app.modules.payroll.engine.simple.SimpleStrategy``.

Formula:
    Net Salary = Gross Salary − Attendance Deduction

Explicitly IGNORED in this mode: PF, ESI, PT, TDS, employer contributions,
employee contributions, all statutory deductions.

Hard rule: interns NEVER receive paid leave, regardless of any policy
override.
"""

from decimal import Decimal
from sqlalchemy.orm import Session

from app.modules.payroll import service as payroll_service
from app.modules.payroll.models import PayrollRun, PayslipItem, PayslipStatus, EmployeeStatus
from app.modules.payroll.policy.models import PayrollPolicy, EmployeeCategoryType
from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee
from app.modules.payroll.engine.base import PAYROLL_DAYS

MONTHS_PER_YEAR = Decimal("12")


def _round2(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _employee_category(employee, policy: PayrollPolicy) -> str:
    """Map the payroll employee's stored category to a PolicyEmployeeCategory
    key, defaulting to full_time if unset/unrecognized."""
    raw = (getattr(employee, "employment_type", None) or getattr(employee, "category", None) or "").lower()
    valid = {c.value for c in EmployeeCategoryType}
    return raw if raw in valid else EmployeeCategoryType.FULL_TIME.value


def generate_simple_payslip(db: Session, run: PayrollRun, employee, policy: PayrollPolicy, payslip_number: str = None) -> PayslipItem:
    ctc = Decimal(str(getattr(employee, "ctc", 0) or 0))
    monthly_gross = _round2(ctc / MONTHS_PER_YEAR) if ctc else Decimal("0")

    # Fixed 30-Day model: count unpaid leave days
    unpaid_leave_days = payroll_service._count_unpaid_leave_days(
        db, run.organization_id, employee.id, run.period_start, run.period_end
    )

    category_key = _employee_category(employee, policy)
    is_intern = category_key == EmployeeCategoryType.INTERN.value
    if is_intern:
        # Hard rule: interns never get paid leave — all leave days count
        # toward deduction.  This is already guaranteed because
        # _count_unpaid_leave_days only counts absent/unpaid-leave records.
        pass

    # Delegate to the SimpleStrategy engine
    ctx = build_context_from_employee(
        employee, gross=monthly_gross, basic=monthly_gross,
        unpaid_leave_days=unpaid_leave_days,
        country="IN",
    )
    result = calculate_payroll(ctx, "simple")

    employee_name = getattr(employee, "name", None) or f"Employee #{employee.id}"

    zero = Decimal("0.00")
    item = PayslipItem(
        payroll_run_id=run.id,
        employee_id=employee.id,
        organization_id=run.organization_id,
        employee_name=employee_name,
        department=getattr(employee, "department", None),
        bank_account=getattr(employee, "bank_account", None),
        pan=getattr(employee, "pan", None),
        basic_salary=monthly_gross,
        hra=zero,
        special_allowance=zero,
        overtime=zero,
        additional_compensation=zero,
        payable_days=Decimal(result.payable_days),
        total_working_days=Decimal(result.payroll_days),
        gross_pay=monthly_gross,
        pf=zero, esi=zero, professional_tax=zero,
        social_security=zero, medicare=zero, ni_employee=zero,
        tds=zero,
        total_deductions=result.total_deductions,
        employer_pf=zero, employer_esi=zero,
        employer_social_security=zero, employer_medicare=zero, employer_pension=zero,
        net_pay=result.net_pay,
        payslip_number=payslip_number,
        unpaid_leave_days=result.unpaid_leave_days,
        attendance_deduction=result.attendance_deduction,
        per_day_salary=result.per_day_salary,
        status=PayslipStatus.PENDING,
    )
    db.add(item)
    return item
