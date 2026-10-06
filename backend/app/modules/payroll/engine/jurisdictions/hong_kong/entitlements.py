"""Employment Ordinance statutory entitlements (ZP-HK-ENG-001 §9; Labour
Department Concise Guide chapters 4–7, SourceArtifacts ld_cg_04..07).

Every entitlement amount is (days × a rate from the ONE average-wage engine,
average_wage.calculate). Every statutory number (leave scale, sickness accrual
rates and cap, maternity weeks and the HK$80,000 cap for weeks 11–14,
paternity days, eligibility periods) is a pack row. Eligibility that depends
on continuous-contract length reads continuous_contract.resolve's result.

Statuses: ENTITLED / NOT_ENTITLED (with the failed condition), CALCULATED
amounts — never a paid amount without its eligibility trace.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, add_months, cents, dec, fraction_value, rate_value, row_ref,
)
from app.modules.payroll.engine.jurisdictions.hong_kong.continuous_contract import continuous_for_at_least

ANNUAL_LEAVE_SCALE = "HK_ANNUAL_LEAVE_SCALE"
STATUTORY_HOLIDAY = "HK_STATUTORY_HOLIDAY"


def _param(rate_map, key):
    if key == "eo_four_fifths_factor":
        value, row = fraction_value(rate_map, key)
    else:
        value, row = rate_value(rate_map, key)
    return value, row_ref(row)


def statutory_holidays(slabs: list, year: int) -> list:
    """The year's statutory holidays from pack rows (rule_type
    HK_STATUTORY_HOLIDAY: filing_status = the calendar year, tax_formula = the
    ISO date, rate_label = the name). BLOCKS if the pack has no calendar for
    that year."""
    rows = [s for s in slabs or [] if getattr(s, "rule_type", None) == STATUTORY_HOLIDAY
            and str(getattr(s, "filing_status", "")) == str(year)]
    if not rows:
        raise HongKongCalculationBlockedError(
            "statutory_holiday_calendar", f"the rule pack has no statutory-holiday calendar for {year}")
    return [{"date": r.tax_formula, "name": r.rate_label, "ref": row_ref(r)}
            for r in sorted(rows, key=lambda r: r.tax_formula)]


def annual_leave_days(slabs: list, service_year: int) -> tuple:
    """Days for the given completed year of continuous-contract service
    (1st → 7 … 9th or later → 14). rule_type HK_ANNUAL_LEAVE_SCALE:
    min_amount = service year, max_amount = NULL for the open top band,
    flat_amount = days."""
    if service_year < 1:
        return 0, None
    rows = [s for s in slabs or [] if getattr(s, "rule_type", None) == ANNUAL_LEAVE_SCALE]
    for r in sorted(rows, key=lambda r: r.min_amount):
        if dec(r.min_amount) <= service_year and (r.max_amount is None or service_year <= dec(r.max_amount)):
            return int(dec(r.flat_amount)), row_ref(r)
    raise HongKongCalculationBlockedError("annual_leave_scale", f"no annual-leave scale row for service year {service_year}")


def paid_sickness_days_accrued(rate_map: dict, continuous_since: date, as_of: date) -> dict:
    """Paid sickness days accumulated: 2 per completed month in the first
    `eo_sickness_first_year_months` months, 4 per completed month thereafter,
    never more than 120 at any time."""
    first_rate, r1 = _param(rate_map, "eo_sickness_days_per_month_first_year")
    later_rate, r2 = _param(rate_map, "eo_sickness_days_per_month_after")
    cap, r3 = _param(rate_map, "eo_sickness_days_cap")
    first_year_months, r0 = _param(rate_map, "eo_sickness_first_year_months")
    months = 0
    while add_months(continuous_since, months + 1) <= as_of:
        months += 1
    first = min(months, int(first_year_months))
    later = max(months - int(first_year_months), 0)
    accrued = min(Decimal(first) * first_rate + Decimal(later) * later_rate, cap)
    whole = lambda v: f"{v.normalize():f}"  # noqa: E731 — sickness days are whole days
    return {"completedMonths": months, "firstYearMonths": int(first_year_months),
            "accrued": whole(accrued), "cap": whole(cap), "refs": [r0, r1, r2, r3]}


def sickness_allowance(rate_map: dict, cc: dict, average: dict, sickness_days: int, consecutive_days: int,
                       medically_certified: bool, available_paid_days: Decimal, pregnancy_related: bool = False) -> dict:
    min_consecutive, ref_min = _param(rate_map, "eo_sickness_min_consecutive_days")
    factor, ref_f = _param(rate_map, "eo_four_fifths_factor")
    failed = []
    if cc.get("status") != "CONTINUOUS":
        failed.append("not employed under a continuous contract")
    if not pregnancy_related and consecutive_days < int(min_consecutive):
        failed.append(f"sick leave of {consecutive_days} consecutive day(s) is less than {int(min_consecutive)}")
    if not medically_certified:
        failed.append("no appropriate medical certificate")
    paid_days = min(Decimal(sickness_days), dec(available_paid_days))
    if paid_days <= ZERO:
        failed.append("no accumulated paid sickness days available")
    out = {"benefit": "SICKNESS_ALLOWANCE", "refs": [ref_min, ref_f], "averageDailyWage": average["averageDailyWage"]}
    if failed:
        return {**out, "status": "NOT_ENTITLED", "failedConditions": failed, "amount": "0.00"}
    rate = dec(average["averageDailyWage"]) * factor
    return {**out, "status": "ENTITLED", "paidDays": str(paid_days), "dailyRate": str(cents(rate)),
            "amount": str(cents(rate * paid_days)),
            "unpaidDays": str(Decimal(sickness_days) - paid_days)}


def holiday_pay(rate_map: dict, cc: dict, average: dict, holiday_date: date) -> dict:
    months, ref = _param(rate_map, "eo_holiday_pay_cc_months")
    eligible = continuous_for_at_least(cc, holiday_date, months=int(months))
    out = {"benefit": "HOLIDAY_PAY", "holidayDate": holiday_date.isoformat(), "refs": [ref]}
    if not eligible:
        return {**out, "status": "NOT_ENTITLED", "amount": "0.00", "failedConditions": [
            f"not under a continuous contract for {int(months)} months immediately preceding the holiday "
            "(the holiday itself is still granted; only the pay is not due)"]}
    return {**out, "status": "ENTITLED", "amount": str(cents(dec(average["averageDailyWage"])))}


def annual_leave_pay(average: dict, days: Decimal) -> dict:
    return {"benefit": "ANNUAL_LEAVE_PAY", "status": "ENTITLED", "days": str(days),
            "dailyRate": str(cents(dec(average["averageDailyWage"]))),
            "amount": str(cents(dec(average["averageDailyWage"]) * dec(days)))}


def maternity_leave_pay(rate_map: dict, cc: dict, average: dict, leave_start: date, notice_given: bool) -> dict:
    weeks, r1 = _param(rate_map, "eo_maternity_leave_weeks")
    cc_weeks, r2 = _param(rate_map, "eo_maternity_pay_cc_weeks")
    cap_11_14, r3 = _param(rate_map, "eo_maternity_weeks_11_14_cap")
    factor, r4 = _param(rate_map, "eo_four_fifths_factor")
    full_pay_weeks, r5 = _param(rate_map, "eo_maternity_full_pay_weeks")
    if int(full_pay_weeks) >= int(weeks):
        raise HongKongCalculationBlockedError(
            "eo_maternity_full_pay_weeks",
            f"{int(full_pay_weeks)} fully paid weeks does not leave any reduced-pay weeks inside the "
            f"{int(weeks)}-week maternity leave")
    out = {"benefit": "MATERNITY_LEAVE_PAY", "leaveWeeks": str(weeks),
           "fullyPaidWeeks": str(int(full_pay_weeks)), "refs": [r1, r2, r3, r4, r5]}
    failed = []
    if not continuous_for_at_least(cc, leave_start, weeks=int(cc_weeks)):
        failed.append(f"not under a continuous contract for {int(cc_weeks)} weeks immediately before the scheduled leave")
    if not notice_given:
        failed.append("notice of pregnancy / intention to take maternity leave not recorded")
    if failed:
        return {**out, "status": "NOT_ENTITLED", "failedConditions": failed, "amount": "0.00"}
    daily = dec(average["averageDailyWage"]) * factor
    fully_paid_days = int(full_pay_weeks) * 7
    first_10 = cents(daily * fully_paid_days)
    weeks_11_14_raw = cents(daily * (int(weeks) - int(full_pay_weeks)) * 7)
    weeks_11_14 = min(weeks_11_14_raw, cap_11_14)
    return {**out, "status": "ENTITLED", "dailyRate": str(cents(daily)),
            "weeks1to10": str(first_10), "weeks11to14": str(weeks_11_14),
            "weeks11to14Uncapped": str(weeks_11_14_raw), "weeks11to14Cap": str(cap_11_14),
            "reimbursableByGovernment": str(weeks_11_14),
            "amount": str(first_10 + weeks_11_14)}


def paternity_leave_pay(rate_map: dict, cc: dict, average: dict, leave_date: date, days: int,
                        document_provided: bool) -> dict:
    max_days, r1 = _param(rate_map, "eo_paternity_leave_days")
    cc_weeks, r2 = _param(rate_map, "eo_paternity_pay_cc_weeks")
    factor, r3 = _param(rate_map, "eo_four_fifths_factor")
    out = {"benefit": "PATERNITY_LEAVE_PAY", "refs": [r1, r2, r3]}
    if days > int(max_days):
        raise HongKongCalculationBlockedError(
            "paternity_leave_days", f"{days} days requested; the statutory entitlement is {int(max_days)} days")
    failed = []
    if not continuous_for_at_least(cc, leave_date, weeks=int(cc_weeks)):
        failed.append(f"not under a continuous contract for {int(cc_weeks)} weeks immediately before the leave day")
    if not document_provided:
        failed.append("required document (statement / birth evidence) not yet provided")
    if failed:
        return {**out, "status": "NOT_ENTITLED", "failedConditions": failed, "amount": "0.00"}
    daily = dec(average["averageDailyWage"]) * factor
    return {**out, "status": "ENTITLED", "days": days, "dailyRate": str(cents(daily)),
            "amount": str(cents(daily * days))}
