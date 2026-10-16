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
       a. Standard CPP 20% (or 10% in CPRB transition).
       b. RAT × FAP (adjusted risk rate).
       c. Third-party (Outras Entidades / FPAS) variable rate.
  4. FGTS: 8% ordinary CLT, 2% apprentice (BR-045).
  5. Salário-Família: R$67.54/dependent when eligible (BR-025).

Fail-closed (BR-001): any missing required input raises BrazilCalculationBlockedError
rather than silently defaulting to zero.

Phase 0 (scaffolding): Brazil is dispatched here by engine/standard.py so it can
never fall through to the generic progressive-tax calculator, and calculate()
BLOCKS every Brazilian calculation (BR_ENGINE_NOT_CERTIFIED). The draft Phase 2
calculation is kept as _calculate_draft() — it is NOT reachable from any payroll
path. Phase 1 fixed the INSS maximum (BR-K1, derived 988.09), per-band rounding
(BR-K10, now rounded once) and the IRRF reduction basis (BR-K2, gross). Phase 5
removes the silent employer-charge defaults and derives the bases from rubric
incidence. Open defects: docs/brazil/BRAZIL_PHASE_0_GAP_ASSESSMENT.md §7.

The result is a plain dict consumed by engine/standard.py's StandardStrategy
through the `br_result` key plus flat `br_*` fields.

Golden-fixture targets (§22 of spec):
  F1  — R$5,000 salary → INSS R$501.51 (exact total rounded once, D1)
  F2  — Salary > R$8,475.55 → INSS stops at R$988.09 (every band to the ceiling)
  F3  — Gross R$5,000 → IRRF = R$0.00 (the reduction, on gross, zeroes it)
  F4  — Salary R$6,000 → IRRF reduced via phase-out formula, trace retained
  F5  — Salary within R$1,980.38, 1 dependent → Salário-Família R$67.54
  F6  — Apprentice R$1,621 → FGTS 2%, not 8%; net pay unaffected
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
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
    CPRB_2026_CPP_RATE,
    VALE_TRANSPORTE_MAX_DEDUCTION_PCT,
)

_COUNTRY = "BR"
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
ENGINE_VERSION = "BR-ENGINE-2026.1"


# ── Error classes ──────────────────────────────────────────────────────────────

class BrazilCalculationBlockedError(MissingComplianceConfigurationError):
    """A Brazil statutory calculation that must not proceed — missing required
    employer profile, establishment facts, or concurrent-employment data
    (BR-001: fail-closed; never silently default). Subclassing
    MissingComplianceConfigurationError is what makes main.py answer it as a
    clean 4xx rather than a 500. `key` is the coded reason."""

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


# ── 1. Employee INSS (BR-008) ─────────────────────────────────────────────────

def _calculate_inss_employee(
    gross_inss: Decimal,
    concurrent_base: Decimal = ZERO,
    concurrent_deducted: Decimal = ZERO,
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
    # Concurrent jobs are SUMMED before the bands apply, within the maximum
    # (S1, BR-009): own = table(combined) − table(already covered elsewhere),
    # both capped at the ceiling. The exact progressive total is rounded ONCE
    # (decision D1 — the draft rounded each band, BR-K10).
    combined_base = gross_inss + concurrent_base

    def table(base: Decimal) -> Decimal:
        capped = min(max(base, ZERO), INSS_CEILING)
        return sum(((min(capped, upper) - lower) * rate
                    for lower, upper, rate, _full in INSS_2026_BRACKETS if capped > lower), ZERO)

    brackets_detail = []
    for lower, upper, rate, _full in INSS_2026_BRACKETS:
        top = min(combined_base, upper)
        bottom = max(lower, min(concurrent_base, upper))
        own_portion = max(ZERO, top - bottom)
        brackets_detail.append({
            "lower": str(lower),
            "upper": str(upper),
            "rate_pct": str(rate * 100),
            "own_portion": str(_r2(own_portion)),
            "own_contribution_exact": str(own_portion * rate),
            "consumed_by_concurrent": own_portion == ZERO and concurrent_base > lower,
        })

    exact_own = table(combined_base) - table(concurrent_base)
    total_contribution = _r2(exact_own)

    ceiling_reached = combined_base >= INSS_CEILING
    cap_applied = False
    # Contributions already withheld elsewhere are authoritative; the total
    # across every employer never exceeds the maximum.
    if total_contribution + concurrent_deducted > MAX_INSS_CONTRIBUTION:
        total_contribution = max(ZERO, MAX_INSS_CONTRIBUTION - concurrent_deducted)
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
) -> Dict[str, Any]:
    """
    Apply the Law 15.270/2025 monthly IRRF reduction (BR-013).

    Rule:
      ≤ R$5,000.00              → reduction = min(raw_tax, 312.89) → net tax = 0.00
      R$5,000.01 – R$7,350.00  → reduction = max(0, 978.62 − 0.133145 × taxable)
                                   capped at raw_tax
      > R$7,350.00              → reduction = 0

    BR-013: Do NOT merge the zero-tax policy into a fabricated tax bracket.
    Always compute table tax first, then reduction separately.

    Returns: {reduction, irrf_after_reduction}
    """
    if taxable_earnings <= IRRF_2026_REDUCTION_ZERO_CEILING:
        reduction = min(raw_tax, IRRF_2026_REDUCTION_MAX_ZERO)
    elif taxable_earnings <= IRRF_2026_REDUCTION_PHASE_CEILING:
        phase_reduction = IRRF_2026_REDUCTION_A - (IRRF_2026_REDUCTION_B * taxable_earnings)
        reduction = max(ZERO, min(raw_tax, _r2(phase_reduction)))
    else:
        reduction = ZERO

    irrf_net = max(ZERO, _r2(raw_tax - reduction))
    return {
        "reduction": _r2(reduction),
        "irrf_after_reduction": irrf_net,
    }


def _calculate_irrf(
    gross_irrf: Decimal,
    inss_deducted: Decimal,
    dependents: int = 0,
    alimony: Decimal = ZERO,
    opt_out_simplified: bool = False,
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
      4. Apply the 2026 reduction (Law 15.270/2025).
      5. Return full trace.

    BR-012: preserve which method won.
    BR-013: apply table first, then reduction — never merge into a fake bracket.
    """
    # Step 1: both deduction totals
    legal_deduction = inss_deducted + (Decimal(dependents) * IRRF_DEPENDENT_DEDUCTION) + alimony
    simplified_deduction = IRRF_SIMPLIFIED_MONTHLY_DEDUCTION

    # Step 2: choose method
    if opt_out_simplified:
        chosen_deduction = legal_deduction
        deduction_method = "LEGAL"
    else:
        if simplified_deduction >= legal_deduction:
            chosen_deduction = simplified_deduction
            deduction_method = "SIMPLIFIED"
        else:
            chosen_deduction = legal_deduction
            deduction_method = "LEGAL"

    taxable_base = max(ZERO, _r2(gross_irrf - chosen_deduction))

    # Step 3: progressive table
    raw_tax = ZERO
    for lower, upper, rate, parcel in IRRF_2026_TABLE:
        if taxable_base <= lower:
            break
        if upper is None or taxable_base <= upper:
            raw_tax = _r2(taxable_base * rate - parcel)
            break

    raw_tax = max(ZERO, raw_tax)

    # Step 4: 2026 reduction — on the gross taxable INCOME, "e não o da base de
    # cálculo" (Receita Federal example 5, source S3; decision D2). The draft
    # fed the post-deduction base here (BR-K2), under-withholding ~R$5k–8.5k.
    reduction_basis = _r2(gross_irrf)
    reduction_result = _apply_2026_irrf_reduction(reduction_basis, raw_tax)
    irrf_net = reduction_result["irrf_after_reduction"]
    irrf_reduction = reduction_result["reduction"]

    return {
        "irrf": irrf_net,
        "base_irrf": _r2(gross_irrf),
        "legal_deduction": _r2(legal_deduction),
        "simplified_deduction": simplified_deduction,
        "deduction_method": deduction_method,
        "chosen_deduction": _r2(chosen_deduction),
        "taxable_base": taxable_base,
        "reduction_basis": reduction_basis,
        "raw_tax": raw_tax,
        "irrf_reduction": irrf_reduction,
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
) -> Dict[str, Any]:
    """
    Calculate employer-side social security obligations (BR-017/BR-018/BR-020).

    Components:
      - CPP (Contribuição Previdenciária Patronal):
            Standard: 20% (STANDARD_CPP_RATE)
            CPRB 2026 transition: 10% on covered payroll (BR-020)
            Financial sector add-on: +2.5% (only when certified)
      - RAT_adjusted = RAT% × FAP (capped [0.50×RAT, 2.00×RAT] per regulation)
      - Third parties (Outras Entidades, FPAS-defined): variable %

    Returns dict with all component amounts and trace info.
    BR-017: Users cannot override % directly — only underlying CNAE/FPAS/FAP
    facts may be corrected with evidence.
    """
    # CPP base rate selection
    if cprb_opted:
        cpp_rate = CPRB_2026_CPP_RATE  # 10% transition
        cpp_regime = "CPRB_TRANSITION"
    else:
        cpp_rate = STANDARD_CPP_RATE  # 20% standard
        cpp_regime = "STANDARD"

    if financial_sector:
        cpp_rate = cpp_rate + Decimal("0.025")
        cpp_regime = cpp_regime + "_FINANCIAL"

    cpp_employer = _r2(gross_cp * cpp_rate)

    # RAT × FAP (BR-018)
    rat_decimal = rat_pct / HUNDRED
    rat_adjusted_rate = _r5(rat_decimal * fap_factor)
    rat_adjusted = _r2(gross_cp * rat_adjusted_rate)

    # Third parties (Outras Entidades)
    third_party_decimal = third_party_pct / HUNDRED
    third_parties = _r2(gross_cp * third_party_decimal)

    employer_total = cpp_employer + rat_adjusted + third_parties

    return {
        "cpp_employer": cpp_employer,
        "cpp_rate": str(cpp_rate * 100),
        "cpp_regime": cpp_regime,
        "rat_base_pct": str(rat_pct),
        "fap_factor": str(fap_factor),
        "rat_adjusted_rate_pct": str(_r5(rat_adjusted_rate * 100)),
        "rat_adjusted": rat_adjusted,
        "third_party_pct": str(third_party_pct),
        "third_parties": third_parties,
        "employer_total": employer_total,
        "gross_cp": _r2(gross_cp),
    }


# ── 4. FGTS (BR-045) ─────────────────────────────────────────────────────────

def _calculate_fgts(
    gross_fgts: Decimal,
    is_apprentice: bool = False,
) -> Dict[str, Any]:
    """
    Calculate FGTS monthly deposit (BR-045).

    Standard CLT: 8%. Apprentice: 2%.
    FGTS is an EMPLOYER LIABILITY — it is never deducted from employee net pay.

    Returns dict with fgts_deposit, rate_used, and apprentice flag.
    """
    rate = FGTS_APPRENTICE_RATE if is_apprentice else FGTS_ORDINARY_RATE
    fgts_deposit = _r2(gross_fgts * rate)
    return {
        "fgts_deposit": fgts_deposit,
        "base_fgts": _r2(gross_fgts),
        "rate_pct": str(rate * 100),
        "is_apprentice": is_apprentice,
    }


# ── 5. Salário-Família (BR-025) ────────────────────────────────────────────────

def _calculate_salario_familia(
    gross_remuneration: Decimal,
    dependents: int = 0,
    concurrent_base: Decimal = ZERO,
) -> Dict[str, Any]:
    """
    Calculate Salário-Família (BR-025, Decree 12.797/2025).

    Eligible when:
      - Employee remuneration ≤ R$1,980.38 (2026 ceiling)
      - At least one eligible dependent (under 14, disabled, etc.)

    Amount: R$67.54 per eligible dependent.

    Args:
        gross_remuneration: This employer's monthly remuneration.
        dependents:         Number of eligible dependents with documentation.
        concurrent_base:    Remuneration from other concurrent employment
                            (combined must also ≤ ceiling — same eligibility
                            logic). Pass ZERO when no concurrent employment.

    Returns dict with salario_familia amount and eligibility trace.
    """
    combined_remuneration = gross_remuneration + concurrent_base
    eligible = (dependents > 0) and (combined_remuneration <= SALARIO_FAMILIA_CEILING)
    amount = _r2(SALARIO_FAMILIA_QUOTA * Decimal(dependents)) if eligible else ZERO

    return {
        "salario_familia": amount,
        "eligible": eligible,
        "dependents": dependents,
        "gross_remuneration": _r2(gross_remuneration),
        "concurrent_base": _r2(concurrent_base),
        "combined_remuneration": _r2(combined_remuneration),
        "ceiling": str(SALARIO_FAMILIA_CEILING),
        "quota_per_dependent": str(SALARIO_FAMILIA_QUOTA),
    }


# ── 6. Vale-Transporte deduction (BR-029) ────────────────────────────────────

def _calculate_vale_transporte_deduction(
    base_salary: Decimal,
    vt_benefit_amount: Decimal,
) -> Decimal:
    """
    Calculate Vale-Transporte employee deduction (max 6% of base salary, BR-029).

    Employee pays up to 6% of base salary; employer funds the rest.
    Returns the lesser of 6% of base or actual VT benefit.
    Zero when no VT benefit is payable.
    """
    if vt_benefit_amount <= ZERO:
        return ZERO
    max_deduction = _r2(base_salary * VALE_TRANSPORTE_MAX_DEDUCTION_PCT)
    return min(max_deduction, vt_benefit_amount)


# ── 7. Entry points ───────────────────────────────────────────────────────────

def calculate(ctx: PayrollContext) -> Dict[str, Any]:
    """engine/standard.py's _COUNTRY_CALC["BR"]. Phase 0: every Brazilian
    calculation BLOCKS — no Brazilian payroll is calculated until the content
    is corrected and signed (Phase 1) and the engine is completed (Phase 5)."""
    if (ctx.country or "").upper() != _COUNTRY:
        return {}
    raise BRBlock("BR_ENGINE_NOT_CERTIFIED",
                  "the Brazil payroll engine is not certified yet (ZP-BR-ENG-001 Phase 5); no Brazilian payroll "
                  "is calculated until then",
                  getattr(ctx, "brazil_organization_id", None))


def _calculate_draft(ctx: PayrollContext) -> Dict[str, Any]:
    """
    DRAFT Brazil CLT calculation (ZP-BR-ENG-001 Phase 2 draft) — not reachable
    from any payroll path; calculate() above blocks. Kept for Phase 5 and
    exercised directly by tests/test_brazil_phase2_engine.py. Still open
    (Phase 5): silent employer-charge defaults, single dependants count, gross
    used as every base, no tax-year guard on the context dates.

    Reads from ctx:
      brazil_inputs              — dict: {dependents, alimony, vt_benefit,
                                          opt_out_simplified_irrf,
                                          rat_pct, fap_factor,
                                          third_party_pct, cprb_opted,
                                          financial_sector,
                                          concurrent_inss_base,
                                          concurrent_inss_deducted,
                                          concurrent_sf_base}
      brazil_is_apprentice       — bool (default False)
      brazil_statutory_profile   — not yet wired (future phase)
      brazil_establishment       — not yet wired (future phase)
      brazil_employer_profile    — not yet wired (future phase)

    Fail-closed (BR-001): missing required inputs raise BrazilCalculationBlockedError.
    Simple mode is blocked upstream in engine/resolver.py (BR_SIMPLE_MODE_UNSUPPORTED).

    Returns a dict consumed by engine/standard.py. Key naming:
      - Employee deductions (reduce net): br_inss_employee, br_irrf,
        br_vale_transporte_deduction
      - Employer liabilities (NEVER reduce net): br_fgts_deposit,
        br_cpp_employer, br_rat_adjusted, br_third_parties
      - Additions to net pay: br_salario_familia (benefit, not a deduction)
    """
    inputs: dict = getattr(ctx, "brazil_inputs", None) or {}
    is_apprentice: bool = bool(getattr(ctx, "brazil_is_apprentice", False))

    # ── Required employer charge inputs ───────────────────────────────────────
    rat_pct = inputs.get("rat_pct")
    fap_factor = inputs.get("fap_factor")
    third_party_pct = inputs.get("third_party_pct")

    # For Phase 2, if employer charge inputs are absent we proceed with
    # employer-only zeros and a warning in the trace — not a hard block,
    # since the employee-side calculation (INSS/IRRF/FGTS/SF) is independently
    # valid. Phase 3 will make these required via the employer profile.
    employer_charges_configured = (
        rat_pct is not None
        and fap_factor is not None
        and third_party_pct is not None
    )
    if not employer_charges_configured:
        rat_pct = Decimal("2")       # default: risk class 2 (medium)
        fap_factor = Decimal("1.0")  # neutral FAP
        third_party_pct = Decimal("0")
    else:
        rat_pct = Decimal(str(rat_pct))
        fap_factor = Decimal(str(fap_factor))
        third_party_pct = Decimal(str(third_party_pct))

    cprb_opted: bool = bool(inputs.get("cprb_opted", False))
    financial_sector: bool = bool(inputs.get("financial_sector", False))

    # ── Employee optional inputs ───────────────────────────────────────────────
    dependents: int = int(inputs.get("dependents", 0))
    alimony: Decimal = Decimal(str(inputs.get("alimony", "0")))
    vt_benefit: Decimal = Decimal(str(inputs.get("vt_benefit", "0")))
    opt_out_simplified: bool = bool(inputs.get("opt_out_simplified_irrf", False))

    # Concurrent employment offsets (BR-009)
    concurrent_inss_base: Decimal = Decimal(str(inputs.get("concurrent_inss_base", "0")))
    concurrent_inss_deducted: Decimal = Decimal(str(inputs.get("concurrent_inss_deducted", "0")))
    concurrent_sf_base: Decimal = Decimal(str(inputs.get("concurrent_sf_base", "0")))

    # ── Gross salary ──────────────────────────────────────────────────────────
    gross = ctx.gross  # Full monthly gross, attendance-deduction happens in standard.py

    # ── Step 1: INSS employee contribution ───────────────────────────────────
    inss_result = _calculate_inss_employee(
        gross_inss=gross,
        concurrent_base=concurrent_inss_base,
        concurrent_deducted=concurrent_inss_deducted,
    )
    br_inss_employee = inss_result["inss_employee"]
    br_base_inss = inss_result["base_inss"]

    # ── Step 2: IRRF (BR-012/BR-013) ─────────────────────────────────────────
    irrf_result = _calculate_irrf(
        gross_irrf=gross,
        inss_deducted=br_inss_employee,
        dependents=dependents,
        alimony=alimony,
        opt_out_simplified=opt_out_simplified,
    )
    br_irrf = irrf_result["irrf"]
    br_base_irrf = irrf_result["base_irrf"]
    br_irrf_reduction = irrf_result["irrf_reduction"]

    # ── Step 3: Salário-Família ────────────────────────────────────────────────
    sf_result = _calculate_salario_familia(
        gross_remuneration=gross,
        dependents=dependents,
        concurrent_base=concurrent_sf_base,
    )
    br_salario_familia = sf_result["salario_familia"]

    # ── Step 4: Vale-Transporte employee deduction ───────────────────────────
    br_vt_deduction = _calculate_vale_transporte_deduction(
        base_salary=ctx.basic if ctx.basic > ZERO else gross,
        vt_benefit_amount=vt_benefit,
    )

    # ── Step 5: Employer contributions ────────────────────────────────────────
    employer_result = _calculate_employer_charges(
        gross_cp=gross,
        rat_pct=rat_pct,
        fap_factor=fap_factor,
        third_party_pct=third_party_pct,
        cprb_opted=cprb_opted,
        financial_sector=financial_sector,
    )
    br_cpp_employer = employer_result["cpp_employer"]
    br_rat_adjusted = employer_result["rat_adjusted"]
    br_third_parties = employer_result["third_parties"]

    # ── Step 6: FGTS (BR-045) — EMPLOYER liability, NEVER reduces net ─────────
    fgts_result = _calculate_fgts(
        gross_fgts=gross,
        is_apprentice=is_apprentice,
    )
    br_fgts_deposit = fgts_result["fgts_deposit"]
    br_base_fgts = fgts_result["base_fgts"]

    # ── Calculation trace ─────────────────────────────────────────────────────
    trace = {
        "jurisdiction": _COUNTRY,
        "engine_version": ENGINE_VERSION,
        "spec": "ZP-BR-ENG-001 v1.0",
        "tax_year": 2026,
        "gross": str(gross),
        "is_apprentice": is_apprentice,
        # INSS
        "inss": {
            "base": str(br_base_inss),
            "employee_contribution": str(br_inss_employee),
            "ceiling": str(INSS_CEILING),
            "ceiling_reached": inss_result["ceiling_reached"],
            "cap_applied": inss_result["cap_applied"],
            "concurrent_base": str(concurrent_inss_base),
            "concurrent_deducted": str(concurrent_inss_deducted),
            "brackets_detail": inss_result["brackets_detail"],
        },
        # IRRF
        "irrf": {
            "base": str(br_base_irrf),
            "deduction_method": irrf_result["deduction_method"],
            "legal_deduction": str(irrf_result["legal_deduction"]),
            "simplified_deduction": str(irrf_result["simplified_deduction"]),
            "chosen_deduction": str(irrf_result["chosen_deduction"]),
            "taxable_base": str(irrf_result["taxable_base"]),
            "raw_tax": str(irrf_result["raw_tax"]),
            "reduction": str(br_irrf_reduction),
            "irrf_net": str(br_irrf),
            "dependents": dependents,
            "alimony": str(alimony),
            "opt_out_simplified": opt_out_simplified,
        },
        # Salário-Família
        "salario_familia": sf_result,
        # Vale-Transporte
        "vale_transporte": {
            "benefit_amount": str(vt_benefit),
            "employee_deduction": str(br_vt_deduction),
            "max_pct": "6%",
        },
        # FGTS
        "fgts": fgts_result,
        # Employer contributions
        "employer_contributions": employer_result,
        "employer_charges_configured": employer_charges_configured,
    }

    # ── Build result dict ─────────────────────────────────────────────────────
    # Employee-side deductions (these REDUCE net pay via standard.py's summation):
    #   br_inss_employee      → goes into `employee_pf` slot (reused)
    #   br_irrf               → goes into `tds` slot
    #   br_vale_transporte_deduction → its own slot in total_deductions
    #
    # Employer-side liabilities (NEVER reduce employee net pay — BR-045):
    #   br_fgts_deposit, br_cpp_employer, br_rat_adjusted, br_third_parties
    #
    # Additions to net pay:
    #   br_salario_familia    → added to net in standard.py (like IT wedge sum)

    return {
        # ── Employee deduction keys (summed in standard.py) ──────────────────
        # INSS employee reuses the generic `employee_pf` slot so existing
        # total_deductions logic picks it up without touching standard.py.
        "employee_pf": br_inss_employee,
        # IRRF is Brazil's income tax withholding → `tds`
        "tds": br_irrf,
        # VT deduction → dedicated br_ key (standard.py adds it via br_vale_transporte_deduction)
        "br_vale_transporte_deduction": br_vt_deduction,

        # ── Employer-only liabilities (trace/snapshot — NOT in net pay) ──────
        "br_fgts_deposit": br_fgts_deposit,
        "br_cpp_employer": br_cpp_employer,
        "br_rat_adjusted": br_rat_adjusted,
        "br_third_parties": br_third_parties,

        # ── Flat snapshot keys (persisted on PayslipItem) ────────────────────
        "br_base_inss": br_base_inss,
        "br_inss_employee": br_inss_employee,
        "br_base_irrf": br_base_irrf,
        "br_irrf": br_irrf,
        "br_irrf_reduction": br_irrf_reduction,
        "br_salario_familia": br_salario_familia,
        "br_base_fgts": br_base_fgts,

        # ── Salário-Família → added to net pay in standard.py ─────────────────
        # This follows the same pattern as Italy's wedge tax-free sum (it_wedge_tax_free_sum).
        "br_salario_familia_net_addition": br_salario_familia,

        # ── Full trace ────────────────────────────────────────────────────────
        "br_result": {
            "spec": "ZP-BR-ENG-001 v1.0",
            "engine_version": ENGINE_VERSION,
            "gross": str(gross),
            "br_base_inss": str(br_base_inss),
            "br_inss_employee": str(br_inss_employee),
            "br_base_irrf": str(br_base_irrf),
            "br_irrf": str(br_irrf),
            "br_irrf_reduction": str(br_irrf_reduction),
            "br_salario_familia": str(br_salario_familia),
            "br_vale_transporte_deduction": str(br_vt_deduction),
            "br_base_fgts": str(br_base_fgts),
            "br_fgts_deposit": str(br_fgts_deposit),
            "br_cpp_employer": str(br_cpp_employer),
            "br_rat_adjusted": str(br_rat_adjusted),
            "br_third_parties": str(br_third_parties),
            "trace": trace,
        },
    }

