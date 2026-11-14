"""The only reader of Belgium pack rows inside the engine (pure).

Same semantics as the Poland PlPack, plus explicit multi-row access:

  * Every statutory value is read from ``rate_map`` (component_key -> one row OR
    a list of dated rows) and ``slabs`` (rows of the resolved pack: ORM objects
    or plain dicts). A row is selected by the PAY DATE using its OWN
    effective_from / effective_to, so a mid-year change (e.g. a row ending
    30 Jun and its successor starting 1 Jul) is two rows of one key.
  * A row whose label still carries "[PENDING G1]", or whose value is empty or
    "PENDING_G1", raises BECalculationBlockedError(BE_CONTENT_PENDING:<key>):
    nothing is ever defaulted (ZP-BE-ENG-001 §3, BE-010, gate G1).
  * A row signed NOT_SUPPORTED raises BE_FEATURE_BLOCKED:<key>: the decision is
    recorded and the feature stays blocked.
  * rounder() reads ONLY be_rounding_* rows; rounding is never a bare quantize
    elsewhere in the engine (D8).
  * used() lists every row consumed, for the calculation hash (BE-010 replay).

No ORM query and no clock: the caller (belgium_service.calc_inputs, Phase 5)
passes the rows and the pay date.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from app.modules.payroll.engine.countries import belgium_content as content
from app.modules.payroll.engine.jurisdictions.belgium import errors as E

ZERO = Decimal("0")
ONE = Decimal("1")
# Structural currency units (EUR cent / EUR), not statutory content: the
# signed be_rounding_* rule chooses which unit and mode apply.
_CENT = Decimal("0.01")
_EURO = ONE
_PERCENT = Decimal("100")    # a rate_pct is a percentage (structural unit)
PENDING_MARK = content.PENDING_MARK
PENDING = "PENDING_G1"

# Rounding vocabulary: signed rule text -> (unit, mode). A parser, not content.
ROUNDING_RULES = {
    "CENT_HALF_UP": (_CENT, ROUND_HALF_UP),
    "CENT_DOWN": (_CENT, ROUND_DOWN),
    "EURO_HALF_UP": (_EURO, ROUND_HALF_UP),
    "EURO_DOWN": (_EURO, ROUND_DOWN),
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


class BePack:
    """Read-only, pay-date-scoped view of the resolved Belgium pack."""

    def __init__(self, rate_map, slabs, organization_id, as_of: date):
        self.rate_map = rate_map or {}
        self.slabs = list(slabs or [])
        self.organization_id = organization_id
        self.as_of = as_of
        self.rounding_events: list = []
        self._used: dict = {}

    # ── blocking ──────────────────────────────────────────────────────────
    def block(self, code: str, key: str, reason: str):
        raise E.BECalculationBlockedError(E.keyed(code, key), reason, self.organization_id)

    def _pending(self, key: str, reason: str = "not signed (gate G1)"):
        self.block(E.CONTENT_PENDING, key, reason)

    def _note(self, kind: str, ident: str, row) -> None:
        start, end = as_date(field(row, "effective_from")), as_date(field(row, "effective_to"))
        names = (("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value") if kind == "rate"
                 else ("min_amount", "max_amount", "rate_pct", "flat_amount", "assessment_basis", "tax_formula",
                       "formula_expression"))
        self._used[(kind, ident)] = {"kind": kind, "id": ident,
                                     "effectiveFrom": start.isoformat() if start else None,
                                     "effectiveTo": end.isoformat() if end else None,
                                     "value": {n: None if field(row, n) is None else str(field(row, n))
                                               for n in names}}

    # ── scalar rows ───────────────────────────────────────────────────────
    def _candidates(self, key: str) -> list:
        rows = self.rate_map.get(key)
        if rows is None:
            return []
        return list(rows) if isinstance(rows, (list, tuple)) else [rows]

    def row(self, key: str):
        """The ONE signed row of `key` in force on the pay date."""
        rows = [r for r in self._candidates(key)
                if in_window(field(r, "effective_from"), field(r, "effective_to"), self.as_of)]
        if not rows:
            self.block(E.ROW_MISSING, key, "no row of this key is in force on the pay date")
        if len(rows) > 1:
            self._pending(key, "more than one row of this key is in force on the pay date (overlapping windows)")
        row = rows[0]
        if PENDING_MARK in str(field(row, "label") or ""):
            self._pending(key)
        if upper(field(row, "text_value")) == content.NOT_SUPPORTED:
            self.block(E.FEATURE_BLOCKED, key, "signed NOT_SUPPORTED: this feature stays blocked")
        self._note("rate", key, row)
        return row

    def amount(self, key: str) -> Decimal:
        value = field(self.row(key), "flat_amount")
        if value is None or value == "":
            self._pending(key, "row has no amount")
        return dec(value)

    def pct(self, key: str, side: str) -> Decimal:
        name = "employee_rate_pct" if side == "employee" else "employer_rate_pct"
        value = field(self.row(key), name)
        if value is None or value == "":
            self._pending(key, f"row has no {side} rate")
        return dec(value)

    def text(self, key: str, allowed=None) -> str:
        value = upper(field(self.row(key), "text_value"))
        if not value or value == PENDING:
            self._pending(key, "policy is not signed")
        if allowed is not None and value not in tuple(upper(a) for a in allowed):
            self._pending(key, f"{value!r} is not one of {', '.join(allowed)}")
        return value

    def text_list(self, key: str) -> list:
        return [part.strip().upper() for part in self.text(key).split(",") if part.strip()]

    def rounder(self, key: str) -> Callable[[Decimal], Decimal]:
        if not key.startswith("be_rounding_"):
            self.block(E.ROUNDING_KEY_INVALID, key, "rounding is read only from be_rounding_* rows (D8)")
        rule = self.text(key, allowed=tuple(ROUNDING_RULES))
        unit, mode = ROUNDING_RULES[rule]

        def _round(value: Decimal) -> Decimal:
            after = (dec(value) / unit).quantize(ONE, rounding=mode) * unit
            self.rounding_events.append({"key": key, "rule": rule, "before": str(value), "after": str(after)})
            return after

        return _round

    # ── slab content (band / formula / table keys) ────────────────────────
    def table(self, key: str) -> list:
        """The signed slab rows of a band / formula / table key in force on the
        pay date. The key's own marker row must be signed SLAB_ROWS (or it
        blocks as NOT_SUPPORTED / pending) and every slab row must be signed."""
        kind = content.KEYS[key][1] if key in content.KEYS else None
        if kind not in content.SLAB_KINDS:
            self.block(E.ROW_MISSING, key, "not a band / formula / table key")
        marker = self.row(key)
        if upper(field(marker, "text_value")) != content.SLAB_ROWS:
            self._pending(key, "the key is not signed as SLAB_ROWS")
        rule_type = content.RULE_TYPES[key]
        rows = [r for r in self.slabs
                if upper(field(r, "rule_type")) == rule_type
                and in_window(field(r, "effective_from"), field(r, "effective_to"), self.as_of)]
        if not rows:
            self.block(E.TABLE_EMPTY, key, f"{rule_type} has no rows in force on the pay date")
        for index, r in enumerate(rows):
            ident = f"{rule_type}:{field(r, 'filing_status') or ''}:{field(r, 'min_amount')}:{index}"
            if PENDING_MARK in str(field(r, "rate_label") or ""):
                self._pending(ident)
            self._note("slab", ident, r)
        return sorted(rows, key=lambda r: (dec(field(r, "min_amount")), field(r, "sort_order") or 0))

    def band(self, key: str, **dimensions) -> list:
        """The signed band rows of `key` in force on the pay date whose
        dimension (TaxSlab.filing_status, BE_* rule types only) equals exactly
        `dimensions` (e.g. EC=..., WC=...). A key that declares dimensions must
        be asked with all of them; no match raises BE_ROW_MISSING — there is
        never a fallback to a dimensionless row (fail closed)."""
        spec = content.SLAB_SPECS.get(key)
        if spec is None or spec["kind"] != content.KIND_BAND:
            self.block(E.ROW_MISSING, key, "not a band key")
        wanted = {name.upper(): str(value).strip().upper() for name, value in dimensions.items()}
        if set(wanted) != set(spec["dimensions"]):
            self.block(E.ROW_MISSING, key, f"band lookup needs exactly the dimensions {spec['dimensions'] or '()'}")
        rows = []
        for r in self.table(key):
            try:
                have = content.parse_dimension(field(r, "filing_status"))
            except ValueError:
                self._pending(key, "a band row has a malformed dimension")
            if have == wanted:
                rows.append(r)
        if not rows:
            self.block(E.ROW_MISSING, key, f"no signed band row for {content.format_dimension(**wanted) or 'this key'}")
        return rows

    def public_holidays(self, year: int) -> list:
        """[(date, name)] of the SIGNED BE_PUBLIC_HOLIDAY rows of `year`. The key
        must be signed SLAB_ROWS (NOT_SUPPORTED -> BE_FEATURE_BLOCKED); any
        unsigned row of that year raises BE_CONTENT_PENDING; no row raises
        BE_TABLE_EMPTY. Employer substitute days are D15 (Phase 6), not here."""
        key = "be_public_holidays"
        marker = self.row(key)
        if upper(field(marker, "text_value")) != content.SLAB_ROWS:
            self._pending(key, "the key is not signed as SLAB_ROWS")
        rows = []
        for r in self.slabs:
            day = as_date(field(r, "effective_from"))
            if upper(field(r, "rule_type")) != content.PUBLIC_HOLIDAY_RULE or day is None or day.year != year:
                continue
            ident = f"{content.PUBLIC_HOLIDAY_RULE}:{day.isoformat()}"
            if PENDING_MARK in str(field(r, "rate_label") or ""):
                self._pending(ident)
            self._note("slab", ident, r)
            rows.append((day, str(field(r, "tax_formula") or field(r, "rate_label") or "").strip()))
        if not rows:
            self.block(E.TABLE_EMPTY, key, f"no signed public holiday for {year}")
        return sorted(rows)

    def earning_classes(self) -> dict:
        """{(obligation, component): treatment} from BE_EARNING_CLASS rows."""
        rows = [r for r in self.slabs
                if upper(field(r, "rule_type")) == content.EARNING_CLASS_RULE
                and in_window(field(r, "effective_from"), field(r, "effective_to"), self.as_of)]
        if not rows:
            self.block(E.TABLE_EMPTY, content.EARNING_CLASS_RULE, "no earning classification in force")
        out = {}
        for r in rows:
            key = (upper(field(r, "tax_regime")), upper(field(r, "filing_status")))
            ident = f"{content.EARNING_CLASS_RULE}:{key[0]}:{key[1]}"
            if PENDING_MARK in str(field(r, "rate_label") or ""):
                self._pending(ident)
            treatment = upper(field(r, "assessment_basis"))
            if treatment not in content.TREATMENTS:
                self._pending(ident, f"unknown treatment {treatment!r}")
            self._note("slab", ident, r)
            out[key] = treatment
        return out

    # ── Block A3: formulas and band values (restricted grammar only) ────────
    def be_evaluate(self, ident: str, text, variables: dict) -> Decimal:
        """Evaluate signed formula text with the restricted grammar (never eval)."""
        from app.modules.payroll.engine.jurisdictions.belgium import formula as F

        try:
            return F.evaluate_be_formula(text, variables)
        except F.FormulaError as error:
            self.block(E.FORMULA_INVALID, ident, f"the signed formula cannot be evaluated: {error}")

    def formula(self, key: str, name: Optional[str] = None, **variables) -> Decimal:
        """The value of the signed formula row of a KIND_FORMULA key (one row in
        force, or the row named `name`)."""
        if content.KEYS.get(key, (None, None))[1] != content.KIND_FORMULA:
            self.block(E.ROW_MISSING, key, "not a formula key")
        rows = self.table(key)
        if name is not None:
            rows = [r for r in rows if upper(field(r, "tax_formula")) == upper(name)]
        if len(rows) != 1:
            self.block(E.ROW_MISSING, key, "exactly one signed formula row must be in force"
                       + (f" for {name}" if name else ""))
        text = field(rows[0], "formula_expression")
        if not text:
            self._pending(key, "the formula row has no formula text")
        return self.be_evaluate(key, text, variables)

    def band_for(self, key: str, rows: list, amount: Decimal):
        """The band row whose [min_amount, max_amount) contains `amount`
        (max_amount empty = open-ended). None found -> BE_BAND_NOT_FOUND."""
        found = [r for r in rows if dec(field(r, "min_amount")) <= amount
                 and (field(r, "max_amount") in (None, "") or amount < dec(field(r, "max_amount")))]
        if len(found) != 1:
            self.block(E.BAND_NOT_FOUND, key, "no single signed band row covers the amount"
                       if not found else "several signed band rows overlap at the amount")
        return found[0]

    def band_value(self, key: str, row, amount: Decimal, **variables) -> Decimal:
        """A band row's value at `amount`: its signed formula (variables x, low,
        high, rate, flat plus the caller's), otherwise flat + rate% of the part
        of `amount` above the band floor."""
        low, rate, flat = dec(field(row, "min_amount")), dec(field(row, "rate_pct")), dec(field(row, "flat_amount"))
        text = field(row, "formula_expression")
        if text:
            high = field(row, "max_amount")
            return self.be_evaluate(key, text, {"x": amount, "low": low, "rate": rate, "flat": flat,
                                             "high": dec(high) if high not in (None, "") else amount, **variables})
        return flat + (amount - low) * rate / _PERCENT

    def used(self) -> list:
        return [self._used[k] for k in sorted(self._used, key=lambda k: (k[0], str(k[1])))]
