"""Hong Kong MPF mandatory contributions (ZP-HK-ENG-001 §5, MPFA S3).

Order (spec §5): coverage → enrolment timing (60-day rule) → contribution
holiday → relevant income → employer / employee shares. Coverage is NEVER
inferred from full-time/part-time status (HK-004).

Official rules applied (MPFA "Mandatory Contributions — Employees" / "MPF
Coverage"; SourceArtifact rows seeded by scripts/seed_hong_kong_canonical_pack.py):
  * regular employee = aged 18 to 64, employed continuously for 60 days or
    more, unless an exempt person;
  * employer 5% of relevant income from the FIRST day of employment once the
    60-day condition is met, capped at the maximum level; no employer
    holiday; employer pays 5% even below the minimum level;
  * employee: nil below the minimum level, 5% between, fixed at 5% of the
    maximum above it; no contribution for the first 30 days of employment
    and any incomplete wage period immediately following them;
  * monthly levels HK$7,100 / HK$30,000; non-monthly wage periods use the
    daily levels HK$280 / HK$1,000 × days in the wage period;
  * first contribution due on or before the contribution day (10th) of the
    month after the calendar month in which the 60th day of employment falls.

Disclosed fail-closed branches (BLOCK instead of guessing):
  * the 18th or 65th birthday inside the contribution period (apportionment
    rule not in the certified content);
  * domestic employees, casual Industry Scheme employees and contractors —
    out of the first-release scope (spec §1);
  * an exemption code without evidence, or contradicting the worker facts.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, add_months, age_on, cents, dec, days_inclusive,
    rate_value, row_ref, text_value,
)

EXEMPTION_CODES = (
    "NONE", "EXEMPT_AGE", "EXEMPT_DOMESTIC", "EXEMPT_STATUTORY_SCHEME", "EXEMPT_ORSO",
    "EXEMPT_INBOUND", "INDUSTRY_SCHEME_SPECIAL",
)
# Exempt states that need recorded evidence (the fact cannot be derived).
_EVIDENCE_REQUIRED = ("EXEMPT_STATUTORY_SCHEME", "EXEMPT_ORSO", "EXEMPT_INBOUND")
_OUT_OF_SCOPE_RELATIONSHIPS = {
    "DOMESTIC": "domestic-helper payroll needs its own certified package (ZP-HK-ENG-001 §1)",
    "CASUAL_INDUSTRY": "construction/catering casual Industry Scheme is gated until separately certified (§1, §5)",
    "CONTRACTOR_REVIEW": "a contractor is not payrolled as an employee — separate product scope (§1)",
}
MONTHLY_FREQUENCIES = ("Monthly",)


def mpf_parameters(rate_map: dict) -> dict:
    """Every MPF statutory value from the pinned pack — fail-closed."""
    params, refs = {}, {}
    for key, side in (("mpf_employee_rate", "employee"), ("mpf_employer_rate", "employer")):
        params[key], row = rate_value(rate_map, key, side=side)
        refs[key] = row_ref(row)
    for key in ("mpf_min_relevant_income_monthly", "mpf_max_relevant_income_monthly",
                "mpf_min_relevant_income_daily", "mpf_max_relevant_income_daily",
                "mpf_regular_employee_min_age", "mpf_regular_employee_max_age",
                "mpf_regular_employee_days", "mpf_employee_holiday_days", "mpf_contribution_day",
                "mpf_inbound_exempt_months"):
        params[key], row = rate_value(rate_map, key)
        refs[key] = row_ref(row)
    params["partial_month_basis"], row = text_value(rate_map, "mpf_partial_month_threshold_basis")
    refs["mpf_partial_month_threshold_basis"] = row_ref(row)
    return {"values": params, "refs": refs}


def employment_start(facts: dict) -> date:
    start = facts.get("employmentContinuityStart") or facts.get("dateOfJoining")
    if not start:
        raise HongKongCalculationBlockedError("date_of_joining", "the employment start date is required for the MPF 60-day rule")
    return date.fromisoformat(str(start)[:10])


def sixty_day_date(start: date, regular_days: int) -> date:
    """The day the employee has been employed for `regular_days` days
    (start counts as day 1): 16 Jan 2026 → 16 Mar 2026 for 60 days."""
    return start + timedelta(days=regular_days - 1)


def holiday_end(start: date, holiday_days: int) -> date:
    """Last day of the employee's 30-day contribution holiday."""
    return start + timedelta(days=holiday_days - 1)


def employee_holiday_applies(period_start: date, period_end: date, start: date, holiday_days: int) -> bool:
    """True when the whole wage period is inside the holiday: the first 30
    days, plus the incomplete wage period that immediately follows them
    (MPFA). A wage period that begins after day 30 contributes."""
    return period_start <= holiday_end(start, holiday_days)


def first_contribution_day(sixty_day: date, contribution_day: int) -> date:
    """On or before the contribution day of the month after the month in
    which the 60th day falls (statutory extension for non-working /
    suspension days is not modelled — disclosed in the trace)."""
    nxt = add_months(sixty_day.replace(day=1), 1)
    return nxt.replace(day=contribution_day)


def period_contribution_day(period_end: date, contribution_day: int) -> date:
    return add_months(period_end.replace(day=1), 1).replace(day=contribution_day)


def resolve_coverage(facts: dict, period_start: date, period_end: date, params: dict) -> dict:
    """MPF coverage for one contribution period. Returns
    {status, exemptionCode, reason, employmentStart, sixtyDayDate, ...}.
    status: COVERED | PENDING_60_DAY | NOT_COVERED_LEFT_BEFORE_60_DAYS | EXEMPT."""
    v = params["values"]
    relationship = facts.get("employmentRelationship") or "EMPLOYEE"
    if relationship in _OUT_OF_SCOPE_RELATIONSHIPS:
        raise HongKongCalculationBlockedError("employment_relationship", _OUT_OF_SCOPE_RELATIONSHIPS[relationship])
    if relationship != "EMPLOYEE":
        raise HongKongCalculationBlockedError("employment_relationship", f"unknown employment relationship {relationship!r}")

    code = facts.get("mpfExemptionCode") or "NONE"
    if code not in EXEMPTION_CODES:
        raise HongKongCalculationBlockedError("mpf_exemption_code", f"unknown MPF exemption code {code!r}")
    if code == "INDUSTRY_SCHEME_SPECIAL":
        raise HongKongCalculationBlockedError("mpf_exemption_code", _OUT_OF_SCOPE_RELATIONSHIPS["CASUAL_INDUSTRY"])
    if code == "EXEMPT_DOMESTIC":
        raise HongKongCalculationBlockedError("mpf_exemption_code", _OUT_OF_SCOPE_RELATIONSHIPS["DOMESTIC"])

    dob = facts.get("dateOfBirth")
    if not dob:
        raise HongKongCalculationBlockedError("date_of_birth", "date of birth is required to decide MPF coverage (18–64)")
    dob = date.fromisoformat(str(dob)[:10])
    min_age, max_age = int(v["mpf_regular_employee_min_age"]), int(v["mpf_regular_employee_max_age"])
    age_start, age_end = age_on(dob, period_start), age_on(dob, period_end)
    start = employment_start(facts)
    out = {
        "employmentStart": start.isoformat(), "ageAtPeriodStart": age_start, "ageAtPeriodEnd": age_end,
        "exemptionCode": code,
    }
    in_range = lambda a: min_age <= a <= max_age  # noqa: E731
    if in_range(age_start) != in_range(age_end):
        raise HongKongCalculationBlockedError(
            "mpf_age_boundary",
            f"the employee turns {min_age if age_end == min_age else max_age + 1} within this contribution period — "
            "the apportionment of relevant income around the age boundary is not in the certified content",
        )
    if not in_range(age_start):
        # Age alone decides, whatever other exemption is also recorded.
        return {**out, "status": "EXEMPT", "exemptionCode": "EXEMPT_AGE",
                "reason": f"aged {age_start}: outside the regular-employee age range {min_age}–{max_age}"}
    if code == "EXEMPT_AGE":
        raise HongKongCalculationBlockedError(
            "mpf_exemption_code", f"EXEMPT_AGE is recorded but the employee is aged {age_start} (within {min_age}–{max_age})")
    if code in _EVIDENCE_REQUIRED:
        if not facts.get("mpfExemptionEvidenceRef"):
            raise HongKongCalculationBlockedError(
                "mpf_exemption_evidence", f"{code} needs recorded evidence (certificate / permission / scheme membership)")
        if code == "EXEMPT_INBOUND":
            _check_inbound(facts, period_end, int(v["mpf_inbound_exempt_months"]))
        return {**out, "status": "EXEMPT", "reason": facts.get("mpfExemptionReason") or code,
                "evidenceRef": facts.get("mpfExemptionEvidenceRef")}

    regular_days = int(v["mpf_regular_employee_days"])
    sixty = sixty_day_date(start, regular_days)
    out.update({"sixtyDayDate": sixty.isoformat(),
                "firstContributionDay": first_contribution_day(sixty, int(v["mpf_contribution_day"])).isoformat()})
    termination = facts.get("terminationDate")
    termination = date.fromisoformat(str(termination)[:10]) if termination else None
    if termination and termination < sixty:
        return {**out, "status": "NOT_COVERED_LEFT_BEFORE_60_DAYS",
                "employmentDays": days_inclusive(start, termination),
                "reason": (f"employment {start} – {termination} is {days_inclusive(start, termination)} days, fewer than "
                           f"{regular_days}: not a regular employee, no MPF liability is manufactured (HK-008)")}
    if period_end < sixty:
        return {**out, "status": "PENDING_60_DAY",
                "reason": f"the {regular_days}-day condition is not met until {sixty}; contributions accrue from the "
                          "first day and become due once it is met"}
    return {**out, "status": "COVERED", "reason": f"regular employee from {start} (60th day {sixty})"}


def _check_inbound(facts: dict, period_end: date, exempt_months: int) -> None:
    """EXEMPT_INBOUND: entered HK for employment for not more than the statutory
    13 months, or a member of an overseas retirement scheme (MPFA exempt
    persons). The month count is the pack row, not a literal."""
    if facts.get("overseasSchemeMember"):
        return
    if not facts.get("enteredForEmployment"):
        raise HongKongCalculationBlockedError(
            "mpf_exemption_code", "EXEMPT_INBOUND needs either overseas-scheme membership or entry for employment")
    arrival, until = facts.get("arrivalDate"), facts.get("permissionToStayUntil")
    if not arrival or not until:
        raise HongKongCalculationBlockedError(
            "mpf_exemption_code", "EXEMPT_INBOUND (13-month rule) needs the arrival date and permission-to-stay end date")
    arrival, until = date.fromisoformat(str(arrival)[:10]), date.fromisoformat(str(until)[:10])
    limit = add_months(arrival, exempt_months) - timedelta(days=1)
    if until > limit or period_end > limit:
        raise HongKongCalculationBlockedError(
            "mpf_exemption_code",
            f"permission to stay runs to {until} — beyond {exempt_months} months from arrival ({limit}); the inbound "
            "exemption ceases after the 13th month and enrolment is due within 60 days (MPFA)")


def thresholds(params: dict, pay_frequency: str, period_start: date, period_end: date) -> dict:
    """(min, max) relevant-income levels for the wage period."""
    v = params["values"]
    if (pay_frequency or "Monthly") in MONTHLY_FREQUENCIES:
        return {"basis": "MONTHLY", "min": v["mpf_min_relevant_income_monthly"],
                "max": v["mpf_max_relevant_income_monthly"], "days": None,
                "partialMonthBasis": v["partial_month_basis"]}
    days = days_inclusive(period_start, period_end)
    return {"basis": "DAILY_X_DAYS", "days": days,
            "min": v["mpf_min_relevant_income_daily"] * days, "max": v["mpf_max_relevant_income_daily"] * days}


def contributions(relevant_income: Decimal, params: dict, levels: dict, employee_on_holiday: bool) -> dict:
    """Employer / employee mandatory contributions for ONE period's relevant
    income. Rounded half-up to the cent (disclosed: rounding convention is a
    G1 certification item)."""
    v = params["values"]
    ri = dec(relevant_income)
    lo, hi = levels["min"], levels["max"]
    capped = min(ri, hi)
    employer = cents(capped * v["mpf_employer_rate"])
    if ri > hi:
        branch = "ABOVE_MAXIMUM"
    elif ri < lo:
        branch = "BELOW_MINIMUM"
    else:
        branch = "WITHIN_LEVELS"
    if employee_on_holiday:
        employee, employee_basis = ZERO, "CONTRIBUTION_HOLIDAY"
    elif branch == "BELOW_MINIMUM":
        employee, employee_basis = ZERO, "BELOW_MINIMUM_NIL"
    else:
        employee, employee_basis = cents(capped * v["mpf_employee_rate"]), "MANDATORY"
    return {"relevantIncome": str(cents(ri)), "branch": branch, "minLevel": str(lo), "maxLevel": str(hi),
            "employer": str(employer), "employee": str(employee), "employeeBasis": employee_basis}
