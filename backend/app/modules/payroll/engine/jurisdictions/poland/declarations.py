"""Employee statements in force (ZP-PL-ENG-001 PL-005 / PL-007).

Only an APPROVED statement whose effective window covers the pay date counts.
A statement stays effective until changed or withdrawn — there is no annual
expiry here (PL-007). Two approved statements of the same type in force at
once is a conflict and BLOCKS (the service supersedes, never overlaps).
"""
from __future__ import annotations

from datetime import date

from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack, as_date, field, in_window, upper


def in_force(pack: PlPack, declarations, declaration_type: str, on: date):
    """The one approved statement of this type in force on `on`, or None."""
    matches = [d for d in (declarations or [])
               if upper(field(d, "declaration_type")) == declaration_type
               and upper(field(d, "status")) == "APPROVED"
               and in_window(field(d, "effective_from"), field(d, "effective_to"), on)]
    if len(matches) > 1:
        pack.block(E.keyed(E.DECLARATION_CONFLICT, declaration_type),
                   "more than one approved statement of this type is in force")
    return matches[0] if matches else None


def value(declaration, name):
    data = field(declaration, "value") or {}
    return data.get(name) if isinstance(data, dict) else None


def describe(declaration) -> dict:
    if declaration is None:
        return None
    start = as_date(field(declaration, "effective_from"))
    return {"type": upper(field(declaration, "declaration_type")), "id": field(declaration, "id"),
            "effectiveFrom": start.isoformat() if start else None}
