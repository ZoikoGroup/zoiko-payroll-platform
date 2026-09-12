"""
engine/jurisdictions/germany/overtime/classifier.py
------------------------------------------------------------
Phase 8AE — Germany overtime/shift-premium statutory time-window
CLASSIFICATION. Determines WHICH §3b EStG premium category applies to
WHICH portion of a GermanyOvertimeWorkRecord's worked time.

THIS MODULE NEVER CALCULATES A EURO AMOUNT. No premium amount, no
Grundlohn multiplication, no wage-tax or social-insurance split. It
produces GermanyOvertimeTimeSegment rows — statutory/calendar FACTS —
never a GermanyOvertimePremiumComponent (which does not exist anywhere in
this codebase; that is a future, explicitly out-of-scope phase).

── STATUTORY FACT vs. ENGINEERING DESIGN vs. UNRESOLVED QUESTION ─────────
See docs/PHASE_8AE_GERMANY_OVERTIME_STATUTORY_CLASSIFICATION.md for the
full verification trail. Summary of what is STATUTORY FACT (verbatim §3b
EStG text, fetched fresh this phase directly from gesetze-im-internet.de,
not cited from Phase 8Z's earlier summary):

  - Nachtarbeit (night work) = 20:00-06:00 local time (§3b Abs. 2 Satz 2).
  - The 40% "extended" rate (§3b Abs. 3 Nr. 1) applies to the 00:00-04:00
    portion ONLY when night work was "vor 0 Uhr aufgenommen" (commenced
    before midnight) — i.e. the SAME continuous work record already
    included night-qualifying time (20:00-24:00) on the preceding
    calendar day. Otherwise the 00:00-06:00 portion is NIGHT_STANDARD.
  - Sonntagsarbeit/Feiertagsarbeit = 00:00-24:00 of the calendar day
    (§3b Abs. 2 Satz 3), PLUS an extension: 00:00-04:00 of the day AFTER
    a Sunday/holiday ALSO counts as Sunday/holiday work (§3b Abs. 3
    Nr. 2) — a distinct, separately-worded provision from the night
    extension above, structurally analogous but not the same rule.
  - HOLIDAY_SPECIAL (150%) applies to FIXED CALENDAR DATES named directly
    in the statute — Dec 24 from 14:00, Dec 25, Dec 26, May 1 (§3b Abs. 1
    Nr. 4) — computable with NO holiday-registry dependency at all.
  - HOLIDAY_STANDARD (125%) applies to Dec 31 from 14:00 (also a fixed
    date) OR any "gesetzlicher Feiertag" (§3b Abs. 1 Nr. 3) — and §3b
    Abs. 2 Satz 4 itself states legal holidays are determined by the
    rules in force "am Ort der Arbeitsstätte" (at the place of work) —
    i.e. GENUINELY LAND-SPECIFIC by the statute's own text, not merely an
    engineering inference.
  - §3b contains NO explicit concurrence/stacking rule for multiple
    simultaneous categories (fetched and searched specifically this
    phase — no "Zusammentreffen" sentence exists in the statute).
    STATUTORY_CONCURRENCE_RULE_NOT_FOUND_IN_PRIMARY_TEXT. This module
    therefore NEVER sums or max()'s percentages — it emits one segment
    row per applicable category over the same physical time range and
    leaves any arithmetic combination to a future, separately-verified
    phase.

ENGINEERING DESIGN choices made this phase (not statutory fact):
  - Europe/Berlin (Python stdlib `zoneinfo`) is used as the authoritative
    local timezone for every boundary computation — the only DST-safe,
    non-custom option available, since no timezone foundation existed
    anywhere else in this codebase before this phase.
  - HOLIDAY_STANDARD's "gesetzlicher Feiertag" (Land-dependent) portion is
    classified ONLY from `PayrollHoliday` rows with `category="National"`
    for `country="DE"` — verified this phase (not assumed) that the
    seed list behind that category (`_DEFAULT_HOLIDAYS_BY_COUNTRY["DE"]`
    in service.py: New Year's Day, Good Friday, Easter Monday, German
    Unity Day, Christmas Day) contains ONLY holidays genuinely observed
    in all 16 Länder — no Land-restricted holiday is ever tagged
    "National". `category="Company"` rows (admin-added, arbitrary,
    non-statutory) are NEVER used for statutory classification.
  - RESIDUAL GAP, disclosed not hidden: a Land-specific ADDITIONAL legal
    holiday (e.g. Fronleichnam, Reformationstag, Heilige Drei Könige,
    Allerheiligen — observed in some but not all Länder) is NOT
    detectable by this module at all, since `PayrollHoliday` has no Land
    dimension and no such holiday is in the safe "National" seed set.
    This is a FALSE-NEGATIVE risk (a real Land holiday goes
    unclassified), not a false-positive one — judged the safer direction
    to err in, and explicitly NOT silently assumed away. Adding a Land
    column to `PayrollHoliday` was evaluated (Step 11) and NOT
    implemented this phase — the safe (nationwide) subset already
    provides real value without inventing Land coverage this codebase
    does not have.

UNRESOLVED QUESTIONS, explicitly not decided by this phase:
  - Whether/how multiple concurrent categories (e.g. SUNDAY +
    NIGHT_STANDARD) combine into one monetary amount — no rule found in
    §3b's primary text; a future phase must either find that rule
    elsewhere in German tax law/administrative guidance or treat it as a
    product decision.
  - Land-specific additional-holiday detection (see above) — deferred,
    not solved.
"""

from dataclasses import dataclass
from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

GERMANY_TZ = ZoneInfo("Europe/Berlin")


def _seconds_between(a: datetime, b: datetime) -> float:
    """Real elapsed seconds between two aware datetimes, computed via a
    UTC-normalized subtraction rather than a plain `b - a`.

    This is NOT optional or stylistic: CPython's datetime subtraction
    takes a "same tzinfo" fast path — when both operands share the
    identical tzinfo object (as every datetime built from the module-
    level GERMANY_TZ singleton does), it subtracts naive wall-clock
    values directly and silently ignores any UTC-offset (DST) change
    between them, e.g. `datetime(2026,3,29,4,0,tzinfo=tz) -
    datetime(2026,3,29,0,0,tzinfo=tz)` returns 4 hours even though only
    3 real hours elapsed across the spring-forward transition. Converting
    both sides to UTC first forces the correct, offset-aware subtraction.
    Discovered and verified empirically while building this module's own
    DST tests — see docs/PHASE_8AE_..._CLASSIFICATION.md §8."""
    return (a.astimezone(timezone.utc) - b.astimezone(timezone.utc)).total_seconds()

_NIGHT_CATEGORIES = {"NIGHT_STANDARD", "NIGHT_EXTENDED"}
_HOLIDAY_CATEGORIES = {"HOLIDAY_STANDARD", "HOLIDAY_SPECIAL"}
_ALL_CATEGORIES = _NIGHT_CATEGORIES | {"SUNDAY"} | _HOLIDAY_CATEGORIES


class GermanyOvertimeClassificationError(Exception):
    """Base: this work record cannot safely be classified. Carries a
    stable `code` (mirrors GermanyCalculationError's shape in
    germany_pap/core.py) — deliberately a SEPARATE exception hierarchy,
    since this is classification, not the real Germany payroll
    calculation path, and must never be caught/handled as if it were."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class GermanyOvertimeTimezoneFoundationRequiredError(GermanyOvertimeClassificationError):
    def __init__(self, message: str):
        super().__init__("TIMEZONE_FOUNDATION_REQUIRED", message)


class GermanyOvertimeInvalidIntervalError(GermanyOvertimeClassificationError):
    def __init__(self, message: str):
        super().__init__("INVALID_INTERVAL", message)


@dataclass
class _AtomicSegment:
    start: datetime  # Europe/Berlin-aware
    end: datetime    # Europe/Berlin-aware
    categories: List[str]


def _require_aware(dt: datetime, label: str) -> None:
    if dt.tzinfo is None:
        raise GermanyOvertimeTimezoneFoundationRequiredError(
            f"{label} has no timezone information — cannot safely determine the German local "
            "date/time boundary (night/Sunday/holiday windows are defined in local time, §3b EStG "
            "Abs. 2). A naive datetime is never silently treated as UTC or as local time."
        )


def _to_berlin(dt: datetime) -> datetime:
    return dt.astimezone(GERMANY_TZ)


def _day_boundary_candidates(start_local: datetime, end_local: datetime) -> List[datetime]:
    """Every 00:00/04:00/06:00/20:00 Europe/Berlin instant touching
    [start_local, end_local], plus the interval's own endpoints — the
    exact set of points where category membership can change, per the
    verified §3b Abs. 2/3 boundaries. Uses `datetime.combine` +
    `.replace(tzinfo=...)` on a real IANA zone (zoneinfo), never manual
    UTC-offset arithmetic, so DST transitions are handled correctly by
    the standard library rather than by hand."""
    points = {start_local, end_local}
    day = start_local.date()
    last_day = end_local.date()
    while day <= last_day:
        for hour in (0, 4, 6, 20):
            candidate = datetime.combine(day, time_cls(hour, 0), tzinfo=GERMANY_TZ)
            if start_local <= candidate <= end_local:
                points.add(candidate)
        day += timedelta(days=1)
    return sorted(points)


def _is_safe_national_de_holiday(db: Session, local_date: date_cls) -> bool:
    """Query PayrollHoliday for a verified-nationwide (category="National",
    country="DE") row on this date — see the module docstring for why
    this specific category is safe to trust without Land data, and why
    category="Company" rows are never used here. A single query per
    call; the caller batches calls to at most the handful of distinct
    local dates one work record can touch."""
    from app.modules.payroll.models import PayrollHoliday

    return (
        db.query(PayrollHoliday)
        .filter(
            PayrollHoliday.country == "DE",
            PayrollHoliday.category == "National",
            PayrollHoliday.date == local_date,
        )
        .first()
        is not None
    )


def _is_fixed_holiday_special(local_dt: datetime) -> bool:
    """§3b Abs. 1 Nr. 4 — fixed calendar dates, no registry needed."""
    d = local_dt.date()
    t = local_dt.time()
    if d.month == 12 and d.day == 24 and t >= time_cls(14, 0):
        return True
    if d.month == 12 and d.day in (25, 26):
        return True
    if d.month == 5 and d.day == 1:
        return True
    return False


def _is_fixed_holiday_standard_date(local_dt: datetime) -> bool:
    """§3b Abs. 1 Nr. 3's own fixed component — Dec 31 from 14:00."""
    d = local_dt.date()
    t = local_dt.time()
    return d.month == 12 and d.day == 31 and t >= time_cls(14, 0)


def _categories_for_instant(db: Session, work_record_start_local: datetime, instant: datetime) -> List[str]:
    """Categories applicable to the atomic sub-interval STARTING at
    `instant` (up to, but not including, the next boundary candidate).
    `instant` is used as the representative point for the whole
    sub-interval, which is valid because sub-intervals are constructed
    (see _day_boundary_candidates) to never cross a category boundary."""
    categories: List[str] = []
    t = instant.time()
    d = instant.date()

    # ── Night (§3b Abs. 2 Satz 2, Abs. 3 Nr. 1) ──────────────────────────
    if time_cls(20, 0) <= t or t < time_cls(6, 0):
        if t < time_cls(4, 0):
            # Extended (40%) only if THIS work record's night work began
            # before this local midnight (Abs. 3 Nr. 1's "vor 0 Uhr
            # aufgenommen") — i.e. the record's start is strictly on an
            # earlier calendar day than `instant`.
            midnight = datetime.combine(d, time_cls(0, 0), tzinfo=GERMANY_TZ)
            if work_record_start_local < midnight:
                categories.append("NIGHT_EXTENDED")
            else:
                categories.append("NIGHT_STANDARD")
        else:
            categories.append("NIGHT_STANDARD")

    # ── Sunday / Holiday (§3b Abs. 2 Satz 3, Abs. 3 Nr. 2) ───────────────
    # Each of SUNDAY / HOLIDAY_STANDARD / HOLIDAY_SPECIAL is checked and
    # emitted INDEPENDENTLY (never elif) — nothing in §3b establishes a
    # priority between them, and a date can genuinely be both (e.g.
    # Christmas Day falling on a Sunday). This module represents that
    # concurrence rather than picking one, per the "no invented priority/
    # stacking" rule.
    is_holiday_special_today = _is_fixed_holiday_special(instant)
    is_holiday_standard_today = _is_fixed_holiday_standard_date(instant) or _is_safe_national_de_holiday(db, d)
    is_sunday_today = d.weekday() == 6  # Monday=0 ... Sunday=6

    if is_holiday_special_today:
        categories.append("HOLIDAY_SPECIAL")
    if is_holiday_standard_today:
        categories.append("HOLIDAY_STANDARD")
    if is_sunday_today:
        categories.append("SUNDAY")

    # §3b Abs. 3 Nr. 2 extension: 00:00-04:00 of the day AFTER a
    # Sunday/holiday ALSO counts as that same category — checked
    # independently per category, and only added when the category isn't
    # already asserted for `instant`'s own day above (avoids a redundant
    # duplicate tag for a day that already independently qualifies).
    if t < time_cls(4, 0):
        prev_day = d - timedelta(days=1)
        prev_instant = datetime.combine(prev_day, time_cls(23, 59), tzinfo=GERMANY_TZ)
        if _is_fixed_holiday_special(prev_instant) and not is_holiday_special_today:
            categories.append("HOLIDAY_SPECIAL")
        prev_holiday_standard = _is_fixed_holiday_standard_date(prev_instant) or _is_safe_national_de_holiday(db, prev_day)
        if prev_holiday_standard and not is_holiday_standard_today:
            categories.append("HOLIDAY_STANDARD")
        if prev_day.weekday() == 6 and not is_sunday_today:
            categories.append("SUNDAY")

    return categories


def build_time_segments(db: Session, work_record) -> List[dict]:
    """Pure classification (no persistence, no DB writes) — returns a
    list of dicts, one per (atomic sub-interval x applicable category)
    pair. Never calculates a Euro amount; never resolves anything but the
    §3b EStG category itself plus (separately) whether a PUBLISHED
    GermanyOvertimePremiumCategory row exists for it as of that date."""
    from app.modules.payroll import service as payroll_service

    _require_aware(work_record.start_datetime, "start_datetime")
    _require_aware(work_record.end_datetime, "end_datetime")
    if _seconds_between(work_record.end_datetime, work_record.start_datetime) <= 0:
        raise GermanyOvertimeInvalidIntervalError("end_datetime must be after start_datetime.")

    start_local = _to_berlin(work_record.start_datetime)
    end_local = _to_berlin(work_record.end_datetime)

    boundaries = _day_boundary_candidates(start_local, end_local)
    results: List[dict] = []
    total_seconds = 0.0

    for a, b in zip(boundaries, boundaries[1:]):
        duration_seconds = _seconds_between(b, a)
        if duration_seconds <= 0:
            continue
        total_seconds += duration_seconds
        hours = Decimal(duration_seconds) / Decimal(3600)
        for category in _categories_for_instant(db, start_local, a):
            rule = payroll_service.resolve_germany_overtime_premium_category(db, category, as_of=a.date())
            results.append(dict(
                segment_start=a, segment_end=b, hours=hours, premium_category=category,
                classification_status="CONFIGURED" if rule is not None else "NOT_CONFIGURED",
                category_rule_id=rule.id if rule is not None else None,
                work_date_local=a.date(),
            ))

    # Invariant guard (defensive, not a statutory rule): the physical time
    # actually sliced must equal the requested interval — no gap, no
    # overrun. Raised as a hard error since it would indicate a bug in
    # the boundary-splitting logic itself, never a data problem.
    expected_seconds = _seconds_between(end_local, start_local)
    if abs(total_seconds - expected_seconds) > 1e-6:
        raise GermanyOvertimeInvalidIntervalError(
            "Internal classification error: sliced segment duration does not match the work record's "
            "actual interval duration."
        )

    return results


def classify_germany_overtime_work_record(db: Session, work_record, persist: bool = True) -> List[dict]:
    """Classify one GermanyOvertimeWorkRecord. If `persist`, replaces any
    existing GermanyOvertimeTimeSegment rows for this work record with
    the freshly-computed set (re-classification is idempotent and safe —
    nothing downstream depends on segment immutability yet; a future
    finalization/calculation phase is responsible for freezing whatever
    it actually consumes). Returns the list of segment dicts either way.

    Does NOT: calculate a premium amount, resolve Grundlohn, invoke PAP,
    touch PayslipItem, or modify ctx.overtime — none of those concepts
    are referenced anywhere in this function."""
    from app.modules.payroll.models import GermanyOvertimeTimeSegment

    segments = build_time_segments(db, work_record)

    if persist:
        db.query(GermanyOvertimeTimeSegment).filter(
            GermanyOvertimeTimeSegment.work_record_id == work_record.id,
        ).delete()
        rows = []
        for seg in segments:
            row = GermanyOvertimeTimeSegment(work_record_id=work_record.id, **seg)
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
        return rows

    return segments
