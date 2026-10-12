"""
app/tasks/email_tasks.py
-------------------------
Celery tasks for email sending and notifications.

Handles asynchronous email delivery with retry logic and templates.
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from typing import List, Dict, Any, Optional
from datetime import date, datetime

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="emails",
)
def send_email_task(self, to: List[str], subject: str, template: str, 
                     context: Dict, cc: Optional[List[str]] = None,
                     bcc: Optional[List[str]] = None) -> Dict:
    raise NotImplementedError(
        "send_email_task is not implemented: this task has no mail transport; reporting 'sent' without a message leaving the process is a false receipt. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_payslip_email_task(self, employee_email: str, employee_name: str,
                             payslip_id: int, pdf_attachment_b64: Optional[str] = None) -> Dict:
    raise NotImplementedError(
        "send_payslip_email_task is not implemented: this task has no payslip mailer; the PDF it would attach is never rendered. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_payroll_run_notification_task(self, organization_id: int, run_id: int,
                                        notification_type: str, recipients: List[str]) -> Dict:
    raise NotImplementedError(
        "send_payroll_run_notification_task is not implemented: this task has no run notification mailer. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_leave_approval_email_task(self, employee_email: str, employee_name: str,
                                    leave_type: str, start_date: str, end_date: str,
                                    status: str, approver_name: str) -> Dict:
    raise NotImplementedError(
        "send_leave_approval_email_task is not implemented: this task has no leave decision mailer. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_bulk_notification_task(self, recipients: List[str], subject: str,
                                 template: str, context: Dict) -> Dict:
    raise NotImplementedError(
        "send_bulk_notification_task is not implemented: this task has no bulk mailer; it reported every recipient 'sent' without sending anything. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_reminder_email_task(self, to: str, subject: str, template: str,
                              context: Dict, send_at: Optional[str] = None) -> Dict:
    raise NotImplementedError(
        "send_reminder_email_task is not implemented: this task has no reminder scheduler/mailer. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_welcome_email_task(self, email: str, name: str, organization_name: str,
                             login_url: str) -> Dict:
    raise NotImplementedError(
        "send_welcome_email_task is not implemented: this task has no welcome mailer. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="emails",
)
def send_password_reset_email_task(self, email: str, reset_token: str,
                                    reset_url: str, expires_hours: int = 24) -> Dict:
    raise NotImplementedError(
        "send_password_reset_email_task is not implemented: this task has no reset-token mailer; a silently undelivered reset token looks like a security control. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
