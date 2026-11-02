"""Japan Phase 6: work-conditions versions, attendance facts and the service
loaders (ZP-JP-ENG-001 S6/S14). Synthetic values only."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import japan_service as jp
from app.modules.payroll.models import (
    PayrollAttendanceRecord, PayrollEmployee, PayrollJpWorkConditions,
)


def D(value):
    return Decimal(str(value))


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="JP-WC-1",
                          name="Taro Suzuki")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _body(effective_from=date(2026, 1, 1), **overrides):
    body = {
        "effective_from": effective_from,
        "working_time_system": "STANDARD",
        "week_start_day": 0,
        "scheduled_daily_minutes": 480,
        "scheduled_monthly_hours": "240",
        "workplace_prefecture": "13",
        "specific_minimum_wage_applies": False,
    }
    body.update(overrides)
    return body


def _conditions(organization, **overrides):
    row = PayrollJpWorkConditions(
        organization_id=organization.id,
        effective_from=overrides.pop("effective_from", date(2026, 1, 1)),
        effective_to=overrides.pop("effective_to", None),
        working_time_system="STANDARD",
        week_start_day=0,
        scheduled_daily_minutes=480,
        scheduled_monthly_hours=D(240),
        workplace_prefecture="13",
        specific_minimum_wage_applies=False,
        status=overrides.pop("status", "ACTIVE"),
        **overrides,
    )
    return row


def _attendance(organization, employee, day, hours="8", status="present",
                check_in=None, check_out=None):
    return PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=employee.id, date=day,
        hours=hours, status=status, check_in=check_in, check_out=check_out)


# ── writers and approvals ─────────────────────────────────────────────────

def test_record_work_conditions_creates_a_cleaned_draft(db, organization):
    row = jp.record_work_conditions(db, organization.id, _body(), 1)
    db.commit()
    assert row.status == "DRAFT"
    assert row.week_start_day == 0
    assert row.scheduled_daily_minutes == 480
    assert row.scheduled_monthly_hours == D(240)
    assert row.specific_minimum_wage_applies is False
    assert row.created_by_id == 1


def test_unknown_work_condition_fields_fail_closed(db, organization):
    with pytest.raises(BadRequestException, match="unknown field"):
        jp.record_work_conditions(
            db, organization.id, _body(overtime_rate="1.25"), 1)


def test_required_work_condition_fields_fail_closed(db, organization):
    body = _body()
    body.pop("scheduled_monthly_hours")
    with pytest.raises(BadRequestException, match="required field"):
        jp.record_work_conditions(db, organization.id, body, 1)


def test_invalid_whole_numbers_fail_closed(db, organization):
    with pytest.raises(BadRequestException, match="whole number"):
        jp.record_work_conditions(
            db, organization.id, _body(scheduled_daily_minutes="eight"), 1)


def test_approval_requires_a_second_person(db, organization):
    row = jp.record_work_conditions(db, organization.id, _body(), 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        jp.approve_work_conditions(db, organization.id, row.id, 1)
    assert row.status == "DRAFT"


def test_approval_activates_and_supersedes_the_prior_version(db, organization):
    first = jp.record_work_conditions(db, organization.id, _body(), 1)
    jp.approve_work_conditions(db, organization.id, first.id, 2)
    db.commit()
    assert first.status == "ACTIVE" and first.approved_by_id == 2

    second = jp.record_work_conditions(
        db, organization.id, _body(effective_from=date(2027, 1, 1)), 1)
    jp.approve_work_conditions(db, organization.id, second.id, 2)
    db.commit()
    assert second.status == "ACTIVE"
    assert first.status == "SUPERSEDED"
    assert first.effective_to == date(2026, 12, 31)


def test_a_backdated_version_cannot_supersede_a_later_one(db, organization):
    first = jp.record_work_conditions(
        db, organization.id, _body(effective_from=date(2026, 6, 1)), 1)
    jp.approve_work_conditions(db, organization.id, first.id, 2)
    db.commit()
    later = jp.record_work_conditions(
        db, organization.id, _body(effective_from=date(2026, 1, 1)), 1)
    with pytest.raises(BadRequestException, match="on or after"):
        jp.approve_work_conditions(db, organization.id, later.id, 2)
    assert later.status == "DRAFT"


def test_only_a_draft_can_be_approved(db, organization):
    row = jp.record_work_conditions(db, organization.id, _body(), 1)
    jp.approve_work_conditions(db, organization.id, row.id, 2)
    with pytest.raises(BadRequestException, match="Only a DRAFT"):
        jp.approve_work_conditions(db, organization.id, row.id, 2)


# ── attendance loader ─────────────────────────────────────────────────────

def test_present_attendance_becomes_hours_with_night_and_schedule(db, organization, employee):
    db.add(_attendance(organization, employee, date(2026, 6, 1),
                       hours="8", check_in="21:00", check_out="23:00"))
    db.commit()
    conditions = SimpleNamespace(scheduled_daily_minutes=480)
    got = jp._jp_hours_for_period(
        db, organization.id, employee.id, date(2026, 6, 1), date(2026, 6, 30),
        conditions)
    assert got == [{
        "date": "2026-06-01", "worked_minutes": 480, "scheduled_minutes": 480,
        "check_in": "21:00", "check_out": "23:00", "is_holiday": False,
    }]


def test_absent_and_leave_rows_are_not_facts(db, organization, employee):
    db.add_all([
        _attendance(organization, employee, date(2026, 6, 1), status="absent"),
        _attendance(organization, employee, date(2026, 6, 2), status="leave"),
        _attendance(organization, employee, date(2026, 6, 3)),
    ])
    db.commit()
    got = jp._jp_hours_for_period(
        db, organization.id, employee.id, date(2026, 6, 1), date(2026, 6, 30),
        SimpleNamespace(scheduled_daily_minutes=480))
    assert [row["date"] for row in got] == ["2026-06-03"]


def test_attendance_outside_the_period_is_excluded(db, organization, employee):
    db.add_all([
        _attendance(organization, employee, date(2026, 5, 31)),
        _attendance(organization, employee, date(2026, 6, 1)),
        _attendance(organization, employee, date(2026, 7, 1)),
    ])
    db.commit()
    got = jp._jp_hours_for_period(
        db, organization.id, employee.id, date(2026, 6, 1), date(2026, 6, 30),
        SimpleNamespace(scheduled_daily_minutes=480))
    assert [row["date"] for row in got] == ["2026-06-01"]


def test_missing_work_conditions_means_no_hours(db, organization, employee):
    db.add(_attendance(organization, employee, date(2026, 6, 1)))
    db.commit()
    assert jp._jp_hours_for_period(
        db, organization.id, employee.id, date(2026, 6, 1), date(2026, 6, 30),
        None) == []


def test_invalid_attendance_hours_fail_closed(db, organization, employee):
    db.add(_attendance(organization, employee, date(2026, 6, 1), hours="eight"))
    db.commit()
    with pytest.raises(BadRequestException, match="not a number"):
        jp._jp_hours_for_period(
            db, organization.id, employee.id, date(2026, 6, 1), date(2026, 6, 30),
            SimpleNamespace(scheduled_daily_minutes=480))


def test_period_prefers_explicit_dates_then_the_run_then_the_month():
    run = SimpleNamespace(period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
    assert jp._jp_period(run, (date(2026, 1, 1), date(2026, 1, 31)),
                         date(2026, 6, 15)) == (date(2026, 1, 1), date(2026, 1, 31))
    assert jp._jp_period(run, None, date(2026, 6, 15)) == (
        date(2026, 6, 1), date(2026, 6, 30))
    assert jp._jp_period(None, None, date(2026, 2, 15)) == (
        date(2026, 2, 1), date(2026, 2, 28))


# ── calc-input loader ─────────────────────────────────────────────────────

def test_calc_inputs_loads_the_active_version_and_approved_hours(db, organization, employee):
    db.add(_conditions(organization))
    db.add(_attendance(organization, employee, date(2026, 6, 1)))
    db.commit()
    got = jp.resolve_jp_calc_inputs(
        db, organization.id, employee, date(2026, 6, 15),
        period=(date(2026, 6, 1), date(2026, 6, 30)))
    assert got["jp_work_conditions"].workplace_prefecture == "13"
    assert got["jp_hours_approved"] is True
    assert got["jp_hours"][0]["worked_minutes"] == 480


def test_pack_holidays_without_an_in_force_pack_seeds_nothing(db):
    assert jp._jp_pack_holidays(db, 2026) == []


def test_freeze_context_carries_the_work_conditions_and_attendance():
    conditions = SimpleNamespace(
        id=3, effective_from=date(2026, 1, 1), effective_to=None,
        working_time_system="STANDARD", week_start_day=0,
        scheduled_daily_minutes=480, scheduled_monthly_hours=D(240),
        workplace_prefecture="13", specific_minimum_wage_applies=False,
        status="ACTIVE", evidence_ref="SYNTHETIC")
    ctx = SimpleNamespace(jp_work_conditions=conditions,
                          jp_hours=[{"date": "2026-06-01", "worked_minutes": 480}],
                          jp_hours_approved=True)
    frozen = jp.jp_freeze_context(ctx)
    assert frozen["workConditions"]["workplace_prefecture"] == "13"
    assert frozen["attendance"]["approved"] is True
    assert frozen["attendance"]["days"][0]["worked_minutes"] == 480


def test_calc_inputs_ignores_drafts_and_no_hours_is_unapproved(db, organization, employee):
    db.add(_conditions(organization, status="DRAFT"))
    db.commit()
    got = jp.resolve_jp_calc_inputs(
        db, organization.id, employee, date(2026, 6, 15),
        period=(date(2026, 6, 1), date(2026, 6, 30)))
    assert got["jp_work_conditions"] is None
    assert got["jp_hours"] == [] and got["jp_hours_approved"] is False


def test_two_versions_in_force_are_a_configuration_error(db, organization, employee):
    db.add_all([
        _conditions(organization, effective_to=date(2026, 12, 31)),
        _conditions(organization, effective_from=date(2026, 1, 1)),
    ])
    db.commit()
    with pytest.raises(BadRequestException, match="exactly one"):
        jp.resolve_jp_calc_inputs(
            db, organization.id, employee, date(2026, 6, 15),
            period=(date(2026, 6, 1), date(2026, 6, 30)))
