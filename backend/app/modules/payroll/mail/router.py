"""
modules/payroll/mail/router.py
----------------------------------
HTTP endpoints for Payroll email settings + inbound leave-request mail.

Mounted as a sub-router of payroll_router (see
app/modules/payroll/router.py), exactly like policy_router/enterprise_router.

  GET   /mail/settings                              -> current org's email settings (get-or-create)
  PUT   /mail/settings                               -> update sender identity + notification toggles (admin only)
  GET   /mail/inbox                                  -> list inbound messages
  POST  /mail/inbox/{message_id}/convert-to-leave-request  (admin only)
  POST  /mail/inbox/{message_id}/ignore              (admin only)
  POST  /mail/poll-now                               -> manually trigger a poll for this org (admin only, for testing once IMAP is configured)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_user, get_current_payroll_operator
from app.modules.payroll.mail import service
from app.modules.payroll.mail.schemas import (
    PayrollEmailSettingsResponse, PayrollEmailSettingsUpdate,
    InboundMessageResponse, ConvertToLeaveRequestRequest, SuccessResponse,
)

mail_router = APIRouter(prefix="/mail", tags=["Payroll Email & Leave-Request Inbox"])


def _serialize_message(msg) -> dict:
    matched_name = None
    if msg.matched_employee_id and msg.employee:
        matched_name = f"{msg.employee.first_name} {msg.employee.last_name}"
    return {
        "id": msg.id,
        "fromEmail": msg.from_email,
        "subject": msg.subject,
        "bodyText": msg.body_text,
        "receivedAt": msg.received_at,
        "status": msg.status,
        "matchedEmployeeId": msg.matched_employee_id,
        "matchedEmployeeName": matched_name,
        "leaveRequestId": msg.leave_request_id,
        "attachments": [
            {"id": a.id, "fileName": a.file_name, "fileSize": a.file_size, "mimeType": a.mime_type}
            for a in (msg.attachments or [])
        ],
    }


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


@mail_router.get(
    "/inbox", response_model=list[InboundMessageResponse], response_model_by_alias=True,
    summary="List inbound leave-request emails",
)
def list_inbox(status: str = None, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    messages = service.list_inbound_messages(db, current_user.organization_id, status=status)
    return [_serialize_message(m) for m in messages]


@mail_router.post(
    "/inbox/{message_id}/convert-to-leave-request",
    summary="Convert an inbound email into a real leave request (org admin only)",
)
def convert(
    message_id: int, data: ConvertToLeaveRequestRequest, db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.convert_to_leave_request(db, current_user.organization_id, message_id, data, actor_id=current_user.id)


@mail_router.post(
    "/inbox/{message_id}/ignore", response_model=InboundMessageResponse, response_model_by_alias=True,
    summary="Dismiss an inbound message that isn't a leave request (org admin only)",
)
def ignore(message_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_payroll_operator)):
    return service.mark_ignored(db, current_user.organization_id, message_id, actor_id=current_user.id)


@mail_router.post(
    "/poll-now", response_model=SuccessResponse,
    summary="Manually trigger an IMAP poll for this org right now (org admin only)",
)
def poll_now(db: Session = Depends(get_db), current_user=Depends(get_current_payroll_operator)):
    result = service.poll_mailbox_for_org(db, current_user.organization_id)
    if result.get("skipped"):
        return {"success": False, "message": result.get("reason", "IMAP not configured for this organization.")}
    if result.get("error"):
        return {"success": False, "message": f"Poll failed: {result['error']}"}
    return {"success": True, "message": f"Fetched {result.get('fetched', 0)} new message(s)."}
