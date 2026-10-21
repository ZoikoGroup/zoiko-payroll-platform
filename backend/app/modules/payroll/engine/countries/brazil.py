"""
engine/countries/brazil.py
--------------------------
Brazil (CLT) payroll calculation engine — ZP-BR-ENG-001 v1.0, Priority Market #12.

Pure: no ORM, no framework — everything it reads arrives on the PayrollContext
(the brazil_* fields in engine/base.py), resolved by the service layer before
dispatch.  This module NEVER queries the database, reads config files, or calls
any I/O.

Statutory scope (2026 baseline):
  1. Employee INSS progressive table (BR-008) — four brackets, 7.5/9/12/14%.
     Multi-employment offset: unknown concurrent data → BLOCKED (BR-009).
  2. IRRF monthly withholding (BR-012/BR-013):
       a. Legal deductions vs Simplified Monthly Deduction (R$607.20) — the
          more beneficial for the employee wins automatically.
       b. Progressive table (five bands, 0–27.5%).
       c. 2026 reduction (Law 15.270/2025): zero-tax up to R$5,000; declining
          reduction to R$7,350; none above.
  3. Employer contributions (BR-017/BR-018/BR-020):
       a. Standard CPP 20% (or 10% in the CPRB 2026 transition).
       b. RAT × FAP (adjusted risk rate).
       c. Third-party (Outras Entidades / FPAS) variable rate.
  4. FGTS: 8% ordinary CLT, 2% apprentice (BR-045).
  5. Salário-Família: R$67.54/dependent when eligible (BR-025).
  6. Vale-Transporte (BR-029): the employee pays up to 6% of the CONTRACTED
     base salary, never more than the actual benefit.
  7. Alimony (BR-032): a court order reduces BOTH the IRRF legal-deduction base
     and the employee's net pay (it is paid out, not retained).

Phase 5 (this file) makes the engine real:
  * `calculate()` is the entry point; the Phase 2 draft and its silent defaults
    are gone.
  * FAIL-CLOSED (BR-001): every required input comes from `ctx.brazil_inputs`
    and a missing one raises BrazilCalculationBlockedError — never a default.
    The old RAT 2% / FAP 1.0 / third-party 0% fallbacks are removed.
  * DATE-DRIVEN (BR-014): INSS/FGTS/Salário-Família/CPP resolve from the
    competence month; IRRF (table, reduction) from the payment date. A date
    outside the content raises BR_CONTENT_YEAR_UNAVAILABLE.
  * BASES from rubric incidence (BR-002/BR-005): each earning contributes to a
    base only when its eSocial incidence code says so
    (engine/jurisdictions/brazil/bases.py) — gross is no longer every base.
  * Apprentice status comes from the eSocial category (101 ordinary CLT /
    103 apprentice — BR-045), not a raw boolean.
  * Minimum-wage floor (BR-040): a contracted salary below the statutory
    minimum blocks BR_BELOW_MINIMUM_WAGE.

Open defects and gates: docs/brazil/BRAZIL_PHASE_0_GAP_ASSESSMENT.md §7;
content is DRAFT until the human gate-G1 review (docs/brazil/BRAZIL_PHASE_5_PLAN.md).

The result is a plain dict consumed by engine/standard.py's StandardStrategy
through the `br_result` key plus flat `br_*` fields.

Golden-fixture targets (§18 of spec):
  F1  — Ordinary CLT monthly wage (INSS, IRRF with reduction, FGTS)
  F2  — Wage with variable/premium components (Phase 5b)
  F3  — 13th-salary (Phase 7)
  F4  — Vacation (Phase 7)
  F5  — Termination (Phase 7)
  F6  — Minimum-wage floor case
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries import brazil_content as content
from app.modules.payroll.engine.countries.brazil_content import (
    # INSS
    INSS_2026_BRACKETS,
    INSS_CEILING,
    MAX_INSS_CONTRIBUTION,
    # IRRF
    IRRF_2026_TABLE,
    IRRF_DEPENDENT_DEDUCTION,
    IRRF_SIMPLIFIED_MONTHLY_DEDUCTION,
    IRRF_2026_REDUCTION_ZERO_CEILING,
    IRRF_2026_REDUCTION_MAX_ZERO,
    IRRF_2026_REDUCTION_PHASE_CEILING,
    IRRF_2026_REDUCTION_A,
    IRRF_2026_REDUCTION_B,
    # Salário-Família
    SALARIO_FAMILIA_CEILING,
    SALARIO_FAMILIA_QUOTA,
    # FGTS
    FGTS_ORDINARY_RATE,
    FGTS_APPRENTICE_RATE,
    # Employer
    STANDARD_CPP_RATE,
    FINANCIAL_SECTOR_CPP_ADDON,
    CPRB_2026_CPP_RATE,
    VALE_TRANSPORTE_MAX_DEDUCTION_PCT,
    STANDARD_SYSTEM_RUBRICS,
)
from app.modules.payroll.engine.jurisdictions.brazil.bases import resolve_bases

_COUNTRY = "BR"
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
ENGINE_VERSION = "BR-ENGINE-2026.2"

# eSocial employee categories this engine models: 101 = ordinary CLT employee,
# 103 = apprentice (FGTS 2%). Anything else BLOCKS (BR-045).
CATEGORY_ORDINARY_CLT = "101"
CATEGORY_APPRENTICE = "103"
SUPPORTED_CATEGORIES = (CATEGORY_ORDINARY_CLT, CATEGORY_APPRENTICE)


# ── Error classes ──────────────────────────────────────────────────────────────

class BrazilCalculationBlockedError(MissingComplianceConfigurationError):
    """A Brazil statutory calculation that must not proceed — a missing required
    input, an unknown category/rubric, a date outside the content, or a
    below-minimum contracted salary (BR-001: fail-closed; never silently
    default). Subclassing MissingComplianceConfigurationError is what makes
    main.py answer it as a clean 4xx rather than a 500. `key` is the coded
    reason."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Brazil calculation blocked ({key}): {reason}",)


BRBlock = BrazilCalculationBlockedError


# ── Internal helpers ───────────────────────────────────────────────────────────

def _r2(value: Decimal) -> Decimal:
    """Round to 2 decimal places, ROUND_HALF_UP (Brazilian standard)."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r5(value: Decimal) -> Decimal:
    """Round to 5 decimal places (rate/intermediate precision)."""
    return Decimal(value).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def _dec(value) -> Decimal:
    return Decimal(str(value))


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _as_date(value) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


# ── 1. Employee INSS (BR-008) ─────────────────────────────────────────────────

def _calculate_inss_employee(
    gross_inss: Decimal,
    concurrent_base: Decimal = ZERO,
    concurrent_deducted: Decimal = ZERO,
    brackets=INSS_2026_BRACKETS,
    ceiling: Decimal = INSS_CEILING,
    maximum: Decimal = MAX_INSS_CONTRIBUTION,
) -> Dict[str, Any]:
    """
    Calculate progressive employee INSS contribution (BR-008).

    Args:
        gross_inss:          Employee's own CP-includable salary this period.
        concurrent_base:     Salary-of-contribution already absorbed across all
                             prior/concurrent employment THIS month (BR-009).
                             Pass ZERO when no concurrent employment.
        concurrent_deducted: INSS already deducted/paid across all concurrent
                             employment. Pass ZERO when no concurrent employment.
        brackets/ceiling/maximum: the date-resolved table (Phase 5); the pinned
                             2026 constants are the defaults for direct unit
                             tests.

    Returns a dict with:
        inss_employee        — rounded employee contribution (deducted from net)
        base_inss            — CP-includable gross used as input
        concurrent_base      — echo of input
        concurrent_deducted  — echo of input
        brackets_detail      — list of per-bracket dicts (for trace)
        ceiling_reached      — True if combined salary ≥ INSS ceiling
        cap_applied          — True if contribution was forced to statutory max

    Rule BR-009: If concurrent data is required (caller passed concurrent_base
    or concurrent_deducted > 0), the function works normally. The caller is
    responsible for BLOCKING the calculation when concurrent data is known to
    exist but unavailable (unknown external data must never be assumed zero).
    """
    # Concurrent employment: the combined salary is progressive, and the own
    # portion is (table on combined) − (table on the concurrent base). The exact
    # total is rounded ONCE (decision D1).
    def table(amount: Decimal) -> Decimal:
        total = ZERO
        for lower, upper, rate, _full in brackets:
            if amount <= lower:
                break
            top = amount if upper is None else min(amount, upper)
            total += (top - lower) * rate
        return total

    brackets_detail = []
    for lower, upper, rate, _full in brackets:
        band_top = (gross_inss + concurrent_base) if upper is None else min(gross_inss + concurrent_base, upper)
        band_bottom = max(lower, concurrent_base)
        own_portion = max(ZERO, band_top - band_bottom)
        brackets_detail.append({
            "lower": str(lower),
            "upper": str(upper) if upper is not None else None,
            "rate_pct": str(rate * HUNDRED),
            "own_portion": str(_r2(own_portion)),
            "own_contribution_exact": str(own_portion * rate),
            "consumed_by_concurrent": own_portion == ZERO and concurrent_base > lower,
        })

    exact_own = table(gross_inss + concurrent_base) - table(concurrent_base)
    total_contribution = _r2(exact_own)

    ceiling_reached = (gross_inss + concurrent_base) >= ceiling
    cap_applied = False
    if total_contribution + concurrent_deducted > maximum:
        total_contribution = max(ZERO, maximum - concurrent_deducted)
        cap_applied = True

    return {
        "inss_employee": total_contribution,
        "base_inss": _r2(gross_inss),
        "concurrent_base": _r2(concurrent_base),
        "concurrent_deducted": _r2(concurrent_deducted),
        "brackets_detail": brackets_detail,
        "ceiling_reached": ceiling_reached,
        "cap_applied": cap_applied,
    }


# ── 2. IRRF with 2026 reduction (BR-012/BR-013) ───────────────────────────────

def _apply_2026_irrf_reduction(
    taxable_earnings: Decimal,
    raw_tax: Decimal,
    zero_ceiling: Decimal = IRRF_2026_REDUCTION_ZERO_CEILING,
    max_zero: Decimal = IRRF_2026_REDUCTION_MAX_ZERO,
    phase_ceiling: Decimal = IRRF_2026_REDUCTION_PHASE_CEILING,
    a: Decimal = IRRF_2026_REDUCTION_A,
    b: Decimal = IRRF_2026_REDUCTION_B,
) -> Dict[str, Any]:
    """
    Apply the Law 15.270/2025 monthly IRRF reduction (BR-013).

    Rule:
      ≤ R$5,000.00              → reduction = min(raw_tax, 312.89) → net tax = 0.00
      R$5,000.01 … R$7,350.00   → reduction = max(0, 978.62 − 0.133145 × rendimentos)
      > R$7,350.00             → no reduction

    The reduction is computed from the monthly taxable INCOME (the gross bases
    before deductions), never from the base de cálculo (decision D2, BR-K2 fixed
    in Phase 1). `taxable_earnings` is that income.
    """
    if taxable_earnings <= zero_ceiling:
        reduction = min(raw_tax, max_zero)
    elif taxable_earnings <= phase_ceiling:
        reduction = min(raw_tax, a - (b * taxable_earnings))
    else:
        reduction = ZERO

    reduction = _r2(max(ZERO, reduction))
    irrf_net = max(ZERO, _r2(raw_tax - reduction))
    return {
        "reduction": reduction,
        "irrf_after_reduction": irrf_net,
    }


def _calculate_irrf(
    gross_irrf: Decimal,
    inss_deducted: Decimal,
    dependents: int = 0,
    alimony: Decimal = ZERO,
    opt_out_simplified: bool = False,
    table=IRRF_2026_TABLE,
    dependent_deduction: Decimal = IRRF_DEPENDENT_DEDUCTION,
    simplified_deduction: Decimal = IRRF_SIMPLIFIED_MONTHLY_DEDUCTION,
    reduction_params=None,
) -> Dict[str, Any]:
    """
    Calculate ordinary monthly IRRF (BR-012/BR-013).

    Steps:
      1. Compute both deduction methods:
           a. Legal: INSS + dependents × R$189.59 + alimony
           b. Simplified: R$607.20
      2. Use the method producing the lower taxable base (more beneficial for
         the employee), unless the worker explicitly opted out of simplified.
      3. Apply the 2026 progressive table.
      4. Apply the 2026 reduction (Law 15.270/2025) on the gross taxable income.
      5. Return full trace.

    `table` and `reduction_params` are the date-resolved IRRF content (Phase 5);
    the pinned 2026 constants are the defaults for direct unit tests. BR-012:
    preserve which method won. BR-013: apply the table first, then the
    reduction — never merge the two into a fake bracket.
    """
    gross_irrf = _dec(gross_irrf)
    alimony = _dec(alimony)

    legal_deduction = _dec(inss_deducted) + (Decimal(dependents) * dependent_deduction) + alimony

    if opt_out_simplified or legal_deduction > simplified_deduction:
        chosen_deduction = legal_deduction
        deduction_method = "LEGAL"
    else:
        chosen_deduction = simplified_deduction
        deduction_method = "SIMPLIFIED"

    taxable_base = max(ZERO, _r2(gross_irrf - chosen_deduction))

    raw_tax = ZERO
    for lower, upper, rate, parcel in table:
        if taxable_base <= lower:
            break
        if upper is None or taxable_base <= upper:
            raw_tax = _r2(taxable_base * rate - parcel)
            break
    raw_tax = max(ZERO, raw_tax)

    reduction_kwargs = {}
    if reduction_params is not None:
        zero_ceiling, max_zero, phase_ceiling, a, b = reduction_params
        reduction_kwargs = {"zero_ceiling": zero_ceiling, "max_zero": max_zero,
                            "phase_ceiling": phase_ceiling, "a": a, "b": b}
    reduction_basis = _r2(gross_irrf)
    reduction_result = _apply_2026_irrf_reduction(reduction_basis, raw_tax, **reduction_kwargs)

    return {
        "irrf": reduction_result["irrf_after_reduction"],
        "base_irrf": _r2(gross_irrf),
        "legal_deduction": _r2(legal_deduction),
        "simplified_deduction": simplified_deduction,
        "deduction_method": deduction_method,
        "chosen_deduction": _r2(chosen_deduction),
        "taxable_base": taxable_base,
        "reduction_basis": reduction_basis,
        "raw_tax": raw_tax,
        "irrf_reduction": reduction_result["reduction"],
        "dependents": dependents,
        "alimony": _r2(alimony),
        "opt_out_simplified": opt_out_simplified,
    }


# ── 3. Employer Contributions (BR-017/BR-018/BR-020) ─────────────────────────

def _calculate_employer_charges(
    gross_cp: Decimal,
    rat_pct: Decimal,
    fap_factor: Decimal,
    third_party_pct: Decimal,
    cprb_opted: bool = False,
    financial_sector: bool = False,
    cpp_standard: Decimal = STANDARD_CPP_RATE,
    cpp_cprb: Decimal = CPRB_2026_CPP_RATE,
    cpp_addon: Decimal = FINANCIAL_SECTOR_CPP_ADDON,
) -> Dict[str, Any]:
    """
    Calculate employer-side social security obligations (BR-017/BR-018/BR-020).

    Components:
      - CPP (Contribuição Previdenciária Patronal):
            Standard: 20% (STANDARD_CPP_RATE)
            CPRB 2026 transition: 10% on covered payroll (BR-020)
            Financial sector add-on: +2.5% (only when certified)
      - RAT_adjusted = RAT% × FAP
      - Third parties (Outras Entidades, FPAS-defined): variable %

    The rates are the date-resolved content (Phase 5). BR-017: users cannot
    override a % directly — only the underlying CNAE/FPAS/FAP facts may be
    corrected with evidence.
    """
    if cprb_opted:
        cpp_rate = cpp_cprb
        cpp_regime = "CPRB_TRANSITION"
    else:
        cpp_rate = cpp_standard
        cpp_regime = "STANDARD"

    if financial_sector:
        cpp_rate = cpp_rate + cpp_addon
        cpp_regime = cpp_regime + "_FINANCIAL"

    cpp_employer = _r2(gross_cp * cpp_rate)
    rat_adjusted_rate = _r5(rat_pct * fap_factor / HUNDRED)
    rat_adjusted = _r2(gross_cp * rat_adjusted_rate)
    third_parties = _r2(gross_cp * third_party_pct / HUNDRED)

    return {
        "cpp_employer": cpp_employer,
        "cpp_rate_pct": str(cpp_rate * HUNDRED),
        "cpp_regime": cpp_regime,
        "rat_pct": str(rat_pct),
        "fap_factor": str(fap_factor),
        "rat_adjusted_rate_pct": str(rat_adjusted_rate * HUNDRED),
        "rat_adjusted": rat_adjusted,
        "third_party_pct": str(third_party_pct),
        "third_parties": third_parties,
        "employer_total": _r2(cpp_employer + rat_adjusted + third_parties),
        "gross_cp": _r2(gross_cp),
    }


# ── 4. FGTS (BR-045) ─────────────────────────────────────────────────────────

def _calculate_fgts(
    gross_fgts: Decimal,
    is_apprentice: bool = False,
    ordinary_rate: Decimal = FGTS_ORDINARY_RATE,
    apprentice_rate: Decimal = FGTS_APPRENTICE_RATE,
) -> Dict[str, Any]:
    """
    Calculate the FGTS monthly deposit (BR-045).

    Standard CLT: 8%. Apprentice (category 103): 2%. FGTS is an EMPLOYER
    LIABILITY — it is never deducted from employee net pay.
    """
    rate = apprentice_rate if is_apprentice else ordinary_rate
    return {
        "fgts_deposit": _r2(gross_fgts * rate),
        "base_fgts": _r2(gross_fgts),
        "rate_pct": str(rate * HUNDRED),
        "is_apprentice": is_apprentice,
    }


# ── 5. Salário-Família (BR-025) ────────────────────────────────────────────────

def _calculate_salario_familia(
    gross_remuneration: Decimal,
    dependents: int = 0,
    concurrent_base: Decimal = ZERO,
    ceiling: Decimal = SALARIO_FAMILIA_CEILING,
    quota: Decimal = SALARIO_FAMILIA_QUOTA,
) -> Dict[str, Any]:
    """
    Calculate Salário-Família (BR-025, Decree 12.797/2025).

    Eligible when the employee's total remuneration (own + concurrent) is
    ≤ R$1,980.38 and there is at least one eligible dependent. The benefit is
    R$67.54 per eligible dependent and is ADDED to net pay (never a deduction).
    """
    combined_remuneration = gross_remuneration + concurrent_base
    eligible = (dependents > 0) and (combined_remuneration <= ceiling)
    amount = _r2(quota * Decimal(dependents)) if eligible else ZERO

    return {
        "salario_familia": amount,
        "eligible": eligible,
        "dependents": dependents,
        "gross_remuneration": _r2(gross_remuneration),
        "concurrent_base": _r2(concurrent_base),
        "combined_remuneration": _r2(combined_remuneration),
        "ceiling": str(ceiling),
        "quota_per_dependent": str(quota),
    }


# ── 6. Vale-Transporte deduction (BR-029) ─────────────────────────────────────

def _calculate_vale_transporte_deduction(
    base_salary: Decimal,
    vt_benefit_amount: Decimal,
    max_pct: Decimal = VALE_TRANSPORTE_MAX_DEDUCTION_PCT,
) -> Decimal:
    """
    Calculate the Vale-Transporte employee deduction (BR-029).

    The employee pays up to 6% of the CONTRACTED base salary; the employer funds
    the rest. Returns the lesser of 6% of base or the actual VT benefit. Zero
    when no VT benefit is payable.
    """
    if vt_benefit_amount <= ZERO:
        return ZERO
    return min(_r2(base_salary * max_pct), _dec(vt_benefit_amount))


# ── 7. Entry point ────────────────────────────────────────────────────────────

def _require(inputs: Dict[str, Any], key: str, org: Optional[int]):
    value = inputs.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise BRBlock("BR_MISSING_INPUT",
                      f"brazil_inputs.{key} is required (BR-001: fail-closed, never defaulted)", org)
    return value


def calculate(ctx: PayrollContext) -> Dict[str, Any]:
    """engine/standard.py's _COUNTRY_CALC["BR"] — the Brazil CLT calculation.

    Reads every input from `ctx.brazil_inputs` (see engine/base.py); a missing
    required input BLOCKS (BR-001). Resolves each statutory rule from the
    content in force on the correct date and BLOCKS when a date is uncovered
    (BR-014). Derives the CP/IRRF/FGTS bases from the earnings' rubric
    incidences (BR-002/BR-005)."""
    if (ctx.country or "").upper() != _COUNTRY:
        return {}

    org = getattr(ctx, "brazil_organization_id", None)
    inputs = dict(getattr(ctx, "brazil_inputs", None) or {})

    def require(key):
        if key not in inputs or inputs[key] is None:
            raise BRBlock("BR_MISSING_INPUT",
                          f"brazil_inputs.{key} is required (BR-001 fail-closed; never defaulted)", org)
        return inputs[key]

    # ── Dates (BR-014) ────────────────────────────────────────────────────────
    competence = _as_date(require("competence_month"))
    if competence is None:
        raise BRBlock("BR_MISSING_INPUT",
                      "brazil_inputs.competence_month must be an ISO date (YYYY-MM-DD)", org)
    pay_date = _as_date(ctx.pay_date) or _as_date(inputs.get("pay_date")) or competence

    # ── Employer charge facts (required — no silent defaults) ─────────────────
    rat_pct = _dec(require("rat_pct"))
    fap_factor = _dec(require("fap_factor"))
    third_party_pct = _dec(require("third_party_pct"))
    cprb_opted = _as_bool(require("cprb_opted"))
    financial_sector = _as_bool(require("financial_sector"))

    # ── eSocial category → apprentice flag (BR-045) ───────────────────────────
    category = str(require("esocial_category")).strip()
    if category not in SUPPORTED_CATEGORIES:
        raise BRBlock("BR_UNSUPPORTED_CATEGORY",
                      f"esocial_category {category!r} is not modelled (supported: "
                      f"{', '.join(SUPPORTED_CATEGORIES)})", org)
    is_apprentice = category == CATEGORY_APPRENTICE

    # ── Contracted salary + minimum-wage floor (BR-040) ───────────────────────
    contract_salary = _dec(require("contract_salary"))

    # ── Optional employee facts ───────────────────────────────────────────────
    dependents = int(inputs.get("dependents", 0) or 0)
    alimony = _dec(inputs.get("alimony", "0") or "0")
    vt_benefit = _dec(inputs.get("vt_benefit", "0") or "0")
    opt_out_simplified = _as_bool(inputs.get("opt_out_simplified_irrf", False))
    concurrent_inss_base = _dec(inputs.get("concurrent_inss_base", "0") or "0")
    concurrent_inss_deducted = _dec(inputs.get("concurrent_inss_deducted", "0") or "0")
    concurrent_sf_base = _dec(inputs.get("concurrent_sf_base", "0") or "0")

    # ── Content in force (BR-014) ─────────────────────────────────────────────
    try:
        inss_brackets = content.inss_brackets(competence)
        inss_ceiling = content.inss_ceiling(competence)
        inss_max = content.inss_maximum_on(competence)
        irrf_table = content.irrf_table(pay_date)
        irrf_dependent = content.irrf_deduction_dependent(pay_date)
        irrf_simplified = content.irrf_deduction_simplified(pay_date)
        reduction_params = content.irrf_reduction_params(pay_date)
        sf_ceiling, sf_quota = content.salario_familia_params(competence)
        fgts_ordinary, fgts_apprentice = content.fgts_rates(competence)
        cpp_standard, cpp_addon, cpp_cprb = content.cpp_rates(competence)
        min_wage_monthly = content.minimum_wage(competence, "MONTHLY")
    except content.BrazilContentMissing as exc:
        raise BRBlock("BR_CONTENT_YEAR_UNAVAILABLE", str(exc), org)

    # ── Minimum-wage floor (BR-040) ───────────────────────────────────────────
    if contract_salary < min_wage_monthly:
        raise BRBlock("BR_BELOW_MINIMUM_WAGE",
                      f"contracted monthly salary R$ {contract_salary} is below the statutory minimum "
                      f"wage R$ {min_wage_monthly} for {competence.isoformat()}", org)

    # ── Bases from rubric incidence (BR-002/BR-005) ───────────────────────────
    earnings = require("earnings")
    if not isinstance(earnings, (list, tuple)) or not earnings:
        raise BRBlock("BR_MISSING_INPUT",
                      "brazil_inputs.earnings must be a non-empty list of {rubricCode, amount} (BR-002)", org)
    bases = resolve_bases(earnings, STANDARD_SYSTEM_RUBRICS)
    if bases["unmapped"]:
        raise BRBlock("BR_ENGINE_RUBRIC_UNKNOWN",
                      f"earnings reference rubrics with no statutory incidence in the catalogue: "
                      f"{', '.join(bases['unmapped'])}", org)
    base_cp = bases["base_cp"]
    base_irrf = bases["base_irrf"]
    base_fgts = bases["base_fgts"]

    # ── 1. Employee INSS (BR-008) ─────────────────────────────────────────────
    inss = _calculate_inss_employee(
        base_cp, concurrent_inss_base, concurrent_inss_deducted,
        brackets=inss_brackets, ceiling=inss_ceiling, maximum=inss_max,
    )
    br_inss_employee = inss["inss_employee"]

    # ── 2. IRRF (BR-012/BR-013) ───────────────────────────────────────────────
    irrf = _calculate_irrf(
        base_irrf, br_inss_employee, dependents=dependents, alimony=alimony,
        opt_out_simplified=opt_out_simplified, table=irrf_table,
        dependent_deduction=irrf_dependent, simplified_deduction=irrf_simplified,
        reduction_params=reduction_params,
    )
    br_irrf = irrf["irrf"]
    br_irrf_reduction = irrf["irrf_reduction"]

    # ── 3. Salário-Família (BR-025) ───────────────────────────────────────────
    sf = _calculate_salario_familia(
        base_cp, dependents=dependents, concurrent_base=concurrent_sf_base,
        ceiling=sf_ceiling, quota=sf_quota,
    )
    br_salario_familia = sf["salario_familia"]

    # ── 4. Vale-Transporte (BR-029) — on the CONTRACTED salary ────────────────
    br_vt_deduction = _calculate_vale_transporte_deduction(contract_salary, vt_benefit)

    # ── 5. Employer contributions (BR-017/BR-018/BR-020) — covered payroll ────
    employer = _calculate_employer_charges(
        base_cp, rat_pct, fap_factor, third_party_pct,
        cprb_opted=cprb_opted, financial_sector=financial_sector,
        cpp_standard=cpp_standard, cpp_cprb=cpp_cprb, cpp_addon=cpp_addon,
    )
    br_cpp_employer = employer["cpp_employer"]
    br_rat_adjusted = employer["rat_adjusted"]
    br_third_parties = employer["third_parties"]

    # ── 6. FGTS (BR-045) — employer liability, never in net ───────────────────
    fgts = _calculate_fgts(
        base_fgts, is_apprentice=is_apprentice,
        ordinary_rate=fgts_ordinary, apprentice_rate=fgts_apprentice,
    )
    br_fgts_deposit = fgts["fgts_deposit"]

    # ── Trace ─────────────────────────────────────────────────────────────────
    trace = {
        "jurisdiction": _COUNTRY,
        "engine_version": ENGINE_VERSION,
        "spec": "ZP-BR-ENG-001 v1.0",
        "competence_month": competence.isoformat(),
        "pay_date": pay_date.isoformat(),
        "esocial_category": category,
        "is_apprentice": is_apprentice,
        "contract_salary": str(_r2(contract_salary)),
        "minimum_wage_monthly": str(min_wage_monthly),
        "bases": {
            "source": "rubric_incidence",
            "base_cp": str(base_cp),
            "base_irrf": str(base_irrf),
            "base_fgts": str(base_fgts),
            "lines": bases["lines"],
        },
        "inss": {
            "base": str(inss["base_inss"]),
            "employee_contribution": str(br_inss_employee),
            "ceiling": str(inss_ceiling),
            "ceiling_reached": inss["ceiling_reached"],
            "cap_applied": inss["cap_applied"],
            "concurrent_base": str(inss["concurrent_base"]),
            "concurrent_deducted": str(inss["concurrent_deducted"]),
            "brackets_detail": inss["brackets_detail"],
        },
        "irrf": {
            "base": str(irrf["base_irrf"]),
            "legal_deduction": str(irrf["legal_deduction"]),
            "simplified_deduction": str(irrf["simplified_deduction"]),
            "deduction_method": irrf["deduction_method"],
            "chosen_deduction": str(irrf["chosen_deduction"]),
            "taxable_base": str(irrf["taxable_base"]),
            "raw_tax": str(irrf["raw_tax"]),
            "reduction_basis": str(irrf["reduction_basis"]),
            "reduction": str(br_irrf_reduction),
            "irrf": str(br_irrf),
            "dependents": dependents,
            "alimony": str(_r2(alimony)),
            "opt_out_simplified": opt_out_simplified,
        },
        "salario_familia": sf,
        "vale_transporte": {
            "benefit_amount": str(_r2(vt_benefit)),
            "base_salary": str(_r2(contract_salary)),
            "employee_deduction": str(br_vt_deduction),
            "max_pct": str(VALE_TRANSPORTE_MAX_DEDUCTION_PCT * HUNDRED) + "%",
        },
        "alimony_deduction": str(_r2(alimony)),
        "fgts": fgts,
        "employer_contributions": employer,
    }

    # ── Result dict (consumed by engine/standard.py) ──────────────────────────
    return {
        # Employee-side deductions (summed into total_deductions by standard.py):
        "employee_pf": br_inss_employee,                 # INSS employee
        "tds": br_irrf,                                  # IRRF withholding
        "br_vale_transporte_deduction": br_vt_deduction,
        "br_alimony_deduction": _r2(alimony),
        # Employer-only liabilities (never in net pay — BR-045):
        "br_fgts_deposit": br_fgts_deposit,
        "br_cpp_employer": br_cpp_employer,
        "br_rat_adjusted": br_rat_adjusted,
        "br_third_parties": br_third_parties,
        # Flat snapshot keys (persisted on PayslipItem):
        "br_base_inss": inss["base_inss"],
        "br_inss_employee": br_inss_employee,
        "br_base_irrf": irrf["base_irrf"],
        "br_irrf": br_irrf,
        "br_irrf_reduction": br_irrf_reduction,
        "br_salario_familia": br_salario_familia,
        "br_base_fgts": fgts["base_fgts"],
        # Salário-Família is a benefit added to net pay in standard.py:
        "br_salario_familia_net_addition": br_salario_familia,
        # Full trace:
        "br_result": {
            "spec": "ZP-BR-ENG-001 v1.0",
            "engine_version": ENGINE_VERSION,
            "competence_month": competence.isoformat(),
            "pay_date": pay_date.isoformat(),
            "esocial_category": category,
            "is_apprentice": is_apprentice,
            "contract_salary": str(_r2(contract_salary)),
            "minimum_wage_monthly": str(min_wage_monthly),
            "br_base_inss": str(inss["base_inss"]),
            "br_inss_employee": str(br_inss_employee),
            "br_base_irrf": str(irrf["base_irrf"]),
            "br_irrf": str(br_irrf),
            "br_irrf_reduction": str(br_irrf_reduction),
            "br_salario_familia": str(br_salario_familia),
            "br_vale_transporte_deduction": str(br_vt_deduction),
            "br_alimony_deduction": str(_r2(alimony)),
            "br_base_fgts": str(fgts["base_fgts"]),
            "br_fgts_deposit": str(br_fgts_deposit),
            "br_cpp_employer": str(br_cpp_employer),
            "br_rat_adjusted": str(br_rat_adjusted),
            "br_third_parties": str(br_third_parties),
            "trace": trace,
        },
    }
