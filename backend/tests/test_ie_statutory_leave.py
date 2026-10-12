"""
tests/test_ie_statutory_leave.py
--------------------------------
ZP-IE-ENG-001 Phase 4 — Irish statutory leave and public-holiday content.

Three things are covered here, and the boundary between them is the point of
the file:

1. ``calculate_statutory_sick_pay()`` in engine/countries/ireland.py — the
   §11 / IE-037 entitlement itself: 5 days per CALENDAR year, 13 weeks' service,
   medical certification, 70% of usual daily earnings capped at EUR 110/day.
2. The Irish statutory public-holiday calendar, including the one date rule no
   existing rule type could express (St Brigid's Day) and the deliberate
   ABSENCE of any weekend substitute-day shifting.
3. That the assessment lands in ``IrelandStatutorySickLeaveRecord`` with the
   full IE-037 evidence — and that it does so only behind
   ``_IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES``, which ships EMPTY.

That last point is a deliberate, tested product decision, not an omission. The
entitlement is implemented and proven, but the payroll MECHANIC (how the credit
interacts with the pay the employee would otherwise have received, and when the
calendar-year counter resets) is a G5 question. The switch test below is the
regression guard that stops a later edit quietly turning statutory sick pay
into a live change to Irish net pay.
"""

from datetime import date
from decimal import Decimal

import pytest

ZERO = Decimal("0")

from app.modules.payroll import service
from app.modules.payroll.engine.countries import shared as shared_module
from app.modules.payroll.engine.countries.ireland import (
    IrelandCalculationBlockedError,
    build_rate_pack,
    calculate_statutory_sick_pay,
    statutory_sick_weeks_service,
)
from app.modules.payroll.models import (
    ContributionRate,
    IrelandStatutorySickLeaveRecord,
    PayrollEmployee,
    PayrollLeaveRequest,
    PayrollRun,
    PayslipItem,
    PayslipStatus,
    PayrollStatus,
    TaxSlab,
)

# Mirrors tests/test_engine_ireland.py's Rate stub.
class Rate:
    def __init__(self, flat_amount=None, employee_rate_pct=None, employer_rate_pct=None,
                 effective_from=None, effective_to=None, text_value=None):
        self.flat_amount = None if flat_amount is None else Decimal(str(flat_amount))
        self.employee_rate_pct = None if employee_rate_pct is None else Decimal(str(employee_rate_pct))
        self.employer_rate_pct = None if employer_rate_pct is None else Decimal(str(employer_rate_pct))
        self.effective_from = effective_from
        self.effective_to = effective_to
        self.text_value = text_value


# 2026 signed values: 5 days, 70%, EUR 110/day cap, 13 weeks' service.
SICK_PACK_2026 = {
    "ie_sick_leave_days": Rate(flat_amount=5),
    "ie_sick_leave_pct": Rate(employee_rate_pct=70),
    "ie_sick_leave_daily_cap": Rate(flat_amount=110),
    "ie_sick_leave_service_weeks": Rate(flat_amount=13),
}

# Long-serving employee so the service test does not need two years of history.
LONG_SERVICE_START = date(2024, 1, 1)
ABSENCE_START = date(2026, 6, 1)


def _assess(**overrides):
    kwargs = dict(
        pack=build_rate_pack(SICK_PACK_2026, None),
        usual_daily_earnings=Decimal("100"),
        days_claimed=Decimal("2"),
        service_start_date=LONG_SERVICE_START,
        absence_start_date=ABSENCE_START,
        absence_end_date=date(2026, 6, 2),
        certified=True,
    )
    kwargs.update(overrides)
    return calculate_statutory_sick_pay(**kwargs)


# ── 1. The entitlement calculation ───────────────────────────────────────

def test_uncapped_rate_is_seventy_percent_of_usual_daily_earnings():
    result = _assess(usual_daily_earnings=Decimal("100"), days_claimed=Decimal("2"))
    assert result["eligible"] is True
    assert result["cap_applied"] is False
    assert result["daily_rate"] == Decimal("70.0")
    assert result["amount"] == Decimal("140.00")


def test_daily_cap_binds_and_is_recorded_before_and_after():
    result = _assess(usual_daily_earnings=Decimal("200"), days_claimed=Decimal("3"))
    assert result["eligible"] is True
    assert result["cap_applied"] is True
    # 70% of 200 is 140, capped to 110 — and the uncapped figure is retained
    # so the arithmetic behind the capped amount stays auditable (IE-037).
    assert result["daily_rate_before_cap"] == Decimal("140.0")
    assert result["daily_rate"] == Decimal("110")
    assert result["amount"] == Decimal("330.00")


def test_cap_boundary_exactly_at_cap_is_not_flagged_as_capped():
    # 70% of X == 110 exactly when X == 157.142857...; use a clean case where
    # the rate lands precisely on the cap instead.
    result = _assess(usual_daily_earnings=Decimal("1100") / Decimal("7"), days_claimed=Decimal("1"))
    assert result["daily_rate"] == Decimal("110")
    assert result["cap_applied"] is False


def test_exactly_thirteen_weeks_of_service_qualifies():
    # 13 weeks before 2026-06-01 is 2026-03-02.
    result = _assess(service_start_date=date(2026, 3, 2), days_claimed=Decimal("1"))
    assert result["service_weeks_satisfied"] is True
    assert result["eligible"] is True


def test_one_day_short_of_thirteen_weeks_is_disallowed():
    result = _assess(service_start_date=date(2026, 3, 3), days_claimed=Decimal("1"))
    assert result["service_weeks_satisfied"] is False
    assert result["eligible"] is False
    assert result["days_credited"] == Decimal("0")
    assert result["days_disallowed"] == Decimal("1")
    assert "service_qualification_not_met" in result["reason"]


def test_missing_service_start_date_is_not_treated_as_zero_service():
    # Failing closed on missing EVIDENCE, not on a computed zero.
    result = _assess(service_start_date=None, days_claimed=Decimal("1"))
    assert result["service_weeks_actual"] is None
    assert result["eligible"] is False
    assert "evidence is missing" in result["reason"]


def test_uncertified_absence_is_disallowed_even_when_otherwise_qualified():
    result = _assess(certified=False, days_claimed=Decimal("1"))
    assert result["eligible"] is False
    assert "certification_missing" in result["reason"]
    assert result["days_disallowed"] == Decimal("1")


def test_entitlement_is_exhausted_after_five_credited_days_in_the_calendar_year():
    result = _assess(days_taken_in_calendar_year=Decimal("5"), days_claimed=Decimal("1"))
    assert result["eligible"] is False
    assert "entitlement_exhausted" in result["reason"]


def test_claim_beyond_the_remaining_entitlement_is_partly_allowed():
    result = _assess(days_taken_in_calendar_year=Decimal("4"), days_claimed=Decimal("3"))
    assert result["eligible"] is True
    assert result["days_credited"] == Decimal("1")
    assert result["days_disallowed"] == Decimal("2")
    # The amount must cover the credited days only, never the disallowed ones.
    assert result["amount"] == Decimal("70.00")
    assert "partially_allowed" in result["reason"]


def test_calendar_year_is_taken_from_the_first_day_of_absence():
    # The pure function deliberately has no year arithmetic of its own: it is
    # given the counter for the year being claimed, because the CALLER is what
    # scopes that counter (service._ie_sick_days_taken_in_calendar_year filters
    # on record.calendar_year). Feeding it a fresh year therefore means a fresh
    # counter, and 2027's entitlement is a full 5 days.
    result = _assess(
        absence_start_date=date(2027, 1, 4),
        days_taken_in_calendar_year=ZERO,
        days_claimed=Decimal("2"),
    )
    assert result["eligible"] is True
    assert result["calendar_year"] == 2027
    assert result["days_credited"] == Decimal("2")
    assert result["entitlement_remaining_before"] == Decimal("5")


def test_a_counter_already_exhausted_within_the_same_year_disallows_further_days():
    # The other half of the same discipline: a used-up counter passed in for the
    # year being claimed really does block, and 70% of nothing is never paid.
    result = _assess(
        absence_start_date=date(2027, 6, 1),
        days_taken_in_calendar_year=Decimal("5"),
        days_claimed=Decimal("2"),
    )
    assert result["eligible"] is False
    assert "entitlement_exhausted" in result["reason"]
    assert result["days_credited"] == ZERO
    assert result["days_disallowed"] == Decimal("2")
    assert result["amount"] == ZERO


def test_missing_usual_daily_earnings_is_not_treated_as_zero_earnings():
    # 70% of nothing must never become a genuine entitlement.
    result = _assess(usual_daily_earnings=Decimal("0"), days_claimed=Decimal("1"))
    assert result["eligible"] is False
    assert "usual_daily_earnings_evidence_missing" in result["reason"]


def test_zero_days_claimed_is_a_no_op_not_an_error():
    result = _assess(days_claimed=Decimal("0"))
    assert result["eligible"] is False
    assert result["reason"] == "no_sick_days_claimed"
    assert result["amount"] == Decimal("0")


def test_assessment_reads_every_figure_from_the_pack_not_hardcoded():
    # A deliberately non-2026 pack: if any of 5 / 70 / 110 / 13 were hardcoded,
    # these assertions would fail. This is what makes the whole entitlement
    # re-drivable when the signed content is versioned.
    pack = build_rate_pack({
        "ie_sick_leave_days": Rate(flat_amount=7),
        "ie_sick_leave_pct": Rate(employee_rate_pct=60),
        "ie_sick_leave_daily_cap": Rate(flat_amount=90),
        "ie_sick_leave_service_weeks": Rate(flat_amount=4),
    }, None)
    result = calculate_statutory_sick_pay(
        pack=pack, usual_daily_earnings=Decimal("100"), days_claimed=Decimal("1"),
        service_start_date=date(2026, 5, 1), absence_start_date=date(2026, 6, 1),
    )
    assert result["service_weeks_required"] == Decimal("4")
    assert result["entitlement_days"] == Decimal("7")
    assert result["daily_rate_before_cap"] == Decimal("60.0")
    assert result["daily_rate"] == Decimal("60.0")
    assert result["cap_applied"] is False
    assert result["amount"] == Decimal("60.00")


def test_unsigned_sick_content_blocks_rather_than_defaulting():
    with pytest.raises(IrelandCalculationBlockedError) as exc:
        calculate_statutory_sick_pay(
            pack=build_rate_pack({}, None), usual_daily_earnings=Decimal("100"),
            days_claimed=Decimal("1"), service_start_date=LONG_SERVICE_START,
            absence_start_date=ABSENCE_START,
        )
    assert exc.value.code == "IE_STATUTORY_CONTENT_NOT_CONFIGURED"


def test_partial_content_blocks_only_on_the_keys_the_assessment_uses():
    # An unconfigured tax head must not stop a sick-leave assessment, but a
    # missing sick-leave head must. The probe is registered on the very pack that
    # is then assessed, otherwise this would only prove the assertion helper
    # works and never prove the assessment ignores unrelated gaps.
    pack = build_rate_pack(dict(SICK_PACK_2026), None)
    # Reading an unrelated, unconfigured key registers the gap (and returns
    # ZERO) rather than raising. The probe is on the very pack that is then
    # assessed, otherwise this would only prove the assertion helper works and
    # never prove the assessment ignores unrelated gaps.
    assert pack.amount("ie_lpt_exemption_threshold") == ZERO
    assert "ie_lpt_exemption_threshold" in pack.missing

    result = calculate_statutory_sick_pay(
        pack=pack, usual_daily_earnings=Decimal("100"), days_claimed=Decimal("1"),
        service_start_date=LONG_SERVICE_START, absence_start_date=ABSENCE_START,
    )
    assert result["eligible"] is True

    incomplete = build_rate_pack({"ie_sick_leave_days": Rate(flat_amount=5)}, None)
    with pytest.raises(IrelandCalculationBlockedError):
        calculate_statutory_sick_pay(
            pack=incomplete, usual_daily_earnings=Decimal("100"),
            days_claimed=Decimal("1"), service_start_date=LONG_SERVICE_START,
            absence_start_date=ABSENCE_START,
        )


def test_statutory_sick_weeks_service_is_derived_from_two_real_dates():
    assert statutory_sick_weeks_service(date(2026, 1, 1), date(2026, 6, 1)) == Decimal("151") / Decimal("7")
    assert statutory_sick_weeks_service(date(2026, 1, 1), date(2026, 1, 1)) == Decimal("0")
    assert statutory_sick_weeks_service(date(2026, 6, 1), date(2026, 1, 1)) == Decimal("0")
    assert statutory_sick_weeks_service(None, date(2026, 1, 1)) is None


# ── 2. Public holidays ───────────────────────────────────────────────────

def _ie_holidays(year):
    from app.modules.payroll.service import _DEFAULT_HOLIDAYS_BY_COUNTRY, _resolve_holiday_date
    return {e["name"]: _resolve_holiday_date(e, year) for e in _DEFAULT_HOLIDAYS_BY_COUNTRY["IE"]}


def test_ireland_has_exactly_the_ten_statutory_public_holidays():
    assert len(_ie_holidays(2026)) == 10
    assert set(_ie_holidays(2026)) == {
        "New Year's Day", "St Brigid's Day", "St Patrick's Day", "Easter Monday",
        "May Day", "June Holiday", "August Holiday", "October Holiday",
        "Christmas Day", "St Stephen's Day",
    }


def test_ireland_2026_holiday_dates_derive_from_their_statutory_rules():
    holidays = _ie_holidays(2026)
    assert holidays["New Year's Day"] == date(2026, 1, 1)
    assert holidays["St Brigid's Day"] == date(2026, 2, 2)      # 1 Feb 2026 is a Sunday
    assert holidays["St Patrick's Day"] == date(2026, 3, 17)
    assert holidays["Easter Monday"] == date(2026, 4, 6)        # Easter Sunday 5 Apr
    assert holidays["May Day"] == date(2026, 5, 4)
    assert holidays["June Holiday"] == date(2026, 6, 1)
    assert holidays["August Holiday"] == date(2026, 8, 3)
    assert holidays["October Holiday"] == date(2026, 10, 26)    # LAST Monday
    assert holidays["Christmas Day"] == date(2026, 12, 25)
    assert holidays["St Stephen's Day"] == date(2026, 12, 26)


def test_brigids_day_falls_on_1_february_when_that_is_a_friday():
    # 1 Feb 2030 is a Friday, so the holiday is 1 Feb — NOT the first Monday
    # of that month. This is the conditional no pre-existing rule type could
    # express, which is why "first_monday_unless_friday" exists.
    assert _ie_holidays(2030)["St Brigid's Day"] == date(2030, 2, 1)
    # A non-Friday 1 Feb still resolves to the first Monday.
    assert _ie_holidays(2029)["St Brigid's Day"] == date(2029, 2, 5)


def test_weekend_holidays_are_never_shifted_to_a_substitute_weekday():
    # 2027: Christmas falls on a Saturday and St Stephen's on a Sunday. Ireland
    # has no substitute-day rule, so both stay on their statutory dates and
    # nothing appears on Monday 27 December.
    holidays = _ie_holidays(2027)
    assert holidays["Christmas Day"] == date(2027, 12, 25)
    assert holidays["St Stephen's Day"] == date(2027, 12, 26)
    assert date(2027, 12, 27) not in set(holidays.values())


def test_october_holiday_is_the_last_monday_not_the_first():
    for year in (2026, 2027, 2028):
        october = _ie_holidays(year)["October Holiday"]
        assert october.weekday() == 0
        assert 25 <= october.day <= 31


def test_existing_countries_are_unaffected_by_the_new_rule_type():
    from app.modules.payroll.service import _DEFAULT_HOLIDAYS_BY_COUNTRY, _resolve_holiday_date
    for country in ("IN", "US", "UK", "AU", "CA", "DE"):
        for entry in _DEFAULT_HOLIDAYS_BY_COUNTRY[country]:
            assert _resolve_holiday_date(entry, 2026) is not None
    assert len(_DEFAULT_HOLIDAYS_BY_COUNTRY) == 7


# ── 3. Rollout switch: the assessment is off until G5 ────────────────────

def test_ireland_sick_leave_switch_ships_empty():
    # G5 ("NMW, sick leave, annual/public holiday and sector-rule gating
    # validated for launch cohort") is not evidenced. If this test ever fails
    # because someone enabled it, that is a deliberate act needing the
    # specialist ruling on the payroll mechanism — not a side effect.
    assert shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES == set()


def _make_ie_employee(db, org_id, code="IE-SICK", joined=LONG_SERVICE_START):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="IE", ctc=Decimal("4000"), pay_frequency="Monthly",
        date_of_joining=joined,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _seed_ie_sick_rates(db, org_id):
    rows = [
        ("ie_sick_leave_days", None, Decimal("5")),
        ("ie_sick_leave_pct", Decimal("70"), None),
        ("ie_sick_leave_daily_cap", None, Decimal("110")),
        ("ie_sick_leave_service_weeks", None, Decimal("13")),
    ]
    for key, pct, flat in rows:
        db.add(ContributionRate(
            organization_id=org_id, jurisdiction_country="IE", component_key=key,
            label=key, employee_share=str(pct) if pct else "—",
            employer_share="—", total=str(pct) if pct else str(flat),
            employee_rate_pct=pct, flat_amount=flat,
        ))
    db.commit()


def _make_leave_request(db, org_id, employee_id, leave_type, start_date, end_date):
    days = (end_date - start_date).days + 1
    record = PayrollLeaveRequest(
        organization_id=org_id, employee_id=employee_id, leave_type=leave_type,
        start_date=start_date, end_date=end_date, days=days, status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _approve(db, organization, request_id):
    class _Data:
        status = "approved"
    return service.review_payroll_leave_request(db, request_id, _Data(), organization.id, reviewer_id=1)


def _make_paid_payslip(db, org_id, employee, pay_date, gross_pay):
    run = PayrollRun(
        organization_id=org_id, period_label="History",
        period_start=pay_date, period_end=pay_date, pay_date=pay_date,
        status=PayrollStatus.PAID.value,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=org_id,
        employee_name=employee.name, gross_pay=gross_pay,
        status=PayslipStatus.PAID.value,
    )
    db.add(item)
    db.commit()
    return item


def test_approving_an_ie_sick_request_writes_nothing_while_the_switch_is_off(db, organization):
    _seed_ie_sick_rates(db, organization.id)
    emp = _make_ie_employee(db, organization.id, "IE-OFF1")
    record = _make_leave_request(db, organization.id, emp.id, "sick",
                                 date(2026, 6, 1), date(2026, 6, 2))
    result = _approve(db, organization, record.id)

    assert result["ireStatutorySickLeave"] is None
    assert db.query(IrelandStatutorySickLeaveRecord).filter(
        IrelandStatutorySickLeaveRecord.organization_id == organization.id
    ).count() == 0
    # The pre-existing leave behaviour must be untouched by any of this.
    assert result["status"] == "approved"


def test_switch_on_assesses_the_claim_and_freezes_the_ie037_evidence(db, organization):
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    _seed_ie_sick_rates(db, organization.id)
    emp = _make_ie_employee(db, organization.id, "IE-ON1")
    # Paid on 2026-05-01 for EUR 2000, absence starts 31 days later:
    # usual daily earnings = 2000/31 = 64.52, 70% = 45.16, under the cap.
    _make_paid_payslip(db, organization.id, emp, date(2026, 5, 1), Decimal("2000"))
    record = _make_leave_request(db, organization.id, emp.id, "sick",
                                 date(2026, 6, 1), date(2026, 6, 2))

    result = _approve(db, organization, record.id)
    summary = result["ireStatutorySickLeave"]

    assert summary is not None
    assert summary["calendarYear"] == 2026
    assert summary["daysClaimed"] == 2
    assert summary["absenceStartDate"] == date(2026, 6, 1)
    # No certification evidence exists on a generic leave request, so the claim
    # is assessed as uncertified and disallowed — never silently assumed paid.
    assert summary["certified"] is False
    assert summary["eligible"] is False
    assert "certification_missing" in summary["reason"]
    assert summary["daysCredited"] == 0
    assert summary["daysDisallowed"] == 2
    # The frozen statutory figures are recorded even on a disallowed claim.
    assert summary["entitlementDays"] == Decimal("5")
    assert summary["serviceWeeksRequired"] == Decimal("13")
    assert summary["serviceQualified"] is True
    assert summary["usualDailyEarnings"] is not None


def test_assessment_does_not_change_net_pay_or_payslip_gross(db, organization):
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    _seed_ie_sick_rates(db, organization.id)
    emp = _make_ie_employee(db, organization.id, "IE-NOPAY1")
    _make_paid_payslip(db, organization.id, emp, date(2026, 5, 1), Decimal("2000"))
    record = _make_leave_request(db, organization.id, emp.id, "sick",
                                 date(2026, 6, 1), date(2026, 6, 1))
    _approve(db, organization, record.id)

    rows = db.query(IrelandStatutorySickLeaveRecord).all()
    assert len(rows) == 1
    assert rows[0].amount == Decimal("0")
    # Nothing was written into any payslip by the assessment itself.
    assert all(i.gross_pay == Decimal("2000") for i in db.query(PayslipItem).all())


def test_non_sick_leave_and_non_irish_employees_are_never_assessed(db, organization):
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    _seed_ie_sick_rates(db, organization.id)
    emp = _make_ie_employee(db, organization.id, "IE-OTHER1")
    paid = _make_leave_request(db, organization.id, emp.id, "paid",
                               date(2026, 6, 1), date(2026, 6, 2))
    _approve(db, organization, paid.id)

    uk_emp = PayrollEmployee(
        organization_id=organization.id, employee_code="UK-SICK1", name="UK Employee",
        country_code="UK", ctc=Decimal("3000"), pay_frequency="Monthly",
        date_of_joining=LONG_SERVICE_START,
    )
    db.add(uk_emp)
    db.commit()
    db.refresh(uk_emp)
    uk_record = _make_leave_request(db, organization.id, uk_emp.id, "sick",
                                    date(2026, 6, 1), date(2026, 6, 2))
    _approve(db, organization, uk_record.id)

    assert db.query(IrelandStatutorySickLeaveRecord).count() == 0


def test_calendar_year_counter_sees_earlier_credited_claims(db, organization):
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    _seed_ie_sick_rates(db, organization.id)
    emp = _make_ie_employee(db, organization.id, "IE-CTR1")
    _make_paid_payslip(db, organization.id, emp, date(2026, 5, 1), Decimal("2000"))

    first = _make_leave_request(db, organization.id, emp.id, "sick",
                                date(2026, 6, 1), date(2026, 6, 5))
    _approve(db, organization, first.id)
    # Credit the first claim by hand so the counter has something to exclude;
    # the automatic path always assesses uncertified in this phase.
    row = db.query(IrelandStatutorySickLeaveRecord).filter(
        IrelandStatutorySickLeaveRecord.leave_request_id == first.id
    ).one()
    row.eligible = True
    row.certified = True
    row.days_credited = Decimal("4")
    row.days_disallowed = Decimal("0")
    db.commit()

    second = _make_leave_request(db, organization.id, emp.id, "sick",
                                 date(2026, 7, 1), date(2026, 7, 1))
    _approve(db, organization, second.id)
    second_row = db.query(IrelandStatutorySickLeaveRecord).filter(
        IrelandStatutorySickLeaveRecord.leave_request_id == second.id
    ).one()
    assert second_row.days_taken_before == Decimal("4")
    assert second_row.entitlement_remaining_after == Decimal("1")


def test_reversed_claim_returns_its_days_to_the_counter(db, organization):
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    _seed_ie_sick_rates(db, organization.id)
    emp = _make_ie_employee(db, organization.id, "IE-REV1")
    _make_paid_payslip(db, organization.id, emp, date(2026, 5, 1), Decimal("2000"))

    first = _make_leave_request(db, organization.id, emp.id, "sick",
                                date(2026, 6, 1), date(2026, 6, 5))
    _approve(db, organization, first.id)
    row = db.query(IrelandStatutorySickLeaveRecord).filter(
        IrelandStatutorySickLeaveRecord.leave_request_id == first.id
    ).one()
    row.eligible = True
    row.days_credited = Decimal("5")
    row.status = "REVERSED"
    db.commit()

    second = _make_leave_request(db, organization.id, emp.id, "sick",
                                 date(2026, 7, 1), date(2026, 7, 1))
    _approve(db, organization, second.id)
    second_row = db.query(IrelandStatutorySickLeaveRecord).filter(
        IrelandStatutorySickLeaveRecord.leave_request_id == second.id
    ).one()
    assert second_row.days_taken_before == Decimal("0")


def test_usual_daily_earnings_ignores_unpaid_payslips(db, organization):
    # Only PAID payslips are evidence of ordinary earnings. A pending payslip
    # must not create an entitlement, and a zero gross must not become 70% of 0.
    emp = _make_ie_employee(db, organization.id, "IE-PEND1")
    run = PayrollRun(
        organization_id=organization.id, period_label="Draft",
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 1),
        pay_date=date(2026, 5, 1), status=PayrollStatus.DRAFT.value,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
        employee_name=emp.name, gross_pay=Decimal("2000"),
        status=PayslipStatus.PENDING.value,
    ))
    db.commit()

    assert service._ie_usual_daily_earnings(db, emp.id, date(2026, 6, 1)) is None


def test_unconfigured_employer_gets_the_signed_catalog_and_is_not_blocked(db, organization):
    # Deliberately NO manual seeding. Resolving the sick-leave rows must behave
    # like a payroll run would: seed the Ireland catalog on first access, then
    # assess. An employer who has finished nothing in Compliance must still be
    # able to approve a sick request.
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    emp = _make_ie_employee(db, organization.id, "IE-NOCFG1")
    _make_paid_payslip(db, organization.id, emp, date(2026, 5, 1), Decimal("2000"))
    record = _make_leave_request(db, organization.id, emp.id, "sick",
                                 date(2026, 6, 1), date(2026, 6, 2))
    result = _approve(db, organization, record.id)

    assert result["status"] == "approved"
    assert result["ireStatutorySickLeave"] is not None
    # Still refused, on the certification condition, not on missing content.
    assert result["ireStatutorySickLeave"]["reason"].startswith("certification_missing")


def test_sick_leave_assessment_never_depends_on_configured_tax_slabs(db, organization):
    # The decisive one for the resolver split: statutory sick pay is an
    # entitlement, not a tax case. `_resolve_effective_rate_inputs` refuses to
    # resolve at all until tax SLABS are configured, so calling it from the
    # leave path would have silently skipped every assessment for any employer
    # who has not finished tax configuration. No slabs exist in this test.
    shared_module._IE_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("IE")
    assert db.query(TaxSlab).filter(TaxSlab.jurisdiction_country == "IE").count() == 0

    rate_map = service._ie_rate_map_for_statutory_leave(db, organization.id, date(2026, 6, 1))
    assert "ie_sick_leave_days" in rate_map
    assert "ie_sick_leave_daily_cap" in rate_map


def test_model_shape_matches_the_ie037_evidence_list():
    columns = {c.name for c in IrelandStatutorySickLeaveRecord.__table__.columns}
    required = {
        # dates
        "absence_start_date", "absence_end_date", "calendar_year",
        # entitlement used
        "days_claimed", "days_credited", "days_disallowed", "days_taken_before",
        "entitlement_days", "entitlement_remaining_after",
        # daily rate and cap
        "usual_daily_earnings", "daily_rate_before_cap", "daily_rate",
        "daily_cap", "cap_applied", "pct_applied",
        # service qualification
        "service_start_date", "service_weeks_actual", "service_weeks_required",
        "service_qualified", "certified",
        # the decision itself, and its audit trail
        "eligible", "reason", "status", "amount",
    }
    assert required <= columns
    # The claim must be linkable to the leave request that produced it without
    # either side depending on the other.
    assert "leave_request_id" in columns
