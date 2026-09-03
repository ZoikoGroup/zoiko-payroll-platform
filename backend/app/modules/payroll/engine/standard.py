"""
modules/payroll/engine/standard
-------------------------------
Standard Payroll strategy — country dispatch + the universal Fixed 30-Day
attendance model.

Formula:
    Net Salary =
        Gross Salary
        − Attendance Deduction
        − PF (Employee + Employer)
        − ESI (Employee + Employer, if gross ≤ ₹21,000)
        − Professional Tax (flat ₹200/mo)
        − TDS (progressive slabs, FY 2025-26 New Regime)

Attendance deduction is ALWAYS computed first via the Fixed 30-Day model,
then statutory deductions are applied on the full gross (not prorated).

Country-specific logic is dispatched from here for "standard" mode — the
same engine serves IN, US, UK, AU, DE, and CA under the Standard policy
(and, via EnterpriseStrategy re-using this dispatch table, under the
Enterprise policy too). Each country's actual formulas now live in their
own file under engine/countries/ (india.py, us.py, uk.py, australia.py,
germany.py, canada.py) plus engine/countries/shared.py for the
genuinely cross-cutting helpers — this file re-exports every one of
those under its original private name (`_calc_india`, `MONTHS_PER_YEAR`,
`_IN_STANDARD_DEDUCTION`, etc.) purely for backward compatibility, since
engine/enterprise.py and this module's own test suite import them
directly from here. Nothing about those contracts changed — only the
implementation moved to make one country's formulas readable/editable
without touching the other five.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)
from app.modules.payroll.engine.countries.shared import (
    MONTHS_PER_YEAR,
    evaluate_tax_formula,
    _param_amount,
    _param_pct,
    _calculate_annual_tax,
)
from app.modules.payroll.engine.countries import india as _india
from app.modules.payroll.engine.countries import us as _us
from app.modules.payroll.engine.countries import uk as _uk
from app.modules.payroll.engine.countries import australia as _australia
from app.modules.payroll.engine.countries import germany as _germany
from app.modules.payroll.engine.countries import canada as _canada
from app.modules.payroll.engine.countries import generic as _generic

# ── Backward-compatible re-exports ──────────────────────────────────────
# Every name below existed directly in this file before the engine/
# countries/ split — kept importable from exactly this path, exactly
# these names, so no external caller needs to change.

ESI_MONTHLY_WAGE_CEILING = _india.ESI_MONTHLY_WAGE_CEILING
_IN_STANDARD_DEDUCTION = _india._IN_STANDARD_DEDUCTION
_IN_REBATE_87A_LIMIT = _india._IN_REBATE_87A_LIMIT
_IN_REBATE_87A_MAX = _india._IN_REBATE_87A_MAX
_apply_section_87a_rebate = _india._apply_section_87a_rebate
_calculate_annual_tax_in = _india._calculate_annual_tax_in
_calc_india = _india.calculate

_US_STANDARD_DEDUCTION = _us._US_STANDARD_DEDUCTION
_US_SOCIAL_SECURITY_WAGE_BASE = _us._US_SOCIAL_SECURITY_WAGE_BASE
_US_SOCIAL_SECURITY_RATE = _us._US_SOCIAL_SECURITY_RATE
_US_MEDICARE_RATE = _us._US_MEDICARE_RATE
_US_MEDICARE_ADDITIONAL_RATE = _us._US_MEDICARE_ADDITIONAL_RATE
_US_MEDICARE_ADDITIONAL_THRESHOLD = _us._US_MEDICARE_ADDITIONAL_THRESHOLD
_calculate_annual_tax_us = _us._calculate_annual_tax_us
_calc_us = _us.calculate

_UK_PERSONAL_ALLOWANCE = _uk._UK_PERSONAL_ALLOWANCE
_UK_PA_TAPER_THRESHOLD = _uk._UK_PA_TAPER_THRESHOLD
_UK_NI_PRIMARY_THRESHOLD = _uk._UK_NI_PRIMARY_THRESHOLD
_UK_NI_UPPER_THRESHOLD = _uk._UK_NI_UPPER_THRESHOLD
_UK_NI_PRIMARY_RATE = _uk._UK_NI_PRIMARY_RATE
_UK_NI_UPPER_RATE = _uk._UK_NI_UPPER_RATE
_UK_PENSION_MIN_ENPLOYER = _uk._UK_PENSION_MIN_ENPLOYER
_calculate_annual_tax_uk = _uk._calculate_annual_tax_uk
_calc_uk = _uk.calculate

_AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD = _australia._AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD
_AU_MLS_THRESHOLD = _australia._AU_MLS_THRESHOLD
_AU_MLS_RATE = _australia._AU_MLS_RATE
_AU_SUPER_MAX_CONTRIBUTION_BASE = _australia._AU_SUPER_MAX_CONTRIBUTION_BASE
_calc_australia = _australia.calculate

_DE_GRUNDFREIBETRAG = _germany._DE_GRUNDFREIBETRAG
_DE_CONTRIBUTION_CEILING = _germany._DE_CONTRIBUTION_CEILING
_DE_SOLI_THRESHOLD = _germany._DE_SOLI_THRESHOLD
_DE_SOLI_RATE = _germany._DE_SOLI_RATE
_calculate_annual_tax_de = _germany._calculate_annual_tax_de
_calc_germany = _germany.calculate

_CA_CPP_YMPE = _canada._CA_CPP_YMPE
_CA_CPP_BASIC_EXEMPTION = _canada._CA_CPP_BASIC_EXEMPTION
_CA_EI_MIE = _canada._CA_EI_MIE
_CA_BASIC_PERSONAL_AMOUNT = _canada._CA_BASIC_PERSONAL_AMOUNT
_calculate_annual_tax_ca = _canada._calculate_annual_tax_ca
_calc_canada = _canada.calculate

_calc_generic = _generic.calculate


_COUNTRY_CALC = {
    "IN": _calc_india,
    "US": _calc_us,
    "UK": _calc_uk,
    "AU": _calc_australia,
    "DE": _calc_germany,
    "CA": _calc_canada,
}


# ── Strategy class ─────────────────────────────────────────────────────────

class StandardStrategy(PayrollStrategy):
    """Standard payroll with country-specific statutory compliance.

    Supports IN, US, UK, AU, DE, CA natively.  Unrecognised countries fall
    through to a generic progressive-tax calculator.
    """

    def calculate(self, ctx: PayrollContext) -> PayrollResult:
        payroll_days = ctx.payroll_days or PAYROLL_DAYS
        unpaid = max(ctx.unpaid_leave_days, 0)
        payable_days = max(payroll_days - unpaid, 0)

        per_day_salary = _round2(ctx.gross / Decimal(payroll_days)) if payroll_days else Decimal("0")
        attendance_deduction = min(_round2(per_day_salary * Decimal(unpaid)), ctx.gross)

        # Country-specific compliance deductions (computed on full gross)
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
            + deductions.get("study_loan_deduction", Decimal("0"))
            + deductions.get("employee_pension", Decimal("0"))
            + deductions.get("church_tax", Decimal("0"))
            + deductions.get("cpp2", Decimal("0"))
            + deductions.get("state_disability_insurance", Decimal("0"))
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
            study_loan_deduction=deductions.get("study_loan_deduction", Decimal("0")),
            employee_pension=deductions.get("employee_pension", Decimal("0")),
            church_tax=deductions.get("church_tax", Decimal("0")),
            cpp2=deductions.get("cpp2", Decimal("0")),
            employer_social_security=deductions.get("employer_social_security", Decimal("0")),
            employer_medicare=deductions.get("employer_medicare", Decimal("0")),
            employer_pension=deductions.get("employer_pension", Decimal("0")),
            employer_ni=deductions.get("employer_ni", Decimal("0")),
            employer_futa=deductions.get("employer_futa", Decimal("0")),
            employer_sui=deductions.get("employer_sui", Decimal("0")),
            employer_cpp2=deductions.get("employer_cpp2", Decimal("0")),
            ytd_pensionable_earnings=deductions.get("ytd_pensionable_earnings"),
            ytd_cpp2_pensionable_earnings=deductions.get("ytd_cpp2_pensionable_earnings"),
            ytd_insurable_earnings=deductions.get("ytd_insurable_earnings"),
            ytd_basic_exemption_used=deductions.get("ytd_basic_exemption_used"),
            tds=deductions.get("tds", Decimal("0")),
            annual_tax=deductions.get("annual_tax", Decimal("0")),
            surcharge=deductions.get("surcharge", Decimal("0")),
            cess=deductions.get("cess", Decimal("0")),
            federal_income_tax=deductions.get("federal_income_tax", Decimal("0")),
            state_income_tax=deductions.get("state_income_tax", Decimal("0")),
            local_tax=deductions.get("local_tax", Decimal("0")),
            state_disability_insurance=deductions.get("state_disability_insurance", Decimal("0")),
            total_deductions=total_employee_deductions,
            net_pay=net_pay,
        )
