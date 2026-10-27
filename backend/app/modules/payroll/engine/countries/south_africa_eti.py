"""modules/payroll/engine/countries/south_africa_eti.py
------------------------------------------------------
South Africa (ZP-ZA-ENG-001) — the Employment Tax Incentive, evaluated as a
PURE function of configured content. "ZA" is South Africa; "SA" in this
repository is Saudi Arabia.

ETI is an EMPLOYER incentive (ZA-010): the result here is the amount that may
reduce the employer's PAYE remittance. It is never an employee deduction, never
reduces the employee's PAYE and never changes net pay. The engine keeps it out
of every employee/employer total; only the EMP201 remittance may use it.

Every figure comes from the content rows the caller passes in (`rate_map` via
`pack`, and `slabs` rule_type="ZA_ETI_BAND"). A missing or ambiguous row calls
`pack.block(...)`, which raises the engine's ZACalculationBlockedError; the
engine catches that for ETI alone, so a bad ETI configuration can never stop an
employee's pay.

Check order (spec §2, §4, F3; PENDING_G1 where the spec leaves a policy open):
  1. employer not ETI-registered                -> NOT_REGISTERED
  2. no eligibility evidence (`za_eti_eligible`) -> INELIGIBLE
  3. a required fact is missing                 -> BLOCKED
  4. paid hours are zero or negative            -> BLOCKED (cannot normalise)
  5. age outside the configured ETI age window  -> INELIGIBLE
  6. qualifying month beyond the maximum        -> INELIGIBLE
  7. hourly remuneration below the NMW          -> INELIGIBLE
  8. qualifying period from the month number
  9. normalise remuneration to the configured paid-hours normaliser
 10. select the period's band (min <= remuneration < max)
 11. PCT / FLAT / TAPER, then un-normalise, then clamp at zero

PENDING_G1 (not decided here; recorded rather than guessed):
  * whether a month whose ETI amount is zero still counts as a qualifying month;
  * the SARS rule for normalising remuneration when paid hours differ from the
    configured normaliser (the content's 160-hour rule is used as configured).
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.countries import south_africa_content as _content

COUNTRY = "ZA"
ZERO = Decimal("0")
HUNDRED = Decimal("100")

ELIGIBLE = "ELIGIBLE"
INELIGIBLE = "INELIGIBLE"
NOT_REGISTERED = "NOT_REGISTERED"
BLOCKED = "BLOCKED"

FIRST_12, SECOND_12 = _content.ETI_PERIODS


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _age_on(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _result(status, *, reason=None, month_no=None, period=None, paid_hours=None,
            remuneration=None, normalised=None, band=None, amount=None, rnd=None):
    """A JSON-safe result. `amount` stays a Decimal for the caller (the engine
    converts it to a string in `za_result`); everything else is a string/None."""
    if amount is None:
        amount = rnd(ZERO) if rnd is not None else ZERO
    return {
        "status": status,
        "reasons": [reason] if reason else [],
        "qualifyingMonthNo": None if month_no is None else int(month_no),
        "period": period,
        "paidHours": None if paid_hours is None else str(paid_hours),
        "remuneration": None if remuneration is None else str(remuneration),
        "normalisedRemuneration": None if normalised is None else str(normalised),
        "band": band,
        "amount": amount,
    }


def blocked_result(reason, *, month_no=None, paid_hours=None, rnd=None) -> dict:
    """The engine's fail-closed ETI result: an ETI-only BLOCK that never stops
    the employee's PAYE / UIF / SDL calculation."""
    return _result(BLOCKED, reason=reason, month_no=month_no, paid_hours=paid_hours, rnd=rnd)


def _select_band(slabs, period: str, remuneration: Decimal, pack):
    """The one ZA_ETI_BAND row for the period whose [min, max) holds the
    normalised remuneration. No rows at all is missing configuration (BLOCK);
    rows that simply do not match means zero ETI (the capped top of the table)."""
    rows = [r for r in (slabs or [])
            if (getattr(r, "rule_type", None) or "") == _content.ZA_ETI_BAND_RULE
            and (getattr(r, "filing_status", None) or "").upper() == period]
    if not rows:
        pack.block("za_eti_band", f"no ETI band rows are configured for {period}")
    matches = []
    for row in rows:
        lo_raw = getattr(row, "min_amount", None)
        hi_raw = getattr(row, "max_amount", None)
        if lo_raw is None or hi_raw is None:
            pack.block("za_eti_band", f"an ETI {period} band has no lower/upper bound configured")
        lo, hi = _dec(lo_raw), _dec(hi_raw)
        if lo <= remuneration < hi:
            matches.append((row, lo, hi))
    if len(matches) > 1:
        pack.block("za_eti_band", f"{len(matches)} ETI {period} bands match remuneration {remuneration} — "
                                   "the band table is ambiguous")
    return matches[0] if matches else None


def compute_eti(*, claim_month_end, date_of_birth, hire_date, eligible_flag, employer_registered,
                paid_hours, remuneration, qualifying_month_no, pack, slabs, rnd) -> dict:
    """Evaluate ETI for one employee and one claim month. See the module
    docstring for the check order and the PENDING_G1 notes."""
    month_end = _as_date(claim_month_end)
    month_no = None if qualifying_month_no in (None, "") else int(qualifying_month_no)

    if employer_registered is None:
        return _result(BLOCKED, reason="employer ETI registration status is not recorded",
                       month_no=month_no, rnd=rnd)
    if employer_registered is not True:
        return _result(NOT_REGISTERED, reason="employer is not recorded as ETI-registered",
                       month_no=month_no, rnd=rnd)
    if eligible_flag is None:
        return _result(BLOCKED, reason="no ETI eligibility evidence recorded (za_eti_eligible)",
                       month_no=month_no, rnd=rnd)
    if eligible_flag is not True:
        return _result(INELIGIBLE, reason="no ETI eligibility evidence (za_eti_eligible)",
                       month_no=month_no, rnd=rnd)

    born = _as_date(date_of_birth)
    hired = _as_date(hire_date)
    missing = [name for name, value in (
        ("claim month end", month_end), ("date of birth", born), ("hire date", hired),
        ("paid hours", paid_hours), ("remuneration", remuneration), ("qualifying month number", month_no),
    ) if value is None]
    if missing:
        return _result(BLOCKED, reason="missing " + ", ".join(missing), month_no=month_no, rnd=rnd)

    hours = _dec(paid_hours)
    pay = _dec(remuneration)
    if hours <= ZERO:
        return _result(BLOCKED, reason="paid hours must be greater than zero",
                       month_no=month_no, paid_hours=hours, remuneration=pay, rnd=rnd)
    if pay < ZERO:
        return _result(BLOCKED, reason="remuneration is negative", month_no=month_no,
                       paid_hours=hours, remuneration=pay, rnd=rnd)

    min_age = int(pack.require_amount("za_eti_min_age"))
    max_age = int(pack.require_amount("za_eti_max_age"))
    age = _age_on(born, month_end)
    if age < min_age or age > max_age:
        return _result(INELIGIBLE, reason=f"age {age} at {month_end} is outside the ETI window "
                                          f"{min_age}..{max_age}", month_no=month_no,
                       paid_hours=hours, remuneration=pay, rnd=rnd)

    max_months = int(pack.require_amount("za_eti_qualifying_months_max"))
    if month_no < 1:
        return _result(BLOCKED, reason="qualifying month number must be at least 1", month_no=month_no,
                       paid_hours=hours, remuneration=pay, rnd=rnd)
    if month_no > max_months:
        return _result(INELIGIBLE, reason=f"qualifying month {month_no} exceeds the maximum {max_months}",
                       month_no=month_no, paid_hours=hours, remuneration=pay, rnd=rnd)

    hourly = pay / hours
    nmw = pack.require_amount("za_nmw_hourly")
    if hourly < nmw:
        return _result(INELIGIBLE, reason=f"hourly remuneration {hourly} is below the national minimum "
                                          f"wage {nmw}", month_no=month_no, paid_hours=hours,
                       remuneration=pay, rnd=rnd)

    period = FIRST_12 if month_no <= 12 else SECOND_12
    normaliser = pack.require_amount("za_eti_hours_normaliser")
    if normaliser <= ZERO:
        pack.block("za_eti_hours_normaliser", "the ETI hours normaliser must be greater than zero")
    if hours < normaliser:
        normalised = pay * normaliser / hours
    else:
        normalised = pay

    selected = _select_band(slabs, period, normalised, pack)
    if selected is None:
        return _result(ELIGIBLE, reason="no ETI band matches the normalised remuneration — zero incentive",
                       month_no=month_no, period=period, paid_hours=hours, remuneration=pay,
                       normalised=normalised, rnd=rnd)
    row, lo, hi = selected
    formula = (getattr(row, "tax_regime", None) or "").upper()
    if formula not in _content.ETI_FORMULAS:
        pack.block("za_eti_band", f"unknown ETI formula {formula!r} in the {period} band")
    rate = getattr(row, "rate_pct", None)
    flat = getattr(row, "flat_amount", None)
    if formula in ("PCT", "TAPER") and rate is None:
        pack.block("za_eti_band", f"the {period} {formula} band has no rate configured")
    if formula in ("FLAT", "TAPER") and flat is None:
        pack.block("za_eti_band", f"the {period} {formula} band has no flat amount configured")
    rate = _dec(rate)
    flat = _dec(flat)

    if formula == "PCT":
        amount = normalised * rate / HUNDRED
    elif formula == "FLAT":
        amount = flat
    else:  # TAPER
        amount = flat - (normalised - lo) * rate / HUNDRED
    if hours < normaliser:
        amount = amount * hours / normaliser
    amount = rnd(max(amount, ZERO))

    band = {"period": period, "formula": formula, "min": str(lo), "max": str(hi)}
    return _result(ELIGIBLE, month_no=month_no, period=period, paid_hours=hours, remuneration=pay,
                   normalised=normalised, band=band, amount=amount, rnd=rnd)
