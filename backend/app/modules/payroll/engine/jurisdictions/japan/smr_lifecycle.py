"""Japan standard monthly remuneration lifecycle (ZP-JP-ENG-001 §5/§11, S7).

Pure functions: they read pay history and the signed content rows and return
a PROPOSAL. Nothing here writes an enrolment; an approved event is applied by
japan_lifecycle.py as a new enrolment version (JP-010, JP-011).

  * annual_determination   — April–June pay (content months) -> grade, in
                             force September–August;
  * adhoc_revision_candidate — a fixed-pay change whose three-month average
                             moves the grade by the signed gap -> always
                             REVIEW_REQUIRED, never applied automatically;
  * care_state_on          — COVERED inside the content age band;
  * exemption_events_in_month — maternity / childcare exemption events that
                             touch a pay month (the engine BLOCKS on them).

Grade rows are TaxSlab rule_type JP_SMR_GRADE: filing_status HEALTH or
PENSION, tax_table_number = grade, min_amount / max_amount = the remuneration
band, flat_amount = the SMR of the grade.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.japan.social_insurance import (
    _age_on,
    _amount,
    _as_date,
    _block,
    _dec,
    _field,
    _in_force,
    _row,
    _upper,
)

ZERO = Decimal("0")
_RULE_SMR = "JP_SMR_GRADE"
KINDS = ("HEALTH", "PENSION")
EXEMPTION_EVENTS = ("MATERNITY_EXEMPTION", "CHILDCARE_EXEMPTION")
REVIEW_REQUIRED = "REVIEW_REQUIRED"
NO_REVISION = "NO_REVISION"
NOT_ELIGIBLE = "NOT_ELIGIBLE"


class SMRProposal(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _text(pack, key, as_of):
    row = _row(pack, key)
    if row is None or not _in_force(row, as_of):
        _block(pack, key, "no configured row is in force")
    value = str(_field(row, "text_value") or "").strip()
    if not value or value.upper() == "PENDING_G1":
        _block(pack, key, "row has no signed value")
    return value


def _month_range(pack, key, as_of):
    text = _text(pack, key, as_of)
    try:
        first, last = (int(part) for part in text.split("-"))
    except ValueError:
        _block(pack, key, f"{text!r} is not MM-MM")
    if not (1 <= first <= 12 and 1 <= last <= 12):
        _block(pack, key, f"{text!r} is not MM-MM")
    return first, last


def _whole(pack, key, as_of):
    value = _amount(pack, key, as_of)
    if value != value.to_integral_value() or value < ZERO:
        _block(pack, key, f"{value} is not a whole number")
    return int(value)


def _add_months(year, month, count):
    index = year * 12 + (month - 1) + count
    return index // 12, index % 12 + 1


def _month_key(value):
    if isinstance(value, date):
        return value.year, value.month
    text = str(value or "")
    try:
        return int(text[:4]), int(text[5:7])
    except ValueError:
        return None


def _pay_by_month(monthly_pay, pack):
    """{(year, month): (amount, base_days)}; a duplicated month BLOCKS."""
    out = {}
    for entry in monthly_pay or []:
        key = _month_key(_field(entry, "month"))
        if key is None:
            _block(pack, "jp_smr_pay_history", f"pay month {_field(entry, 'month')!r} is not YYYY-MM")
        if key in out:
            _block(pack, "jp_smr_pay_history", f"pay month {key[0]}-{key[1]:02d} appears twice")
        amount = _dec(_field(entry, "amount"))
        days = _field(entry, "base_days")
        if amount < ZERO:
            _block(pack, "jp_smr_pay_history", f"pay for {key[0]}-{key[1]:02d} is negative")
        if not isinstance(days, int) or days < 0:
            _block(pack, "jp_smr_pay_history",
                   f"payment base days for {key[0]}-{key[1]:02d} are not a whole number")
        out[key] = (amount, days)
    return out


def grade_for(average, kind, slabs, pack, as_of):
    """The grade row whose remuneration band holds ``average``."""
    kind = _upper(kind)
    if kind not in KINDS:
        _block(pack, "jp_smr_kind", f"{kind!r} is not HEALTH or PENSION")
    rows = [row for row in (slabs or [])
            if _upper(_field(row, "rule_type")) == _RULE_SMR
            and _upper(_field(row, "filing_status")) == kind
            and _in_force(row, as_of)]
    if not rows:
        _block(pack, f"jp_smr_grades_{kind.lower()}", f"no {kind.lower()} SMR grade table is in force")
    matches = [row for row in rows
               if average >= _dec(_field(row, "min_amount"))
               and (_field(row, "max_amount") is None or average < _dec(_field(row, "max_amount")))]
    if len(matches) != 1:
        _block(pack, f"jp_smr_grades_{kind.lower()}",
               f"{len(matches)} {kind.lower()} grade rows cover {average}; exactly one is required")
    row = matches[0]
    grade = _field(row, "tax_table_number")
    smr = _field(row, "flat_amount")
    if grade is None or smr is None:
        _block(pack, f"jp_smr_grades_{kind.lower()}", "the grade row has no grade number or SMR")
    return int(grade), _dec(smr), row


def annual_determination(monthly_pay, year, kind, slabs, pack):
    """The annual determination (S7) for ``year``: the average pay of the
    determination months that reach the signed payment base days selects the
    grade, in force from the first application month of ``year`` to the end
    of the month before it in the following year."""
    first, last = _month_range(pack, "jp_smr_determination_months", date(year, 1, 1))
    applies_from, _applies_to = _month_range(pack, "jp_smr_application_months", date(year, 1, 1))
    report_text = _text(pack, "jp_smr_report_month", date(year, 1, 1))
    if not report_text.isdigit() or not 1 <= int(report_text) <= 12:
        _block(pack, "jp_smr_report_month", f"{report_text!r} is not MM")
    report_month = int(report_text)
    min_days = _whole(pack, "jp_smr_min_payment_base_days", date(year, 1, 1))
    pay = _pay_by_month(monthly_pay, pack)

    months = [(year, month) for month in range(first, last + 1)]
    missing = [f"{y}-{m:02d}" for (y, m) in months if (y, m) not in pay]
    if missing:
        _block(pack, "jp_smr_pay_history", f"no pay recorded for {', '.join(missing)}")
    counted = [(y, m) for (y, m) in months if pay[(y, m)][1] >= min_days]
    if not counted:
        # The insurer-determined path (no month reaches the base days) is
        # not certified.
        _block(pack, "JP_SMR_INSURER_DETERMINATION",
               f"no {year} determination month reaches {min_days} payment base days")
    average = sum((pay[key][0] for key in counted), ZERO) / Decimal(len(counted))
    effective_from = date(year, applies_from, 1)
    end_year, end_month = _add_months(year, applies_from, 12)
    effective_to = date.fromordinal(date(end_year, end_month, 1).toordinal() - 1)
    grade, smr, row = grade_for(average, kind, slabs, pack, effective_from)
    return SMRProposal(
        kind=_upper(kind), basis="ANNUAL_DETERMINATION", grade=grade, smr=smr, average=average,
        months_counted=[f"{y}-{m:02d}" for (y, m) in counted],
        effective_from=effective_from, effective_to=effective_to,
        report_month=f"{year}-{report_month:02d}", status=REVIEW_REQUIRED, row=row)


def adhoc_revision_candidate(change_month, direction, monthly_pay, current_grade, kind, slabs, pack):
    """An ad hoc revision candidate (S7) after a fixed-pay change in
    ``change_month``. ``direction`` is UP or DOWN (the fixed-pay change). The
    three months from the change month must all reach the signed payment base
    days; the grade must move in the same direction by at least the signed
    gap. A candidate is only ever REVIEW_REQUIRED — it is never applied
    automatically."""
    change = _as_date(change_month)
    if change is None:
        _block(pack, "jp_smr_change_month", "the fixed-pay change month is required")
    direction = _upper(direction)
    if direction not in ("UP", "DOWN"):
        _block(pack, "jp_smr_change_direction", f"{direction!r} is not UP or DOWN")
    if current_grade is None:
        _block(pack, "jp_smr_current_grade", "the current grade is required")
    from_month = _whole(pack, "jp_smr_adhoc_revision_from_month", change)
    min_days = _whole(pack, "jp_smr_min_payment_base_days", change)
    gap_min = _whole(pack, "jp_smr_adhoc_grade_gap", change)
    if from_month < 1:
        _block(pack, "jp_smr_adhoc_revision_from_month", f"{from_month} is not a month offset")
    pay = _pay_by_month(monthly_pay, pack)

    window = [_add_months(change.year, change.month, offset) for offset in range(3)]
    missing = [f"{y}-{m:02d}" for (y, m) in window if (y, m) not in pay]
    if missing:
        _block(pack, "jp_smr_pay_history", f"no pay recorded for {', '.join(missing)}")
    short = [f"{y}-{m:02d}" for (y, m) in window if pay[(y, m)][1] < min_days]
    base = SMRProposal(kind=_upper(kind), basis="ADHOC_REVISION", current_grade=int(current_grade),
                       months=[f"{y}-{m:02d}" for (y, m) in window])
    if short:
        return SMRProposal(base, status=NOT_ELIGIBLE,
                           reason=f"below {min_days} payment base days in {', '.join(short)}")

    average = sum((pay[key][0] for key in window), ZERO) / Decimal(3)
    eff_year, eff_month = _add_months(change.year, change.month, from_month - 1)
    effective_from = date(eff_year, eff_month, 1)
    grade, smr, row = grade_for(average, kind, slabs, pack, effective_from)
    moved = grade - int(current_grade)
    if (direction == "UP" and moved < gap_min) or (direction == "DOWN" and -moved < gap_min):
        return SMRProposal(base, status=NO_REVISION, grade=grade, average=average,
                           reason=f"grade moves {moved:+d}; {direction} needs at least {gap_min}")
    return SMRProposal(base, status=REVIEW_REQUIRED, grade=grade, smr=smr, average=average,
                       effective_from=effective_from, row=row)


def care_state_on(date_of_birth, on, pack):
    """COVERED when the age on ``on`` is inside the content care band
    (jp_care_min_age..jp_care_max_age), otherwise NOT_COVERED."""
    born = _as_date(date_of_birth)
    on = _as_date(on)
    if born is None:
        _block(pack, "jp_date_of_birth", "date of birth is required for care insurance")
    if on is None:
        _block(pack, "pay_date", "a date is required")
    age = _age_on(born, on)
    low = _whole(pack, "jp_care_min_age", on)
    high = _whole(pack, "jp_care_max_age", on)
    return "COVERED" if low <= age <= high else "NOT_COVERED"


def exemption_events_in_month(events, pay_date):
    """Event types of the maternity / childcare exemption events that touch
    the month of ``pay_date``. Every event that is not REJECTED counts — an
    unapproved exemption is still a reason not to charge by assumption."""
    pay_date = _as_date(pay_date)
    if pay_date is None or not events:
        return []
    month_start = date(pay_date.year, pay_date.month, 1)
    next_year, next_month = _add_months(pay_date.year, pay_date.month, 1)
    month_end = date.fromordinal(date(next_year, next_month, 1).toordinal() - 1)
    found = []
    for event in events:
        kind = _upper(_field(event, "event_type"))
        if kind not in EXEMPTION_EVENTS:
            continue
        if _upper(_field(event, "submission_status")) == "REJECTED":
            continue
        start = _as_date(_field(event, "effective_from"))
        end = _as_date(_field(event, "effective_to"))
        if start is None or start > month_end or (end is not None and end < month_start):
            continue
        found.append(kind)
    return sorted(set(found))
