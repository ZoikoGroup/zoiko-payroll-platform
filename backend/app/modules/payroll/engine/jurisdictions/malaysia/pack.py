"""The only reader of Malaysia pack rows inside the engine (pure).

Every statutory value the engine uses is read here from ``ctx.rate_map`` /
``ctx.slabs`` (rows of the resolved pack: ORM objects or plain dicts),
selected by the PAY DATE. A row whose label still carries "[PENDING G1]"
blocks even inside an Active pack, an empty value blocks, and a policy row
still at "PENDING_G1" (or signed NOT_SUPPORTED) blocks: nothing is ever
defaulted (spec page 1, G1).

Territorial labour rows are read with ``row(key, territory)`` (MY-024); a
contribution is read from its schedule TABLE with ``schedule()`` (MY-005 /
MY-011), which also records the exact row used.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Callable, Optional

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
SEN = Decimal("0.01")
FIVE_SEN = Decimal("0.05")
PENDING_MARK = "[PENDING G1]"
PENDING = "PENDING_G1"
NOT_SUPPORTED = "NOT_SUPPORTED"

# Rounding vocabulary: rule text (from the pack) -> (unit, mode). A parser, not
# statutory content; malaysia_content.ROUNDING_RULES lists the same names.
ROUNDING_RULES = {
    "SEN_HALF_UP": (SEN, ROUND_HALF_UP),
    "SEN_DOWN": (SEN, ROUND_DOWN),
    "SEN_UP": (SEN, ROUND_UP),
    "FIVE_SEN_UP": (FIVE_SEN, ROUND_UP),
    "RINGGIT_HALF_UP": (ONE, ROUND_HALF_UP),
    "RINGGIT_DOWN": (ONE, ROUND_DOWN),
    "RINGGIT_UP": (ONE, ROUND_UP),
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
    """2-dp string for my_result only (presentation, never statutory rounding)."""
    return format(dec(value).quantize(SEN, rounding=ROUND_HALF_UP), "f")


class MyPack:
    """Read-only, date-scoped view of the resolved Malaysia pack."""

    def __init__(self, rate_map, slabs, organization_id, as_of: date):
        self.rate_map = rate_map or {}
        self.slabs = list(slabs or [])
        self.organization_id = organization_id
        self.as_of = as_of
        self.rounding_events: list = []
        self._used: dict = {}

    # ── blocking ─────────────────────────────────────────────────────────
    def block(self, key: str, reason: str):
        raise E.MYCalculationBlockedError(key, reason, self.organization_id)

    def _signed(self, ident: str, label) -> None:
        if label and PENDING_MARK in str(label):
            self.block(E.keyed(E.PACK_UNSIGNED, ident), f"{ident} is not signed (gate G1)")

    def _note(self, kind: str, ident: str, row, value: dict) -> None:
        start, end = as_date(field(row, "effective_from")), as_date(field(row, "effective_to"))
        self._used[(kind, ident)] = {"kind": kind, "id": ident, "rowId": field(row, "id"),
                                     "effectiveFrom": start.isoformat() if start else None,
                                     "effectiveTo": end.isoformat() if end else None, "value": value}

    # ── scalar rows ──────────────────────────────────────────────────────
    def key(self, base: str, territory: Optional[str] = None) -> str:
        return base if territory is None else content.territory_key(base, territory)

    def in_force(self, base: str, territory: Optional[str] = None, on: Optional[date] = None) -> bool:
        row = self.rate_map.get(self.key(base, territory))
        return row is not None and in_window(field(row, "effective_from"), field(row, "effective_to"),
                                             on or self.as_of)

    def row(self, base: str, territory: Optional[str] = None):
        key = self.key(base, territory)
        row = self.rate_map.get(key)
        if row is None or not in_window(field(row, "effective_from"), field(row, "effective_to"), self.as_of):
            self.block(E.keyed(E.ROW_MISSING, key), "no parameter row is in force on the pay date")
        self._signed(key, field(row, "label"))
        names = ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value")
        self._note("rate", key, row, {n: None if field(row, n) is None else str(field(row, n)) for n in names})
        return row

    def amount(self, base: str, territory: Optional[str] = None) -> Decimal:
        value = field(self.row(base, territory), "flat_amount")
        if value is None or value == "":
            self.block(E.keyed(E.ROW_MISSING, self.key(base, territory)), "row has no amount configured")
        return dec(value)

    def pct(self, base: str, side: str, territory: Optional[str] = None) -> Decimal:
        name = "employee_rate_pct" if side == "employee" else "employer_rate_pct"
        value = field(self.row(base, territory), name)
        if value is None or value == "":
            self.block(E.keyed(E.ROW_MISSING, self.key(base, territory)), f"row has no {side} rate configured")
        return dec(value)

    def text(self, base: str, allowed=None, territory: Optional[str] = None) -> str:
        key = self.key(base, territory)
        value = upper(field(self.row(base, territory), "text_value"))
        if not value or value == PENDING:
            self.block(E.keyed(E.POLICY_PENDING, key), "policy is not signed (PENDING_G1)")
        if value == NOT_SUPPORTED:
            self.block(E.keyed(E.POLICY_NOT_SUPPORTED, key), "the policy is signed NOT_SUPPORTED")
        if allowed is not None and value not in tuple(upper(a) for a in allowed):
            self.block(E.keyed(E.POLICY_PENDING, key), f"{value!r} is not one of {', '.join(allowed)}")
        return value

    def text_list(self, base: str) -> list:
        return [part.strip().upper() for part in self.text(base).split(",") if part.strip()]

    def rounder(self, base: str) -> Callable[[Decimal], Decimal]:
        rule = self.text(base, allowed=tuple(ROUNDING_RULES))
        unit, mode = ROUNDING_RULES[rule]

        def _round(value: Decimal) -> Decimal:
            after = (dec(value) / unit).quantize(ONE, rounding=mode) * unit
            self.rounding_events.append({"key": base, "rule": rule, "before": str(value), "after": str(after)})
            return after

        return _round

    # ── tables ───────────────────────────────────────────────────────────
    def table(self, rule_type: str) -> list:
        rows = [r for r in self.slabs
                if upper(field(r, "rule_type")) == rule_type
                and in_window(field(r, "effective_from"), field(r, "effective_to"), self.as_of)]
        if not rows:
            self.block(E.keyed(E.TABLE_EMPTY, rule_type), f"{rule_type} has no rows in force on the pay date")
        for index, r in enumerate(rows):
            self._signed(f"{rule_type}:{field(r, 'filing_status') or ''}:{field(r, 'tax_regime') or ''}"
                         f":{field(r, 'min_amount')}:{index}", field(r, "rate_label"))
        return sorted(rows, key=lambda r: (dec(field(r, "min_amount")), field(r, "sort_order") or 0))

    def schedule(self, rule_type: str, member_class: str, wage: Decimal) -> dict:
        """The signed schedule band for `wage` (lower bound exclusive, upper
        inclusive; the first band includes 0): employee and employer amounts
        and the exact rows used. No band -> blocks; never a percentage."""
        rows = [r for r in self.table(rule_type) if upper(field(r, "filing_status")) == member_class]
        if not rows:
            self.block(E.keyed(E.SCHEDULE_ROW_MISSING, f"{rule_type}:{member_class}"),
                       "the schedule has no rows for this member class")
        wage = dec(wage)
        picked = {}
        for r in rows:
            lo = dec(field(r, "min_amount"))
            hi = None if field(r, "max_amount") in (None, "") else dec(field(r, "max_amount"))
            inside = (wage > lo or (lo == ZERO and wage >= ZERO)) and (hi is None or wage <= hi)
            if inside:
                side = upper(field(r, "tax_regime"))
                if side in picked:
                    self.block(E.keyed(E.SCHEDULE_ROW_MISSING, f"{rule_type}:{member_class}"),
                               "two schedule bands cover the same wage")
                picked[side] = r
        if set(picked) != {"EMPLOYEE", "EMPLOYER"}:
            self.block(E.keyed(E.SCHEDULE_ROW_MISSING, f"{rule_type}:{member_class}:{money(wage)}"),
                       "no schedule band covers this wage")
        out = {}
        for side, r in picked.items():
            ident = f"{rule_type}:{member_class}:{side}:{field(r, 'min_amount')}"
            self._note("slab", ident, r, {"min": str(field(r, "min_amount")), "max": str(field(r, "max_amount")),
                                          "amount": str(field(r, "flat_amount"))})
            out[side] = {"amount": dec(field(r, "flat_amount")), "rowId": field(r, "id"),
                         "band": [money(field(r, "min_amount")),
                                  None if field(r, "max_amount") in (None, "") else money(field(r, "max_amount"))]}
        return {"employee": out["EMPLOYEE"]["amount"], "employer": out["EMPLOYER"]["amount"],
                "rule": rule_type, "memberClass": member_class, "wage": money(wage),
                "rows": {"employee": out["EMPLOYEE"]["rowId"], "employer": out["EMPLOYER"]["rowId"]},
                "band": out["EMPLOYEE"]["band"]}

    def earning_classes(self) -> dict:
        """{(obligation, component): treatment} from MY_EARNING_CLASS rows."""
        out = {}
        for r in self.table(content.MY_EARNING_CLASS_RULE):
            key = (upper(field(r, "tax_regime")), upper(field(r, "filing_status")))
            treatment = upper(field(r, "assessment_basis"))
            if treatment not in content.TREATMENTS:
                self.block(E.keyed(E.EARNING_CLASS_MISSING, ":".join(key)), f"unknown treatment {treatment!r}")
            out[key] = treatment
        return out

    def used(self) -> list:
        return [self._used[k] for k in sorted(self._used, key=lambda k: (k[0], str(k[1])))]
