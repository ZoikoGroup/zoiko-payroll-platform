"""Japan year-end adjustment (ZP-JP-ENG-001 §8, S3) — pure and fail-closed.

Recomputes the year's income tax from the annual figures and the employee's
APPROVED declarations, and returns the difference against what was withheld:

  income (this employer + a declared previous employer)
    -> employment-income deduction            JP_YEA_EID band on annual pay
    -> deductions: social insurance withheld / paid, life insurance
       (JP_YEA_LIFE_INS), earthquake insurance (capped), small-enterprise
       mutual aid, spouse (JP_YEA_SPOUSE), dependants (JP_YEA_DEPENDANT by
       category), basic (JP_YEA_BASIC band on total income)
    -> taxable income, rounded by jp_yea_taxable_rounding
    -> income tax: JP_YEA_RATE band (rate_pct of taxable minus flat_amount)
    -> housing-loan credit (never below zero)
    -> special reconstruction income tax (jp_reconstruction_surtax_pct)
    -> annual tax, rounded by jp_yea_rounding
    difference = withheld - annual tax  (positive: refund; negative: collect)

Every table and value ships empty / PENDING_G1, so every case BLOCKS until G1
signs them. No statutory number lives in this file.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries.shared import evaluate_tax_formula
from app.modules.payroll.engine.jurisdictions.japan import social_insurance as _si
from app.modules.payroll.engine.jurisdictions.japan import withholding as _wht

ZERO = Decimal("0")
HUNDRED = Decimal("100")
DECLARATION_TYPES = ("SPOUSE", "DEPENDANTS", "INSURANCE_PREMIUMS", "HOUSING_LOAN",
                     "PREVIOUS_EMPLOYER", "SMALL_ENTERPRISE_MUTUAL_AID")
# Amount fields each declaration may carry; anything else is refused.
DECLARATION_FIELDS = {
    "SPOUSE": ("spouse_income",),
    "DEPENDANTS": ("categories",),
    "INSURANCE_PREMIUMS": ("life", "earthquake", "social_insurance_paid"),
    "HOUSING_LOAN": ("credit",),
    "PREVIOUS_EMPLOYER": ("income", "withheld", "social_insurance"),
    "SMALL_ENTERPRISE_MUTUAL_AID": ("amount",),
}


class YEAResult(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _amount_of(payload, key, pack, rule):
    value = (payload or {}).get(key)
    if value in (None, ""):
        return ZERO
    try:
        amount = Decimal(str(value))
    except Exception:
        _wht._block(pack, rule, f"{key} {value!r} is not an amount")
    if amount < ZERO:
        _wht._block(pack, rule, f"{key} {amount} is negative")
    return amount


def _rows(slabs, rule_type, as_of):
    return [row for row in (slabs or [])
            if str(_wht._field(row, "rule_type") or "") == rule_type and _wht._in_force(row, as_of)]


def _table(slabs, rule_type, amount, pack, as_of):
    rows = _rows(slabs, rule_type, as_of)
    if not rows:
        _wht._block(pack, rule_type, f"the {rule_type} table is empty (signed at G1)")
    return _wht._band(rows, amount, rule_type, pack)


def _row_value(row, base, pack, rule_type):
    """formula(base), or flat + base x rate%, or rate%, or flat."""
    formula = _wht._field(row, "formula_expression")
    flat = _wht._field(row, "flat_amount")
    rate = _wht._field(row, "rate_pct")
    if formula:
        return evaluate_tax_formula(str(formula), base)
    if flat is not None and rate is not None:
        return _wht._dec(flat) + base * _wht._dec(rate) / HUNDRED
    if rate is not None:
        return base * _wht._dec(rate) / HUNDRED
    if flat is not None:
        return _wht._dec(flat)
    _wht._block(pack, rule_type, "the selected row has no formula, amount or rate")


def _scalar(pack, key):
    return _wht._scalar_amount(pack, key)


def yea_eligibility(facts: dict, pack) -> str | None:
    """The reason the employee is outside the year-end adjustment, or None."""
    if str(facts.get("residency") or "").upper() != "RESIDENT":
        return "NON_RESIDENT"
    if str(facts.get("declarationClass") or "").upper() != "PRIMARY":
        return "SECONDARY_COLUMN"
    limit = _scalar(pack, "jp_yea_income_limit")
    if _wht._dec(facts.get("annualIncome")) > limit:
        return "INCOME_ABOVE_LIMIT"
    return None


def year_end_tax(facts: dict, declarations: dict, slabs, pack, as_of=None) -> YEAResult:
    """``facts``: annualIncome, taxWithheld, socialInsuranceWithheld (this
    employer, from committed payslips). ``declarations``: {type: payload} of
    the APPROVED declarations. Returns every step as strings plus Decimals."""
    unknown = sorted(set(declarations) - set(DECLARATION_TYPES))
    if unknown:
        _wht._block(pack, "jp_yea_declaration", f"unknown declaration type(s) {unknown}")
    for kind, payload in declarations.items():
        extra = sorted(set(payload or {}) - set(DECLARATION_FIELDS[kind]))
        if extra:
            _wht._block(pack, "jp_yea_declaration", f"{kind} has unknown field(s) {extra}")

    previous = declarations.get("PREVIOUS_EMPLOYER") or {}
    income = _wht._dec(facts.get("annualIncome")) + _amount_of(previous, "income", pack, "PREVIOUS_EMPLOYER")
    withheld = _wht._dec(facts.get("taxWithheld")) + _amount_of(previous, "withheld", pack, "PREVIOUS_EMPLOYER")
    si = (_wht._dec(facts.get("socialInsuranceWithheld"))
          + _amount_of(previous, "social_insurance", pack, "PREVIOUS_EMPLOYER"))

    eid = _row_value(_table(slabs, "JP_YEA_EID", income, pack, as_of), income, pack, "JP_YEA_EID")
    employment_income = max(ZERO, income - max(ZERO, eid))

    premiums = declarations.get("INSURANCE_PREMIUMS") or {}
    deductions = {"socialInsurance": si + _amount_of(premiums, "social_insurance_paid", pack, "INSURANCE_PREMIUMS")}
    life = _amount_of(premiums, "life", pack, "INSURANCE_PREMIUMS")
    if life > ZERO:
        deductions["lifeInsurance"] = max(ZERO, _row_value(
            _table(slabs, "JP_YEA_LIFE_INS", life, pack, as_of), life, pack, "JP_YEA_LIFE_INS"))
    earthquake = _amount_of(premiums, "earthquake", pack, "INSURANCE_PREMIUMS")
    if earthquake > ZERO:
        deductions["earthquakeInsurance"] = min(earthquake, _scalar(pack, "jp_yea_earthquake_cap"))
    mutual = _amount_of(declarations.get("SMALL_ENTERPRISE_MUTUAL_AID"), "amount", pack,
                        "SMALL_ENTERPRISE_MUTUAL_AID")
    if mutual > ZERO:
        deductions["smallEnterpriseMutualAid"] = mutual
    if "SPOUSE" in declarations:
        spouse_income = _amount_of(declarations["SPOUSE"], "spouse_income", pack, "SPOUSE")
        rows = [row for row in _rows(slabs, "JP_YEA_SPOUSE", as_of)
                if spouse_income >= _wht._dec(_wht._field(row, "min_amount"))
                and (_wht._field(row, "max_amount") is None
                     or spouse_income < _wht._dec(_wht._field(row, "max_amount")))]
        if len(rows) != 1:
            _wht._block(pack, "JP_YEA_SPOUSE",
                        f"{len(rows)} spouse rows cover {spouse_income}; exactly one is required")
        deductions["spouse"] = _wht._dec(_wht._field(rows[0], "flat_amount"))
    categories = ((declarations.get("DEPENDANTS") or {}).get("categories") or {})
    if categories:
        if not isinstance(categories, dict):
            _wht._block(pack, "JP_YEA_DEPENDANT", "dependant categories must be {category: count}")
        rows = {str(_wht._field(r, "filing_status") or "").upper(): r
                for r in _rows(slabs, "JP_YEA_DEPENDANT", as_of)}
        total = ZERO
        for category, count in sorted(categories.items()):
            row = rows.get(str(category).upper())
            if row is None or _wht._field(row, "flat_amount") is None:
                _wht._block(pack, "JP_YEA_DEPENDANT", f"no signed deduction for dependant category {category}")
            if not isinstance(count, int) or count < 0:
                _wht._block(pack, "JP_YEA_DEPENDANT", f"count for {category} is not a whole number")
            total += _wht._dec(_wht._field(row, "flat_amount")) * count
        deductions["dependants"] = total
    basic_row = _table(slabs, "JP_YEA_BASIC", employment_income, pack, as_of)
    if _wht._field(basic_row, "flat_amount") is None:
        _wht._block(pack, "JP_YEA_BASIC", "the basic-deduction row has no amount")
    deductions["basic"] = _wht._dec(_wht._field(basic_row, "flat_amount"))

    events = []
    taxable_raw = max(ZERO, employment_income - sum(deductions.values(), ZERO))
    taxable = _si._rounded(taxable_raw, _si._rounder(pack, None, "jp_yea_taxable_rounding"),
                           "jp_yea_taxable_rounding", "jp_yea_taxable", events)
    rate_row = _table(slabs, "JP_YEA_RATE", taxable, pack, as_of)
    if _wht._field(rate_row, "rate_pct") is None:
        _wht._block(pack, "JP_YEA_RATE", "the selected rate row has no rate")
    income_tax = max(ZERO, taxable * _wht._dec(_wht._field(rate_row, "rate_pct")) / HUNDRED
                     - _wht._dec(_wht._field(rate_row, "flat_amount")))
    credit = _amount_of(declarations.get("HOUSING_LOAN"), "credit", pack, "HOUSING_LOAN")
    after_credit = max(ZERO, income_tax - credit)
    surtax_pct = _scalar(pack, "jp_reconstruction_surtax_pct")
    annual_raw = after_credit + after_credit * surtax_pct / HUNDRED
    annual_tax = _si._rounded(annual_raw, _si._rounder(pack, None, "jp_yea_rounding"),
                              "jp_yea_rounding", "jp_yea_annual_tax", events)
    difference = withheld - annual_tax
    return YEAResult(
        income=income, withheld=withheld, employment_income=employment_income,
        deductions=deductions, taxable=taxable, income_tax=income_tax,
        housing_loan_credit=min(credit, income_tax), annual_tax=annual_tax, difference=difference,
        trace={"income": str(income), "employmentIncomeDeduction": str(max(ZERO, eid)),
               "employmentIncome": str(employment_income),
               "deductions": {k: str(v) for k, v in deductions.items()},
               "taxable": str(taxable), "incomeTax": str(income_tax),
               "housingLoanCredit": str(min(credit, income_tax)),
               "surtaxPct": str(surtax_pct), "annualTax": str(annual_tax),
               "withheld": str(withheld), "difference": str(difference),
               "rateRow": {"min": str(_wht._field(rate_row, "min_amount")),
                           "ratePct": str(_wht._field(rate_row, "rate_pct"))},
               "roundingEvents": events})
