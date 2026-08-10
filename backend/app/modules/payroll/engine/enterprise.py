"""
modules/payroll/engine/enterprise
---------------------------------
Enterprise Payroll strategy — multi-country dispatch.

Formula:
    Net Salary =
        Gross Salary
        − Attendance Deduction
        − Country-Specific Deductions

Each employee's payroll jurisdiction is determined from the org's
CompanyComplianceDetails (or their work_state override). The engine
dispatches to the appropriate country calculator.

Currently supported: IN, US, UK.
New countries are added by implementing a ``_calc_<country>()`` function
and registering it in ``_COUNTRY_REGISTRY``.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)

# Import the country-specific calculators from StandardStrategy —
# the compliance logic is identical; only the strategy routing differs.
from app.modules.payroll.engine.standard import (
    _COUNTRY_CALC,
    _calc_india,
    _calc_us,
    _calc_uk,
    _calc_generic,
)


class EnterpriseStrategy(PayrollStrategy):
    """Multi-country payroll for global organizations.

    Resolves each employee's jurisdiction and delegates to the matching
    country calculator.  Falls back to ``_calc_generic`` for countries
    without a dedicated calculator.
    """

    def calculate(self, ctx: PayrollContext) -> PayrollResult:
        payroll_days = ctx.payroll_days or PAYROLL_DAYS
        unpaid = max(ctx.unpaid_leave_days, 0)
        payable_days = max(payroll_days - unpaid, 0)

        per_day_salary = _round2(ctx.gross / Decimal(payroll_days)) if payroll_days else Decimal("0")
        attendance_deduction = min(_round2(per_day_salary * Decimal(unpaid)), ctx.gross)

        # Dispatch to country-specific compliance calculator
        calc_fn = _COUNTRY_CALC.get(ctx.country.upper(), _calc_generic)
        deductions = calc_fn(ctx)

        total_employee_deductions = (
            attendance_deduction
            + deductions.get("employee_pf", Decimal("0"))
            + deductions.get("employee_esi", Decimal("0"))
            + deductions.get("professional_tax", Decimal("0"))
            + deductions.get("tds", Decimal("0"))
            + deductions.get("social_security", Decimal("0"))
            + deductions.get("medicare", Decimal("0"))
            + deductions.get("ni_employee", Decimal("0"))
        )

        net_pay = max(_round2(ctx.gross - total_employee_deductions), Decimal("0"))

        return PayrollResult(
            payroll_days=payroll_days,
            unpaid_leave_days=unpaid,
            payable_days=payable_days,
            per_day_salary=per_day_salary,
            attendance_deduction=attendance_deduction,
            gross=ctx.gross,
            basic=ctx.basic,
            hra=ctx.hra,
            special_allowance=ctx.special_allowance,
            overtime=ctx.overtime,
            additional_compensation=ctx.additional_compensation,
            employee_pf=deductions.get("employee_pf", Decimal("0")),
            employer_pf=deductions.get("employer_pf", Decimal("0")),
            employee_esi=deductions.get("employee_esi", Decimal("0")),
            employer_esi=deductions.get("employer_esi", Decimal("0")),
            professional_tax=deductions.get("professional_tax", Decimal("0")),
            social_security=deductions.get("social_security", Decimal("0")),
            medicare=deductions.get("medicare", Decimal("0")),
            ni_employee=deductions.get("ni_employee", Decimal("0")),
            employer_social_security=deductions.get("employer_social_security", Decimal("0")),
            employer_medicare=deductions.get("employer_medicare", Decimal("0")),
            employer_pension=deductions.get("employer_pension", Decimal("0")),
            tds=deductions.get("tds", Decimal("0")),
            annual_tax=deductions.get("annual_tax", Decimal("0")),
            total_deductions=total_employee_deductions,
            net_pay=net_pay,
        )
