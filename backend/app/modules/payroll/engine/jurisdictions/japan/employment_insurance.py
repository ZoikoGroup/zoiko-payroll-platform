"""Japan employment-insurance contributions (ZP-JP-ENG-001, JP-004/JP-006)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.jurisdictions.japan.errors import JapanCalculationBlockedError

ZERO = Decimal("0")
HUNDRED = Decimal("100")
PENDING = "PENDING_G1"
_KEYS = {
    "GENERAL": "jp_ei_general",
    "AGRICULTURE_SAKE": "jp_ei_agriculture_sake",
    "CONSTRUCTION": "jp_ei_construction",
}
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


class EIResult(dict):
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


def _upper(value):
    return "" if value is None else str(value).strip().upper()


def _as_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _block(pack, key: str, reason: str):
    if hasattr(pack, "block"):
        return pack.block(key, reason)
    raise JapanCalculationBlockedError(key, reason, getattr(pack, "organization_id", None))


def _row(pack, key):
    if isinstance(pack, dict):
        return pack.get(key)
    rate_map = getattr(pack, "rate_map", None)
    if isinstance(rate_map, dict):
        return rate_map.get(key)
    return None


def _in_force(row, as_of):
    if row is None or as_of is None:
        return True
    start = _as_date(_field(row, "effective_from"))
    end = _as_date(_field(row, "effective_to"))
    return (start is None or start <= as_of) and (end is None or end >= as_of)


def _rounder(pack, rounding):
    if isinstance(rounding, dict):
        rounding = rounding.get("jp_ei_employee_share_rounding")
    if callable(rounding):
        return rounding
    key = "jp_ei_employee_share_rounding"
    row = _row(pack, key)
    if row is None:
        _block(pack, key, "no rounding row is configured")
    text = _upper(_field(row, "text_value"))
    if not text or text == PENDING:
        _block(pack, key, "rounding is PENDING_G1")
    unit = Decimal("1")
    mode_name = text
    if text.startswith("DOWN_") and text[5:].isdigit():
        unit = Decimal(text[5:])
        mode_name = "DOWN"
    mode = _MODES.get(mode_name)
    if mode is None:
        _block(pack, key, f"unsupported rounding rule {text!r}")
    return lambda value: (value / unit).quantize(Decimal("1"), rounding=mode) * unit


def _rounded(value, rounder, field, events):
    before = value
    after = rounder(value)
    if after != before:
        events.append({"field": field, "row": "jp_ei_employee_share_rounding",
                       "before": str(before), "after": str(after)})
    return after


def monthly_employment_insurance(profile, base, pack, as_of=None, rounding=None, on=None):
    """Return the employee and employer employment-insurance amounts."""
    as_of = on or as_of
    if as_of is None:
        _block(pack, "pay_date", "payment date is required")
    if _field(profile, "insured") is False:
        return EIResult(employee=ZERO, employer=ZERO, rate_row=None,
                        trace={"insured": False, "roundingEvents": []})
    industry = _upper(_field(profile, "industry_class"))
    key = _KEYS.get(industry)
    if key is None:
        _block(pack, "jp_ei_industry_class", f"unknown employment-insurance class {industry!r}")
    row = _row(pack, key)
    if row is None:
        _block(pack, key, "no employment-insurance rate row is configured")
    if not _in_force(row, as_of):
        _block(pack, key, "no employment-insurance rate row is in force for the pay date")
    employee_rate = _field(row, "employee_rate_pct")
    employer_rate = _field(row, "employer_rate_pct")
    if employee_rate is None or employer_rate is None:
        _block(pack, key, "the employment-insurance employee / employer pair is not configured")

    amount_base = _dec(base)
    rounder = _rounder(pack, rounding)
    events = []
    employee = _rounded(amount_base * _dec(employee_rate) / HUNDRED, rounder,
                        "jp_ei_employee", events)
    employer = _rounded(amount_base * _dec(employer_rate) / HUNDRED, rounder,
                        "jp_ei_employer", events)
    return EIResult(employee=employee, employer=employer, rate_row=row,
                    trace={"insured": True, "industryClass": industry,
                           "employeeRatePct": str(_dec(employee_rate)),
                           "employerRatePct": str(_dec(employer_rate)),
                           "roundingEvents": events})
