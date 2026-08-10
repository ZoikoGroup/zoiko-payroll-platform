"""
modules/payroll/mail/service.py
----------------------------------
Business logic for Payroll email settings + inbound leave-request capture.

Tenant isolation follows the exact convention already used everywhere else
in this module (_apply_org_filter). Nothing here touches SMTP/IMAP
credentials except to read whatever an org admin has already entered
through the settings endpoint this same submodule exposes — no credential
is fabricated, guessed, or read from any file by this code.
"""

import os as _os
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundException, BadRequestException
from app.core.crypto import encrypt_secret, decrypt_secret
from app.modules.payroll.mail.models import (
    PayrollEmailSettings, InboundMessage, InboundAttachment, InboundMessageStatus,
)
from app.modules.payroll.mail.schemas import PayrollEmailSettingsUpdate, ConvertToLeaveRequestRequest
from app.modules.payroll.models import PayrollEmployee, ActivityStatus
from app.modules.payroll.service import _apply_org_filter, log_activity, create_payroll_leave_request

logger = logging.getLogger("zoiko")

# Same env-var-driven convention as _COMPLIANCE_DOC_UPLOAD_DIR in service.py —
# no new storage mechanism, no .env edit required (safe default provided).
_INBOUND_ATTACHMENT_DIR = _os.environ.get(
    "PAYROLL_INBOUND_ATTACHMENT_DIR",
    _os.path.join(_os.environ.get("UPLOAD_BASE_DIR", "/tmp/uploads"), "payroll_inbound_attachments"),
)


# ── Email settings (per-tenant send identity + IMAP config) ─────────────

def get_or_create_email_settings(db: Session, organization_id: int) -> PayrollEmailSettings:
    row = (
        db.query(PayrollEmailSettings)
        .filter(PayrollEmailSettings.organization_id == organization_id)
        .first()
    )
    if not row:
        row = PayrollEmailSettings(organization_id=organization_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_email_settings(
    db: Session, organization_id: int, data: PayrollEmailSettingsUpdate, actor_id: Optional[int] = None,
) -> PayrollEmailSettings:
    row = get_or_create_email_settings(db, organization_id)
    updates = data.model_dump(exclude_unset=True, by_alias=False)

    imap_password_touched = "imap_password" in updates
    if imap_password_touched:
        # Encrypted at rest (app/core/crypto.py) — never stored plaintext.
        # An empty string clears it; omitting the field entirely (the
        # normal case) leaves whatever password is already stored alone.
        updates["imap_password"] = encrypt_secret(updates.pop("imap_password"))

    for field, value in updates.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    log_activity(
        db, organization_id,
        "Payroll email sender identity updated."
        + (" IMAP mailbox password rotated." if imap_password_touched else ""),
        ActivityStatus.INFO, actor_id=actor_id,
    )
    return row


def resolve_send_identity(db: Session, organization_id: Optional[int]) -> tuple:
    """Returns (from_email, from_display_name) — both None if the org
    hasn't configured an override, meaning "use the shared platform
    default" (see email_service.py — a None here changes nothing there)."""
    if organization_id is None:
        return None, None
    row = (
        db.query(PayrollEmailSettings)
        .filter(PayrollEmailSettings.organization_id == organization_id)
        .first()
    )
    if not row:
        return None, None
    return row.from_email, row.from_display_name


def is_notification_enabled(db: Session, organization_id: int, kind: str) -> bool:
    """kind: 'payslip_ready' | 'run_approved'. Defaults to True (matches the
    existing DEFAULT_INTEGRATIONS 'notifications'->'email' default of True)
    if the org has no PayrollEmailSettings row yet."""
    row = (
        db.query(PayrollEmailSettings)
        .filter(PayrollEmailSettings.organization_id == organization_id)
        .first()
    )
    if not row:
        return True
    return row.notify_payslip_ready if kind == "payslip_ready" else row.notify_run_approved


# ── Inbound messages ──────────────────────────────────────────────────

def list_inbound_messages(db: Session, organization_id: int, status: Optional[str] = None) -> List[InboundMessage]:
    query = db.query(InboundMessage)
    query = _apply_org_filter(query, InboundMessage, organization_id)
    if status:
        query = query.filter(InboundMessage.status == status)
    return query.order_by(InboundMessage.received_at.desc()).all()


def get_inbound_message(db: Session, organization_id: int, message_id: int) -> InboundMessage:
    query = db.query(InboundMessage).filter(InboundMessage.id == message_id)
    query = _apply_org_filter(query, InboundMessage, organization_id)
    row = query.first()
    if not row:
        raise NotFoundException("InboundMessage", message_id)
    return row


def convert_to_leave_request(
    db: Session, organization_id: int, message_id: int,
    data: ConvertToLeaveRequestRequest, actor_id: Optional[int] = None,
) -> dict:
    message = get_inbound_message(db, organization_id, message_id)
    if not message.matched_employee_id:
        raise BadRequestException(
            "This message isn't matched to a known employee — it can't be converted automatically."
        )
    if message.status == InboundMessageStatus.CONVERTED.value:
        raise BadRequestException("This message has already been converted to a leave request.")

    leave_data = SimpleNamespace(
        employee_id=message.matched_employee_id,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=data.reason or message.subject,
        source="email",
    )
    result = create_payroll_leave_request(db, leave_data, organization_id)

    message.status = InboundMessageStatus.CONVERTED.value
    message.leave_request_id = result["id"]
    db.commit()

    log_activity(
        db, organization_id,
        f"Leave request created from inbound email (message #{message.id} from {message.from_email}).",
        ActivityStatus.SUCCESS, actor_id=actor_id,
    )
    return result


def mark_ignored(db: Session, organization_id: int, message_id: int, actor_id: Optional[int] = None) -> InboundMessage:
    message = get_inbound_message(db, organization_id, message_id)
    message.status = InboundMessageStatus.IGNORED.value
    db.commit()
    db.refresh(message)
    log_activity(
        db, organization_id, f"Inbound message #{message.id} from {message.from_email} marked ignored.",
        ActivityStatus.INFO, actor_id=actor_id,
    )
    return message


# ── IMAP polling ──────────────────────────────────────────────────────
# NOTE: this connects to a real mailbox using whatever credentials an org
# admin has entered via the settings endpoint above. It cannot be
# exercised end-to-end without real IMAP credentials, which this code
# never reads from anywhere except the database row the admin filled in.

def _save_attachment(message_id: int, filename: str, content: bytes) -> InboundAttachment:
    _os.makedirs(_INBOUND_ATTACHMENT_DIR, exist_ok=True)
    safe_name = f"{message_id}_{filename}".replace("/", "_").replace("\\", "_")
    path = _os.path.join(_INBOUND_ATTACHMENT_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(content)
    return InboundAttachment(
        message_id=message_id, file_path=path, file_name=filename,
        file_size=len(content), mime_type=None,
    )


def poll_mailbox_for_org(db: Session, organization_id: int) -> dict:
    """Fetches unseen messages for one org's configured leave-request
    mailbox. Returns a summary dict; never raises past its own boundary so
    a scheduler job iterating many orgs can isolate per-org failures."""
    settings = get_or_create_email_settings(db, organization_id)
    if not settings.imap_enabled:
        return {"organizationId": organization_id, "skipped": True, "reason": "IMAP not enabled for this org"}
    if not (settings.imap_host and settings.imap_username and settings.imap_password):
        return {"organizationId": organization_id, "skipped": True, "reason": "IMAP settings incomplete"}

    try:
        from imapclient import IMAPClient
        import email as email_lib
        from email.utils import parseaddr
    except ImportError:
        logger.error("[payroll-mail] imapclient is not installed — add it to requirements.txt before enabling IMAP polling.")
        return {"organizationId": organization_id, "skipped": True, "reason": "imapclient not installed"}

    fetched = 0
    matched_employees = {
        e.email.lower(): e.id
        for e in db.query(PayrollEmployee).filter(
            PayrollEmployee.organization_id == organization_id,
            PayrollEmployee.email.isnot(None),
        ).all()
        if e.email
    }

    imap_password = decrypt_secret(settings.imap_password)
    if not imap_password:
        return {"organizationId": organization_id, "skipped": True, "reason": "Stored IMAP password could not be decrypted"}

    try:
        with IMAPClient(settings.imap_host, port=int(settings.imap_port or 993), ssl=settings.imap_use_ssl, timeout=30) as client:
            client.login(settings.imap_username, imap_password)
            client.select_folder("INBOX")
            uids = client.search(["UNSEEN"])

            for uid in uids:
                # Dedup happens at insert time via the (organization_id, message_uid)
                # unique constraint — a re-poll that sees the same UID again is a
                # normal, harmless no-op, not an error.
                raw = client.fetch([uid], ["RFC822"])[uid][b"RFC822"]
                msg = email_lib.message_from_bytes(raw)

                from_name, from_email = parseaddr(msg.get("From", ""))
                subject = msg.get("Subject", "")

                body_text, body_html = "", ""
                attachments_payload = []
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        disposition = str(part.get("Content-Disposition") or "")
                        if "attachment" in disposition:
                            filename = part.get_filename()
                            if filename:
                                attachments_payload.append((filename, part.get_payload(decode=True) or b""))
                        elif content_type == "text/plain" and not body_text:
                            body_text = (part.get_payload(decode=True) or b"").decode(errors="replace")
                        elif content_type == "text/html" and not body_html:
                            body_html = (part.get_payload(decode=True) or b"").decode(errors="replace")
                else:
                    body_text = (msg.get_payload(decode=True) or b"").decode(errors="replace")

                matched_employee_id = matched_employees.get((from_email or "").lower())

                row = InboundMessage(
                    organization_id=organization_id,
                    message_uid=str(uid),
                    from_email=from_email or "unknown",
                    to_email=settings.imap_username,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                    received_at=datetime.utcnow(),
                    status=InboundMessageStatus.MATCHED.value if matched_employee_id else InboundMessageStatus.UNMATCHED.value,
                    matched_employee_id=matched_employee_id,
                )
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    continue  # already fetched this UID in a previous poll
                db.refresh(row)

                for filename, content in attachments_payload:
                    db.add(_save_attachment(row.id, filename, content))
                db.commit()

                fetched += 1

            settings.last_polled_at = datetime.utcnow()
            db.commit()

    except Exception as exc:
        logger.error(f"[payroll-mail] IMAP poll failed for org {organization_id}: {exc}")
        return {"organizationId": organization_id, "skipped": False, "error": str(exc), "fetched": fetched}

    return {"organizationId": organization_id, "skipped": False, "fetched": fetched}


def poll_all_mailboxes(db: Session) -> dict:
    """Entry point for the scheduled job — iterates every org with IMAP
    enabled, isolating failures per org (same philosophy as the existing
    recurring-billing job processing all orgs in one pass)."""
    org_ids = [
        row.organization_id
        for row in db.query(PayrollEmailSettings).filter(PayrollEmailSettings.imap_enabled.is_(True)).all()
    ]
    results = []
    for org_id in org_ids:
        try:
            results.append(poll_mailbox_for_org(db, org_id))
        except Exception as exc:
            logger.error(f"[payroll-mail] Unexpected error polling org {org_id}: {exc}")
            results.append({"organizationId": org_id, "skipped": False, "error": str(exc)})
    return {"orgsPolled": len(org_ids), "results": results}
