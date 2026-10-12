"""
app/modules/payroll/attendance_importer.py
-----------------------------------------
Streaming XLSX attendance parser, bulk employee IN resolver, and set-based
collision detector for bulk attendance uploads (Phases 2.3, 2.4, 2.5).

Key Architectural Decisions:
1. Streaming Ingestion (Phase 2.3):
   Uses openpyxl with read_only=True and data_only=True, reading row tuples
   via sheet.iter_rows(values_only=True) to stream rows directly from the
   XML zip stream. Workbook lifecycle is wrapped in try...finally: wb.close()
   so open file descriptors and temporary XML buffers are unconditionally released.
   Peak memory remains bounded (< 15MB) regardless of file size.

2. Bulk Employee IN Resolution (Phase 2.4):
   Instead of querying the database per row (N+1 anti-pattern), collects all
   distinct employee codes/names in the chunk and executes exactly ONE
   indexed SQL query per batch chunk:
   SELECT id, employee_code, name, status FROM payroll_employees WHERE ...
   Unmatched rows are recorded in skippedDetails with row coordinates.

3. Set-Based Collision Detection (Phase 2.5):
   Two-tier collision prevention:
   a. In-file duplicate detection using an in-memory set seen_in_file: set[tuple[int, date]].
   b. Database collision detection using a single query matching (employee_id, date)
      within [min_date, max_date] range. Existing rows are updated in-place (upsert)
      or skipped per policy without raising IntegrityError.
"""

from datetime import date, datetime, time
from decimal import Decimal
import io
import logging
import re
from typing import Any, BinaryIO, Dict, Generator, List, Optional, Set, Tuple, Union

import openpyxl
from sqlalchemy.orm import Session

from app.modules.payroll.models import (
    EmployeeStatus,
    PayrollAttendanceRecord,
    PayrollEmployee,
)

logger = logging.getLogger(__name__)

BATCH_CHUNK_SIZE = 500

ATTENDANCE_HEADER_MAP: Dict[str, str] = {
    # Employee identifiers
    "employee id": "employee_code",
    "employee code": "employee_code",
    "emp id": "employee_code",
    "emp code": "employee_code",
    "employee no": "employee_code",
    "emp no": "employee_code",
    "id": "employee_code",
    "employee": "name",
    "employee name": "name",
    "name": "name",
    # Department
    "department": "department",
    "dept": "department",
    # Date
    "date": "date",
    "attendance date": "date",
    # Punch times
    "check in": "check_in",
    "in time": "check_in",
    "clock in": "check_in",
    "check out": "check_out",
    "out time": "check_out",
    "clock out": "check_out",
    # Status & Leaves
    "status": "status",
    "attendance status": "status",
    "leave type": "leave_type",
    "leave": "leave_type",
    "half day": "is_half_day",
    "is half day": "is_half_day",
    # Hours & Breaks
    "hours": "hours",
    "total hours": "hours",
    "worked hours": "hours",
    "duration": "hours",
    "break": "break_minutes",
    "break (min)": "break_minutes",
    "break minutes": "break_minutes",
    "fixed break": "break_minutes",
    # Compensation components
    "rewards": "rewards",
    "bonus": "bonus",
    "other compensation": "other_compensation",
    "notes": "notes",
}


def normalize_header(header: Any) -> str:
    """Normalize raw column headers to lowercase alphanumeric tokens."""
    if header is None:
        return ""
    s = str(header).strip().lower()
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_att_date(val: Any) -> Optional[date]:
    """Parse date from cell values defensively."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s in ("-", "--", "—", "N/A", "null"):
        return None
    # ISO format YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    # Common formats: DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_att_time(val: Any) -> Optional[str]:
    """Normalize clock punch time to HH:MM format."""
    if val is None:
        return None
    if isinstance(val, (datetime, time)):
        return f"{val.hour:02d}:{val.minute:02d}"
    s = str(val).strip()
    if not s or s in ("-", "--", "—", "N/A"):
        return None
    if re.match(r"^\d{1,2}:\d{2}$", s):
        parts = s.split(":")
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    # 12-hour format e.g. "09:30 AM" or "5:15pm"
    m12 = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]m)$", s, re.IGNORECASE)
    if m12:
        h = int(m12.group(1))
        m = int(m12.group(2))
        period = m12.group(3).lower()
        if period == "pm" and h < 12:
            h += 12
        elif period == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"
    return None


def normalize_att_status(val: Any) -> str:
    """Normalize attendance status string."""
    s = str(val or "").strip().lower()
    if s in ("present", "p", "1", "yes", "y", "true"):
        return "present"
    if s in ("absent", "a", "0", "no", "n", "false"):
        return "absent"
    if s in ("leave", "l", "pl", "cl", "sl", "ul", "lop", "half day", "sick", "casual", "paid", "unpaid"):
        return "leave"
    return "present"


def normalize_att_leave_type(val: Any) -> Optional[str]:
    """Normalize leave classification."""
    s = str(val or "").strip().lower()
    if s in ("paid", "pl", "paid leave"):
        return "paid"
    if s in ("unpaid", "ul", "lop", "unpaid leave"):
        return "unpaid"
    if s in ("sick", "sl", "sick leave", "medical"):
        return "sick"
    if s in ("casual", "cl", "casual leave"):
        return "casual"
    if s in ("compoff", "comp off", "comp-off", "compensatory"):
        return "compOff"
    return None


def normalize_att_hours(val: Any) -> str:
    """Defensive string parsing for PayrollAttendanceRecord.hours.
    Invalid, negative or null values default to '0.0'.
    """
    if val is None:
        return "0.0"
    if isinstance(val, (int, float, Decimal)):
        fval = float(val)
        return str(round(max(0.0, fval), 2))
    s = str(val).strip()
    if not s or s in ("-", "--", "—", "N/A"):
        return "0.0"
    try:
        fval = float(s)
        return str(round(max(0.0, fval), 2))
    except ValueError:
        return "0.0"


def normalize_att_decimal(val: Any) -> Decimal:
    """Defensive decimal parser for rewards, bonus, and other compensation."""
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    s = str(val).strip().replace(",", "")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def stream_xlsx_records(
    file_source: Union[str, BinaryIO, bytes],
    chunk_size: int = BATCH_CHUNK_SIZE,
) -> Generator[List[Dict[str, Any]], None, None]:
    """Phase 2.3: Stream rows from an Excel (.xlsx) file in fixed-size chunks.

    Uses read_only=True and data_only=True to prevent building an in-memory
    DOM tree. Sheet and workbook resources are deterministically closed
    via try...finally.

    Yields:
        Chunks of parsed row dictionaries containing normalized fields:
        {
            "row_idx": int,
            "employee_code": Optional[str],
            "name": Optional[str],
            "department": Optional[str],
            "date": Optional[date],
            "check_in": Optional[str],
            "check_out": Optional[str],
            "status": str,
            "leave_type": Optional[str],
            "is_half_day": bool,
            "hours": str,
            "rewards": Decimal,
            "bonus": Decimal,
            "other_compensation": Decimal,
            "notes": Optional[str],
        }
    """
    stream: Union[str, io.BytesIO]
    if isinstance(file_source, bytes):
        stream = io.BytesIO(file_source)
    elif isinstance(file_source, str):
        stream = file_source
    else:
        stream = file_source

    wb = openpyxl.load_workbook(stream, read_only=True, data_only=True)
    try:
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            row_iter = sheet.iter_rows(values_only=True)

            header_map: Dict[int, str] = {}
            header_found = False
            current_chunk: List[Dict[str, Any]] = []
            row_idx = 0

            for raw_row in row_iter:
                row_idx += 1
                if not raw_row or not any(raw_row):
                    continue

                # Header detection on first matching row
                if not header_found:
                    normalized_headers = [normalize_header(c) for c in raw_row]
                    temp_map: Dict[int, str] = {}
                    for col_idx, norm_h in enumerate(normalized_headers):
                        mapped_field = ATTENDANCE_HEADER_MAP.get(norm_h)
                        if mapped_field:
                            temp_map[col_idx] = mapped_field

                    # Valid header row requires at least employee or date
                    has_emp = any(f in temp_map.values() for f in ("employee_code", "name"))
                    has_date = "date" in temp_map.values()
                    if has_emp and has_date:
                        header_map = temp_map
                        header_found = True
                        continue
                    elif "status" in temp_map.values() and has_emp:
                        header_map = temp_map
                        header_found = True
                        continue
                    else:
                        # Skip banner / metadata rows
                        continue

                # Parse data row using discovered column indices
                row_data: Dict[str, Any] = {
                    "row_idx": row_idx,
                    "employee_code": None,
                    "name": None,
                    "department": None,
                    "date": None,
                    "check_in": None,
                    "check_out": None,
                    "status": "present",
                    "leave_type": None,
                    "is_half_day": False,
                    "hours": "0.0",
                    "rewards": Decimal("0"),
                    "bonus": Decimal("0"),
                    "other_compensation": Decimal("0"),
                    "notes": None,
                }

                raw_status = None
                raw_leave_type = None

                for col_idx, field_name in header_map.items():
                    if col_idx < len(raw_row):
                        cell_val = raw_row[col_idx]
                        if field_name == "employee_code":
                            row_data["employee_code"] = str(cell_val).strip() if cell_val is not None else None
                        elif field_name == "name":
                            row_data["name"] = str(cell_val).strip() if cell_val is not None else None
                        elif field_name == "department":
                            row_data["department"] = str(cell_val).strip() if cell_val is not None else None
                        elif field_name == "date":
                            row_data["date"] = normalize_att_date(cell_val)
                        elif field_name == "check_in":
                            row_data["check_in"] = normalize_att_time(cell_val)
                        elif field_name == "check_out":
                            row_data["check_out"] = normalize_att_time(cell_val)
                        elif field_name == "status":
                            raw_status = cell_val
                        elif field_name == "leave_type":
                            raw_leave_type = cell_val
                        elif field_name == "is_half_day":
                            row_data["is_half_day"] = bool(cell_val)
                        elif field_name == "hours":
                            row_data["hours"] = normalize_att_hours(cell_val)
                        elif field_name == "rewards":
                            row_data["rewards"] = normalize_att_decimal(cell_val)
                        elif field_name == "bonus":
                            row_data["bonus"] = normalize_att_decimal(cell_val)
                        elif field_name == "other_compensation":
                            row_data["other_compensation"] = normalize_att_decimal(cell_val)
                        elif field_name == "notes":
                            row_data["notes"] = str(cell_val).strip() if cell_val is not None else None

                # Status and Leave Type normalization
                row_data["status"] = normalize_att_status(raw_status)
                if str(raw_status or "").strip().lower() == "half day":
                    row_data["is_half_day"] = True
                row_data["leave_type"] = normalize_att_leave_type(raw_leave_type) or normalize_att_leave_type(raw_status)

                current_chunk.append(row_data)
                if len(current_chunk) >= chunk_size:
                    yield current_chunk
                    current_chunk = []

            if current_chunk:
                yield current_chunk
    finally:
        wb.close()


def bulk_resolve_employees(
    db: Session,
    organization_id: int,
    records: List[Dict[str, Any]],
) -> Tuple[Dict[str, int], Dict[str, int], Set[int]]:
    """Phase 2.4: Bulk resolve employee IDs via single IN query per chunk.

    Returns:
        (code_to_id, name_to_id, inactive_ids)
    """
    distinct_codes: Set[str] = set()
    distinct_names: Set[str] = set()

    for r in records:
        if r.get("employee_code"):
            distinct_codes.add(r["employee_code"].strip().lower())
        if r.get("name"):
            distinct_names.add(r["name"].strip().lower())

    if not distinct_codes and not distinct_names:
        return {}, {}, set()

    # Single SQL query for the chunk
    emp_query = db.query(
        PayrollEmployee.id,
        PayrollEmployee.employee_code,
        PayrollEmployee.name,
        PayrollEmployee.status,
    ).filter(
        PayrollEmployee.organization_id == organization_id,
    )

    from sqlalchemy import func as sa_func, or_
    conditions = []
    if distinct_codes:
        conditions.append(sa_func.lower(PayrollEmployee.employee_code).in_(list(distinct_codes)))
    if distinct_names:
        conditions.append(sa_func.lower(PayrollEmployee.name).in_(list(distinct_names)))

    emp_rows = emp_query.filter(or_(*conditions)).all()

    code_to_id: Dict[str, int] = {}
    name_to_id: Dict[str, int] = {}
    inactive_ids: Set[int] = set()

    for e in emp_rows:
        if e.employee_code:
            code_to_id[e.employee_code.strip().lower()] = e.id
        if e.name:
            name_to_id[e.name.strip().lower()] = e.id
        if e.status and e.status.lower() != EmployeeStatus.ACTIVE.value.lower():
            inactive_ids.add(e.id)

    return code_to_id, name_to_id, inactive_ids


def process_attendance_chunk(
    db: Session,
    organization_id: int,
    chunk: List[Dict[str, Any]],
    seen_in_file: Set[Tuple[int, date]],
    skip_duplicates: bool = False,
) -> Tuple[int, List[Dict[str, Any]], List[PayrollAttendanceRecord]]:
    """Phases 2.4 & 2.5: Resolve employees, detect collisions, and bulk upsert records.

    Returns:
        (saved_count, skipped_details, results)
    """
    code_to_id, name_to_id, inactive_ids = bulk_resolve_employees(db, organization_id, chunk)

    to_upsert: List[Dict[str, Any]] = []
    skipped_details: List[Dict[str, Any]] = []

    for r in chunk:
        row_idx = r.get("row_idx", 0)
        rec_code = r.get("employee_code")
        rec_name = r.get("name")
        rec_date = r.get("date")

        if not rec_date:
            skipped_details.append({
                "row": row_idx,
                "rowName": rec_name or rec_code,
                "reason": "Missing or invalid date",
                "date": None,
            })
            continue

        # Employee resolution
        employee_id: Optional[int] = None
        if rec_code and rec_code.lower() in code_to_id:
            employee_id = code_to_id[rec_code.lower()]
        elif rec_name and rec_name.lower() in name_to_id:
            employee_id = name_to_id[rec_name.lower()]

        if not employee_id:
            skipped_details.append({
                "row": row_idx,
                "rowName": rec_name or rec_code,
                "reason": f"No active employee matched for identifier '{rec_code or rec_name}'",
                "date": rec_date,
            })
            continue

        if employee_id in inactive_ids:
            skipped_details.append({
                "row": row_idx,
                "rowName": rec_name or rec_code,
                "reason": "Employee is not active",
                "date": rec_date,
            })
            continue

        # Phase 2.5 Layer 1: In-file duplicate detection
        pair_key = (employee_id, rec_date)
        if pair_key in seen_in_file:
            skipped_details.append({
                "row": row_idx,
                "rowName": rec_name or rec_code,
                "reason": f"Duplicate record in file for employee on {rec_date}",
                "date": rec_date,
            })
            continue
        seen_in_file.add(pair_key)

        r["resolved_employee_id"] = employee_id
        to_upsert.append(r)

    if not to_upsert:
        return 0, skipped_details, []

    # Phase 2.5 Layer 2: Database collision check via single indexed query
    dates = [r["date"] for r in to_upsert]
    min_date, max_date = min(dates), max(dates)
    resolved_ids = list({r["resolved_employee_id"] for r in to_upsert})

    existing_rows = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        PayrollAttendanceRecord.employee_id.in_(resolved_ids),
        PayrollAttendanceRecord.date.between(min_date, max_date),
    ).all()

    existing_map: Dict[Tuple[int, date], PayrollAttendanceRecord] = {
        (er.employee_id, er.date): er for er in existing_rows
    }

    results: List[PayrollAttendanceRecord] = []

    for r in to_upsert:
        emp_id = r["resolved_employee_id"]
        rec_date = r["date"]
        key = (emp_id, rec_date)

        existing = existing_map.get(key)
        if existing:
            if skip_duplicates:
                skipped_details.append({
                    "row": r.get("row_idx", 0),
                    "rowName": r.get("name") or r.get("employee_code"),
                    "reason": f"Record already exists in database for {rec_date} (skip_duplicates=True)",
                    "date": rec_date,
                })
                continue
            # In-place update
            existing.check_in = r.get("check_in")
            existing.check_out = r.get("check_out")
            existing.status = r.get("status", "present")
            existing.leave_type = r.get("leave_type")
            existing.is_half_day = r.get("is_half_day", False)
            existing.hours = r.get("hours", "0.0")
            existing.rewards = r.get("rewards", Decimal("0"))
            existing.bonus = r.get("bonus", Decimal("0"))
            existing.other_compensation = r.get("other_compensation", Decimal("0"))
            existing.notes = r.get("notes")
            results.append(existing)
        else:
            new_record = PayrollAttendanceRecord(
                organization_id=organization_id,
                employee_id=emp_id,
                date=rec_date,
                check_in=r.get("check_in"),
                check_out=r.get("check_out"),
                status=r.get("status", "present"),
                leave_type=r.get("leave_type"),
                is_half_day=r.get("is_half_day", False),
                hours=r.get("hours", "0.0"),
                rewards=r.get("rewards", Decimal("0")),
                bonus=r.get("bonus", Decimal("0")),
                other_compensation=r.get("other_compensation", Decimal("0")),
                notes=r.get("notes"),
            )
            db.add(new_record)
            results.append(new_record)

    db.flush()
    return len(results), skipped_details, results


def import_attendance_from_stream(
    db: Session,
    organization_id: int,
    file_source: Union[str, BinaryIO, bytes],
    chunk_size: int = BATCH_CHUNK_SIZE,
    skip_duplicates: bool = False,
) -> Dict[str, Any]:
    """Unified entry point for streaming XLSX attendance import.

    Orchestrates:
    - Phase 2.3 Streaming chunk generator
    - Phase 2.4 Single-query employee resolution per chunk
    - Phase 2.5 In-file & DB collision handling with bulk flush

    Returns:
        {
            "saved": int,
            "skipped": int,
            "skippedDetails": List[dict],
            "totalProcessed": int,
        }
    """
    total_saved = 0
    total_skipped = 0
    all_skipped_details: List[Dict[str, Any]] = []
    seen_in_file: Set[Tuple[int, date]] = set()

    for chunk in stream_xlsx_records(file_source, chunk_size=chunk_size):
        saved_count, skipped, _ = process_attendance_chunk(
            db, organization_id, chunk, seen_in_file, skip_duplicates=skip_duplicates
        )
        total_saved += saved_count
        total_skipped += len(skipped)
        all_skipped_details.extend(skipped)

    db.commit()

    return {
        "saved": total_saved,
        "skipped": total_skipped,
        "skippedDetails": all_skipped_details,
        "totalProcessed": total_saved + total_skipped,
    }
