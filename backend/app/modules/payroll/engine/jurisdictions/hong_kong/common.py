"""Shared Hong Kong helpers — errors, dates, year of assessment, provenance."""

import calendar
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

COUNTRY = "HK"
ZERO = Decimal("0")
CENT = Decimal("0.01")


class HongKongCalculationBlockedError(MissingComplianceConfigurationError):
    """A Hong Kong statutory outcome that must not be produced — a missing
    statutory row, a missing/contradictory worker fact, or an out-of-scope
    case. Subclasses MissingComplianceConfigurationError so main.py returns the
    same MISSING_COMPLIANCE_CONFIGURATION 400 every fail-closed jurisdiction
    uses (same pattern as SingaporeCalculationBlockedError)."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, COUNTRY, organization_id)
        self.key = key
        self.reason = reason
        self.args = (f"Hong Kong calculation blocked ({key}): {reason}",)


def dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def cents(value: Decimal) -> Decimal:
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def age_on(date_of_birth: date, on: date) -> int:
    return on.year - date_of_birth.year - ((on.month, on.day) < (date_of_birth.month, date_of_birth.day))


def add_months(d: date, months: int) -> date:
    """Same day `months` later, clamped to the month end (1 Jan + 1 = 1 Feb;
    31 Jan + 1 = 28/29 Feb)."""
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:              # 29 Feb in a non-leap year
        return d.replace(year=d.year + years, day=28)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def days_inclusive(start: date, end: date) -> int:
    return (end - start).days + 1


def each_day(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def year_of_assessment(on: date) -> str:
    """Hong Kong year of assessment containing `on` — 1 April to 31 March
    (IRD; HK-011: never the calendar year). 15 Mar 2026 → "2025/26"."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def year_of_assessment_bounds(ya: str) -> tuple:
    start = int(ya[:4])
    return date(start, 4, 1), date(start + 1, 3, 31)


def row_ref(row):
    """Provenance of one pack row for the trace (rule id, window, evidence)."""
    if row is None:
        return None
    ref = {}
    for attr, key in (("rate_label", "rule"), ("component_key", "componentKey"), ("rule_type", "ruleType"),
                      ("id", "rowId"), ("source_document_id", "sourceDocumentId"),
                      ("jurisdiction_pack_id", "packId")):
        value = getattr(row, attr, None)
        if value not in (None, ""):
            ref[key] = value
    for attr, key in (("effective_from", "effectiveFrom"), ("effective_to", "effectiveTo")):
        value = getattr(row, attr, None)
        if value is not None:
            ref[key] = value.isoformat()
    return ref


def canonical_hash(payload) -> str:
    """Deterministic SHA-256 of a JSON-able payload (sorted keys) — evidence
    hashes for snapshots, IRD payloads and termination results."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def rate_value(rate_map: dict, key: str, *, side: str = "employee"):
    """A pack ContributionRate value, fail-closed: a missing row BLOCKS (HK
    has no hardcoded fallback — never a default statutory value)."""
    row = (rate_map or {}).get(key)
    if row is None:
        raise HongKongCalculationBlockedError(key, f"no Hong Kong statutory row '{key}' in the resolved rule pack")
    if getattr(row, "flat_amount", None) is not None:
        return dec(row.flat_amount), row
    pct = row.employer_rate_pct if side == "employer" else row.employee_rate_pct
    if pct is None:
        raise HongKongCalculationBlockedError(key, f"statutory row '{key}' has no value")
    return dec(pct), row


def fraction_value(rate_map: dict, key: str):
    """An exact statutory fraction stored as text ("2/3", "4/5") — flat_amount
    has two decimals, so a fraction is never rounded into a rate row."""
    from fractions import Fraction

    value, row = text_value(rate_map, key)
    try:
        frac = Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise HongKongCalculationBlockedError(key, f"statutory fraction {value!r} is not a valid fraction")
    return Decimal(frac.numerator) / Decimal(frac.denominator), row


def text_value(rate_map: dict, key: str, required: bool = True):
    row = (rate_map or {}).get(key)
    value = getattr(row, "text_value", None) if row is not None else None
    if required and not value:
        raise HongKongCalculationBlockedError(key, f"no Hong Kong statutory rule '{key}' in the resolved rule pack")
    return value, row


# IRD reporting TIMING rows. The pack carries the periods so a due date can
# never be produced from a literal in the code: an IRD deadline is a statutory
# outcome and must resolve from the pack that also carries the rate rows and
# the source evidence (ZP-HK-ENG-001 §7; D-4).
REPORTING_TIMING_KEYS = (
    "ird_ir56e_months",
    "ird_ir56f_months_before",
    "ird_ir56g_months_before",
    "ird_ir56g_hold_months",
    "ird_ir56b_due_months",
    "ird_return_issue_month",
    "ird_return_issue_day",
    "ird_ir56g_absence_months",
)


def resolve_timing(rate_map: dict, keys=REPORTING_TIMING_KEYS) -> dict:
    """The reporting-timing rows of the resolved pack as {key: Decimal} —
    fail-closed, one missing row blocks the whole deadline."""
    return {key: rate_value(rate_map, key)[0] for key in keys}


def timing_months(timing: dict, key: str) -> int:
    """A whole-month period from a resolved timing map (never a literal)."""
    if not timing or key not in timing:
        raise HongKongCalculationBlockedError(key, f"the statutory period '{key}' was not resolved from the rule pack")
    value = dec(timing[key])
    if value != value.to_integral_value():
        raise HongKongCalculationBlockedError(key, f"statutory period '{key}' must be a whole number of months, not {value}")
    return int(value)


def timing_day(timing: dict, key: str) -> int:
    """A whole-day-of-month from a resolved timing map (the BIR56A issue day)."""
    if not timing or key not in timing:
        raise HongKongCalculationBlockedError(key, f"the statutory date part '{key}' was not resolved from the rule pack")
    value = int(dec(timing[key]))
    if not 1 <= value <= 31:
        raise HongKongCalculationBlockedError(key, f"statutory day-of-month '{key}' must be 1–31, not {value}")
    return value


PERIOD_SPLIT_KEYS = ("smw_hourly_rate", "smw_hours_record_cap_monthly")


def rule_segments(rows, period_start: date, period_end: date, keys=PERIOD_SPLIT_KEYS) -> dict:
    """Every row of the pinned pack for the period-split rules that overlaps
    [period_start, period_end], as {key: [{from, to, value, ref}]} — so a wage
    period crossing an effective date sees BOTH values (resolve_tax_
    configuration filters rows at one as-of date only)."""
    out = {k: [] for k in keys}
    for r in rows:
        if r.component_key not in out:
            continue
        start = r.effective_from or date.min
        if start > period_end or (r.effective_to is not None and r.effective_to < period_start):
            continue
        out[r.component_key].append({"from": start.isoformat(), "to": r.effective_to.isoformat() if r.effective_to else None,
                                     "value": str(r.flat_amount), "ref": row_ref(r)})
    for k in out:
        out[k].sort(key=lambda s: s["from"])
    return out
