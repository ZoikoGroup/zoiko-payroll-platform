"""
app/tasks/attendance_tasks.py
------------------------------
Celery tasks for attendance processing.

Handles asynchronous bulk attendance upload, processing, and validation.
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.modules.payroll import service as payroll_service
from app.modules.payroll.models import PayrollAttendanceRecord, PayrollEmployee
from app.core.exceptions import NotFoundException

logger = get_task_logger(__name__)


def get_db() -> Session:
    """Get a new database session for the task."""
    return SessionLocal()


import base64
from app.modules.payroll.attendance_importer import import_attendance_from_stream


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="attendance",
)
def bulk_upload_attendance_task(self, organization_id: int, file_content_b64: str, 
                                  filename: str, upload_mode: str = "day",
                                  upload_month: Optional[int] = None,
                                  upload_year: Optional[int] = None,
                                  standard_hours: float = 8.0):
    """Phase 2.3: stream XLSX attendance file and bulk upsert records."""
    file_bytes = base64.b64decode(file_content_b64)
    db = SessionLocal()
    try:
        result = import_attendance_from_stream(
            db=db,
            organization_id=organization_id,
            file_source=file_bytes,
            chunk_size=500,
            skip_duplicates=False,
        )
        logger.info(
            "bulk_upload_attendance_task completed for org %s: saved=%s, skipped=%s",
            organization_id,
            result.get("saved"),
            result.get("skipped"),
        )
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("Failed bulk_upload_attendance_task for org %s: %s", organization_id, exc)
        raise exc
    finally:
        db.close()
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="attendance",
)
def bulk_generate_attendance_task(self, organization_id: int, employee_ids: List[int],
                                   start_date: str, end_date: str,
                                   check_in: str, check_out: str,
                                   check_in_period: str = "AM", check_out_period: str = "PM",
                                   break_minutes: int = 60, exclude_weekends: bool = True,
                                   exclude_holidays: bool = True):
    """
    Generate bulk attendance records for a date range.
    
    Args:
        organization_id: Organization ID
        employee_ids: List of employee IDs
        start_date: Start date (ISO format)
        end_date: End date (ISO format)
        check_in: Check-in time (HH:MM)
        check_out: Check-out time (HH:MM)
        check_in_period: AM/PM
        check_out_period: AM/PM
        break_minutes: Break minutes
        exclude_weekends: Exclude weekends
        exclude_holidays: Exclude holidays
        
    Returns:
        Dict with generation results
    """
    db = SessionLocal()
    try:
        raise NotImplementedError(
            "bulk_generate_attendance_task is not implemented: this task calls "
            "payroll_service.save_attendance_records, which does not exist (the "
            "real entry point is bulk_save_attendance(db, BulkAttendanceRequest, "
            "organization_id)), and service.get_holidays, which also does not "
            "exist. It is kept in the registry so the intended surface stays "
            "visible, but it fails loudly rather than writing a partial batch and "
            "reporting success. Implement it before enqueueing it anywhere."
        )
    finally:
        db.close()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
    queue="attendance",
)
def validate_attendance_upload_task(self, organization_id: int, file_content_b64: str,
                                     filename: str) -> Dict[str, Any]:
    """
    Validate attendance upload file without saving.
    
    Returns validation results with any errors/warnings.
    """
    db = SessionLocal()
    try:
        raise NotImplementedError(
            "validate_attendance_upload_task is not implemented: it opened the "
            "workbook, counted sheets, and returned valid=True without checking a "
            "single row, so it would tell an operator their file was clean when "
            "nothing had been verified. It is kept in the registry so the intended "
            "surface stays visible, but it fails loudly rather than returning a "
            "fabricated result. Implement it before enqueueing it anywhere."
        )
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="attendance",
)
def generate_attendance_report_task(self, organization_id: int, start_date: str, 
                                     end_date: str, format: str = "xlsx") -> Dict[str, Any]:
    """
    Generate attendance report for a date range.
    
    Args:
        organization_id: Organization ID
        start_date: Start date (ISO format)
        end_date: End date (ISO format)
        format: Output format (xlsx, csv, pdf)
        
    Returns:
        Dict with report generation result
    """
    db = SessionLocal()
    try:
        raise NotImplementedError(
            "generate_attendance_report_task is not implemented: this task has no "
            "attendance report renderer; the returned URL would 404. It is kept in "
            "the registry so the intended surface stays visible, but it fails "
            "loudly rather than returning a fabricated result. Implement it before "
            "enqueueing it anywhere."
        )
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="attendance",
)
def sync_attendance_to_leave_task(self, organization_id: int, start_date: str, end_date: str):
    """
    Sync attendance records to leave requests for the date range.
    
    Args:
        organization_id: Organization ID
        start_date: Start date (ISO format)
        end_date: End date (ISO format)
    """
    db = SessionLocal()
    try:
        raise NotImplementedError(
            "sync_attendance_to_leave_task is not implemented: this task calls "
            "payroll_service.sync_attendance_to_leave, which does not exist. It is "
            "kept in the registry so the intended surface stays visible, but it "
            "fails loudly rather than returning a fabricated result. Implement it "
            "before enqueueing it anywhere."
        )
    finally:
        db.close()