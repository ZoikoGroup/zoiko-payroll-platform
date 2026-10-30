"""Japan national withholding (ZP-JP-ENG-001, JP-002/JP-004/JP-005)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.countries.shared import evaluate_tax_formula
from app.modules.payroll.engine.jurisdictions.japan.errors import JapanCalculationBlockedError

ZERO = Decimal("0")
HUNDRED = Decimal("100")
PENDING = "PENDING_G1"
COMPUTER = "COMPUTER"
TABLE = "TABLE"
_RULE_MONTHLY = "JP_WHT_MONTHLY"
_RULE_EID = "JP_WHT_CMP_EID"
_RULE_RATE = "JP_WHT_CMP_RATE"
_COMPUTER_METHOD = "COMPUTER_PRIMARY_TABLES_OTHERS"
_TABLES_ONLY = "TABLES_ONLY"
_MODES = {
    "DOWN": ROUND_DOWN,
    "ROUND_DOWN": ROUND_DOWN,
    "UP": ROUND_UP,
    "ROUND_UP": ROUND_UP,
    "CEILING": ROUND_CEILING,
    "FLOOR": ROUND_FLOOR,
    "HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
    "BANKERS": ROUND_HALF_EVEN,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
}


class WithholdingResult(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _field(value, name):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _row(source, key):
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(key)
    rate_map = getattr(source, "rate_map", None)
    if isinstance(rate_map, dict):
        return rate_map.get(key)
    return getattr(source, key, None)


def _block(pack, key: str, reason: str):
    if hasattr(pack, "block"):
        return pack.block(key, reason)
    raise JapanCalculationBlockedError(key, reason, getattr(pack, "organization_id", None))


def _in_force(row, as_of):
    if row is None or as_of is None:
        return True
    start = _field(row, "effective_from")
    end = _field(row, "effective_to")
    if isinstance(start, str):
        start = date.fromisoformat(start[:10]) if start else None
    if isinstance(end, str):
        end = date.fromisoformat(end[:10]) if end else None
    return (start is None or start <= as_of) and (end is None or end >= as_of)


def _rounder(pack, rounding):
    if callable(rounding):
        return rounding
    round_row = _row(pack, "jp_wht_rounding")
    if round_row is None:
        _block(pack, "jp_wht_rounding", "no withholding rounding row is configured")
    text = str(_field(round_row, "text_value") or "").strip().upper()
    if not text or text == PENDING:
        _block(pack, "jp_wht_rounding", "withholding rounding is PENDING_G1")
    unit = Decimal("1")
    mode_name = text
    if text.startswith("DOWN_") and text[5:].isdigit():
        unit = Decimal(text[5:])
        mode_name = "DOWN"
    mode = _MODES.get(mode_name)
    if mode is None:
        _block(pack, "jp_wht_rounding", f"unsupported withholding rounding rule {text!r}")
    return lambda value: (value / unit).quantize(Decimal("1"), rounding=mode) * unit


def _round_value(value, rounder, key, field, events):
    before = value
    after = rounder(value)
    if after != before:
        events.append({"field": field, "row": key, "before": str(before), "after": str(after)})
    return after


def _band(rows, amount, key, pack):
    matches = []
    for row in rows:
        low = _dec(_field(row, "min_amount"))
        high = _field(row, "max_amount")
        if amount >= low and (high is None or amount < _dec(high)):
            matches.append(row)
    if not matches:
        for row in rows:
            low = _dec(_field(row, "min_amount"))
            high = _field(row, "max_amount")
            if amount >= low and (high is None or amount <= _dec(high)):
                matches.append(row)
    if not matches:
        _block(pack, key, f"no {key} row covers {amount}")
    matches.sort(key=lambda row: _dec(_field(row, "min_amount")))
    return matches[-1]


def _slabs(source, rule_type):
    return [row for row in (getattr(source, "slabs", None) or [])
            if str(_field(row, "rule_type") or "") == rule_type]


def _scalar_amount(pack, key):
    row = _row(pack, key)
    value = _field(row, "flat_amount") if row is not None else None
    if value is None:
        _block(pack, key, "no signed amount is configured")
    return _dec(value)


def _tax_from_row(row, taxable, rounder, events, pack, key):
    flat = _field(row, "flat_amount")
    formula = _field(row, "formula_expression")
    if formula:
        tax = evaluate_tax_formula(str(formula), taxable)
    elif flat is not None:
        tax = _dec(flat)
    else:
        rate = _field(row, "rate_pct")
        if rate is None:
            _block(pack, key, "the selected row has neither an amount, a rate nor a formula")
        tax = taxable * _dec(rate) / HUNDRED
    return _round_value(max(ZERO, tax), rounder, "jp_wht_rounding", "jp_wht", events)


def _table_tax(base, declaration_class, dependants, slabs, pack, rounder):
    rows = [row for row in slabs
            if str(_field(row, "rule_type") or "") == _RULE_MONTHLY
            and str(_field(row, "tax_column") or "").upper() == declaration_class
            and str(_field(row, "tax_table_number")) == str(dependants)]
    if not rows:
        _block(pack, _RULE_MONTHLY,
               f"no monthly table row for {declaration_class} with {dependants} dependants")
    row = _band(rows, base, _RULE_MONTHLY, pack)
    events = []
    tax = _tax_from_row(row, base, rounder, events, pack, _RULE_MONTHLY)
    return tax, TABLE, row, events


def _computer_tax(base, dependants, slabs, pack, rounder):
    eid_rows = [row for row in slabs if str(_field(row, "rule_type") or "") == _RULE_EID]
    if not eid_rows:
        _block(pack, _RULE_EID, "no employment-income deduction rows are configured")
    eid_row = _band(eid_rows, base, _RULE_EID, pack)
    formula = _field(eid_row, "formula_expression")
    flat = _field(eid_row, "flat_amount")
    rate = _field(eid_row, "rate_pct")
    if formula:
        deduction = evaluate_tax_formula(str(formula), base)
    elif flat is not None and rate is not None:
        deduction = _dec(flat) + base * _dec(rate) / HUNDRED
    elif rate is not None:
        deduction = base * _dec(rate) / HUNDRED
    elif flat is not None:
        deduction = _dec(flat)
    else:
        _block(pack, _RULE_EID, "the selected employment-income row has no value")

    basic = _scalar_amount(pack, "jp_wht_cmp_basic_deduction")
    per_dependant = _scalar_amount(pack, "jp_wht_cmp_dependant_deduction")
    taxable = max(ZERO, base - deduction - basic - per_dependant * Decimal(int(dependants)))

    events = []
    if taxable <= ZERO:
        return ZERO, COMPUTER, eid_row, events

    rate_rows = [row for row in slabs if str(_field(row, "rule_type") or "") == _RULE_RATE]
    if not rate_rows:
        _block(pack, _RULE_RATE, "no computer-method tax-rate rows are configured")
    rate_row = _band(rate_rows, taxable, _RULE_RATE, pack)
    tax_formula = _field(rate_row, "formula_expression")
    tax_rate = _field(rate_row, "rate_pct")
    tax_flat = _field(rate_row, "flat_amount")
    if tax_formula:
        raw_tax = evaluate_tax_formula(str(tax_formula), taxable)
    else:
        if tax_rate is None:
            _block(pack, _RULE_RATE, "the selected tax-rate row has no rate")
        raw_tax = taxable * _dec(tax_rate) / HUNDRED - _dec(tax_flat)
    tax = _round_value(max(ZERO, raw_tax), rounder, "jp_wht_rounding", "jp_wht", events)
    return tax, COMPUTER, rate_row, events


def monthly_withholding(base_after_si, declaration_class, dependants, method, slabs, scalars,
                        rounding=None):
    """Return national withholding for a monthly salary payment."""
    base = _dec(base_after_si)
    declaration = str(declaration_class or "").strip().upper()
    if declaration not in ("PRIMARY", "SECONDARY"):
        _block(scalars, "jp_wht_declaration_class",
               f"declaration class {declaration_class!r} is not PRIMARY or SECONDARY")
    try:
        dep = int(dependants)
    except (TypeError, ValueError):
        _block(scalars, "jp_wht_dependants", f"dependant count {dependants!r} is not a whole number")
    if dep < 0 or dep > 7:
        _block(scalars, "jp_wht_dependants", f"dependant count {dep} is outside the NTA table (0-7)")

    method = str(method or "").strip().upper()
    if not method or method == PENDING:
        _block(scalars, "jp_withholding_method", "withholding method is PENDING_G1")
    if method not in (_COMPUTER_METHOD, _TABLES_ONLY):
        _block(scalars, "jp_withholding_method", f"unsupported withholding method {method!r}")

    rounder = _rounder(scalars, rounding)
    if declaration == "PRIMARY" and method == _COMPUTER_METHOD:
        tax, branch, row, events = _computer_tax(base, dep, slabs, scalars, rounder)
    else:
        tax, branch, row, events = _table_tax(base, declaration, dep, slabs, scalars, rounder)
    return WithholdingResult(tax=tax, branch=branch, row=row, rounding_events=events)
