"""Student-loan deductions (spec §5).

Main SL codes deduct above the pay-period threshold; secondary SL codes deduct
on the whole payment. An Inland Revenue certificate (special deduction rate
or nil deduction) overrides the standard deduction for its period, and
approved STUDENT_LOAN_EXTRA notices are added on top.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from typing import Optional

from . import errors as E
from .pack import HUNDRED, SL_THRESHOLD_KEY, ZERO, NzPack, dec, field, in_window, money, upper

NIL, RATE = "NIL_DEDUCTION", "SPECIAL_DEDUCTION_RATE"
WHOLE_PAYMENT = "WHOLE_PAYMENT"


@dataclass
class SlResult:
    deduction: Decimal
    standard: Decimal
    extra: Decimal
    basis: str
    threshold: Optional[Decimal]
    steps: list = dc_field(default_factory=list)


def _certificate(profile, pay_date: date, pack: NzPack) -> Optional[str]:
    kind = upper(field(profile, "sl_certificate_type"))
    if not kind:
        return None
    if kind not in (NIL, RATE) or not field(profile, "sl_certificate_ref") \
            or field(profile, "sl_certificate_valid_from") is None:
        pack.block(E.SL_CERTIFICATE_INVALID, "the student-loan certificate is incomplete")
    if kind == RATE and field(profile, "sl_certificate_rate_pct") is None:
        pack.block(E.SL_CERTIFICATE_INVALID, "the special deduction rate certificate has no rate")
    if not in_window(field(profile, "sl_certificate_valid_from"), field(profile, "sl_certificate_valid_to"), pay_date):
        return None
    return kind


def _extras(base: Decimal, notices: list, pay_date: date, rnd) -> Decimal:
    total = ZERO
    for notice in notices or []:
        if upper(field(notice, "deduction_type")) != "STUDENT_LOAN_EXTRA" \
                or upper(field(notice, "status")) != "APPROVED" \
                or not in_window(field(notice, "effective_from"), field(notice, "effective_to"), pay_date):
            continue
        if field(notice, "amount_per_payday") is not None:
            total += rnd(dec(field(notice, "amount_per_payday")))
        else:
            total += rnd(base * dec(field(notice, "rate_pct")) / HUNDRED)
    return total


def calculate_student_loan(base: Decimal, code, profile, frequency: str, pay_date: date,
                           notices: list, pack: NzPack) -> SlResult:
    rnd = pack.rounder("nz_sl_rounding")
    certificate = _certificate(profile, pay_date, pack)
    threshold = None
    if certificate == NIL:
        standard, basis = ZERO, "NIL"
    elif certificate == RATE:
        standard, basis = rnd(base * dec(field(profile, "sl_certificate_rate_pct")) / HUNDRED), "CERTIFICATE"
    elif not code.student_loan:
        standard, basis = ZERO, "NONE"
    elif code.income_class == "MAIN":
        threshold = pack.amount(SL_THRESHOLD_KEY[frequency])
        standard = rnd(max(base - threshold, ZERO) * pack.pct("nz_sl_rate") / HUNDRED)
        basis = "MAIN_THRESHOLD"
    else:
        pack.text("nz_sl_secondary_basis", allowed=(WHOLE_PAYMENT,))
        standard, basis = rnd(base * pack.pct("nz_sl_rate") / HUNDRED), WHOLE_PAYMENT
    extra = _extras(base, notices, pay_date, rnd)
    steps = [{"step": "basis", "value": basis, "note": None},
             {"step": "standard", "value": money(standard),
              "note": f"threshold {money(threshold)}" if threshold is not None else None},
             {"step": "extra", "value": money(extra), "note": None}]
    return SlResult(standard + extra, standard, extra, basis, threshold, steps)
