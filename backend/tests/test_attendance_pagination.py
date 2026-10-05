"""Attendance paging contract (Phase 1.2 / 1.4 backend support).

The list endpoint returns a bare list, so a client that pages through
attendance data has to guess where the data ends. get_attendance_records_page
exists to make that explicit: an exact `total` plus a server-computed
`hasMore`. These tests pin that contract, because the frontend's history tab
depends on `hasMore` being correct rather than "page came back short".
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
START = date(2026, 1, 1)


@pytest.fixture()
def attendance_seed(db, organization):
    """25 rows for one employee, 10 rows for another, plus a known gap in dates.

    Two employees are needed so the employee filter can be exercised; the
    differing row counts make an offset bug (a filter applied to the page but
    not the count, or vice versa) visible.
    """
    ann = PayrollEmployee(
        organization_id=ORG, name="Ann", employee_code="E001",
        status=EmployeeStatus.ACTIVE.value,
    )
    bob = PayrollEmployee(
        organization_id=ORG, name="Bob", employee_code="E002",
        status=EmployeeStatus.ACTIVE.value,
    )
    db.add_all([ann, bob])
    db.flush()

    for i in range(25):
        db.add(PayrollAttendanceRecord(
            organization_id=ORG, employee_id=ann.id,
            date=START + timedelta(days=i), status="present",
        ))
    for i in range(10):
        db.add(PayrollAttendanceRecord(
            organization_id=ORG, employee_id=bob.id,
            date=START + timedelta(days=i), status="present",
        ))
    db.commit()
    return {"ann": ann.id, "bob": bob.id}


def test_first_page_reports_total_and_has_more(db, attendance_seed):
    page = service.get_attendance_records_page(db, ORG, limit=10, offset=0)

    assert page["total"] == 35
    assert len(page["items"]) == 10
    assert page["hasMore"] is True
    assert page["limit"] == 10
    assert page["offset"] == 0


def test_last_page_is_short_and_closes_has_more(db, attendance_seed):
    page = service.get_attendance_records_page(db, ORG, limit=10, offset=30)

    assert page["total"] == 35
    assert len(page["items"]) == 5
    assert page["hasMore"] is False


def test_offset_past_the_end_is_empty_but_total_survives(db, attendance_seed):
    """A client that pages until hasMore is false may over-shoot; total must not
    be scoped by the page, or the UI would show 'showing 0 of 0'."""
    page = service.get_attendance_records_page(db, ORG, limit=10, offset=35)

    assert page["items"] == []
    assert page["hasMore"] is False
    assert page["total"] == 35


def test_page_size_dividing_the_total_is_exact(db, attendance_seed):
    page = service.get_attendance_records_page(db, ORG, limit=7, offset=28)

    assert len(page["items"]) == 7
    assert page["hasMore"] is False


def test_ordering_is_newest_first(db, attendance_seed):
    page = service.get_attendance_records_page(db, ORG, limit=35)

    dates = [r["date"] for r in page["items"]]
    assert dates == sorted(dates, reverse=True)


def test_paging_the_whole_set_yields_every_row_exactly_once(db, attendance_seed):
    """The real reason a stable tiebreak matters: attendance rows share dates,
    so ordering by date alone can return a row on two pages and skip another.
    Offset paging needs a unique tiebreak to be correct."""
    seen = []
    offset = 0
    while True:
        page = service.get_attendance_records_page(db, ORG, limit=6, offset=offset)
        seen.extend(r["id"] for r in page["items"])
        if not page["hasMore"]:
            break
        offset += 6

    assert len(seen) == 35
    assert len(set(seen)) == 35


def test_date_range_narrows_total_and_has_more(db, attendance_seed):
    page = service.get_attendance_records_page(
        db, ORG, start_date=START, end_date=START + timedelta(days=9), limit=50,
    )

    # 10 days x 2 employees
    assert page["total"] == 20
    assert page["hasMore"] is False


def test_employee_filter_applies_to_items_and_total(db, attendance_seed):
    page = service.get_attendance_records_page(
        db, ORG, employee_id=attendance_seed["bob"], limit=50,
    )

    assert page["total"] == 10
    assert {r["employee_id"] for r in page["items"]} == {attendance_seed["bob"]}


def test_employee_filter_with_no_rows_is_empty_not_error(db, attendance_seed):
    page = service.get_attendance_records_page(db, ORG, employee_id=4242, limit=10)

    assert page["items"] == []
    assert page["total"] == 0
    assert page["hasMore"] is False


def test_outer_join_keeps_attendance_for_a_deleted_employee(db, attendance_seed):
    """An attendance row must survive its employee being removed; the paging
    count must still include it, otherwise totals silently shrink after a
    delete and the UI under-reports."""
    db.add(PayrollAttendanceRecord(
        organization_id=ORG, employee_id=9999, date=date(2026, 3, 1), status="present",
    ))
    db.commit()

    page = service.get_attendance_records_page(db, ORG, limit=100)

    assert page["total"] == 36
    orphan = [r for r in page["items"] if r["employee_id"] == 9999]
    assert len(orphan) == 1
    assert orphan[0]["name"] is None


def test_other_organizations_are_excluded(db, attendance_seed):
    """No organization filter bug that would leak another tenant's rows."""
    other = PayrollEmployee(
        organization_id=2, name="Other Tenant", employee_code="X001",
        status=EmployeeStatus.ACTIVE.value,
    )
    db.add(other)
    db.flush()
    leaked = PayrollAttendanceRecord(
        organization_id=2, employee_id=other.id, date=START, status="present",
    )
    db.add(leaked)
    db.commit()
    leaked_id = leaked.id

    page = service.get_attendance_records_page(db, ORG, limit=100)

    assert page["total"] == 35
    assert leaked_id not in {r["id"] for r in page["items"]}
    assert "Other Tenant" not in {r["name"] for r in page["items"]}


def test_legacy_list_reader_is_unchanged(db, attendance_seed):
    """Existing callers of get_attendance_records must keep getting a bare list,
    so the new endpoint is additive rather than a breaking change."""
    rows = service.get_attendance_records(db, ORG, limit=5)

    assert isinstance(rows, list)
    assert len(rows) == 5
    assert rows[0].keys() >= {
        "id", "employee_id", "name", "department", "designation", "date",
        "check_in", "check_out", "status", "leave_type", "is_half_day",
        "leave_request_id", "hours", "rewards", "bonus",
        "other_compensation", "notes",
    }


def test_has_more_is_false_when_a_page_exactly_ends_the_data(db, attendance_seed):
    """The boundary case that makes a `len(items) < limit` guess wrong: a full
    page that is also the last page."""
    page = service.get_attendance_records_page(db, ORG, limit=35, offset=0)

    assert len(page["items"]) == 35
    assert page["hasMore"] is False


def test_page_response_serializes_has_more_as_camel_case():
    """The frontend reads `hasMore`. FastAPI serializes this route by alias, so
    a rename here would silently make the UI page forever."""
    from app.modules.payroll.schemas import AttendancePageResponse

    payload = AttendancePageResponse(**{
        "items": [], "total": 0, "limit": 100, "offset": 0, "hasMore": False,
    }).model_dump(by_alias=True)

    assert payload["hasMore"] is False
    assert "has_more" not in payload


def test_date_span_covers_the_whole_filtered_set_not_just_the_page(db, attendance_seed):
    """A paged client needs the true range of the data to report the span,
    which it cannot get from whichever page it is holding."""
    page = service.get_attendance_records_page(db, ORG, limit=5, offset=0)

    # 25 days from 2026-01-01 for Ann; Bob shares the same window.
    assert page["firstDate"] == date(2026, 1, 1)
    assert page["lastDate"] == date(2026, 1, 25)


def test_date_span_is_narrowed_by_the_date_filter(db, attendance_seed):
    page = service.get_attendance_records_page(
        db, ORG, start_date=date(2026, 1, 5), end_date=date(2026, 1, 9), limit=50,
    )

    assert page["firstDate"] == date(2026, 1, 5)
    assert page["lastDate"] == date(2026, 1, 9)


def test_date_span_is_null_when_there_are_no_rows(db, attendance_seed):
    page = service.get_attendance_records_page(
        db, ORG, start_date=date(2020, 1, 1), end_date=date(2020, 1, 31),
    )

    assert page["items"] == []
    assert page["firstDate"] is None
    assert page["lastDate"] is None


def test_page_route_is_registered_with_bounded_limit():
    """limit is clamped at the router so a client cannot ask for the whole
    table and defeat the point of paging."""
    from app.modules.payroll.router import payroll_router

    route = next(
        (r for r in payroll_router.routes
         if getattr(r, "path", None) == "/payroll/attendance/page"),
        None,
    )
    assert route is not None, "GET /payroll/attendance/page is not registered"

    limit = next(p for p in route.dependant.query_params if p.name == "limit")
    assert limit.default == 100
    assert limit.field_info.metadata[-1].le == 1000
