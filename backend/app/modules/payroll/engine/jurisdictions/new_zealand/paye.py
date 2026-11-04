"""PAYE (spec §3): tax-code routing and the MAIN / SECONDARY / ND / STC branches.

An unsupported code is rejected, never mapped to a "closest" code. The main
code method, secondary and no-notification rates and the independent earner
tax credit come only from signed authority tables (empty until gate G1).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.countries import new_zealand_content as content
from . import errors as E
from .pack import HUNDRED, ZERO, NzPack, dec, field, in_window, money, opt_dec, upper

ANNUALISE_BANDS = "ANNUALISE_BANDS"
MAIN, SECONDARY, SPECIAL = "MAIN", "SECONDARY", "SPECIAL"
SL_SUFFIX = " SL"


@dataclass(frozen=True)
class TaxCode:
    code: str
    income_class: str
    student_loan: bool
    independent_earner: bool


@dataclass
class PayeResult:
    paye: Decimal
    branch: str
    period_factor: Optional[Decimal]
    steps: list = dc_field(default_factory=list)


def resolve_tax_code(profile, pack: NzPack) -> TaxCode:
    rows = {upper(field(r, "filing_status")): r for r in pack.table(content.NZ_TAX_CODE_RULE, "tax_codes")}
    code = upper(field(profile, "tax_code"))
    row = rows.get(code)
    if row is None:
        pack.block(E.TAX_CODE_UNSUPPORTED, f"tax code {code!r} is not in the New Zealand catalogue")
    if upper(field(row, "assessment_basis")) == "REFUSED":
        pack.block(E.keyed(E.TAX_CODE_REFUSED, code), f"tax code {code} is outside the first release")
    state = upper(field(profile, "ird_number_state"))
    if state in ("MISSING", "INVALID") and code != "ND":
        pack.block(E.TAX_CODE_UNSUPPORTED, f"IRD number state {state} requires the ND code")
    if code == "ND" and upper(field(profile, "tax_code_source")) != "NO_NOTIFICATION":
        pack.block(E.TAX_CODE_UNSUPPORTED, "ND applies only when no tax code was notified")
    return TaxCode(code=code, income_class=upper(field(row, "tax_regime")),
                   student_loan=upper(field(row, "tax_column")) == "SL",
                   independent_earner=upper(field(row, "tax_table_number")) == "IETC")


def band_tax(annual: Decimal, bands: list) -> tuple:
    """Tax on `annual`: each band's rate applies to the part above min_amount
    up to max_amount (None = no upper limit)."""
    total, steps = ZERO, []
    for band in bands:
        low, high, rate = dec(field(band, "min_amount")), opt_dec(field(band, "max_amount")), dec(field(band, "rate_pct"))
        if annual <= low:
            break
        part = (annual if high is None or annual < high else high) - low
        tax = part * rate / HUNDRED
        total += tax
        steps.append({"step": f"band {low}-{high if high is not None else 'open'} @ {rate}%",
                      "value": money(tax), "note": f"on {money(part)}"})
    return total, steps


def ietc_credit(annual: Decimal, rows: list, pack: NzPack) -> Decimal:
    """Independent earner tax credit (annual): flat_amount less rate_pct of the
    income above the band's min_amount, never below zero. Bands must be
    contiguous; income in no band earns no credit."""
    for current, following in zip(rows, rows[1:]):
        if opt_dec(field(current, "max_amount")) != dec(field(following, "min_amount")):
            pack.block(E.keyed(E.TABLE_EMPTY, "ietc_parameters"), "independent earner bands are not contiguous")
    for row in rows:
        low, high = dec(field(row, "min_amount")), opt_dec(field(row, "max_amount"))
        if low < annual and (high is None or annual <= high):
            credit = dec(field(row, "flat_amount")) - (annual - low) * dec(field(row, "rate_pct")) / HUNDRED
            return max(credit, ZERO)
    return ZERO


def _single(pack: NzPack, rows: list, key: str, what: str):
    if len(rows) != 1:
        pack.block(E.keyed(E.ROW_MISSING, key), f"expected exactly one {what}, found {len(rows)}")
    return rows[0]


def calculate_paye(gross: Decimal, code: TaxCode, profile, frequency: str, pay_date: date,
                   pack: NzPack) -> PayeResult:
    rnd = pack.rounder("nz_paye_rounding")
    steps = [{"step": "taxCode", "value": code.code, "note": code.income_class}]

    if code.code == "STC":
        if not in_window(field(profile, "tailored_valid_from"), field(profile, "tailored_valid_to"), pay_date) \
                or field(profile, "tailored_valid_from") is None:
            pack.block(E.STC_OUT_OF_WINDOW, "the tailored tax code certificate does not cover the payday")
        rate = dec(field(profile, "tailored_rate_pct"))
        paye = rnd(gross * rate / HUNDRED)
        steps.append({"step": "tailoredRate", "value": str(rate), "note": None})
        return PayeResult(paye, "STC", None, steps)

    if code.code == "ND":
        row = _single(pack, pack.table(content.NZ_ND_RATE_RULE, "paye_nd_rate"), "paye_nd_rate", "ND rate")
        rate = dec(field(row, "rate_pct"))
        steps.append({"step": "ndRate", "value": str(rate), "note": None})
        return PayeResult(rnd(gross * rate / HUNDRED), "ND", None, steps)

    if code.income_class == SECONDARY:
        base_code = code.code[:-len(SL_SUFFIX)] if code.code.endswith(SL_SUFFIX) else code.code
        rows = [r for r in pack.table(content.NZ_SECONDARY_RATE_RULE, "paye_secondary_rates")
                if upper(field(r, "filing_status")) == base_code]
        row = _single(pack, rows, f"paye_secondary_rates:{base_code}", f"secondary rate for {base_code}")
        rate = dec(field(row, "rate_pct"))
        steps.append({"step": "secondaryRate", "value": str(rate), "note": base_code})
        return PayeResult(rnd(gross * rate / HUNDRED), "SECONDARY", None, steps)

    if code.income_class != MAIN:
        pack.block(E.TAX_CODE_UNSUPPORTED, f"tax code {code.code} has no calculation branch")
    methods = [r for r in pack.table(content.NZ_PAYE_METHOD_RULE, "paye_main_method")
               if upper(field(r, "filing_status")) == frequency]
    method = _single(pack, methods, f"paye_main_method:{frequency}", f"PAYE method for {frequency}")
    if upper(field(method, "tax_formula")) != ANNUALISE_BANDS:
        pack.block(E.keyed(E.ROW_MISSING, "paye_main_method", frequency), "unknown PAYE method")
    factor = dec(field(method, "flat_amount"))
    if factor <= ZERO:
        pack.block(E.keyed(E.ROW_MISSING, "paye_main_method", frequency), "the annualisation factor is not set")
    annual = gross * factor
    steps.append({"step": "annualised", "value": money(annual), "note": f"{money(gross)} x {factor}"})
    annual_tax, band_steps = band_tax(annual, pack.table(content.NZ_PAYE_BAND_RULE, "paye_bands"))
    steps.extend(band_steps)
    if code.independent_earner:
        credit = ietc_credit(annual, pack.table(content.NZ_IETC_RULE, "ietc_parameters"), pack)
        annual_tax = max(annual_tax - credit, ZERO)
        steps.append({"step": "ietcCredit", "value": money(credit), "note": "annual"})
    steps.append({"step": "annualTax", "value": money(annual_tax), "note": None})
    paye = rnd(annual_tax / factor)
    steps.append({"step": "periodTax", "value": money(paye), "note": f"/ {factor}"})
    return PayeResult(paye, "MAIN", factor, steps)
