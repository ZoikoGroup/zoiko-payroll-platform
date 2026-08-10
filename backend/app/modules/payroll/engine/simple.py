"""
modules/payroll/engine/simple
------------------------------
Simple Payroll strategy — no statutory deductions.

Formula:
    Net Pay = Gross Salary − Attendance Deduction

Statutory modules (PF, ESI, PT, TDS, NI, etc.) are all zeroed.
Only unpaid leave reduces salary.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)


class SimpleStrategy(PayrollStrategy):
    """Payroll calculation for startups, freelancers, and contractors
    that do not require statutory compliance."""

    def calculate(self, ctx: PayrollContext) -> PayrollResult:
        payroll_days = ctx.payroll_days or PAYROLL_DAYS
        unpaid = max(ctx.unpaid_leave_days, 0)
        payable_days = max(payroll_days - unpaid, 0)

        per_day_salary = _round2(ctx.gross / Decimal(payroll_days)) if payroll_days else Decimal("0")
        attendance_deduction = min(_round2(per_day_salary * Decimal(unpaid)), ctx.gross)

        net_pay = max(_round2(ctx.gross - attendance_deduction), Decimal("0"))

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
            # All statutory deductions stay at zero
            total_deductions=attendance_deduction,
            net_pay=net_pay,
        )
