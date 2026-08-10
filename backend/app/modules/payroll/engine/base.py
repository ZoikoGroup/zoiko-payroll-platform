"""
modules/payroll/engine/base
---------------------------
Core data structures and abstract strategy interface for the payroll engine.

All payroll strategies receive a ``PayrollContext`` and return a
``PayrollResult``.  The context carries the employee's salary components,
attendance-derived unpaid leave count, and the country-specific rate/slab
configuration needed for statutory deductions.

Fixed 30-Day Payroll Model (applies to ALL strategies):
    PAYROLL_DAYS = 30
    Per Day Salary = Monthly Gross / 30
    Attendance Deduction = Unpaid Leave Days × Per Day Salary
    Payable Days = 30 − Unpaid Leave Days
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

PAYROLL_DAYS = 30


def _round2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class PayrollContext:
    """Immutable input bundle for a single-employee payroll calculation."""

    # Salary components (monthly)
    gross: Decimal
    basic: Decimal
    hra: Decimal = Decimal("0")
    special_allowance: Decimal = Decimal("0")
    overtime: Decimal = Decimal("0")
    additional_compensation: Decimal = Decimal("0")

    # Attendance (fixed 30-day model)
    unpaid_leave_days: int = 0
    payroll_days: int = PAYROLL_DAYS

    # Country / compliance
    country: str = "IN"
    rate_map: dict = field(default_factory=dict)   # component_key → ContributionRate
    slabs: list = field(default_factory=list)       # list[TaxSlab]


@dataclass
class PayrollResult:
    """Output bundle — all figures needed for a PayslipItem and preview."""

    # Attendance
    payroll_days: int = PAYROLL_DAYS
    unpaid_leave_days: int = 0
    payable_days: int = PAYROLL_DAYS
    per_day_salary: Decimal = Decimal("0")
    attendance_deduction: Decimal = Decimal("0")

    # Earnings
    gross: Decimal = Decimal("0")
    basic: Decimal = Decimal("0")
    hra: Decimal = Decimal("0")
    special_allowance: Decimal = Decimal("0")
    overtime: Decimal = Decimal("0")
    additional_compensation: Decimal = Decimal("0")

    # Employee-side deductions
    employee_pf: Decimal = Decimal("0")
    employee_esi: Decimal = Decimal("0")
    professional_tax: Decimal = Decimal("0")
    tds: Decimal = Decimal("0")
    annual_tax: Decimal = Decimal("0")
    social_security: Decimal = Decimal("0")
    medicare: Decimal = Decimal("0")
    ni_employee: Decimal = Decimal("0")

    # Employer-side contributions
    employer_pf: Decimal = Decimal("0")
    employer_esi: Decimal = Decimal("0")
    employer_social_security: Decimal = Decimal("0")
    employer_medicare: Decimal = Decimal("0")
    employer_pension: Decimal = Decimal("0")

    # Totals
    total_deductions: Decimal = Decimal("0")
    net_pay: Decimal = Decimal("0")


class PayrollStrategy(ABC):
    """Abstract base for all payroll calculation strategies.

    New policies are added by implementing this interface and registering
    the class in ``resolver.py``.  The core payroll engine never contains
    hardcoded calculation logic — it delegates entirely to the resolved
    strategy.
    """

    @abstractmethod
    def calculate(self, ctx: PayrollContext) -> PayrollResult:
        """Run the full payroll calculation for one employee.

        Implementations MUST:
        1. Compute attendance deduction using the fixed 30-day model.
        2. Apply policy-specific compliance deductions.
        3. Return a fully-populated PayrollResult.
        """
