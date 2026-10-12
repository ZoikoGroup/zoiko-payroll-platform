"""
tests/test_pr_deposit_schedule.py
------------------------------------
Coverage for service.calculate_pr_deposit_schedule (ZP-PR-ENG-001 §3,
PR-011) — org-scoped Hacienda withholding deposit/filing calendar:
Quarterly Exception/Monthly/Semiweekly depositor status, deposit due
date, $100,000 next-day rule, and the Form 499R-2 January 31-equivalent
deadline. Independent from calculate_us_federal_deposit_schedule (never
calls it, reads PR-scoped rates only) — see that function's own
docstring.

Weekday facts used below (2026-01-01 is a Thursday):
  2026-01-07 Wed, 2026-01-08 Thu, 2026-01-09 Fri,
  2026-01-10 Sat, 2026-01-11 Sun, 2026-01-12 Mon, 2026-01-13 Tue.
  2027-01-31 is a Sunday.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service


def test_deposit_schedule_rejects_negative_lookback_liability(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_pr_deposit_schedule(db, organization.id, Decimal("-1"), Decimal("5000"), date(2026, 3, 10))


def test_deposit_schedule_rejects_negative_current_quarter_withholding(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_pr_deposit_schedule(db, organization.id, Decimal("10000"), Decimal("-1"), date(2026, 3, 10))


def test_deposit_schedule_rejects_negative_accumulated_liability(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_pr_deposit_schedule(
            db, organization.id, Decimal("10000"), Decimal("5000"), date(2026, 3, 10),
            accumulated_undeposited_liability=Decimal("-1"),
        )


def test_quarterly_exception_takes_precedence_at_or_below_threshold(db, organization):
    """PR-011: current-quarter withholding under $2,500 -> QUARTERLY_
    EXCEPTION, even with a large lookback liability that would otherwise
    be SEMIWEEKLY."""
    result = service.calculate_pr_deposit_schedule(
        db, organization.id, Decimal("999999"), Decimal("2500"), date(2026, 3, 10),
    )
    assert result["depositor_status"] == "QUARTERLY_EXCEPTION"
    assert result["deposit_due_date"] is None


def test_monthly_depositor_at_or_below_threshold_due_15th_of_next_month(db, organization):
    result = service.calculate_pr_deposit_schedule(
        db, organization.id, Decimal("50000"), Decimal("5000"), date(2026, 3, 10),
    )
    assert result["depositor_status"] == "MONTHLY"
    assert result["deposit_due_date"] == date(2026, 4, 15)  # a Wednesday, no adjustment needed


def test_semiweekly_depositor_above_threshold(db, organization):
    result = service.calculate_pr_deposit_schedule(
        db, organization.id, Decimal("50000.01"), Decimal("5000"), date(2026, 3, 10),
    )
    assert result["depositor_status"] == "SEMIWEEKLY"


@pytest.mark.parametrize("payday", [date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)])
def test_semiweekly_wed_thu_fri_payday_due_following_wednesday(db, organization, payday):
    result = service.calculate_pr_deposit_schedule(db, organization.id, Decimal("60000"), Decimal("5000"), payday)
    assert result["depositor_status"] == "SEMIWEEKLY"
    assert result["deposit_due_date"] == date(2026, 1, 14)


@pytest.mark.parametrize("payday", [date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 12), date(2026, 1, 13)])
def test_semiweekly_sat_sun_mon_tue_payday_due_following_friday(db, organization, payday):
    result = service.calculate_pr_deposit_schedule(db, organization.id, Decimal("60000"), Decimal("5000"), payday)
    assert result["depositor_status"] == "SEMIWEEKLY"
    assert result["deposit_due_date"] == date(2026, 1, 16)


def test_next_day_rule_not_triggered_when_absent_or_below_threshold(db, organization):
    absent = service.calculate_pr_deposit_schedule(db, organization.id, Decimal("10000"), Decimal("5000"), date(2026, 3, 10))
    assert absent["next_day_rule_triggered"] is False
    assert absent["next_day_deposit_due_date"] is None

    below = service.calculate_pr_deposit_schedule(
        db, organization.id, Decimal("10000"), Decimal("5000"), date(2026, 3, 10),
        accumulated_undeposited_liability=Decimal("99999.99"),
    )
    assert below["next_day_rule_triggered"] is False


def test_next_day_rule_triggered_at_or_above_threshold(db, organization):
    result = service.calculate_pr_deposit_schedule(
        db, organization.id, Decimal("10000"), Decimal("5000"), date(2026, 1, 8),
        accumulated_undeposited_liability=Decimal("100000"),
    )
    assert result["next_day_rule_triggered"] is True
    assert result["next_day_deposit_due_date"] == date(2026, 1, 9)


def test_form_499r2_deadline_adjusted_for_weekend(db, organization):
    result = service.calculate_pr_deposit_schedule(db, organization.id, Decimal("10000"), Decimal("5000"), date(2026, 6, 1))
    assert result["form_499r2_deadline"] == date(2027, 2, 1)  # 2027-01-31 is a Sunday
