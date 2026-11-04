"""The only reader of New Zealand pack rows inside the engine (pure).

Every statutory value the engine uses is read here from ``ctx.rate_map`` /
``ctx.slabs`` (rows of the resolved pack: ORM objects or plain dicts). A row is
selected by the PAYDAY (NZ-008). A row whose label still carries
"[PENDING G1]" blocks even inside an Active pack, an empty value blocks, and an
empty authority table blocks: nothing is ever defaulted (fail-closed).

Rounding is never done with a bare quantize elsewhere in the engine: the rule
text comes from the pack and only its vocabulary lives here (spec §3).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from typing import Callable, Optional

from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import errors as E

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")
PENDING_MARK = "[PENDING G1]"

# Platform pay_frequency values ("Weekly", "Fortnightly", "FourWeekly",
# "Monthly") mapped to the content vocabulary.
FREQUENCY_ALIASES = {"WEEKLY": "WEEKLY", "FORTNIGHTLY": "FORTNIGHTLY", "FOURWEEKLY": "FOUR_WEEKLY",
                     "FOUR_WEEKLY": "FOUR_WEEKLY", "MONTHLY": "MONTHLY"}
SL_THRESHOLD_KEY = {"WEEKLY": "nz_sl_threshold_weekly", "FORTNIGHTLY": "nz_sl_threshold_fortnightly",
                    "FOUR_WEEKLY": "nz_sl_threshold_four_weekly", "MONTHLY": "nz_sl_threshold_monthly"}

# Rounding vocabulary: rule text (from the pack) -> (unit, mode). A parser, not
# statutory content.
ROUNDING_RULES = {
    "NEAREST_CENT_HALF_UP": (CENT, ROUND_HALF_UP),
    "HALF_EVEN_CENT": (CENT, ROUND_HALF_EVEN),
    "DOWN_CENT": (CENT, ROUND_DOWN),
    "UP_CENT": (CENT, ROUND_UP),
    "NEAREST_DOLLAR_HALF_UP": (ONE, ROUND_HALF_UP),
    "DOWN_DOLLAR": (ONE, ROUND_DOWN),
}


def dec(value) -> Decimal:
    """None / "" -> ZERO; anything else -> Decimal(str(value))."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def opt_dec(value) -> Optional[Decimal]:
    """None / "" -> None (a missing bound); anything else -> Decimal."""
    if value is None or value == "":
        return None
    return dec(value)


def field(row, name):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def upper(value) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def as_date(value) -> Optional[date]:
    """date / datetime / ISO string -> date; None / "" -> None."""
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


def money(value: Decimal) -> str:
    """2-dp string for nz_result only (presentation, not a statutory rounding)."""
    return format(dec(value).quantize(CENT, rounding=ROUND_HALF_UP), "f")


def floor_cent(value: Decimal) -> Decimal:
    """Largest whole cent not above `value`. Used only as a protection floor
    (a cap that rounding must never exceed), never as statutory rounding."""
    return dec(value).quantize(CENT, rounding=ROUND_DOWN)


def normalise_frequency(value) -> str:
    return FREQUENCY_ALIASES.get(upper(value).replace(" ", "").replace("-", ""), "")


class NzPack:
    """Read-only, payday-scoped view of the resolved New Zealand pack."""

    def __init__(self, rate_map, slabs, organization_id, as_of: Optional[date]):
        self.rate_map = rate_map or {}
        self.slabs = list(slabs or [])
        self.organization_id = organization_id
        self.as_of = as_of
        self.rounding_events: list = []
        self._used: dict = {}

    def block(self, key: str, reason: str):
        raise E.NZCalculationBlockedError(key, reason, self.organization_id)

    def _signed(self, ident: str, label) -> None:
        if label and PENDING_MARK in str(label):
            self.block(E.PACK_UNSIGNED, f"{ident} is not signed (gate G1)")

    def _note(self, kind: str, ident: str, row) -> None:
        start, end = as_date(field(row, "effective_from")), as_date(field(row, "effective_to"))
        self._used[(kind, ident)] = {"kind": kind, "id": ident,
                                     "effectiveFrom": start.isoformat() if start else None,
                                     "effectiveTo": end.isoformat() if end else None}

    def row(self, key: str, required: bool = True):
        row = self.rate_map.get(key)
        if row is None or (self.as_of is not None and not in_window(
                field(row, "effective_from"), field(row, "effective_to"), self.as_of)):
            if required:
                self.block(E.keyed(E.ROW_MISSING, key), "no parameter row is in force on the payday")
            return None
        self._signed(key, field(row, "label"))
        self._note("rate", key, row)
        return row

    def amount(self, key: str) -> Decimal:
        value = field(self.row(key), "flat_amount")
        if value is None or value == "":
            self.block(E.keyed(E.ROW_MISSING, key), "row has no value configured")
        return dec(value)

    def pct(self, key: str) -> Decimal:
        """A percentage stored as a percent number in flat_amount (12.25 means 12.25%)."""
        return self.amount(key)

    def text(self, key: str, allowed=None) -> str:
        value = upper(field(self.row(key), "text_value"))
        if not value or value == content.PENDING:
            self.block(E.keyed(E.ROW_MISSING, key), "value is not configured (PENDING_G1)")
        if allowed and value not in tuple(upper(a) for a in allowed):
            self.block(E.keyed(E.ROW_MISSING, key), f"{value!r} is not one of {', '.join(allowed)}")
        return value

    def text_list(self, key: str) -> list:
        return [part.strip().upper() for part in self.text(key).split(",") if part.strip()]

    def rounder(self, key: str) -> Callable[[Decimal], Decimal]:
        rule = upper(field(self.row(key), "text_value"))
        if rule not in ROUNDING_RULES:
            self.block(E.keyed(E.ROUNDING_PENDING, key), f"rounding rule {rule or 'PENDING_G1'!r} is not signed")
        unit, mode = ROUNDING_RULES[rule]

        def _round(value: Decimal) -> Decimal:
            after = (dec(value) / unit).quantize(ONE, rounding=mode) * unit
            self.rounding_events.append({"key": key, "rule": rule, "before": str(value), "after": str(after)})
            return after

        return _round

    def table(self, rule_type: str, table_name: str, required: bool = True) -> list:
        rows = [r for r in self.slabs
                if upper(field(r, "rule_type")) == rule_type
                and (self.as_of is None or in_window(field(r, "effective_from"),
                                                     field(r, "effective_to"), self.as_of))]
        if not rows and required:
            self.block(E.keyed(E.TABLE_EMPTY, table_name), f"{table_name} has no rows in force (release gate)")
        for index, r in enumerate(rows):
            ident = f"{rule_type}:{field(r, 'id') if field(r, 'id') is not None else field(r, 'filing_status') or index}"
            self._signed(ident, field(r, "rate_label"))
            self._note("slab", ident, r)
        return sorted(rows, key=lambda r: (dec(field(r, "min_amount")), field(r, "sort_order") or 0))

    def used(self) -> list:
        return [self._used[k] for k in sorted(self._used, key=lambda k: (k[0], str(k[1])))]
