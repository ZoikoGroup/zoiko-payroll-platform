"""
tests/test_attendance_xlsx_streaming.py
---------------------------------------
Unit and integration test suite for:
- Phase 2.3: Streaming XLSX Attendance Parser
- Phase 2.4: Bulk Employee IN Resolution
- Phase 2.5: Set-Based Collision Detection & Bulk Upsert
"""

from datetime import date, timedelta
from decimal import Decimal
import io
import openpyxl
import pytest
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.modules.payroll import service
from app.modules.payroll.attendance_importer import (
    import_attendance_from_stream,
    normalize_att_date,
    normalize_att_hours,
    normalize_att_status,
    normalize_att_time,
    stream_xlsx_records,
)
from app.modules.payroll.models import (
    EmployeeStatus,
    PayrollAttendanceRecord,
    PayrollEmployee,
)


@pytest.fixture(autouse=True)
def _eager_celery(db, monkeypatch):
    """Run Celery tasks locally against an in-memory result backend and test db."""
    from app.tasks import attendance_tasks
    monkeypatch.setitem(celery_app.conf, "result_backend", "cache+memory://")
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)
    monkeypatch.setitem(celery_app.conf, "task_eager_propagates", True)
    monkeypatch.setattr(attendance_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    yield


def _create_sample_xlsx_bytes(
    headers: list,
    rows: list,
    sheet_name: str = "Attendance",
) -> bytes:
    """Helper to generate an in-memory XLSX file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


@pytest.fixture()
def seeded_employees(db: Session, organization):
    """Seed test employees linked to a real Organization row."""
    org_id = organization.id
    e1 = PayrollEmployee(
        organization_id=org_id,
        employee_code="EMP001",
        name="Alice Smith",
        status=EmployeeStatus.ACTIVE.value,
        department="Engineering",
    )
    e2 = PayrollEmployee(
        organization_id=org_id,
        employee_code="EMP002",
        name="Bob Jones",
        status=EmployeeStatus.ACTIVE.value,
        department="Marketing",
    )
    e3 = PayrollEmployee(
        organization_id=org_id,
        employee_code="EMP003",
        name="Charlie Brown",
        status=EmployeeStatus.INACTIVE.value,
        department="Finance",
    )
    db.add_all([e1, e2, e3])
    db.commit()
    for e in (e1, e2, e3):
        db.refresh(e)
    return {"org_id": org_id, "alice": e1, "bob": e2, "charlie": e3}


def test_normalizers_defensive():
    """Assert normalizers handle dirty inputs gracefully without raising."""
    # Dates
    assert normalize_att_date("2026-05-15") == date(2026, 5, 15)
    assert normalize_att_date("15/05/2026") == date(2026, 5, 15)
    assert normalize_att_date("invalid-date") is None
    assert normalize_att_date("") is None

    # Times
    assert normalize_att_time("09:30") == "09:30"
    assert normalize_att_time("9:30 AM") == "09:30"
    assert normalize_att_time("5:45 PM") == "17:45"
    assert normalize_att_time("—") is None
    assert normalize_att_time("N/A") is None

    # Status
    assert normalize_att_status("Present") == "present"
    assert normalize_att_status("P") == "present"
    assert normalize_att_status("A") == "absent"
    assert normalize_att_status("Absent") == "absent"
    assert normalize_att_status("Sick") == "leave"
    assert normalize_att_status("Half Day") == "leave"

    # Hours (PayrollAttendanceRecord.hours string contract: invalid/negative -> '0.0')
    assert normalize_att_hours("8.5") == "8.5"
    assert normalize_att_hours(8) == "8.0"
    assert normalize_att_hours("-4.0") == "0.0"
    assert normalize_att_hours("not_a_number") == "0.0"
    assert normalize_att_hours(None) == "0.0"


def test_streaming_xlsx_generator_chunks():
    """Phase 2.3: stream_xlsx_records yields in bounded chunks."""
    headers = ["Employee ID", "Employee Name", "Date", "Status", "Hours"]
    rows = []
    base_date = date(2026, 1, 1)
    for i in range(120):
        rows.append([f"EMP{i:03d}", f"Emp {i}", (base_date + timedelta(days=i % 30)).isoformat(), "Present", "8.0"])

    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    chunks = list(stream_xlsx_records(xlsx_bytes, chunk_size=50))
    # 120 rows chunked by 50 should yield 3 chunks (50, 50, 20)
    assert len(chunks) == 3
    assert len(chunks[0]) == 50
    assert len(chunks[1]) == 50
    assert len(chunks[2]) == 20
    assert chunks[0][0]["employee_code"] == "EMP000"


def test_bulk_employee_in_resolution(db: Session, seeded_employees):
    """Phase 2.4: employee resolution resolves in batch and flags unknown/inactive."""
    org_id = seeded_employees["org_id"]
    headers = ["Employee Code", "Date", "Status", "Hours"]
    rows = [
        ["EMP001", "2026-06-01", "Present", "8.0"],
        ["EMP002", "2026-06-01", "Present", "7.5"],
        ["EMP003", "2026-06-01", "Present", "8.0"],  # Charlie (Inactive)
        ["UNKNOWN999", "2026-06-01", "Present", "8.0"],  # Unknown
    ]
    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    result = import_attendance_from_stream(db, org_id, xlsx_bytes)

    assert result["saved"] == 2  # Alice and Bob saved
    assert result["skipped"] == 2  # Charlie and UNKNOWN999 skipped

    # Verify skipped details contain specific reasons
    reasons = [d["reason"] for d in result["skippedDetails"]]
    assert any("not active" in r.lower() for r in reasons)
    assert any("no active employee matched" in r.lower() for r in reasons)

    # Verify DB records
    saved_recs = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == org_id
    ).all()
    assert len(saved_recs) == 2
    emp_ids = {r.employee_id for r in saved_recs}
    assert seeded_employees["alice"].id in emp_ids
    assert seeded_employees["bob"].id in emp_ids


def test_set_based_in_file_duplicate_detection(db: Session, seeded_employees):
    """Phase 2.5: In-file duplicate detection catches duplicate rows within the same file."""
    org_id = seeded_employees["org_id"]
    headers = ["Employee ID", "Date", "Status", "Hours"]
    rows = [
        ["EMP001", "2026-07-01", "Present", "8.0"],
        ["EMP001", "2026-07-01", "Present", "4.0"],  # Duplicate date for same employee in file
        ["EMP002", "2026-07-01", "Present", "8.0"],
    ]
    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    result = import_attendance_from_stream(db, org_id, xlsx_bytes)

    assert result["saved"] == 2
    assert result["skipped"] == 1
    assert "duplicate record in file" in result["skippedDetails"][0]["reason"].lower()


def test_database_collision_upsert(db: Session, seeded_employees):
    """Phase 2.5: Database collision updates existing record in place without IntegrityError."""
    org_id = seeded_employees["org_id"]
    alice = seeded_employees["alice"]
    initial_rec = PayrollAttendanceRecord(
        organization_id=org_id,
        employee_id=alice.id,
        date=date(2026, 8, 1),
        status="absent",
        hours="0.0",
    )
    db.add(initial_rec)
    db.commit()

    headers = ["Employee ID", "Date", "Status", "Hours", "Notes"]
    rows = [
        ["EMP001", "2026-08-01", "Present", "8.0", "Updated from upload"],
        ["EMP002", "2026-08-01", "Present", "8.0", "New record"],
    ]
    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    result = import_attendance_from_stream(db, org_id, xlsx_bytes, skip_duplicates=False)

    assert result["saved"] == 2
    assert result["skipped"] == 0

    # Query DB and verify updated in place
    db_alice = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == org_id,
        PayrollAttendanceRecord.employee_id == alice.id,
        PayrollAttendanceRecord.date == date(2026, 8, 1),
    ).one()
    assert db_alice.status == "present"
    assert db_alice.hours == "8.0"
    assert db_alice.notes == "Updated from upload"


def test_database_collision_skip_duplicates_policy(db: Session, seeded_employees):
    """Phase 2.5: With skip_duplicates=True, existing DB records are skipped."""
    org_id = seeded_employees["org_id"]
    alice = seeded_employees["alice"]
    initial_rec = PayrollAttendanceRecord(
        organization_id=org_id,
        employee_id=alice.id,
        date=date(2026, 9, 1),
        status="present",
        hours="8.0",
    )
    db.add(initial_rec)
    db.commit()

    headers = ["Employee ID", "Date", "Status", "Hours"]
    rows = [
        ["EMP001", "2026-09-01", "Absent", "0.0"],
        ["EMP002", "2026-09-01", "Present", "8.0"],
    ]
    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    result = import_attendance_from_stream(db, org_id, xlsx_bytes, skip_duplicates=True)

    assert result["saved"] == 1  # Only EMP002 saved
    assert result["skipped"] == 1  # EMP001 skipped because already exists
    assert "already exists in database" in result["skippedDetails"][0]["reason"].lower()


def test_malformed_rows_graceful_degradation(db: Session, seeded_employees):
    """Malformed dates or invalid rows skip isolated rows without aborting valid ones."""
    org_id = seeded_employees["org_id"]
    headers = ["Employee ID", "Date", "Status", "Hours"]
    rows = [
        ["EMP001", "invalid-date", "Present", "8.0"],  # Malformed date
        ["EMP001", "2026-10-01", "Present", "-99.0"],  # Negative hours -> clamp to 0.0
        ["", "2026-10-01", "Present", "8.0"],  # Missing employee
    ]
    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    result = import_attendance_from_stream(db, org_id, xlsx_bytes)

    assert result["saved"] == 1  # The valid row with clamped hours
    assert result["skipped"] == 2

    # Check clamped hours
    alice = seeded_employees["alice"]
    rec = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == org_id,
        PayrollAttendanceRecord.employee_id == alice.id,
        PayrollAttendanceRecord.date == date(2026, 10, 1),
    ).one()
    assert rec.hours == "0.0"


def test_celery_task_integration(monkeypatch, seeded_employees):
    """Verify Celery task bulk_upload_attendance_task executes end-to-end."""
    import base64
    from app.tasks.attendance_tasks import bulk_upload_attendance_task

    org_id = seeded_employees["org_id"]
    headers = ["Employee ID", "Date", "Status", "Hours"]
    rows = [
        ["EMP001", "2026-11-01", "Present", "8.0"],
        ["EMP002", "2026-11-01", "Present", "7.5"],
    ]
    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)
    b64_content = base64.b64encode(xlsx_bytes).decode("ascii")

    # Run eager task
    result = bulk_upload_attendance_task.apply(
        args=(org_id, b64_content, "test.xlsx")
    ).get()

    assert result["saved"] == 2
    assert result["skipped"] == 0


def test_streaming_1000_rows_scalability(db: Session, seeded_employees):
    """Phase 2.3 & 2.4: 1,000 rows stream in chunks of 500 without memory bloat."""
    org_id = seeded_employees["org_id"]
    headers = ["Employee ID", "Date", "Status", "Hours"]
    rows = []
    base_date = date(2026, 1, 1)
    # Generate 500 rows for Alice and 500 rows for Bob
    for i in range(500):
        rows.append(["EMP001", (base_date + timedelta(days=i)).isoformat(), "Present", "8.0"])
    for i in range(500):
        rows.append(["EMP002", (base_date + timedelta(days=i)).isoformat(), "Present", "8.0"])

    xlsx_bytes = _create_sample_xlsx_bytes(headers, rows)

    result = import_attendance_from_stream(db, org_id, xlsx_bytes, chunk_size=500)

    assert result["saved"] == 1000
    assert result["skipped"] == 0
    assert result["totalProcessed"] == 1000

    # Total in DB
    total_db = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == org_id
    ).count()
    assert total_db == 1000
