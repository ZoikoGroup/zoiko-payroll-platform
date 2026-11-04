"""Child support (spec §5, NZ-010/011/012).

Inland Revenue's instructed amount is deducted each payday, but never more
than the maximum share of net pay (the rest is protected). When the full
amount cannot be taken the shortfall is reported with the signed variation
code; operations can never force a deduction past the protected net.
Court attachment orders and IRD deduction notices are not supported yet: an
approved one in force BLOCKS rather than being silently skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.countries import new_zealand_content as content
from . import errors as E
from .pack import HUNDRED, ZERO, NzPack, dec, field, floor_cent, in_window, money, upper

SUPPORTED = ("CHILD_SUPPORT",)
NOT_YET_SUPPORTED = ("COURT_ATTACHMENT", "IRD_DEDUCTION_NOTICE")
TRIGGER_INSUFFICIENT_NET = "INSUFFICIENT_NET"


@dataclass
class CsResult:
    deduction: Decimal
    required: Decimal
    max_allowed: Decimal
    protected_net: Decimal
    shortfall: Decimal
    variation_code: Optional[str]
    notices: list = dc_field(default_factory=list)
    steps: list = dc_field(default_factory=list)


def in_force(notices: list, types: tuple, pay_date: date) -> list:
    return [n for n in notices or []
            if upper(field(n, "deduction_type")) in types and upper(field(n, "status")) == "APPROVED"
            and in_window(field(n, "effective_from"), field(n, "effective_to"), pay_date)]


def calculate_child_support(net_before: Decimal, notices: list, pay_date: date, pack: NzPack) -> CsResult:
    if in_force(notices, NOT_YET_SUPPORTED, pay_date):
        pack.block(E.CS_NOTICE_INVALID, "an approved court attachment or IRD deduction notice is not supported yet")
    active = in_force(notices, SUPPORTED, pay_date)
    if not active:
        return CsResult(ZERO, ZERO, ZERO, net_before, ZERO, None,
                        steps=[{"step": "notices", "value": "none", "note": None}])
    rnd = pack.rounder("nz_cs_rounding")
    required, listed = ZERO, []
    for notice in active:
        if field(notice, "amount_per_payday") is not None:
            amount = dec(field(notice, "amount_per_payday"))
        elif field(notice, "rate_pct") is not None:
            amount = rnd(net_before * dec(field(notice, "rate_pct")) / HUNDRED)
        else:
            pack.block(E.CS_NOTICE_INVALID, "a child-support notice has neither an amount nor a rate")
        required += amount
        listed.append({"noticeId": field(notice, "notice_id"), "version": field(notice, "version"),
                       "amount": money(amount)})
    max_pct, protected_pct = pack.pct("nz_cs_max_deduction_pct"), pack.pct("nz_cs_protected_net_pct")
    if max_pct + protected_pct != HUNDRED:
        pack.block(E.keyed(E.ROW_MISSING, "nz_cs_protected_net_pct"),
                   "the maximum deduction and protected-net shares do not add up to the whole net pay")
    max_allowed = net_before * max_pct / HUNDRED
    deduction = rnd(min(required, max_allowed))
    if deduction > max_allowed:
        # Rounding must never reach into the protected share (NZ-012).
        deduction = floor_cent(max_allowed)
    shortfall = required - deduction
    variation = None
    if shortfall > ZERO:
        rows = [r for r in pack.table(content.NZ_CS_VARIATION_RULE, "cs_variation_codes")
                if upper(field(r, "tax_formula")) == TRIGGER_INSUFFICIENT_NET]
        if len(rows) != 1:
            pack.block(E.CS_VARIATION_CODE_MISSING, "exactly one signed variation code for insufficient net pay is needed")
        variation = upper(field(rows[0], "filing_status"))
    steps = [{"step": "required", "value": money(required), "note": None},
             {"step": "maxAllowed", "value": money(max_allowed), "note": f"{max_pct}% of {money(net_before)}"},
             {"step": "deduction", "value": money(deduction), "note": None},
             {"step": "shortfall", "value": money(shortfall), "note": variation}]
    return CsResult(deduction, required, max_allowed, net_before - deduction, shortfall, variation, listed, steps)
