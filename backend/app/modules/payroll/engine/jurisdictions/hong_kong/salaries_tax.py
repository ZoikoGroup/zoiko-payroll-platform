"""Hong Kong Salaries Tax — INFORMATIONAL estimate only (ZP-HK-ENG-001 §7,
HK-012; IRD PAM 61(e) "Allowances, Deductions and Tax Rate Table", Aug 2026
— SourceArtifact ird_pam61e).

Hong Kong is NOT a monthly-PAYE jurisdiction: Salaries Tax is assessed by the
IRD on the employee. This module is never called by the payroll calculator,
never produces a `tds` / withholding value, and every result is labelled
INFORMATIONAL_NOT_WITHHELD. It exists for the employee tax-information view
and for reconciling the IRD annual figures.

Tax payable = the LOWER of
  * progressive rates on net chargeable income (income − deductions −
    allowances), bands = pack rows rule_type HK_SALARIES_TAX_PROGRESSIVE;
  * standard rate(s) on net income (before allowances), tiers = pack rows
    rule_type HK_SALARIES_TAX_STANDARD (2024/25 onwards: 15% on the first
    HK$5,000,000, 16% on the remainder);
then reduced by the year's one-off tax reduction where legislated (pack rows
hk_tax_reduction_rate / hk_tax_reduction_cap for that year of assessment).

Allowances are pack rows keyed by year of assessment (effective_from = 1 Apr).
"""

from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, cents, dec, row_ref,
)

PROGRESSIVE = "HK_SALARIES_TAX_PROGRESSIVE"
STANDARD = "HK_SALARIES_TAX_STANDARD"
LABEL = "INFORMATIONAL_NOT_WITHHELD"

# Allowance keys → pack ContributionRate component_key (flat_amount).
ALLOWANCE_KEYS = {
    "basic": "hk_allowance_basic",
    "married": "hk_allowance_married",
    "single_parent": "hk_allowance_single_parent",
    "child": "hk_allowance_child",
    "child_additional": "hk_allowance_child_additional",
    "dependent_parent_60": "hk_allowance_dependent_parent_60",
    "dependent_parent_55": "hk_allowance_dependent_parent_55",
    "dependent_parent_60_additional": "hk_allowance_dependent_parent_60_additional",
    "dependent_parent_55_additional": "hk_allowance_dependent_parent_55_additional",
    "personal_disability": "hk_allowance_personal_disability",
    "disabled_dependant": "hk_allowance_disabled_dependant",
    "dependent_sibling": "hk_allowance_dependent_sibling",
}

# Deduction keys → pack ContributionRate component_key holding the CEILING the
# IRD allows for that year of assessment (PAM 61(e) §3). A claim is operator
# input; the ceiling is statutory, so every claim is capped here and the cap is
# disclosed on the line — an estimate can never show a deduction the IRD would
# disallow, and a claim above the ceiling is visibly capped rather than dropped.
DEDUCTION_KEYS = {
    "mandatory_contributions": "hk_deduction_mandatory_contributions",
    "self_education": "hk_deduction_self_education",
    "home_loan_interest": "hk_deduction_home_loan_interest",
    "elderly_residential_care": "hk_deduction_elderly_residential_care",
    "domestic_rents": "hk_deduction_domestic_rents",
    "voluntary_mpf": "hk_deduction_mpf_voluntary",
    "assisted_reproductive": "hk_deduction_assisted_reproductive",
    "qvhi_premium": "hk_deduction_qvhi_premium",
}
# Claims the IRD limits to a SHARE of income rather than a money ceiling. The
# pack row is a fraction (0.35 = 35%), the ContributionRate convention.
DEDUCTION_PERCENT_KEYS = {"approved_donation": "hk_deduction_approved_donation_pct"}
# Elected ADDITIONAL ceilings (IRD "Increasing ceiling amount for concessionary
# deductions allowable for home loan interest and domestic rent", from YA
# 2024/25): +HK$20,000 when the taxpayer resides with a child born on or after
# 25 Oct 2023 and elects in writing. The election is an operator-asserted fact.
ADDITIONAL_CEILING_ELECTIONS = {
    "home_loan_interest_additional_ceiling": ("home_loan_interest", "hk_deduction_home_loan_interest_additional"),
    "domestic_rents_additional_ceiling": ("domestic_rents", "hk_deduction_domestic_rents_additional"),
}


def _band_tax(amount: Decimal, rows: list) -> tuple:
    remaining, tax, lines = dec(amount), ZERO, []
    for r in sorted(rows, key=lambda r: dec(r.min_amount)):
        lo = dec(r.min_amount)
        hi = dec(r.max_amount) if r.max_amount is not None else None
        width = (hi - lo) if hi is not None else remaining
        portion = max(min(remaining, width), ZERO)
        if portion <= ZERO:
            break
        band_tax = portion * dec(r.rate_pct) / Decimal("100")    # TaxSlab.rate_pct is a whole percentage
        tax += band_tax
        lines.append({"from": str(lo), "to": None if hi is None else str(hi), "rate": str(r.rate_pct),
                      "portion": str(cents(portion)), "tax": str(cents(band_tax)), "ref": row_ref(r)})
        remaining -= portion
    return cents(tax), lines


def _allowances(rate_map: dict, year_of_assessment: str, claims: dict) -> tuple:
    lines, total = [], ZERO
    for key, count in (claims or {}).items():
        if key not in ALLOWANCE_KEYS:
            raise HongKongCalculationBlockedError("salaries_tax_allowance", f"unknown allowance {key!r}")
        row = (rate_map or {}).get(ALLOWANCE_KEYS[key])
        if row is None or row.flat_amount is None:
            raise HongKongCalculationBlockedError(
                ALLOWANCE_KEYS[key], f"no {key} allowance row for {year_of_assessment}")
        amount = dec(row.flat_amount) * int(count)
        total += amount
        lines.append({"allowance": key, "count": int(count), "amount": str(cents(amount)), "ref": row_ref(row)})
    return lines, total


def _deductions(rate_map: dict, year_of_assessment: str, claims: dict, income: Decimal, other: Decimal,
                elections=()) -> tuple:
    """Each claim capped to the statutory ceiling for the year; the cap and any
    truncation are disclosed on the line.

    Approved donations: PAM 61(e) limits them to
    "(Income – Allowable Expenses – Depreciation Allowances) × 35%". The base is
    therefore the income less the already-established allowable outgoings and
    expenses (`other`), and NOT less the concessionary deductions claimed here
    (MPF, self-education, home-loan interest, …). Independent vector ST-22.
    """
    claims = claims or {}
    elections = set(elections or ())
    unknown_elections = elections - set(ADDITIONAL_CEILING_ELECTIONS)
    if unknown_elections:
        raise HongKongCalculationBlockedError("salaries_tax_election", f"unknown election {sorted(unknown_elections)[0]!r}")
    additional = {}
    for election in elections:
        deduction, key = ADDITIONAL_CEILING_ELECTIONS[election]
        row = (rate_map or {}).get(key)
        if row is None or row.flat_amount is None:
            raise HongKongCalculationBlockedError(key, f"no {deduction} additional ceiling row for {year_of_assessment}")
        additional[deduction] = (dec(row.flat_amount), row)
    money_claims = {k: v for k, v in claims.items() if k not in DEDUCTION_PERCENT_KEYS}
    unknown = [k for k in claims if k not in DEDUCTION_KEYS and k not in DEDUCTION_PERCENT_KEYS]
    if unknown:
        raise HongKongCalculationBlockedError("salaries_tax_deduction", f"unknown deduction {sorted(unknown)[0]!r}")

    lines, total = [], ZERO
    for key, claimed in money_claims.items():
        row = (rate_map or {}).get(DEDUCTION_KEYS[key])
        if row is None or row.flat_amount is None:
            raise HongKongCalculationBlockedError(
                DEDUCTION_KEYS[key], f"no {key} deduction ceiling row for {year_of_assessment}")
        ceiling = dec(row.flat_amount)
        extra = additional.get(key)
        if extra is not None:
            ceiling += extra[0]
        allowed = max(min(dec(claimed), ceiling), ZERO)
        total += allowed
        lines.append({"deduction": key, "claimed": str(cents(dec(claimed))), "ceiling": str(cents(ceiling)),
                      "allowed": str(cents(allowed)), "capped": dec(claimed) > ceiling, "basis": "MONEY_CEILING",
                      "ref": row_ref(row),
                      **({"additionalCeiling": str(cents(extra[0])), "additionalCeilingRef": row_ref(extra[1])}
                         if extra is not None else {})})

    # PAM 61(e): the donation base is income − allowable expenses − depreciation,
    # never income after the concessionary deductions above.
    remaining = max(dec(income) - dec(other), ZERO)
    percent_total = ZERO
    for key, claimed in claims.items():
        if key not in DEDUCTION_PERCENT_KEYS:
            continue
        row = (rate_map or {}).get(DEDUCTION_PERCENT_KEYS[key])
        if row is None or row.employee_rate_pct is None:
            raise HongKongCalculationBlockedError(
                DEDUCTION_PERCENT_KEYS[key], f"no {key} percentage row for {year_of_assessment}")
        ceiling = cents(remaining * dec(row.employee_rate_pct))      # fraction, e.g. 0.35
        # Percentage claims share one base, so together they may not exceed it.
        allowed = max(min(dec(claimed), ceiling, max(remaining - percent_total, ZERO)), ZERO)
        percent_total += allowed
        total += allowed
        lines.append({"deduction": key, "claimed": str(cents(dec(claimed))), "ceiling": str(cents(ceiling)),
                      "allowed": str(cents(allowed)), "capped": dec(claimed) > ceiling,
                      "basis": "SHARE_OF_INCOME_LESS_ALLOWABLE_EXPENSES", "base": str(cents(remaining)),
                      "ref": row_ref(row)})
    return lines, total


def estimate(*, year_of_assessment: str, rate_map: dict, slabs: list, income: Decimal,
             deductions: Decimal = ZERO, allowances: dict = None, deduction_claims: dict = None,
             elections=()) -> dict:
    """allowances: {key: count} over ALLOWANCE_KEYS (e.g. {"basic": 1, "child": 2}).
    deductions: an already-established total (e.g. an employee's declared total).
    deduction_claims: {key: amount} itemised over DEDUCTION_KEYS /
    DEDUCTION_PERCENT_KEYS, each capped to the statutory ceiling for the year —
    the itemised total is added to `deductions`.
    elections: ADDITIONAL_CEILING_ELECTIONS keys the taxpayer has made."""
    progressive = [s for s in slabs or [] if getattr(s, "rule_type", None) == PROGRESSIVE]
    standard = [s for s in slabs or [] if getattr(s, "rule_type", None) == STANDARD]
    if not progressive or not standard:
        raise HongKongCalculationBlockedError(
            "salaries_tax_rates", f"the rule pack has no Salaries Tax rate table for {year_of_assessment}")
    allowance_lines, allowance_total = _allowances(rate_map, year_of_assessment, allowances)
    deduction_lines, claimed_total = _deductions(rate_map, year_of_assessment, deduction_claims, dec(income),
                                                 dec(deductions), elections)
    deduction_total = dec(deductions) + claimed_total
    net_income = max(dec(income) - deduction_total, ZERO)
    nci = max(net_income - allowance_total, ZERO)
    prog_tax, prog_lines = _band_tax(nci, progressive)
    std_tax, std_lines = _band_tax(net_income, standard)
    tax = min(prog_tax, std_tax)
    # The one-off reduction is legislated year by year: no rows for a year of
    # assessment means none was legislated (reduction 0, stated in the output).
    # Exactly one of the two rows is a broken configuration, never "no
    # reduction" — refused.
    reduction = ZERO
    red_rate, red_cap = (rate_map or {}).get("hk_tax_reduction_rate"), (rate_map or {}).get("hk_tax_reduction_cap")
    if (red_rate is None) != (red_cap is None):
        missing = "hk_tax_reduction_cap" if red_cap is None else "hk_tax_reduction_rate"
        raise HongKongCalculationBlockedError(
            missing, "the one-off Salaries Tax reduction is half-configured (rate and cap are configured together)")
    if red_rate is not None and red_cap is not None:
        reduction = min(cents(tax * dec(red_rate.employee_rate_pct)), dec(red_cap.flat_amount))
    return {
        "label": LABEL,
        "notice": "Informational estimate only — Hong Kong Salaries Tax is assessed by the IRD on the employee. "
                  "Nothing here is withheld from pay.",
        "yearOfAssessment": year_of_assessment,
        "income": str(cents(dec(income))), "deductions": str(cents(deduction_total)),
        "deductionClaims": deduction_lines, "claimedDeductionTotal": str(cents(claimed_total)),
        "netIncome": str(cents(net_income)), "allowances": allowance_lines,
        "totalAllowances": str(cents(allowance_total)), "netChargeableIncome": str(cents(nci)),
        "progressive": {"tax": str(prog_tax), "bands": prog_lines},
        "standardRate": {"tax": str(std_tax), "tiers": std_lines},
        "basisApplied": "PROGRESSIVE" if prog_tax <= std_tax else "STANDARD_RATE",
        "taxBeforeReduction": str(tax), "taxReduction": str(cents(reduction)),
        "taxReductionBasis": ("PACK_ROWS — hk_tax_reduction_rate / hk_tax_reduction_cap" if red_rate is not None
                              else "NONE CONFIGURED for this year of assessment (one-off reductions are legislated "
                                   "year by year)"),
        "estimatedTax": str(cents(tax - reduction)),
    }
