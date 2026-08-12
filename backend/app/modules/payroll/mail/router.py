"""
modules/payroll/mail/router.py
----------------------------------
HTTP endpoints for Payroll email settings.

Mounted as a sub-router of payroll_router (see
app/modules/payroll/router.py), exactly like policy_router/enterprise_router.

  GET   /mail/settings   -> current org's email settings (get-or-create)
  PUT   /mail/settings   -> update sender identity + notification toggles (admin only)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_user, get_current_payroll_operator
from app.modules.payroll.mail import service
from app.modules.payroll.mail.schemas import PayrollEmailSettingsResponse, PayrollEmailSettingsUpdate

mail_router = APIRouter(prefix="/mail", tags=["Payroll Email"])


@mail_router.get(
    "/settings", response_model=PayrollEmailSettingsResponse, response_model_by_alias=True,
    summary="Get this organization's payroll email settings (get-or-create)",
)
def get_settings(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.get_or_create_email_settings(db, current_user.organization_id)


@mail_router.put(
    "/settings", response_model=PayrollEmailSettingsResponse, response_model_by_alias=True,
    summary="Update sender identity + notification toggles (org admin only)",
)
def update_settings(
    data: PayrollEmailSettingsUpdate, db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.update_email_settings(db, current_user.organization_id, data, actor_id=current_user.id)
