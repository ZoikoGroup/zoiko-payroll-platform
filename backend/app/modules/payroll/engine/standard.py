"""
modules/payroll/engine/standard
-------------------------------
Standard Payroll strategy — Indian statutory compliance (default).

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

Country-specific logic is dispatched from here for "standard" mode —
the same engine serves IN, US, UK, AU, DE, and CA under the Standard
policy (and, via EnterpriseStrategy re-using this dispatch table, under
the Enterprise policy too).
"""

import ast
import operator
from decimal import Decimal

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)

# ── Constants ──────────────────────────────────────────────────────────────

MONTHS_PER_YEAR = Decimal("12")

# India
ESI_MONTHLY_WAGE_CEILING = Decimal("21000")
_IN_STANDARD_DEDUCTION = Decimal("75000")
_IN_REBATE_87A_LIMIT = Decimal("1200000")
_IN_REBATE_87A_MAX = Decimal("60000")

# US
_US_STANDARD_DEDUCTION = Decimal("15000")
_US_SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")
_US_SOCIAL_SECURITY_RATE = Decimal("6.2")
_US_MEDICARE_RATE = Decimal("1.45")
_US_MEDICARE_ADDITIONAL_RATE = Decimal("0.9")

# UK
_UK_PERSONAL_ALLOWANCE = Decimal("12570")
_UK_PA_TAPER_THRESHOLD = Decimal("100000")
_UK_NI_PRIMARY_THRESHOLD = Decimal("12570")
_UK_NI_UPPER_THRESHOLD = Decimal("50270")
_UK_NI_PRIMARY_RATE = Decimal("8")
_UK_NI_UPPER_RATE = Decimal("2")
_UK_PENSION_MIN_ENPLOYER = Decimal("3")

# US Medicare Additional threshold ($200,000/yr) — previously inlined at
# its one call site in _calc_us; named here so it can be sourced from
# rate_map like every other parameter below.
_US_MEDICARE_ADDITIONAL_THRESHOLD = Decimal("200000")


# ── Government-mandated scalar parameters (Global Payroll Tax Engine) ──────
# The constants above remain as documented FALLBACK defaults only — the
# live source is now a ContributionRate row (organization_id set, synced
# from the Super-Admin-owned canonical row of the same component_key) if
# one exists in rate_map, so Super Admin editing e.g. the US Social
# Security wage base actually reaches this calculator. A jurisdiction/org
# with no such row yet (nothing has changed there) behaves EXACTLY as
# before this existed — this is additive, not a behavior change.

def _param_amount(rate_map: dict, key: str, default: Decimal) -> Decimal:
    row = rate_map.get(key)
    if row is not None and row.flat_amount is not None:
        return row.flat_amount
    return default


def _param_pct(rate_map: dict, key: str, side: str, default: Decimal) -> Decimal:
    row = rate_map.get(key)
    if row is not None:
        value = row.employee_rate_pct if side == "employee" else row.employer_rate_pct
        if value is not None:
            return value
    return default


# ── Formula-based tax rules (rule_type="FORMULA") ──────────────────────────
# Not every jurisdiction's income tax is a clean bracket table — Germany's
# real Lohnsteuer is a continuous formula, not flat bands. TABLE_LOOKUP/
# MARGINAL_RATE slabs (every jurisdiction's current data) keep using the
# bracket loop below unchanged; a slab row that opts into rule_type=FORMULA
# is evaluated here instead. Deliberately NOT `eval()` — a restricted AST
# walk that only allows arithmetic on a fixed `income` variable, so a
# formula_expression can never execute arbitrary code.

_SAFE_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_safe_node(node, variables: dict) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_safe_node(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        raise ValueError(f"Unknown variable in tax formula: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_safe_node(node.left, variables), _eval_safe_node(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_safe_node(node.operand, variables))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("min", "max"):
        args = [_eval_safe_node(a, variables) for a in node.args]
        return (min if node.func.id == "min" else max)(*args)
    raise ValueError(f"Disallowed expression in tax formula: {ast.dump(node)}")


def evaluate_tax_formula(expression: str, income: Decimal) -> Decimal:
    """Evaluate a stored formula_expression against a taxable `income`.
    Only arithmetic (+ - * / **), parentheses, min()/max(), and the
    `income` variable are permitted."""
    tree = ast.parse(expression, mode="eval")
    result = _eval_safe_node(tree, {"income": income})
    return max(Decimal("0"), Decimal(result))


# ── Tax computation helpers ────────────────────────────────────────────────

def _calculate_annual_tax(annual_income: Decimal, slabs) -> Decimal:
    """Progressive slab-based tax on annual income.

    If any slab row opts into rule_type="FORMULA", that row's
    formula_expression is evaluated directly against annual_income instead
    of the bracket-sum loop — one formula row replaces the whole table for
    that jurisdiction (matches how Germany's real Lohnsteuer works: one
    continuous function, not a set of bands)."""
    formula_row = next((s for s in slabs if getattr(s, "rule_type", None) == "FORMULA" and s.formula_expression), None)
    if formula_row is not None:
        return evaluate_tax_formula(formula_row.formula_expression, annual_income)

    tax = Decimal("0")
    for slab in sorted(slabs, key=lambda s: s.min_amount):
        lower = slab.min_amount
        upper = slab.max_amount if slab.max_amount is not None else annual_income
        if annual_income <= lower:
            continue
        taxable_in_band = min(annual_income, upper) - lower
        if taxable_in_band > 0:
            tax += taxable_in_band * (slab.rate_pct / Decimal("100"))
    return tax


def _apply_section_87a_rebate(annual_tax: Decimal, taxable_income: Decimal, rate_map: dict) -> Decimal:
    rebate_limit = _param_amount(rate_map, "rebate_87a_limit", _IN_REBATE_87A_LIMIT)
    rebate_max = _param_amount(rate_map, "rebate_87a_max", _IN_REBATE_87A_MAX)
    if taxable_income <= rebate_limit:
        rebate = min(annual_tax, rebate_max)
        return annual_tax - rebate
    tax_on_threshold = rebate_max
    if annual_tax > tax_on_threshold:
        excess_income = taxable_income - rebate_limit
        excess_tax = annual_tax - tax_on_threshold
        if excess_tax <= excess_income:
            return tax_on_threshold + excess_tax
        return annual_tax
    return annual_tax


def _calculate_annual_tax_in(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    standard_deduction = _param_amount(rate_map, "standard_deduction", _IN_STANDARD_DEDUCTION)
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    tax = _calculate_annual_tax(taxable, slabs)
    tax = _apply_section_87a_rebate(tax, taxable, rate_map)
    return max(Decimal("0"), tax)


def _calculate_annual_tax_us(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    standard_deduction = _param_amount(rate_map, "standard_deduction", _US_STANDARD_DEDUCTION)
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    return _calculate_annual_tax(taxable, slabs)


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    pa = _param_amount(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE)
    taper_threshold = _param_amount(rate_map, "pa_taper_threshold", _UK_PA_TAPER_THRESHOLD)
    if annual_gross > taper_threshold:
        taper = (annual_gross - taper_threshold) / Decimal("2")
        pa = max(Decimal("0"), pa - taper)
    taxable = max(Decimal("0"), annual_gross - pa)
    return _calculate_annual_tax(taxable, slabs)


# ── Per-country compliance calculators ─────────────────────────────────────

def _calc_india(ctx: PayrollContext) -> dict:
    """India: PF, ESI, Professional Tax, TDS."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    basic = ctx.basic

    pf_rate = rate_map.get("pf")
    employee_pf = _round2(basic * (pf_rate.employee_rate_pct / 100)) if pf_rate and pf_rate.employee_rate_pct else Decimal("0")
    employer_pf = _round2(basic * (pf_rate.employer_rate_pct / 100)) if pf_rate and pf_rate.employer_rate_pct else Decimal("0")

    esi_rate = rate_map.get("esi")
    esi_ceiling = _param_amount(rate_map, "esi_wage_ceiling", ESI_MONTHLY_WAGE_CEILING)
    esi_applicable = gross <= esi_ceiling
    employee_esi = _round2(gross * (esi_rate.employee_rate_pct / 100)) if esi_rate and esi_rate.employee_rate_pct and esi_applicable else Decimal("0")
    employer_esi = _round2(gross * (esi_rate.employer_rate_pct / 100)) if esi_rate and esi_rate.employer_rate_pct and esi_applicable else Decimal("0")

    pt_rate = rate_map.get("pt")
    professional_tax = pt_rate.flat_amount if pt_rate and pt_rate.flat_amount else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax_in(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employee_esi=employee_esi, employer_esi=employer_esi,
        professional_tax=professional_tax,
        tds=tds, annual_tax=annual_tax,
    )


def _calc_us(ctx: PayrollContext) -> dict:
    """US: Social Security + Medicare + Federal Income Tax.

    Employee/employer Social Security and Medicare rates now come from
    rate_map's "social-security"/"medicare" ContributionRate rows (the
    same rows _CONTRIBUTION_RATES_BY_COUNTRY["US"] already seeds with the
    correct 6.2%/1.45% values) rather than being ignored in favour of a
    hardcoded module constant — closing the gap where editing these rates
    via Compliance previously had zero calculation effect."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ss_rate_employee = _param_pct(rate_map, "social-security", "employee", _US_SOCIAL_SECURITY_RATE)
    ss_rate_employer = _param_pct(rate_map, "social-security", "employer", _US_SOCIAL_SECURITY_RATE)
    ss_wage_base = _param_amount(rate_map, "ss_wage_base", _US_SOCIAL_SECURITY_WAGE_BASE)
    annual_ss_wage = min(annual_gross, ss_wage_base)
    social_security = _round2((annual_ss_wage * ss_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    employer_ss = _round2((annual_ss_wage * ss_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    medicare_rate_employee = _param_pct(rate_map, "medicare", "employee", _US_MEDICARE_RATE)
    medicare_rate_employer = _param_pct(rate_map, "medicare", "employer", _US_MEDICARE_RATE)
    medicare_additional_rate = _param_pct(rate_map, "medicare_additional", "employee", _US_MEDICARE_ADDITIONAL_RATE)
    medicare_additional_threshold = _param_amount(rate_map, "medicare_addl_thresh", _US_MEDICARE_ADDITIONAL_THRESHOLD)

    medicare = _round2((annual_gross * medicare_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    if annual_gross > medicare_additional_threshold:
        medicare += _round2(((annual_gross - medicare_additional_threshold) * medicare_additional_rate / Decimal("100")) / MONTHS_PER_YEAR)
    employer_medicare = _round2((annual_gross * medicare_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax_us(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        social_security=social_security, employer_social_security=employer_ss,
        medicare=medicare, employer_medicare=employer_medicare,
        tds=tds, annual_tax=annual_tax,
    )


def _calc_uk(ctx: PayrollContext) -> dict:
    """UK: National Insurance + Employer Pension + PAYE.

    NI rates/thresholds and the employer pension rate now come from
    rate_map's "national-insurance"/"employer-pension" ContributionRate
    rows (already seeded with the correct 8%/2%/13.8%/3% values) rather
    than being ignored in favour of hardcoded module constants."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ni_primary_threshold = _param_amount(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD)
    ni_upper_threshold = _param_amount(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD)
    ni_primary_rate = _param_pct(rate_map, "national-insurance", "employee", _UK_NI_PRIMARY_RATE)
    ni_upper_rate = _param_pct(rate_map, "ni_upper_rate", "employee", _UK_NI_UPPER_RATE)

    ni_basicable = max(Decimal("0"), min(annual_gross, ni_upper_threshold) - ni_primary_threshold)
    ni_upperable = max(Decimal("0"), annual_gross - ni_upper_threshold)
    ni_employee_annual = (ni_basicable * ni_primary_rate / Decimal("100")) + (ni_upperable * ni_upper_rate / Decimal("100"))
    ni_employee = _round2(ni_employee_annual / MONTHS_PER_YEAR)

    pension_rate = _param_pct(rate_map, "employer-pension", "employer", _UK_PENSION_MIN_ENPLOYER)
    employer_pension = _round2(annual_gross * pension_rate / Decimal("100") / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax_uk(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        ni_employee=ni_employee,
        employer_pension=employer_pension,
        tds=tds, annual_tax=annual_tax,
    )


def _calc_generic(ctx: PayrollContext) -> dict:
    """Fallback: progressive tax only (no country-specific contributions)."""
    annual_gross = ctx.gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)
    return dict(tds=tds, annual_tax=annual_tax)


def _calc_australia(ctx: PayrollContext) -> dict:
    """Australia: Superannuation Guarantee (employer-only) + Medicare Levy
    (employee) + progressive income tax. Rates are DB-backed (ContributionRate/
    TaxSlab, seeded with representative defaults on first use) — same
    configuration-driven pattern as India, not hardcoded module constants.

    Reused PayrollResult fields: `medicare` (Medicare Levy — name already
    matches AU terminology) and `employer_pension` (Superannuation)."""
    rate_map = ctx.rate_map
    gross = ctx.gross

    super_rate = rate_map.get("super")
    employer_pension = _round2(gross * (super_rate.employer_rate_pct / 100)) if super_rate and super_rate.employer_rate_pct else Decimal("0")

    medicare_rate = rate_map.get("medicare-levy")
    medicare = _round2(gross * (medicare_rate.employee_rate_pct / 100)) if medicare_rate and medicare_rate.employee_rate_pct else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        medicare=medicare,
        employer_pension=employer_pension,
        tds=tds, annual_tax=annual_tax,
    )


def _calc_germany(ctx: PayrollContext) -> dict:
    """Germany: Pension insurance (Rentenversicherung) + combined Health/
    Unemployment/Long-term-care insurance (simplified into one "social
    insurance" component) + progressive income tax (simplified bracket
    approximation of Germany's continuous tax formula). DB-backed rates.

    Reused PayrollResult fields: `employee_pf`/`employer_pf` (Pension
    insurance) and `employee_esi`/`employer_esi` (combined social
    insurance) — payslip labels are swapped to German terminology for
    this country in generate_payslip_pdf_bytes."""
    rate_map = ctx.rate_map
    gross = ctx.gross

    pension_rate = rate_map.get("pension")
    employee_pf = _round2(gross * (pension_rate.employee_rate_pct / 100)) if pension_rate and pension_rate.employee_rate_pct else Decimal("0")
    employer_pf = _round2(gross * (pension_rate.employer_rate_pct / 100)) if pension_rate and pension_rate.employer_rate_pct else Decimal("0")

    social_rate = rate_map.get("social-insurance")
    employee_esi = _round2(gross * (social_rate.employee_rate_pct / 100)) if social_rate and social_rate.employee_rate_pct else Decimal("0")
    employer_esi = _round2(gross * (social_rate.employer_rate_pct / 100)) if social_rate and social_rate.employer_rate_pct else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employee_esi=employee_esi, employer_esi=employer_esi,
        tds=tds, annual_tax=annual_tax,
    )


def _calc_canada(ctx: PayrollContext) -> dict:
    """Canada: CPP (Canada Pension Plan) + EI (Employment Insurance) +
    progressive federal income tax (provincial tax excluded for
    simplicity). DB-backed rates.

    Reused PayrollResult fields: `social_security`/`employer_social_security`
    (CPP) and `employee_esi`/`employer_esi` (EI)."""
    rate_map = ctx.rate_map
    gross = ctx.gross

    cpp_rate = rate_map.get("cpp")
    social_security = _round2(gross * (cpp_rate.employee_rate_pct / 100)) if cpp_rate and cpp_rate.employee_rate_pct else Decimal("0")
    employer_social_security = _round2(gross * (cpp_rate.employer_rate_pct / 100)) if cpp_rate and cpp_rate.employer_rate_pct else Decimal("0")

    ei_rate = rate_map.get("ei")
    employee_esi = _round2(gross * (ei_rate.employee_rate_pct / 100)) if ei_rate and ei_rate.employee_rate_pct else Decimal("0")
    employer_esi = _round2(gross * (ei_rate.employer_rate_pct / 100)) if ei_rate and ei_rate.employer_rate_pct else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        social_security=social_security, employer_social_security=employer_social_security,
        employee_esi=employee_esi, employer_esi=employer_esi,
        tds=tds, annual_tax=annual_tax,
    )


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
