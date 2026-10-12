"""
app/tasks/employee_tasks.py
-----------------------------
Celery tasks for employee bulk operations.

Handles asynchronous bulk employee create, update, and delete operations.
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import date

from app.database import SessionLocal
from app.modules.payroll import service as payroll_service
from app.modules.payroll.models import PayrollEmployee, EmployeeStatus
from app.modules.payroll.schemas import BulkEmployeeItem, BulkEmployeeRequest
from app.core.exceptions import NotFoundException, BadRequestException

logger = get_task_logger(__name__)


def get_db() -> Session:
    """Get a new database session for the task."""
    return SessionLocal()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="employees",
)
def bulk_create_employees_task(self, organization_id: int, employees_data: List[Dict[str, Any]],
                                actor_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Bulk create employees from imported data.
    
    Args:
        organization_id: Organization ID
        employees_data: List of employee data dicts
        actor_id: ID of user performing the action
        
    Returns:
        Dict with creation results
    """
    db = SessionLocal()
    try:
        # Convert to BulkEmployeeItem objects
        employee_items = [BulkEmployeeItem(**emp) for emp in employees_data]
        request = BulkEmployeeRequest(employees=employee_items)
        
        result = payroll_service.bulk_create_employees(db, request, organization_id, actor_id)
        
        return {
            "status": "completed",
            "created": result["created"],
            "failed": len(result["failed"]),
            "failed_details": result["failed"],
        }
    except Exception as exc:
        logger.error(f"Bulk employee creation failed: {exc}")
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="employees",
)
def bulk_update_employees_task(self, organization_id: int, employees_data: List[Dict[str, Any]],
                                actor_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Bulk update employees from imported data.
    
    Args:
        organization_id: Organization ID
        employees_data: List of employee data dicts with IDs
        actor_id: ID of user performing the action
        
    Returns:
        Dict with update results
    """
    db = SessionLocal()
    try:
        employee_items = [BulkEmployeeItem(**emp) for emp in employees_data]
        request = BulkEmployeeRequest(employees=employee_items)
        
        result = payroll_service.bulk_update_employees(db, request, organization_id, actor_id)
        
        return {
            "status": "completed",
            "updated": result.get("updated", 0),
            "failed": len(result.get("failed", [])),
            "failed_details": result.get("failed", []),
        }
    except Exception as exc:
        logger.error(f"Bulk employee update failed: {exc}")
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="employees",
)
def bulk_delete_employees_task(self, organization_id: int, employee_ids: List[int],
                                actor_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Bulk delete employees.
    
    Args:
        organization_id: Organization ID
        employee_ids: List of employee IDs to delete
        actor_id: ID of user performing the action
        
    Returns:
        Dict with deletion results
    """
    db = SessionLocal()
    try:
        from app.modules.payroll.schemas import BulkDeleteRequest
        
        request = BulkDeleteRequest(ids=employee_ids)
        result = payroll_service.bulk_delete_employees(db, request, organization_id, actor_id)
        
        return {
            "status": "completed",
            "deleted": result.get("deleted", 0),
            "failed": len(result.get("failed", [])),
            "failed_details": result.get("failed", []),
        }
    except Exception as exc:
        logger.error(f"Bulk employee deletion failed: {exc}")
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="employees",
)
def import_employees_from_xlsx_task(self, organization_id: int, file_content_b64: str,
                                     filename: str, actor_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Import employees from XLSX file.
    
    Args:
        organization_id: Organization ID
        file_content_b64: Base64-encoded XLSX file content
        filename: Original filename
        actor_id: ID of user performing the action
        
    Returns:
        Dict with import results
    """
    db = SessionLocal()
    try:
        import base64
        import io
        import openpyxl
        from app.modules.payroll.service import bulk_create_employees
        from app.modules.payroll.schemas import BulkEmployeeRequest, BulkEmployeeItem
        
        # Decode file
        file_content = base64.b64decode(file_content_b64)
        workbook = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
        
        # Parse first sheet
        sheet = workbook.worksheets[0]
        headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
        
        # Map headers to fields
        field_map = {
            "name": "name",
            "email": "email",
            "employee_code": "employee_code",
            "department": "department",
            "designation": "designation",
            "date_of_joining": "date_of_joining",
            "date_of_birth": "date_of_birth",
            "phone": "phone",
            "address": "address",
            "country_code": "country_code",
            "work_state": "work_state",
            "status": "status",
        }
        
        employees_data = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            row_data = dict(zip(headers, row))
            emp_data = {}
            for header, field in field_map.items():
                if header in row_data and row_data[header] is not None:
                    emp_data[field] = row_data[header]
            
            if emp_data.get("name") and emp_data.get("email"):
                employees_data.append(BulkEmployeeItem(**emp_data))
        
        if not employees_data:
            return {"status": "error", "message": "No valid employee data found in file"}
        
        request = BulkEmployeeRequest(employees=employees_data)
        
        # Report what bulk_create_employees actually did. Counting parsed rows
        # here would report every row as created, including the ones the
        # service rejected as duplicates or invalid.
        result = payroll_service.bulk_create_employees(
            db, request, organization_id, None,
        )

        return {
            "status": "completed",
            "total_rows": len(employees_data),
            "created": result["created"],
            "failed": len(result["failed"]),
            "failed_details": result["failed"],
        }
    except Exception as exc:
        logger.error(f"Employee XLSX import failed: {exc}")
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="employees",
)
def sync_employee_statutory_profiles_task(self, organization_id: int, country: str) -> Dict[str, Any]:
    """
    Sync employee statutory profiles for a country.
    
    Args:
        organization_id: Organization ID
        country: Country code
        
    Returns:
        Dict with sync results
    """
    db = SessionLocal()
    try:
        raise NotImplementedError(
            "sync_employee_statutory_profiles_task is not implemented: this task has "
            "no bulk statutory-profile sync. It is kept in the registry so the intended "
            "surface stays visible, but it fails loudly rather than returning a "
            "fabricated result. Implement it before enqueueing it anywhere."
        )
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="employees",
)
def export_employees_task(self, organization_id: int, format: str = "xlsx",
                           filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Export employees to file.
    
    Args:
        organization_id: Organization ID
        format: Export format (xlsx, csv)
        filters: Optional filters
        
    Returns:
        Dict with export result
    """
    db = SessionLocal()
    try:
        raise NotImplementedError(
            "export_employees_task is not implemented: this task has no export "
            "writer; the returned URL would 404. It is kept in the registry so the "
            "intended surface stays visible, but it fails loudly rather than "
            "returning a fabricated result. Implement it before enqueueing it "
            "anywhere."
        )
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="employees",
)
def sync_employee_statutory_profile_task(self, organization_id: int, employee_id: int,
                                          country: str, profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sync a single employee's statutory profile.
    
    Args:
        organization_id: Organization ID
        employee_id: Employee ID
        country: Country code
        profile_data: Profile data
        
    Returns:
        Dict with sync result
    """
    db = SessionLocal()
    try:
        from app.modules.payroll.service import create_employee_statutory_profile_version
        from app.modules.payroll.schemas import EmployeeStatutoryProfileCreate

        # Signature is (db, employee_id, organization_id, data, actor_id, ...)
        profile_create = EmployeeStatutoryProfileCreate(**profile_data)
        profile = payroll_service.create_employee_statutory_profile_version(
            db, employee_id, organization_id, profile_create, None,
        )
        
        return {"status": "completed", "profile_id": profile.id}
    finally:
        db.close()