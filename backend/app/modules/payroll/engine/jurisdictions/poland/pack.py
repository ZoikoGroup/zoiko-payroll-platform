"""The only reader of Poland pack rows inside the engine (pure).

Every statutory value the engine uses is read here from ``ctx.rate_map`` /
``ctx.slabs`` (rows of the resolved pack: ORM objects or plain dicts). A row is
selected by the PAY DATE. A row whose label still carries "[PENDING G1]"
blocks even inside an Active pack, an empty value blocks, and a policy row
still at "PENDING_G1" blocks: nothing is ever defaulted (spec page 1, G1).

Rounding is never done with a bare quantize elsewhere in the engine: the rule
text comes from the pack, one rule per obligation (PL-004), and only its
vocabulary lives here.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
GROSZ = Decimal("0.01")
PENDING_MARK = "[PENDING G1]"
PENDING = "PENDING_G1"

# Rounding vocabulary: rule text (from the pack) -> (unit, mode). A parser, not
# statutory content; poland_content.ROUNDING_MODES lists the same names.
ROUNDING_RULES = {
    "GROSZ_HALF_UP": (GROSZ, ROUND_HALF_UP),
    "GROSZ_DOWN": (GROSZ, ROUND_DOWN),
    "FULL_PLN_HALF_UP": (ONE, ROUND_HALF_UP),
    "FULL_PLN_DOWN": (ONE, ROUND_DOWN),
}


def dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def field(row, name):
    if row is None:
        return None
    if isinstance(row, dict):
        if name in row:
            return row.get(name)
        camel = "".join(part if i == 0 else part.capitalize() for i, part in enumerate(name.split("_")))
        return row.get(camel)
    return getattr(row, name, None)


def upper(value) -> str:
    return "" if value is None else str(value).strip().upper()


def as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def in_window(start, end, on: date) -> bool:
    start, end = as_date(start), as_date(end)
    if start is not None and on < start:
        return False
    if end is not None and on > end:
        return False
    return True


def money(value) -> str:
    """2-dp string for pl_result only (presentation, never statutory rounding)."""
    return format(dec(value).quantize(GROSZ, rounding=ROUND_HALF_UP), "f")


class PlPack:
    """Read-only, pay-date-scoped view of the resolved Poland pack."""

    def __init__(self, rate_map, slabs, organization_id, as_of: date):
        self.rate_map = rate_map or {}
        self.slabs = list(slabs or [])
        self.organization_id = organization_id
        self.as_of = as_of
        self.rounding_events: list = []
        self._used: dict = {}

    def block(self, key: str, reason: str):
        raise E.PLCalculationBlockedError(key, reason, self.organization_id)

    def _signed(self, ident: str, label) -> None:
        if label and PENDING_MARK in str(label):
            self.block(E.keyed(E.PACK_UNSIGNED, ident), f"{ident} is not signed (gate G1)")

    def _note(self, kind: str, ident: str, row) -> None:
        start, end = as_date(field(row, "effective_from")), as_date(field(row, "effective_to"))
        names = (("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value") if kind == "rate"
                 else ("min_amount", "max_amount", "rate_pct", "flat_amount", "assessment_basis"))
        self._used[(kind, ident)] = {"kind": kind, "id": ident,
                                     "effectiveFrom": start.isoformat() if start else None,
                                     "effectiveTo": end.isoformat() if end else None,
                                     "value": {n: None if field(row, n) is None else str(field(row, n))
                                               for n in names}}

    def row(self, key: str):
        row = self.rate_map.get(key)
        if row is None or not in_window(field(row, "effective_from"), field(row, "effective_to"), self.as_of):
            self.block(E.keyed(E.ROW_MISSING, key), "no parameter row is in force on the pay date")
        self._signed(key, field(row, "label"))
        self._note("rate", key, row)
        return row

    def amount(self, key: str) -> Decimal:
        value = field(self.row(key), "flat_amount")
        if value is None or value == "":
            self.block(E.keyed(E.ROW_MISSING, key), "row has no amount configured")
        return dec(value)

    def pct(self, key: str, side: str) -> Decimal:
        name = "employee_rate_pct" if side == "employee" else "employer_rate_pct"
        value = field(self.row(key), name)
        if value is None or value == "":
            self.block(E.keyed(E.ROW_MISSING, key), f"row has no {side} rate configured")
        return dec(value)

    def text(self, key: str, allowed=None) -> str:
        value = upper(field(self.row(key), "text_value"))
        if not value or value == PENDING:
            self.block(E.keyed(E.POLICY_PENDING, key), "policy is not signed (PENDING_G1)")
        if allowed is not None and value not in tuple(upper(a) for a in allowed):
            self.block(E.keyed(E.POLICY_PENDING, key), f"{value!r} is not one of {', '.join(allowed)}")
        return value

    def text_list(self, key: str) -> list:
        return [part.strip().upper() for part in self.text(key).split(",") if part.strip()]

    def rounder(self, key: str) -> Callable[[Decimal], Decimal]:
        rule = upper(field(self.row(key), "text_value"))
        if rule not in ROUNDING_RULES:
            self.block(E.keyed(E.ROUNDING_PENDING, key), f"rounding rule {rule or PENDING!r} is not signed")
        unit, mode = ROUNDING_RULES[rule]

        def _round(value: Decimal) -> Decimal:
            after = (dec(value) / unit).quantize(ONE, rounding=mode) * unit
            self.rounding_events.append({"key": key, "rule": rule, "before": str(value), "after": str(after)})
            return after

        return _round

    def table(self, rule_type: str) -> list:
        rows = [r for r in self.slabs
                if upper(field(r, "rule_type")) == rule_type
                and in_window(field(r, "effective_from"), field(r, "effective_to"), self.as_of)]
        if not rows:
            self.block(E.keyed(E.TABLE_EMPTY, rule_type), f"{rule_type} has no rows in force on the pay date")
        for index, r in enumerate(rows):
            ident = (f"{rule_type}:{field(r, 'tax_regime') or ''}:{field(r, 'filing_status') or ''}"
                     f":{field(r, 'min_amount')}:{index}")
            self._signed(ident, field(r, "rate_label"))
            self._note("slab", ident, r)
        return sorted(rows, key=lambda r: (dec(field(r, "min_amount")), field(r, "sort_order") or 0))

    def earning_classes(self) -> dict:
        """{(obligation, component): treatment} from PL_EARNING_CLASS rows."""
        out = {}
        for r in self.table(content.PL_EARNING_CLASS_RULE):
            key = (upper(field(r, "tax_regime")), upper(field(r, "filing_status")))
            treatment = upper(field(r, "assessment_basis"))
            if treatment not in content.TREATMENTS:
                self.block(E.keyed(E.EARNING_CLASS_MISSING, ":".join(key)), f"unknown treatment {treatment!r}")
            out[key] = treatment
        return out

    def pit_bands(self) -> list:
        """[(min, max_or_None, rate_pct, published_base)] in ascending order."""
        rows = self.table(content.PL_PIT_BAND_RULE)
        bands = [(dec(field(r, "min_amount")),
                  None if field(r, "max_amount") in (None, "") else dec(field(r, "max_amount")),
                  dec(field(r, "rate_pct")), dec(field(r, "flat_amount"))) for r in rows]
        if len(bands) != 2 or bands[0][0] != ZERO or bands[0][1] is None or bands[1][1] is not None \
                or bands[0][1] != bands[1][0]:
            self.block(E.keyed(E.TABLE_EMPTY, content.PL_PIT_BAND_RULE),
                       "the PIT scale must be two contiguous bands starting at 0 (spec §4)")
        return bands

    def used(self) -> list:
        return [self._used[k] for k in sorted(self._used, key=lambda k: (k[0], str(k[1])))]
