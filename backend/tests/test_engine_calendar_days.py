"""
tests/test_engine_calendar_days.py
----------------------------------
Calendar-day payable-days coverage (28/29/30/31-day periods).

The Fixed 30-Day Payroll Model defines, for EVERY strategy:
    PAYROLL_DAYS = 30
    Per Day Salary = Monthly Gross / 30
    Attendance Deduction = Unpaid Leave Days × Per Day Salary
    Payable Days = calendar days in the pay period − Unpaid Leave Days

The engine used to hard-code the period to 30 days, so a 31-day month
showed 30 payable days. This suite pins the new behaviour: total working
days follow the run's real calendar length while the per-day salary and
attendance deduction stay on the 30-day basis (unchanged by month length),
and the invariant total_working_days − payable_days == unpaid days always
holds so reports/reconciliation stay self-consistent.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.base import PAYROLL_DAYS, PayrollContext, _round2
from app.modules.payroll.engine.enterprise import EnterpriseStrategy
from app.modules.payroll.engine.simple import SimpleStrategy
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.service import _calendar_days

STRATEGIES = [
    pytest.param(StandardStrategy(), id="standard"),
    pytest.param(SimpleStrategy(), id="simple"),
    pytest.param(EnterpriseStrategy(), id="enterprise"),
]

GROSS = Decimal("90000")


def calc(strategy, calendar_days, unpaid, country="ZZ"):
    """Country "ZZ" hits the generic progressive-tax fallback (no slabs →
    no tax), so total_deductions == attendance_deduction and every money
    figure is pure 30-day-model arithmetic."""
    ctx = PayrollContext(
        gross=GROSS,
        basic=GROSS,
        country=country,
        calendar_days=calendar_days,
        unpaid_leave_days=unpaid,
    )
    return strategy.calculate(ctx)


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("calendar_days", [28, 29, 30, 31])
@pytest.mark.parametrize("unpaid", [0, 1, 5])
def test_payable_days_track_calendar_length(strategy, calendar_days, unpaid):
    result = calc(strategy, calendar_days, unpaid)

    assert result.calendar_days == calendar_days
    assert result.unpaid_leave_days == unpaid
    assert result.payable_days == max(calendar_days - unpaid, 0)
    # Headline regression: a full 31-day month pays for all 31 days, a
    # 28-day February for 28 — never a flat 30 unless the period is 30.
    assert result.payroll_days == PAYROLL_DAYS
    # Invariant reports/reconciliation rely on:
    assert result.calendar_days - result.payable_days == unpaid


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("calendar_days", [28, 29, 30, 31])
@pytest.mark.parametrize("unpaid", [0, 1, 5])
def test_month_length_does_not_touch_attendance_deduction(strategy, calendar_days, unpaid):
    result = calc(strategy, calendar_days, unpaid)

    per_day = _round2(GROSS / Decimal(PAYROLL_DAYS))
    assert result.per_day_salary == per_day
    assert result.attendance_deduction == min(_round2(per_day * Decimal(unpaid)), GROSS)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_full_month_no_unpaid_pays_full_gross(strategy):
    result = calc(strategy, 31, 0)
    assert result.payable_days == 31
    assert result.attendance_deduction == Decimal("0")
    assert result.net_pay == GROSS


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("calendar_days", [28, 29, 30, 31])
def test_unpaid_exceeding_calendar_days_floors_payable_at_zero(strategy, calendar_days):
    result = calc(strategy, calendar_days, calendar_days + 5)
    assert result.payable_days == 0
    assert result.calendar_days - result.payable_days == calendar_days
    # Attendance deduction never exceeds gross even when unpaid days do.
    assert result.attendance_deduction == GROSS
    assert result.net_pay == Decimal("0")


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_none_calendar_days_falls_back_to_30(strategy):
    result = calc(strategy, None, 3)
    assert result.calendar_days == PAYROLL_DAYS
    assert result.payable_days == PAYROLL_DAYS - 3
    assert result.calendar_days - result.payable_days == 3


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_zero_calendar_days_is_treated_as_absent(strategy):
    # 0 is falsy, so alongside None it means "caller didn't supply a real
    # period" and falls back to the 30-day basis rather than a 0-day one.
    result = calc(strategy, 0, 0)
    assert result.calendar_days == PAYROLL_DAYS
    assert result.payable_days == PAYROLL_DAYS


# ── _calendar_days (service helper) ─────────────────────────────────────

def test_calendar_days_helper_full_months():
    assert _calendar_days(date(2024, 1, 1), date(2024, 1, 31)) == 31
    assert _calendar_days(date(2024, 2, 1), date(2024, 2, 29)) == 29  # leap year
    assert _calendar_days(date(2025, 2, 1), date(2025, 2, 28)) == 28
    assert _calendar_days(date(2025, 4, 1), date(2025, 4, 30)) == 30
    assert _calendar_days(date(2025, 3, 1), date(2025, 3, 31)) == 31


def test_calendar_days_helper_cross_period_and_single_day():
    assert _calendar_days(date(2025, 1, 15), date(2025, 2, 14)) == 31
    assert _calendar_days(date(2025, 12, 20), date(2026, 1, 10)) == 22
    assert _calendar_days(date(2025, 6, 5), date(2025, 6, 5)) == 1


def test_calendar_days_helper_invalid_or_missing_period():
    assert _calendar_days(None, date(2025, 1, 31)) is None
    assert _calendar_days(date(2025, 1, 1), None) is None
    assert _calendar_days(None, None) is None
    assert _calendar_days(date(2025, 2, 3), date(2025, 2, 1)) is None  # end before start


# ── Service/DB integration: persistence + dashboard reconciliation ──────

def _stub_business_code_generation(monkeypatch):
    """generate_payslips_for_run numbers payslips via generate_business_code,
    which needs a Postgres advisory lock the SQLite test DB can't provide"""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _make_emp_cal_days(db, org_id, code, ctc):
    from app.modules.payroll.models import PayrollEmployee
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="IN", ctc=ctc,
        basic=ctc * Decimal("0.5"), hra=ctc * Decimal("0.2"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def test_generate_payslips_for_run_persists_calendar_days(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollAttendanceRecord, PayrollRun, PayslipItem

    _stub_business_code_generation(monkeypatch)
    # ctc=600000 -> basic=25000, hra=10000, special=15000 -> gross=50000/mo
    # (the same split Section 9 of the jurisdiction integration suite uses)
    emp = _make_emp_cal_days(db, organization.id, "CAL-28-1", Decimal("600000"))
    run = PayrollRun(
        organization_id=organization.id, period_label="Feb 2025",
        period_start=date(2025, 2, 1), period_end=date(2025, 2, 28), pay_date=date(2025, 2, 28),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=emp.id,
        date=date(2025, 2, 5), hours="0", status="absent",
    ))
    db.commit()

    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id,
    ).first()
    assert item is not None
    # 28-day February: payable days = 28 − 1 unpaid = 27 (was 30 − 1 = 29).
    assert item.total_working_days == Decimal("28")
    assert item.payable_days == Decimal("27")
    # Attendance deduction still on the 30-day basis, unchanged by month length.
    assert item.per_day_salary == _round2(Decimal("50000") / Decimal(PAYROLL_DAYS))
    assert item.attendance_deduction == item.per_day_salary
    # Dashboard reconciliation: the SQL SUM over the stored column equals
    # the real deduction for the month's period_start bound.
    assert service._compute_attendance_deductions(db, organization.id, 2025, 2) == item.attendance_deduction


def test_dashboards_attendance_deduction_sums_stored_column(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayslipItem

    emp = _make_emp_cal_days(db, organization.id, "CAL-DASH-1", Decimal("600000"))
    run1 = PayrollRun(
        organization_id=organization.id, period_label="Mar 1", 
        period_start=date(2025, 3, 1), period_end=date(2025, 3, 15), pay_date=date(2025, 3, 31),
    )
    run2 = PayrollRun(
        organization_id=organization.id, period_label="Mar 2",
        period_start=date(2025, 3, 16), period_end=date(2025, 3, 31), pay_date=date(2025, 3, 31),
    )
    db.add(run1)
    db.add(run2)
    db.flush()
    db.add_all([
        PayslipItem(
            payroll_run_id=run1.id, employee_id=emp.id, organization_id=organization.id,
            employee_name="Employee CAL-DASH-1",
            total_working_days=Decimal("31"), payable_days=Decimal("30"),
            attendance_deduction=Decimal("1200.00"),
        ),
        PayslipItem(
            payroll_run_id=run2.id, employee_id=emp.id, organization_id=organization.id,
            employee_name="Employee CAL-DASH-1",
            total_working_days=Decimal("31"), payable_days=Decimal("30"),
            attendance_deduction=Decimal("800.00"),
        ),
    ])
    db.commit()

    # The stored column is summed directly — no proration-reconstruction
    # that would drift in a 31-day month.
    assert service._compute_attendance_deductions(db, organization.id, 2025, 3) == Decimal("2000.00")
    # A different month (period_start outside the bound) contributes nothing.
    assert service._compute_attendance_deductions(db, organization.id, 2025, 1) == Decimal("0")