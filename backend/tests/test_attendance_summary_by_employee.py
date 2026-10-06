"""Per-employee attendance aggregates (Phase 1.4 server-side summary).

The Summary tab used to download every attendance row in range and count days
per employee in the browser. get_attendance_summary_by_employee does that work
in the database. These tests pin the numbers against the exact semantics the
client-side version had, because a silent change in present/leave/unpaid
counts would be a payroll-facing discrepancy that looks perfectly plausible.
"""
from datetime import date, timedelta

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import (
    EmployeeStatus,
    PayrollAttendanceRecord,
    PayrollEmployee,
)

ORG = 1
TODAY = date.today()
PAST = TODAY - timedelta(days=10)


@pytest.fixture()
def staff(db, organization):
    ann = PayrollEmployee(
        organization_id=ORG, name="Ann", employee_code="E001",
        department="Eng", designation="Dev",
        status=EmployeeStatus.ACTIVE.value,
    )
    bob = PayrollEmployee(
        organization_id=ORG, name="Bob", employee_code="E002",
        department="Ops", designation="Lead",
        status=EmployeeStatus.ACTIVE.value,
    )
    db.add_all([ann, bob])
    db.flush()
    return {"ann": ann.id, "bob": bob.id}


def add(db, emp_id, day, status="present", leave_type=None, hours=None,
        check_in=None, check_out=None, org_id=None):
    db.add(PayrollAttendanceRecord(
        organization_id=ORG if org_id is None else org_id,
        employee_id=emp_id, date=day, status=status,
        leave_type=leave_type, hours=hours, check_in=check_in, check_out=check_out,
    ))


def by_id(result):
    return {row["employeeId"]: row for row in result["items"]}


# ── counting ────────────────────────────────────────────────────────────

def test_counts_status_buckets_and_total_days(db, staff):
    add(db, staff["ann"], PAST, "present", hours="8")
    add(db, staff["ann"], PAST - timedelta(days=1), "absent")
    add(db, staff["ann"], PAST - timedelta(days=2), "leave", leave_type="unpaid")
    db.commit()

    row = next(r for r in service.get_attendance_summary_by_employee(db, ORG)["items"]
               if r["employeeId"] == staff["ann"])

    assert row["totalDays"] == 3      # every recorded day, whatever the status
    assert row["present"] == 1
    assert row["absent"] == 1
    assert row["leave"] == 1
    assert row["unpaidLeaves"] == 1
    assert row["paidLeaves"] == 0


def test_paid_leave_is_separated_from_unpaid(db, staff):
    add(db, staff["ann"], PAST, "leave", leave_type="paid")
    add(db, staff["ann"], PAST - timedelta(days=1), "leave", leave_type="unpaid")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["leave"] == 2
    assert row["paidLeaves"] == 1
    assert row["unpaidLeaves"] == 1


@pytest.mark.parametrize("leave_type", [None, "unpaid"])
def test_missing_or_unpaid_leave_type_counts_as_unpaid(db, staff, leave_type):
    """Mirrors _count_unpaid_leave_days in service.py: "unpaid" or missing /
    legacy null is unpaid; "paid" is not."""
    add(db, staff["ann"], PAST, "leave", leave_type=leave_type)
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["unpaidLeaves"] == 1
    assert row["paidLeaves"] == 0


@pytest.mark.parametrize("leave_type", ["sick", "casual"])
def test_sick_and_casual_count_as_leave_only(db, staff, leave_type):
    """Sick/casual must NOT inflate unpaid or paid leave counts."""
    add(db, staff["ann"], PAST, "leave", leave_type=leave_type)
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["leave"] == 1
    assert row["unpaidLeaves"] == 0
    assert row["paidLeaves"] == 0


def test_leave_type_on_a_present_row_is_not_counted_as_leave(db, staff):
    """A stray leave_type on a non-leave status must not produce leave days."""
    add(db, staff["ann"], PAST, "present", leave_type="unpaid")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["leave"] == 0
    assert row["unpaidLeaves"] == 0
    assert row["present"] == 1


# ── hours ───────────────────────────────────────────────────────────────

def test_hours_sum_across_rows_and_employees(db, staff):
    add(db, staff["ann"], PAST, hours="8")
    add(db, staff["ann"], PAST - timedelta(days=1), hours="8.5")
    add(db, staff["bob"], PAST, hours="7.5")
    db.commit()

    rows = by_id(service.get_attendance_summary_by_employee(db, ORG))

    assert rows[staff["ann"]]["totalHours"] == 16.5
    assert rows[staff["bob"]]["totalHours"] == 7.5


def test_repeated_distinct_hours_are_weighted_by_occurrence(db, staff):
    """The sum is computed over DISTINCT hour strings, so the same value on
    three different days must still count three times."""
    for i in range(3):
        add(db, staff["ann"], PAST - timedelta(days=i), hours="8")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["totalHours"] == 24.0


def test_missing_hours_count_as_zero(db, staff):
    add(db, staff["ann"], PAST, hours=None)
    add(db, staff["ann"], PAST - timedelta(days=1), hours=None)
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["totalHours"] == 0.0


@pytest.mark.parametrize("junk", ["", "  ", "N/A", "-", "abc"])
def test_unparseable_hours_are_zero_not_nan(db, staff, junk):
    """hours is a free-text column. The old client did Number(hours || 0),
    which turns "N/A" into NaN and poisons the running total for the employee.
    Non-numeric junk must be treated as 0 here."""
    add(db, staff["ann"], PAST, hours="8")
    add(db, staff["ann"], PAST - timedelta(days=1), hours=junk)
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["totalHours"] == 8.0


# ── modal check-in / check-out ──────────────────────────────────────────

def test_avg_check_in_is_the_most_frequent_time_not_the_mean(db, staff):
    for i, ci in enumerate(["09:00", "09:00", "10:30"]):
        add(db, staff["ann"], PAST - timedelta(days=i), check_in=ci, check_out="18:00")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["avgCheckIn"] == "09:00"
    assert row["avgCheckOut"] == "18:00"


def test_blank_check_times_are_ignored(db, staff):
    add(db, staff["ann"], PAST, check_in="", check_out="")
    add(db, staff["ann"], PAST - timedelta(days=1), check_in=None, check_out=None)
    add(db, staff["ann"], PAST - timedelta(days=2), check_in="09:15", check_out="17:45")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["avgCheckIn"] == "09:15"
    assert row["avgCheckOut"] == "17:45"


def test_check_times_are_tracked_per_employee(db, staff):
    for i in range(3):
        add(db, staff["ann"], PAST - timedelta(days=i), check_in="08:00", check_out="16:00")
    for i in range(3):
        add(db, staff["bob"], PAST - timedelta(days=i), check_in="10:00", check_out="19:00")
    db.commit()

    rows = by_id(service.get_attendance_summary_by_employee(db, ORG))

    assert rows[staff["ann"]]["avgCheckIn"] == "08:00"
    assert rows[staff["bob"]]["avgCheckIn"] == "10:00"


# ── avgBreak ────────────────────────────────────────────────────────────

def test_avg_break_is_zero_because_the_column_does_not_exist(db, staff):
    """Documented gap: payroll_attendance_records has no break_minutes column.
    The previous client read a field that never existed and rendered 0. That is
    preserved rather than invented."""
    add(db, staff["ann"], PAST, check_in="09:00", check_out="18:00")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["avgBreak"] == 0


# ── future dates, ranges, tenant isolation ──────────────────────────────

def test_future_dated_rows_are_excluded(db, staff):
    """Scheduled attendance must not count toward completed stats."""
    add(db, staff["ann"], PAST, status="present", hours="8")
    add(db, staff["ann"], TODAY + timedelta(days=3), status="present", hours="8")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["totalDays"] == 1
    assert row["totalHours"] == 8.0


def test_todays_rows_are_included(db, staff):
    add(db, staff["ann"], TODAY, status="present", hours="8")
    db.commit()

    row = by_id(service.get_attendance_summary_by_employee(db, ORG))[staff["ann"]]

    assert row["totalDays"] == 1


def test_date_range_narrows_the_aggregate(db, staff):
    for i in range(10):
        add(db, staff["ann"], PAST - timedelta(days=i), hours="8")
    db.commit()

    recent = service.get_attendance_summary_by_employee(
        db, ORG, start_date=PAST - timedelta(days=2), end_date=PAST,
    )
    row = by_id(recent)[staff["ann"]]

    assert row["totalDays"] == 3
    assert row["totalHours"] == 24.0


def test_employees_with_no_rows_in_range_are_absent(db, staff):
    add(db, staff["ann"], PAST)
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG)
    assert staff["bob"] not in by_id(result)


def test_other_organizations_are_excluded(db, staff):
    add(db, staff["ann"], PAST)
    outsider = PayrollEmployee(
        organization_id=2, name="Other Tenant", employee_code="X1",
        status=EmployeeStatus.ACTIVE.value,
    )
    db.add(outsider)
    db.flush()
    add(db, outsider.id, PAST, org_id=2)
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG)

    assert result["total"] == 1
    assert "Other Tenant" not in {r["name"] for r in result["items"]}


def test_attendance_for_a_deleted_employee_is_kept_but_not_attributed(db, staff):
    """An attendance row whose employee no longer exists is still this org's
    data, so its day must still be counted -- dropping it would silently
    shrink the org's totals. But it must not be folded into a real employee;
    it gets a placeholder name, matching the old client behaviour of falling
    back to a placeholder when a record has no employee name."""
    add(db, staff["ann"], PAST)
    db.add(PayrollAttendanceRecord(
        organization_id=ORG, employee_id=9999, date=PAST, status="present",
    ))
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG)
    rows = {r["employeeId"]: r for r in result["items"]}

    assert 9999 in rows
    assert rows[9999]["totalDays"] == 1
    assert rows[9999]["name"] == "Employee 9999"
    # Ann's own totals are unaffected by someone else's orphan row.
    assert rows[staff["ann"]]["totalDays"] == 1


# ── paging ──────────────────────────────────────────────────────────────

def test_paging_over_employees(db, organization):
    for i in range(7):
        emp = PayrollEmployee(
            organization_id=ORG, name=f"Emp{i:02d}", employee_code=f"E{i:02d}",
            status=EmployeeStatus.ACTIVE.value,
        )
        db.add(emp)
        db.flush()
        add(db, emp.id, PAST)
    db.commit()

    seen = []
    offset = 0
    while True:
        page = service.get_attendance_summary_by_employee(db, ORG, limit=3, offset=offset)
        seen.extend(r["employeeId"] for r in page["items"])
        if not page["hasMore"]:
            break
        offset += 3

    assert len(seen) == 7
    assert len(set(seen)) == 7


def test_total_reports_employee_count_not_row_count(db, organization):
    for i in range(3):
        emp = PayrollEmployee(
            organization_id=ORG, name=f"Emp{i}", employee_code=f"E{i}",
            status=EmployeeStatus.ACTIVE.value,
        )
        db.add(emp)
        db.flush()
        for d in range(5):
            add(db, emp.id, PAST - timedelta(days=d))
    db.commit()

    page = service.get_attendance_summary_by_employee(db, ORG, limit=1)

    assert page["total"] == 3
    assert len(page["items"]) == 1
    assert page["hasMore"] is True


def test_empty_org_returns_an_empty_page_not_an_error(db, organization):
    page = service.get_attendance_summary_by_employee(db, ORG)

    assert page["items"] == []
    assert page["total"] == 0
    assert page["hasMore"] is False


def test_page_totals_stay_full_when_a_page_is_loaded(db, staff):
    add(db, staff["ann"], PAST)
    add(db, staff["bob"], PAST)
    db.commit()

    page = service.get_attendance_summary_by_employee(db, ORG, limit=1, offset=1)

    assert len(page["items"]) == 1
    assert page["total"] == 2
    assert page["hasMore"] is False


# ── org-wide totals ─────────────────────────────────────────────────────

def test_totals_cover_every_employee_not_just_the_page(db, organization):
    """The stat cards sum every employee while the table is paged. Summing the
    page would under-report as soon as a second page exists."""
    for i in range(4):
        emp = PayrollEmployee(
            organization_id=ORG, name=f"Emp{i}", employee_code=f"E{i}",
            status=EmployeeStatus.ACTIVE.value,
        )
        db.add(emp)
        db.flush()
        add(db, emp.id, PAST, "present", hours="8")
        add(db, emp.id, PAST - timedelta(days=1), "leave", leave_type="unpaid")
    db.commit()

    page = service.get_attendance_summary_by_employee(db, ORG, limit=1)

    assert len(page["items"]) == 1
    assert page["total"] == 4
    assert page["hasMore"] is True
    assert page["totals"]["totalDays"] == 8       # 4 employees x 2 days
    assert page["totals"]["present"] == 4
    assert page["totals"]["leave"] == 4
    assert page["totals"]["unpaidLeaves"] == 4


def test_totals_match_the_sum_of_every_page(db, organization):
    for i in range(5):
        emp = PayrollEmployee(
            organization_id=ORG, name=f"Emp{i}", employee_code=f"E{i}",
            status=EmployeeStatus.ACTIVE.value,
        )
        db.add(emp)
        db.flush()
        add(db, emp.id, PAST, "present", hours="8")
    db.commit()

    first = service.get_attendance_summary_by_employee(db, ORG, limit=2, offset=0)
    rows = list(first["items"])
    while first["hasMore"]:
        first = service.get_attendance_summary_by_employee(
            db, ORG, limit=2, offset=first["offset"] + first["limit"],
        )
        rows.extend(first["items"])

    for field in ("totalDays", "present", "absent", "leave",
                  "unpaidLeaves", "paidLeaves"):
        assert sum(r[field] for r in rows) == first["totals"][field], field


def test_totals_are_zero_when_there_is_no_data(db, organization):
    page = service.get_attendance_summary_by_employee(db, ORG)

    assert page["totals"] == {
        "totalDays": 0, "present": 0, "absent": 0, "leave": 0,
        "unpaidLeaves": 0, "paidLeaves": 0,
    }


# ── server-side search ──────────────────────────────────────────────────

def test_search_matches_employee_name(db, staff):
    add(db, staff["ann"], PAST)
    add(db, staff["bob"], PAST)
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG, search="ann")

    assert result["total"] == 1
    assert result["items"][0]["employeeId"] == staff["ann"]


def test_search_matches_department(db, staff):
    add(db, staff["ann"], PAST)
    add(db, staff["bob"], PAST)
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG, search="Ops")

    assert result["total"] == 1
    assert result["items"][0]["employeeId"] == staff["bob"]


def test_search_is_case_insensitive(db, staff):
    add(db, staff["ann"], PAST)
    db.commit()

    assert service.get_attendance_summary_by_employee(db, ORG, search="ANN")["total"] == 1
    assert service.get_attendance_summary_by_employee(db, ORG, search="aNn")["total"] == 1


def test_search_with_no_match_is_empty_with_zero_totals(db, staff):
    add(db, staff["ann"], PAST)
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG, search="nobody-here")

    assert result["items"] == []
    assert result["total"] == 0
    assert result["hasMore"] is False
    assert result["totals"]["totalDays"] == 0


def test_search_respects_the_date_range(db, staff):
    add(db, staff["ann"], PAST)
    add(db, staff["ann"], PAST - timedelta(days=200))
    db.commit()

    result = service.get_attendance_summary_by_employee(
        db, ORG, search="Ann", start_date=PAST - timedelta(days=5), end_date=PAST,
    )

    assert result["items"][0]["totalDays"] == 1


def test_search_does_not_match_another_tenant(db, staff):
    outsider = PayrollEmployee(
        organization_id=2, name="Ann", employee_code="X1",
        status=EmployeeStatus.ACTIVE.value,
    )
    db.add(outsider)
    db.flush()
    add(db, outsider.id, PAST, org_id=2)
    add(db, staff["bob"], PAST)
    db.commit()

    result = service.get_attendance_summary_by_employee(db, ORG, search="Ann")

    assert result["total"] == 0


# ── parity with the previous client-side implementation ─────────────────

def test_matches_the_old_client_side_aggregation(db, staff):
    """Replays the exact algorithm the Summary tab used, over the same rows,
    and asserts the server produces identical numbers."""
    raw = [
        # employee, date, status, leave_type, hours, check_in, check_out
        (staff["ann"], PAST,             "present", None,    "8",   "09:00", "18:00"),
        (staff["ann"], PAST - timedelta(1), "leave",  "unpaid", "8",   None,    None),
        (staff["ann"], PAST - timedelta(2), "present", None,  "8.5", "09:00", "17:30"),
        (staff["ann"], PAST - timedelta(3), "present", None,  None,   "10:00", "18:00"),
        (staff["ann"], PAST - timedelta(4), "absent",  None,   None,   None,    None),
        (staff["bob"], PAST,             "present", None,    "7.5", "08:30", "16:45"),
        (staff["bob"], PAST - timedelta(1), "leave",  "paid",  None,   None,    None),
        (staff["bob"], PAST - timedelta(2), "leave",  "sick",  None,   None,    None),
    ]
    for emp_id, day, status, leave_type, hours, ci, co in raw:
        add(db, emp_id, day, status, leave_type, hours, ci, co)
    db.commit()

    # ── the old browser-side implementation, verbatim ──
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def old(rows):
        acc = {}
        for r in rows:
            k = r["employee_id"]
            e = acc.setdefault(k, {
                "totalDays": 0, "present": 0, "absent": 0, "leave": 0,
                "unpaidLeaves": 0, "paidLeaves": 0, "totalHours": 0.0,
                "in": {}, "out": {},
            })
            if r["status"] == "present":
                e["present"] += 1
            elif r["status"] == "absent":
                e["absent"] += 1
            elif r["status"] == "leave":
                e["leave"] += 1
                if r["leave_type"] == "paid":
                    e["paidLeaves"] += 1
                elif r["leave_type"] in (None, "unpaid"):
                    e["unpaidLeaves"] += 1
            e["totalDays"] += 1
            e["totalHours"] += _num(r["hours"]) if r["hours"] else 0.0
            if r["check_in"]:
                e["in"][r["check_in"]] = e["in"].get(r["check_in"], 0) + 1
            if r["check_out"]:
                e["out"][r["check_out"]] = e["out"].get(r["check_out"], 0) + 1
        for e in acc.values():
            e["avgCheckIn"] = sorted(e["in"].items(), key=lambda kv: -kv[1])[0][0] if e["in"] else ""
            e["avgCheckOut"] = sorted(e["out"].items(), key=lambda kv: -kv[1])[0][0] if e["out"] else ""
            e["totalHours"] = round(e["totalHours"], 2)
            del e["in"], e["out"]
        return acc

    expected = old([
        {"employee_id": e, "status": s, "leave_type": lt, "hours": h,
         "check_in": ci, "check_out": co}
        for e, _d, s, lt, h, ci, co in raw
    ])

    actual = by_id(service.get_attendance_summary_by_employee(db, ORG))

    for emp_id, want in expected.items():
        got = actual[emp_id]
        for field in ("totalDays", "present", "absent", "leave",
                      "unpaidLeaves", "paidLeaves", "totalHours",
                      "avgCheckIn", "avgCheckOut"):
            assert got[field] == want[field], f"emp {emp_id} {field}: {got[field]!r} != {want[field]!r}"
