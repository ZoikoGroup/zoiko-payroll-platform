"""tests/test_attendance_gate.py
------------------------------
Phase 1 of the 2026-10-06 attendance / state-tax / deploy fix plan.

Payroll is deduct-on-absence: a day with no attendance row is paid as
present. The old guard only checked "is there at least one attendance row
across ALL selected employees" (and only when employeeIds was sent), so one
employee's attendance let everyone else be paid in full. The gate now checks
every in-scope employee against every expected working day, on create,
generate and recalculate, with an audited admin override.

Every test here opts into the real gate (conftest neutralises it for the
engine tests that never record attendance). Imports are lazy — see conftest.
"""
from datetime import date
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.attendance_gate

# Mon 2026-09-07 .. Sun 2026-09-13: 5 weekdays + Sat + Sun.
WEEK_START = date(2026, 9, 7)
WEEK_END = date(2026, 9, 13)
WEEKDAYS = [date(2026, 9, d) for d in range(7, 12)]


def _employee(db, org, code, **kwargs):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Emp {code}", country_code="IN",
                          compliance_fields={}, **kwargs)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _attendance(db, org, emp, days, status="present"):
    from app.modules.payroll.models import PayrollAttendanceRecord

    for d in days:
        db.add(PayrollAttendanceRecord(organization_id=org.id, employee_id=emp.id, date=d, status=status))
    db.commit()


def _policy(db, org, **fields):
    from app.modules.payroll.policy.service import get_active_policy

    policy = get_active_policy(db, org.id)
    for k, v in fields.items():
        setattr(policy, k, v)
    db.commit()
    return policy


def _run_create(**kwargs):
    from app.modules.payroll.schemas import PayrollRunCreate

    payload = {"periodStart": WEEK_START, "periodEnd": WEEK_END, "payDate": WEEK_END}
    payload.update(kwargs)
    return PayrollRunCreate(**payload)


@pytest.fixture()
def stub_generation(monkeypatch):
    """Payslip generation is not under test here — only whether the gate lets
    the run reach it. Run-code generation takes a Postgres advisory lock
    SQLite doesn't have, so it is stubbed the same way
    test_ca_bc_mb_nl_levy_service_integration.py does."""
    import app.core.code_generation as code_generation
    from app.modules.payroll import service

    calls = []
    counter = {"n": 0}

    def _fake(db, run, organization_id=None, employee_ids=None):
        calls.append(employee_ids)
        return run

    def _fake_code(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(service, "generate_payslips_for_run", _fake)
    monkeypatch.setattr(code_generation, "generate_business_code", _fake_code)
    return calls


# ── check_attendance_readiness ────────────────────────────────────────────

def test_readiness_counts_only_weekdays_and_reports_each_employee(db, organization):
    from app.modules.payroll.service import check_attendance_readiness

    full = _employee(db, organization, "E1")
    partial = _employee(db, organization, "E2")
    _employee(db, organization, "E3")                       # nothing recorded
    _attendance(db, organization, full, WEEKDAYS)
    _attendance(db, organization, partial, WEEKDAYS[:3])

    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END)

    assert report["required"] is True
    assert report["ready"] is False
    assert report["totalEmployees"] == 3
    assert report["completeEmployees"] == 1
    assert report["incompleteEmployees"] == 2
    by_code = {m["employeeCode"]: m for m in report["missing"]}
    assert by_code["E3"]["expectedDays"] == 5           # Sat/Sun not expected
    assert by_code["E3"]["missingDays"] == 5
    assert by_code["E2"]["recordedDays"] == 3
    assert by_code["E2"]["missingDates"] == ["2026-09-10", "2026-09-11"]
    assert report["missing"][0]["employeeCode"] == "E3"  # most-missing first


def test_any_status_counts_as_recorded(db, organization):
    from app.modules.payroll.service import check_attendance_readiness

    emp = _employee(db, organization, "E1")
    _attendance(db, organization, emp, WEEKDAYS[:2], status="absent")
    _attendance(db, organization, emp, WEEKDAYS[2:], status="leave")

    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END)
    assert report["ready"] is True
    assert report["completeEmployees"] == 1


def test_one_employees_attendance_no_longer_covers_everyone(db, organization):
    """The exact hole the old aggregate count left open."""
    from app.modules.payroll.service import check_attendance_readiness

    covered = _employee(db, organization, "E1")
    others = [_employee(db, organization, f"X{i}") for i in range(3)]
    _attendance(db, organization, covered, WEEKDAYS)

    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END,
                                        [covered.id] + [o.id for o in others])
    assert report["ready"] is False
    assert report["incompleteEmployees"] == 3


def test_joining_and_leaving_dates_shrink_expected_days(db, organization):
    from app.modules.payroll.service import check_attendance_readiness

    joiner = _employee(db, organization, "J", date_of_joining=date(2026, 9, 10))   # Thu
    leaver = _employee(db, organization, "L", date_of_leaving=date(2026, 9, 8))    # Tue
    _attendance(db, organization, joiner, [date(2026, 9, 10), date(2026, 9, 11)])
    _attendance(db, organization, leaver, [date(2026, 9, 7), date(2026, 9, 8)])

    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END)
    assert report["ready"] is True
    assert report["completeEmployees"] == 2


def test_holidays_excluded_for_matching_country_only(db, organization):
    from app.modules.payroll.models import PayrollHoliday
    from app.modules.payroll.service import check_attendance_readiness

    india = _employee(db, organization, "IN1")
    uk = _employee(db, organization, "UK1")
    uk.country_code = "UK"
    db.add(PayrollHoliday(organization_id=organization.id, date=date(2026, 9, 9), country="IN", name="Test"))
    db.commit()
    without_holiday = [d for d in WEEKDAYS if d != date(2026, 9, 9)]
    _attendance(db, organization, india, without_holiday)
    _attendance(db, organization, uk, without_holiday)

    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END)
    assert report["incompleteEmployees"] == 1
    assert report["missing"][0]["employeeCode"] == "UK1"
    assert report["missing"][0]["missingDates"] == ["2026-09-09"]


def test_policy_weekly_off_days_and_employment_type_scope(db, organization):
    from app.modules.payroll.service import check_attendance_readiness

    six_day = _employee(db, organization, "F1")
    contractor = _employee(db, organization, "C1", employment_type="Contract")
    _attendance(db, organization, six_day, WEEKDAYS + [date(2026, 9, 12)])

    _policy(db, organization, attendance_weekly_off_days=[6], attendance_required_employment_types=["Full-time"])
    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END)
    assert report["weeklyOffDays"] == [6]
    assert report["exemptEmployees"] == 1                 # the contractor
    assert report["ready"] is True
    assert contractor.id not in [m["employeeId"] for m in report["missing"]]


def test_requirement_off_reports_but_never_blocks(db, organization):
    from app.modules.payroll.service import check_attendance_readiness, enforce_attendance_readiness

    _employee(db, organization, "E1")
    _policy(db, organization, attendance_required=False)

    report = check_attendance_readiness(db, organization.id, WEEK_START, WEEK_END)
    assert report["required"] is False
    assert report["incompleteEmployees"] == 1
    assert report["ready"] is True
    assert enforce_attendance_readiness(db, organization.id, WEEK_START, WEEK_END) is None


# ── create_payroll_run ────────────────────────────────────────────────────

def test_create_run_all_employees_is_blocked_without_attendance(db, organization, stub_generation):
    """employeeIds omitted ("all employees") used to skip the check entirely."""
    from app.core.exceptions import AttendanceIncompleteException
    from app.modules.payroll.models import PayrollRun
    from app.modules.payroll.service import create_payroll_run

    _employee(db, organization, "E1")
    with pytest.raises(AttendanceIncompleteException) as exc:
        create_payroll_run(db, None, _run_create(), organization.id)

    assert exc.value.error_code == "ATTENDANCE_INCOMPLETE"
    assert exc.value.trace["incompleteEmployees"] == 1
    assert db.query(PayrollRun).count() == 0            # no orphaned Draft run
    assert stub_generation == []


def test_create_run_passes_with_complete_attendance(db, organization, stub_generation):
    from app.modules.payroll.service import create_payroll_run

    emp = _employee(db, organization, "E1")
    _attendance(db, organization, emp, WEEKDAYS)
    run = create_payroll_run(db, None, _run_create(employeeIds=[emp.id]), organization.id)

    assert run.id is not None
    assert run.attendance_override_reason is None
    assert stub_generation == [[emp.id]]


def test_create_run_override_is_recorded_and_logged(db, organization, stub_generation):
    from app.modules.payroll.models import PayrollActivityLog
    from app.modules.payroll.service import create_payroll_run

    _employee(db, organization, "E1")
    reason = "Biometric export delayed; HR verified attendance manually"
    run = create_payroll_run(db, None, _run_create(attendanceOverrideReason=reason), organization.id)

    assert run.attendance_override_reason == reason
    assert run.attendance_override_at is not None
    assert len(stub_generation) == 1
    logs = [a.description for a in db.query(PayrollActivityLog).all()]
    assert any("incomplete attendance" in d and reason in d for d in logs)


def test_create_run_rejects_a_too_short_override_reason(db, organization, stub_generation):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.service import create_payroll_run

    _employee(db, organization, "E1")
    with pytest.raises(BadRequestException):
        create_payroll_run(db, None, _run_create(attendanceOverrideReason="ok"), organization.id)


def test_create_run_without_payslip_generation_is_not_gated(db, organization, stub_generation):
    from app.modules.payroll.service import create_payroll_run

    _employee(db, organization, "E1")
    run = create_payroll_run(db, None, _run_create(auto_generate_payslips=False), organization.id)
    assert run.id is not None


def test_extending_an_existing_run_gates_the_new_employees(db, organization, stub_generation):
    from app.core.exceptions import AttendanceIncompleteException
    from app.modules.payroll.service import create_payroll_run

    first = _employee(db, organization, "E1")
    _attendance(db, organization, first, WEEKDAYS)
    create_payroll_run(db, None, _run_create(employeeIds=[first.id]), organization.id)

    second = _employee(db, organization, "E2")
    with pytest.raises(AttendanceIncompleteException):
        create_payroll_run(db, None, _run_create(employeeIds=[second.id]), organization.id)


# ── generate-payslips endpoint & recalculate ──────────────────────────────

def _draft_run(db, org, **fields):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=org.id, period_label="Sep 7-13, 2026", period_start=WEEK_START,
                     period_end=WEEK_END, pay_date=WEEK_END, **fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_generate_endpoint_is_gated_and_accepts_an_override(db, organization, stub_generation):
    from app.core.exceptions import AttendanceIncompleteException
    from app.modules.payroll.router import generate_run_payslips
    from app.modules.payroll.schemas import GeneratePayslipsRequest

    _employee(db, organization, "E1")
    run = _draft_run(db, organization)
    user = SimpleNamespace(id=None, organization_id=organization.id)

    with pytest.raises(AttendanceIncompleteException):
        generate_run_payslips(run.id, async_dispatch=False, data=None, db=db, current_user=user)
    assert stub_generation == []

    body = GeneratePayslipsRequest(attendanceOverrideReason="Attendance verified offline by HR")
    generate_run_payslips(run.id, async_dispatch=False, data=body, db=db, current_user=user)
    db.refresh(run)
    assert run.attendance_override_reason == "Attendance verified offline by HR"
    assert len(stub_generation) == 1


def test_recalculate_is_gated_unless_the_run_was_overridden(db, organization):
    from app.core.exceptions import AttendanceIncompleteException
    from app.modules.payroll.models import PayslipItem
    from app.modules.payroll.service import enforce_attendance_readiness, regenerate_employee_payslip

    emp = _employee(db, organization, "E1")
    run = _draft_run(db, organization)
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                       employee_name=emp.name))
    db.commit()

    with pytest.raises(AttendanceIncompleteException):
        regenerate_employee_payslip(db, run.id, emp.id, organization.id)

    run.attendance_override_reason = "Approved by finance for the September cycle"
    db.commit()
    assert enforce_attendance_readiness(db, organization.id, WEEK_START, WEEK_END, [emp.id], run=run) is None


# ── policy settings ───────────────────────────────────────────────────────

def test_policy_update_validates_attendance_settings():
    from pydantic import ValidationError
    from app.modules.payroll.policy.schemas import PayrollPolicyUpdate

    ok = PayrollPolicyUpdate(attendanceRequired=False, attendanceWeeklyOffDays=[4, 5],
                             attendanceRequiredEmploymentTypes=["Part-time"])
    assert ok.attendance_weekly_off_days == [4, 5]
    for bad in ({"attendanceWeeklyOffDays": [7]}, {"attendanceWeeklyOffDays": [0, 1, 2, 3, 4, 5, 6]},
                {"attendanceWeeklyOffDays": [5, 5]}, {"attendanceRequiredEmploymentTypes": ["Freelance"]},
                {"attendanceRequired": None}):
        with pytest.raises(ValidationError):
            PayrollPolicyUpdate(**bad)


def test_policy_update_persists_attendance_settings(db, organization):
    from app.modules.payroll.policy.schemas import PayrollPolicyResponse, PayrollPolicyUpdate
    from app.modules.payroll.policy.service import get_active_policy, update_policy

    policy = get_active_policy(db, organization.id)
    assert policy.attendance_required is True                # default on
    updated = update_policy(db, policy.id, PayrollPolicyUpdate(
        attendanceRequired=False, attendanceWeeklyOffDays=[6], attendanceRequiredEmploymentTypes=["Contract"],
    ), organization.id)
    body = PayrollPolicyResponse.model_validate(updated).model_dump(by_alias=True)
    assert body["attendanceRequired"] is False
    assert body["attendanceWeeklyOffDays"] == [6]
    assert body["attendanceRequiredEmploymentTypes"] == ["Contract"]


# ── bulk save (batched reload after commit) ───────────────────────────────

def test_bulk_save_inserts_then_updates_and_returns_every_row(db, organization):
    from app.modules.payroll.models import PayrollAttendanceRecord
    from app.modules.payroll.schemas import BulkAttendanceRequest
    from app.modules.payroll.service import bulk_save_attendance

    a = _employee(db, organization, "A1")
    b = _employee(db, organization, "B1")
    rows = [{"employeeId": e.id, "date": d.isoformat(), "status": "present", "hours": "8"}
            for e in (a, b) for d in WEEKDAYS]
    result = bulk_save_attendance(db, BulkAttendanceRequest(records=rows), organization.id)
    assert result["saved"] == 10
    assert len(result["records"]) == 10
    assert {r["employee_id"] for r in result["records"]} == {a.id, b.id}

    update = [{"employeeId": a.id, "date": WEEKDAYS[0].isoformat(), "status": "absent"}]
    result = bulk_save_attendance(db, BulkAttendanceRequest(records=update), organization.id)
    assert result["saved"] == 1
    assert result["records"][0]["status"] == "absent"
    assert db.query(PayrollAttendanceRecord).count() == 10    # upserted, not duplicated


# ── migration c5981cbcbe13 ────────────────────────────────────────────────

def test_migration_adds_and_drops_columns_idempotently():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "c5981cbcbe13_attendance_gate_policy_and_run_override.py"
    spec = importlib.util.spec_from_file_location("attendance_gate_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.begin()
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE payroll_policies (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE payroll_runs (id INTEGER PRIMARY KEY)"))
        module.op = Operations(MigrationContext.configure(connection))

        def cols(table):
            return {c["name"] for c in sa.inspect(connection).get_columns(table)}

        module.upgrade()
        module.upgrade()                                   # second run is a no-op
        assert {"attendance_required", "attendance_required_employment_types",
                "attendance_weekly_off_days"} <= cols("payroll_policies")
        assert {"attendance_override_reason", "attendance_override_by",
                "attendance_override_at"} <= cols("payroll_runs")
        connection.execute(sa.text("INSERT INTO payroll_policies (id) VALUES (1)"))
        assert connection.execute(sa.text("SELECT attendance_required FROM payroll_policies")).scalar() in (1, True, "true")

        module.downgrade()
        module.downgrade()
        assert cols("payroll_policies") == {"id"}
        assert cols("payroll_runs") == {"id"}
