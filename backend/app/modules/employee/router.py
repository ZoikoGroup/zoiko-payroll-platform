"""
modules/employee/router.py
--------------------------
Employee self-service (ESS) endpoints for the standalone Payroll Platform.

An employee account is matched to its PayrollEmployee record by email (the
payroll employee master is the single employee source of truth; there is no
HR module). Every endpoint is restricted to the caller's own record and own
organization.

Also exposes a minimal payroll-employee listing for org-scoped admins that
prefer the /hr-style path (the full CRUD lives in /payroll/employees).
"""

import io
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_employee,
    get_current_org_admin,
    get_current_user,
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.auth.models import UserRole
from app.modules.employee.schemas import MyPayslipsResponse, MyProfileResponse

router = APIRouter(prefix="/employee", tags=["Employee Self-Service"])
hr_router = APIRouter(prefix="/hr", tags=["Employees"])


def _my_employee(db: Session, user):
    from app.modules.payroll.models import PayrollEmployee

    if not user.email:
        raise NotFoundException("Employee", "email")
    employee = (
        db.query(PayrollEmployee)
        .filter(
            PayrollEmployee.organization_id == user.organization_id,
            PayrollEmployee.email == user.email,
        )
        .first()
    )
    if employee is None:
        raise NotFoundException("PayrollEmployee", "email")
    return employee


@router.get("/me", response_model=MyProfileResponse, summary="My payroll profile")
def my_profile(
    current_user=Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.modules.payroll.models import PayrollEmployee

    employee = _my_employee(db, current_user)
    return MyProfileResponse(
        id=employee.id,
        employee_code=employee.employee_code,
        name=employee.name,
        email=employee.email,
        phone=employee.phone,
        department=employee.department,
        designation=employee.designation,
        employment_type=employee.employment_type,
        status=employee.status,
        work_state=employee.work_state,
        date_of_joining=employee.date_of_joining,
        ctc=str(employee.ctc) if employee.ctc is not None else None,
        bank_name=employee.bank_name,
        bank_account=employee.bank_account,
        pan=employee.pan,
    )


@router.get("/payslips", response_model=MyPayslipsResponse, summary="My payslips")
def my_payslips(
    period: Optional[str] = Query(None),
    current_user=Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.modules.payroll.models import PayslipItem

    employee = _my_employee(db, current_user)
    query = db.query(PayslipItem).filter(PayslipItem.employee_id == employee.id)
    if period:
        query = query.filter(PayslipItem.period_label == period)
    payslips = (
        query.order_by(PayslipItem.period_start.desc())
        .limit(100)
        .all()
    )
    return MyPayslipsResponse(payslips=payslips, total=len(payslips))


@router.get("/payslips/{payslip_id}/download", summary="Download my payslip PDF")
def download_my_payslip(
    payslip_id: int,
    current_user=Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.modules.payroll.models import PayslipItem

    employee = _my_employee(db, current_user)
    item = db.query(PayslipItem).filter(PayslipItem.id == payslip_id).first()
    if item is None or item.employee_id != employee.id:
        raise NotFoundException("Payslip", "id")
    if item.organization_id != current_user.organization_id:
        raise ForbiddenException("Access denied to this payslip.")

    from app.modules.payroll.service import generate_payslip_pdf_bytes

    pdf_bytes = generate_payslip_pdf_bytes(db, payslip_id, current_user.organization_id)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip-{payslip_id}.pdf"'},
    )


@router.get("/payslips/{payslip_id}", summary="Get my single payslip")
def my_payslip(
    payslip_id: int,
    current_user=Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.modules.payroll.models import PayslipItem
    from app.modules.payroll.schemas import PayslipItemResponse

    employee = _my_employee(db, current_user)
    item = db.query(PayslipItem).filter(PayslipItem.id == payslip_id).first()
    if item is None or item.employee_id != employee.id:
        raise NotFoundException("Payslip", "id")
    return PayslipItemResponse.model_validate(item)


@hr_router.get(
    "/employees",
    response_model=List[MyProfileResponse],
    summary="List payroll employees (org-scoped)",
    dependencies=[Depends(get_current_org_admin)],
)
def list_employees(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.modules.payroll.models import PayrollEmployee

    query = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == current_user.organization_id
    )
    if search:
        like = f"%{search}%"
        query = query.filter(
            (PayrollEmployee.name.ilike(like))
            | (PayrollEmployee.employee_code.ilike(like))
            | (PayrollEmployee.email.ilike(like))
        )
    return query.order_by(PayrollEmployee.name).all()
