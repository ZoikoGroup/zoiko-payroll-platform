"""Statutory deduction order (NZ-011): an approved country policy, never tenant
configuration. It must name every statutory deduction exactly once and place
child support after the tax deductions, so a configurable order can never
override the protected-net rule. Voluntary deductions always come after.
"""
from __future__ import annotations

from . import errors as E
from .pack import NzPack

STATUTORY = ("PAYE", "ACC_LEVY", "STUDENT_LOAN", "KS_EMPLOYEE", "CHILD_SUPPORT")
TAX_LIKE = ("PAYE", "ACC_LEVY")
# A named order, so the policy fits ContributionRate.text_value (String(50)):
# the explicit five-item list is longer than that. The explicit comma list is still
# accepted (gate removal P8 fix, 2026-11-26).
NAMED_ORDERS = {"STATUTORY_ORDER": STATUTORY}


def expand(order: list) -> list:
    """A one-item list naming a NAMED_ORDERS entry expands to that order."""
    if len(order) == 1 and order[0] in NAMED_ORDERS:
        return list(NAMED_ORDERS[order[0]])
    return order


def precedence(pack: NzPack) -> list:
    try:
        order = pack.text_list("nz_deduction_precedence")
    except E.NZCalculationBlockedError as blocked:
        if not str(blocked.key).startswith(E.ROW_MISSING):
            raise
        pack.block(E.PRECEDENCE_PENDING, "the statutory deduction order is not decided (NZ-011)")
    order = expand(order)
    if sorted(order) != sorted(STATUTORY):
        pack.block(E.PRECEDENCE_PENDING, "the deduction order must name every statutory deduction exactly once")
    if any(order.index("CHILD_SUPPORT") < order.index(item) for item in TAX_LIKE):
        pack.block(E.PRECEDENCE_PENDING, "child support must come after PAYE and the ACC levy")
    return order


def before(order: list, item: str) -> list:
    return order[:order.index(item)]
