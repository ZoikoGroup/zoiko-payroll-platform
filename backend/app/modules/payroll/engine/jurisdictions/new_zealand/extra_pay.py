"""Extra pay (lump sums, bonuses, final holiday pay, holiday pay in advance
taxed the alternative way) — spec §10, Phase 6. Pure.

The IRD extra-pay method is not stated by the specification: the method text
(nz_lump_sum_paye_method) and its parameters (NZ_LUMP_SUM rows) are signed
content, empty until gate G1, so every extra payment blocks in the shipped
pack. Secondary, no-notification and tailored codes keep their own flat rate
(the P3 branches). ACC and KiwiSaver run on the combined regular + extra base
in the caller, so the ACC cap is shared (NZ-013).

NZ_LUMP_SUM rows are keyed by filing_status:
  ANNUALISATION_FACTOR  flat_amount = the factor applied to the prior four
                        weeks' PAYE gross;
  SL_ON_EXTRA_PAY       tax_formula = WHOLE (student loan on the whole extra
                        payment, no pay-period threshold);
  IETC_ON_EXTRA_PAY     tax_formula = NONE (independent-earner codes take no
                        credit on extra pay) — required for ME codes.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.countries import new_zealand_content as content
from . import errors as E
from . import paye as _paye
from . import student_loan as _sl
from .pack import HUNDRED, ZERO, NzPack, dec, field, money, upper

FOUR_WEEK_ANNUALISE = "EXTRA_PAY_FOUR_WEEK_ANNUALISE"
WHOLE, NONE = "WHOLE", "NONE"


@dataclass
class ExtraPaye:
    paye: Decimal
    method: str
    steps: list = dc_field(default_factory=list)


def _method_row(pack: NzPack, name: str, required: bool = True):
    rows = [r for r in pack.table(content.NZ_LUMP_SUM_RULE, "lump_sum_method")
            if upper(field(r, "filing_status")) == name]
    if len(rows) != 1:
        if not required:
            return None
        pack.block(E.keyed(E.ROW_MISSING, "lump_sum_method", name), f"expected one {name} row, found {len(rows)}")
    return rows[0]


def extra_pay_paye(extra: Decimal, prior_four_week_gross, code, profile, frequency: str, pay_date: date,
                   pack: NzPack) -> ExtraPaye:
    """PAYE on an extra payment. MAIN codes: tax on (annualised prior four
    weeks + extra) less tax on the annualised prior four weeks."""
    if extra <= ZERO:
        return ExtraPaye(ZERO, "NONE", [])
    if code.income_class != _paye.MAIN:
        flat = _paye.calculate_paye(extra, code, profile, frequency, pay_date, pack)
        return ExtraPaye(flat.paye, f"FLAT_{flat.branch}", flat.steps)
    method = pack.text("nz_lump_sum_paye_method", allowed=(FOUR_WEEK_ANNUALISE,))
    factor = dec(field(_method_row(pack, "ANNUALISATION_FACTOR"), "flat_amount"))
    if factor <= ZERO:
        pack.block(E.keyed(E.ROW_MISSING, "lump_sum_method", "ANNUALISATION_FACTOR"), "the factor is not set")
    if code.independent_earner and upper(field(_method_row(pack, "IETC_ON_EXTRA_PAY"), "tax_formula")) != NONE:
        pack.block(E.keyed(E.ROW_MISSING, "lump_sum_method", "IETC_ON_EXTRA_PAY"),
                   "the independent earner treatment of extra pay is not signed")
    if prior_four_week_gross is None:
        pack.block(E.EXTRA_PAY_HISTORY_MISSING, "the prior four weeks' PAYE gross is not known")
    bands = pack.table(content.NZ_PAYE_BAND_RULE, "paye_bands")
    annual = dec(prior_four_week_gross) * factor
    without, _ = _paye.band_tax(annual, bands)
    with_extra, band_steps = _paye.band_tax(annual + extra, bands)
    paye = pack.rounder("nz_paye_rounding")(with_extra - without)
    steps = [{"step": "annualisedPrior", "value": money(annual), "note": f"{money(prior_four_week_gross)} x {factor}"},
             {"step": "taxWithout", "value": money(without), "note": None},
             {"step": "taxWith", "value": money(with_extra), "note": f"+ {money(extra)}"},
             *band_steps,
             {"step": "extraPaye", "value": money(paye), "note": method}]
    return ExtraPaye(paye, method, steps)


def extra_pay_student_loan(extra: Decimal, code, profile, pay_date: date, pack: NzPack) -> tuple:
    """(deduction, steps). A certificate in force overrides; otherwise SL
    codes deduct on the whole extra payment (signed SL_ON_EXTRA_PAY row)."""
    if extra <= ZERO:
        return ZERO, []
    rnd = pack.rounder("nz_sl_rounding")
    certificate = _sl._certificate(profile, pay_date, pack)
    if certificate == _sl.NIL:
        return ZERO, [{"step": "extraStudentLoan", "value": "0.00", "note": "NIL certificate"}]
    if certificate == _sl.RATE:
        amount = rnd(extra * dec(field(profile, "sl_certificate_rate_pct")) / HUNDRED)
        return amount, [{"step": "extraStudentLoan", "value": money(amount), "note": "certificate rate"}]
    if not code.student_loan:
        return ZERO, []
    if upper(field(_method_row(pack, "SL_ON_EXTRA_PAY"), "tax_formula")) != WHOLE:
        pack.block(E.keyed(E.ROW_MISSING, "lump_sum_method", "SL_ON_EXTRA_PAY"), "unknown student-loan treatment")
    amount = rnd(extra * pack.pct("nz_sl_rate") / HUNDRED)
    return amount, [{"step": "extraStudentLoan", "value": money(amount), "note": "whole extra payment"}]


def advance_method(options: Optional[dict], pack: NzPack) -> tuple:
    """(method, periods) for a HOLIDAY_PAY_ADVANCE run: the operator's choice,
    allowed only when a signed NZ_HOLIDAY_ADVANCE row names it."""
    options = options or {}
    method = upper(options.get("holidayAdvanceMethod"))
    allowed = {upper(field(r, "filing_status"))
               for r in pack.table(content.NZ_HOLIDAY_ADVANCE_RULE, "holiday_pay_advance_method")}
    if method not in allowed:
        pack.block(E.ADVANCE_METHOD_INVALID, f"holiday pay advance method {method or 'missing'!r} is not signed")
    periods = None
    if method == "STANDARD":
        try:
            periods = int(options.get("advancePeriods"))
        except (TypeError, ValueError):
            periods = 0
        if periods < 1:
            pack.block(E.ADVANCE_METHOD_INVALID, "the standard method needs the number of periods the pay covers")
    return method, periods
