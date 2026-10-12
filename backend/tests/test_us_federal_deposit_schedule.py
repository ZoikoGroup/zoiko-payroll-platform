"""
tests/test_us_federal_deposit_schedule.py
---------------------------------------------
Coverage for service.calculate_us_federal_deposit_schedule (ZP-TAX-US-
2026-001 §3.5, gap-closure 2026-09-12) — org-scoped (no employee_id) IRS
federal deposit/filing calendar: depositor status, deposit due date,
$100,000 next-day rule, $500 FUTA deposit trigger, and the Form W-2/W-3
January 31 deadline.

Weekday facts used below (2026-01-01 is a Thursday):
  2026-01-07 Wed, 2026-01-08 Thu, 2026-01-09 Fri,
  2026-01-10 Sat, 2026-01-11 Sun, 2026-01-12 Mon, 2026-01-13 Tue.
  2027-01-31 is a Sunday (365-day 2026 pushes 2027-01-01 to Friday).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service


def test_deposit_schedule_rejects_negative_lookback_liability(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("-1"), date(2026, 3, 10))


def test_deposit_schedule_rejects_negative_optional_liabilities(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_us_federal_deposit_schedule(
            db, organization.id, Decimal("10000"), date(2026, 3, 10), accumulated_undeposited_liability=Decimal("-1"),
        )
    with pytest.raises(BadRequestException):
        service.calculate_us_federal_deposit_schedule(
            db, organization.id, Decimal("10000"), date(2026, 3, 10), quarterly_futa_liability=Decimal("-1"),
        )


def test_monthly_depositor_at_or_below_threshold_due_15th_of_next_month(db, organization):
    result = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("50000"), date(2026, 3, 10))
    assert result["depositor_status"] == "MONTHLY"
    # April 15, 2026 is a Wednesday -- no weekend adjustment needed here.
    assert result["deposit_due_date"] == date(2026, 4, 15)


def test_semiweekly_depositor_above_threshold(db, organization):
    result = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("50000.01"), date(2026, 3, 10))
    assert result["depositor_status"] == "SEMIWEEKLY"


@pytest.mark.parametrize("payday", [date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)])
def test_semiweekly_wed_thu_fri_payday_due_following_wednesday(db, organization, payday):
    result = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("60000"), payday)
    assert result["depositor_status"] == "SEMIWEEKLY"
    assert result["deposit_due_date"] == date(2026, 1, 14)


@pytest.mark.parametrize("payday", [date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 12), date(2026, 1, 13)])
def test_semiweekly_sat_sun_mon_tue_payday_due_following_friday(db, organization, payday):
    result = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("60000"), payday)
    assert result["depositor_status"] == "SEMIWEEKLY"
    assert result["deposit_due_date"] == date(2026, 1, 16)


def test_next_day_rule_not_triggered_when_absent_or_below_threshold(db, organization):
    absent = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("10000"), date(2026, 3, 10))
    assert absent["next_day_rule_triggered"] is False
    assert absent["next_day_deposit_due_date"] is None

    below = service.calculate_us_federal_deposit_schedule(
        db, organization.id, Decimal("10000"), date(2026, 3, 10), accumulated_undeposited_liability=Decimal("99999.99"),
    )
    assert below["next_day_rule_triggered"] is False


def test_next_day_rule_triggered_at_or_above_threshold(db, organization):
    result = service.calculate_us_federal_deposit_schedule(
        db, organization.id, Decimal("10000"), date(2026, 1, 8), accumulated_undeposited_liability=Decimal("100000"),
    )
    assert result["next_day_rule_triggered"] is True
    assert result["next_day_deposit_due_date"] == date(2026, 1, 9)  # next banking day after a Thursday payday


def test_futa_deposit_required_only_above_threshold(db, organization):
    at_threshold = service.calculate_us_federal_deposit_schedule(
        db, organization.id, Decimal("10000"), date(2026, 3, 10), quarterly_futa_liability=Decimal("500"),
    )
    assert at_threshold["futa_deposit_required"] is False
    above = service.calculate_us_federal_deposit_schedule(
        db, organization.id, Decimal("10000"), date(2026, 3, 10), quarterly_futa_liability=Decimal("500.01"),
    )
    assert above["futa_deposit_required"] is True
    absent = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("10000"), date(2026, 3, 10))
    assert absent["futa_deposit_required"] is None


def test_form_w2_w3_deadline_adjusted_for_weekend(db, organization):
    result = service.calculate_us_federal_deposit_schedule(db, organization.id, Decimal("10000"), date(2026, 6, 1))
    # 2027-01-31 is a Sunday -> pushed to Monday 2027-02-01.
    assert result["form_w2_w3_deadline"] == date(2027, 2, 1)
