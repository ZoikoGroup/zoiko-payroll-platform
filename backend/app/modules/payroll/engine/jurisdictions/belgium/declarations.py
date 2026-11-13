"""Belgium declarations resolved by the pay date (ZP-BE-ENG-001 §5 stages 1
and 5, BE-012; Block A3). Pure.

Only APPROVED declarations whose window contains the pay date count; a
RECEIVED, WITHDRAWN or SUPERSEDED one never changes a calculation. When two
APPROVED declarations of one type are both in force (which approval prevents),
the calculation blocks instead of choosing one.
"""
from __future__ import annotations

from datetime import date

from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack, field, in_window, upper


def approved(pack: BePack, declarations, pay_date: date) -> dict:
    """{declaration_type: declaration} of the APPROVED declarations in force."""
    out: dict = {}
    for d in declarations or ():
        if upper(field(d, "status")) != "APPROVED":
            continue
        if not in_window(field(d, "effective_from"), field(d, "effective_to"), pay_date):
            continue
        kind = upper(field(d, "declaration_type"))
        if kind in out:
            pack.block(E.DECLARATION_INVALID, kind, "two APPROVED declarations of this type are in force")
        out[kind] = d
    return out


def whole_number(pack: BePack, declaration, name: str) -> int:
    """A non-negative whole number from an approved declaration's value."""
    value = (field(declaration, "value") or {}).get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        pack.block(E.DECLARATION_INVALID, upper(field(declaration, "declaration_type")),
                   f"the approved declaration has no valid whole-number {name!r}")
    return value
