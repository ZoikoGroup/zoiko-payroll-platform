"""
engine/jurisdictions/mexico/content.py
--------------------------------------
Typed read access over the pack rows a PayrollContext carries (MX-003): the
`rate_map` ({component_key: {employee_rate_pct, employer_rate_pct,
flat_amount, jurisdiction_state, text_value}}) and the `slabs` list, both
already selected by the resolver for the legal date. The engine never reads
mexico_content's constants and never has a default: a missing row raises
MXBlock("MX_CONTENT_MISSING").

Percent convention: Mexican rate rows are stored in percent units ("1.10"
means 1.10 %); `pct()` returns the fraction (0.0110).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ...countries import mexico_content as _c
from .errors import MXBlock

_HUNDRED = Decimal("100")


def _dec(value, what: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MXBlock("MX_CONTENT_INVALID", f"{what} is not a number ({value!r})")
    if not out.is_finite():
        raise MXBlock("MX_CONTENT_INVALID", f"{what} is not a finite number")
    return out


class Content:
    """One set of pack rows — the national rows in force on one legal date
    (the pay date, or one contribution segment's date)."""

    def __init__(self, rate_map, slabs, label: str = "pay date"):
        self.rate_map = rate_map or {}
        self.slabs = slabs or []
        self.label = label
        self.used: list = []          # (key, value) of every row read — the trace's content list

    # ── scalar rows ──
    def _row(self, key: str) -> dict:
        row = self.rate_map.get(key)
        if not row:
            raise MXBlock("MX_CONTENT_MISSING", f"no {key} row in force on the {self.label}")
        return row

    def _field(self, key: str, field: str):
        value = self._row(key).get(field)
        if value is None or value == "":
            raise MXBlock("MX_CONTENT_MISSING", f"the {key} row in force on the {self.label} has no {field}")
        return value

    def amount(self, key: str) -> Decimal:
        out = _dec(self._field(key, "flat_amount"), key)
        self.used.append((key, str(out)))
        return out

    def pct(self, key: str) -> Decimal:
        """The row's single side as a fraction. Which side is the key's kind
        in MX_PARAMETER_KEYS — never guessed from whichever field is set."""
        kind = _c.MX_PARAMETER_KEYS.get(key, (None,))[0]
        field = {"employee_pct": "employee_rate_pct", "employer_pct": "employer_rate_pct"}.get(kind)
        if field is None:
            raise MXBlock("MX_CONTENT_INVALID", f"{key} is not a percentage parameter")
        value = _dec(self._field(key, field), key)
        self.used.append((key, f"{value}%"))
        return value / _HUNDRED

    def text(self, key: str) -> str:
        value = str(self._field(key, "text_value")).strip()
        if not value:
            raise MXBlock("MX_CONTENT_MISSING", f"the {key} row in force on the {self.label} is empty")
        self.used.append((key, value))
        return value

    def has(self, key: str) -> bool:
        row = self.rate_map.get(key)
        return bool(row) and any(row.get(f) not in (None, "") for f in
                                 ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value"))

    # ── slab rows ──
    def _slabs(self, rule_type: str) -> list:
        return [s for s in self.slabs if s.get("rule_type") == rule_type]

    def isr_tariff(self, period: str) -> list:
        """Art. 96 brackets of one payment period, ordered by lower limit:
        [{lower, upper (None = open), fixed, rate (fraction)}]."""
        rows = [s for s in self._slabs(_c.MX_ISR_TARIFF_RULE) if s.get("filing_status") == period]
        if not rows:
            raise MXBlock("MX_CONTENT_MISSING", f"no ISR tariff for the {period} period on the {self.label}")
        out = []
        for s in rows:
            out.append({
                "lower": _dec(s.get("min_amount"), "ISR lower limit"),
                "upper": None if s.get("max_amount") in (None, "") else _dec(s.get("max_amount"), "ISR upper limit"),
                "fixed": _dec(s.get("flat_amount"), "ISR fixed quota"),
                "rate": _dec(s.get("rate_pct"), "ISR rate") / _HUNDRED,
                "rate_pct": _dec(s.get("rate_pct"), "ISR rate"),
            })
        out.sort(key=lambda b: b["lower"])
        self.used.append((f"{_c.MX_ISR_TARIFF_RULE}:{period}", f"{len(out)} brackets"))
        return out

    def min_wage(self, code: str, zone: str = None) -> Decimal:
        """Daily minimum wage of a zone code (GENERAL / ZLFN) or a
        professional code (restricted to `zone` when the row names one)."""
        rows = [s for s in self._slabs(_c.MX_MIN_WAGE_RULE) if s.get("filing_status") == code]
        if zone is not None:
            rows = [s for s in rows if s.get("jurisdiction_state") in (None, "", zone)]
        if not rows:
            raise MXBlock("MX_CONTENT_MISSING", f"no {code} minimum wage on the {self.label}")
        if len(rows) > 1:
            raise MXBlock("MX_CONTENT_INVALID", f"two {code} minimum-wage rows in force on the {self.label}")
        out = _dec(rows[0].get("flat_amount"), f"{code} minimum wage")
        self.used.append((f"{_c.MX_MIN_WAGE_RULE}:{code}", str(out)))
        return out

    def ceav_bands(self) -> list:
        """Employer CEAV bands in force: [{lower, lower_unit, upper (None =
        open), upper_unit, rate (fraction)}], ordered by lower multiple."""
        rows = self._slabs(_c.MX_CEAV_BAND_RULE)
        if not rows:
            raise MXBlock("MX_CONTENT_MISSING", f"no CEAV employer bands on the {self.label}")
        out = []
        for s in rows:
            units = str(s.get("assessment_basis") or "")
            lower_unit, _, upper_unit = units.partition("/")
            if lower_unit not in ("SM", "UMA") or upper_unit not in ("SM", "UMA", "-"):
                raise MXBlock("MX_CONTENT_INVALID", f"CEAV band {s.get('filing_status')} has units {units!r}")
            upper = None if s.get("max_amount") in (None, "") else _dec(s.get("max_amount"), "CEAV upper multiple")
            if (upper is None) != (upper_unit == "-"):
                raise MXBlock("MX_CONTENT_INVALID", f"CEAV band {s.get('filing_status')} has an inconsistent upper limit")
            out.append({"label": s.get("filing_status"), "lower": _dec(s.get("min_amount"), "CEAV lower multiple"),
                        "lower_unit": lower_unit, "upper": upper, "upper_unit": None if upper is None else upper_unit,
                        "rate": _dec(s.get("rate_pct"), "CEAV employer rate") / _HUNDRED,
                        "rate_pct": _dec(s.get("rate_pct"), "CEAV employer rate")})
        out.sort(key=lambda b: b["lower"])
        self.used.append((_c.MX_CEAV_BAND_RULE, f"{len(out)} bands"))
        return out

    def workweek_max_hours(self) -> Decimal:
        rows = [s for s in self._slabs(_c.MX_WORKWEEK_RULE) if s.get("filing_status") == "WEEKLY_MAX"]
        if len(rows) != 1:
            raise MXBlock("MX_CONTENT_MISSING" if not rows else "MX_CONTENT_INVALID",
                          f"{'no' if not rows else 'more than one'} statutory weekly maximum on the {self.label}")
        out = _dec(rows[0].get("flat_amount"), "weekly maximum hours")
        self.used.append((_c.MX_WORKWEEK_RULE, str(out)))
        return out

    def vacation_days(self, service_year: int) -> Decimal:
        """Statutory vacation days for a service year (1 = first year)."""
        for s in self._slabs(_c.MX_VACATION_DAYS_RULE):
            lo = int(_dec(s.get("min_amount"), "vacation year from"))
            hi = None if s.get("max_amount") in (None, "") else int(_dec(s.get("max_amount"), "vacation year to"))
            if lo <= service_year and (hi is None or service_year <= hi):
                out = _dec(s.get("flat_amount"), "vacation days")
                self.used.append((f"{_c.MX_VACATION_DAYS_RULE}:YEAR_{service_year}", str(out)))
                return out
        raise MXBlock("MX_CONTENT_MISSING", f"no statutory vacation days for service year {service_year} on the {self.label}")
