"""
Email service for the standalone Payroll Platform.

Templates are stored in app/email_templates/ as HTML files. SMTP settings
come from the platform's own .env (SMTP_*), with an optional per-org
override stored in PlatformSetting. The SMTP password is read only from
the environment, never from the DB.

Branding (company name, legal entity, address) resolves from the
standalone platform's own Organization table — never the old platform's
billing/HR modules.
"""

import html as _html
import logging
import os
import re
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import certifi

logger = logging.getLogger("zoiko_payroll")

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "email_templates")

_IF_BLOCK_RE = re.compile(r"\{\{#if (\w+)\}\}(.*?)\{\{/if\}\}", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _load_template(name: str) -> str:
    path = os.path.join(TEMPLATE_DIR, name)
    if not os.path.exists(path):
        logger.warning(f"Email template not found: {path}")
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _render_template(template: str, context: dict) -> str:
    def _eval_if(match):
        key, inner = match.group(1), match.group(2)
        return inner if context.get(key) else ""

    result = _IF_BLOCK_RE.sub(_eval_if, template)
    for key, value in context.items():
        if value is None:
            value = ""
        result = result.replace("{{" + key + "}}", str(value))
    return result


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", html)
    text = _TAG_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_smtp_settings(db=None) -> dict:
    from app.config import settings as _settings

    defaults = {
        "host": _settings.SMTP_HOST,
        "port": _settings.SMTP_PORT,
        "username": _settings.SMTP_USERNAME,
        "password": _settings.SMTP_PASSWORD,
        "from_email": _settings.SMTP_FROM_EMAIL,
        "use_tls": _settings.SMTP_USE_TLS,
    }
    try:
        from app.modules.super_admin.models import PlatformSetting

        own_session = False
        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            own_session = True
        try:
            rows = db.query(PlatformSetting).filter(
                PlatformSetting.key.like("smtp_%")
            ).all()
            mapping = {s.key: s.value for s in rows if s.value}
            return {
                "host": mapping.get("smtp_host", defaults["host"]),
                "port": mapping.get("smtp_port", defaults["port"]),
                "username": mapping.get("smtp_username", defaults["username"]),
                "password": defaults["password"],
                "from_email": mapping.get("smtp_from_email", defaults["from_email"]),
                "use_tls": mapping.get("smtp_use_tls", defaults["use_tls"]),
            }
        finally:
            if own_session:
                db.close()
    except Exception as e:
        logger.warning(f"[email] Could not load SMTP settings from DB, using defaults: {e}")
        return defaults


_BRANDING_DEFAULTS = {
    "company_name": "Zoiko Payroll",
    "support_email": "",
    "website": "",
    "logo_url": "",
    "invoice_footer": "",
    "legal_entity": "",
    "billing_address": "",
    "billing_phone": "",
}


def _get_org_branding(organization_id=None, db=None) -> dict:
    """Resolve template branding from the standalone Organization table."""
    if not organization_id:
        return dict(_BRANDING_DEFAULTS)
    try:
        from app.modules.organizations.models import Organization

        own_session = False
        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            own_session = True
        try:
            org = db.query(Organization).filter(Organization.id == organization_id).first()
            if org is None:
                return dict(_BRANDING_DEFAULTS)
            company_name = org.organization_name or _BRANDING_DEFAULTS["company_name"]
            legal_entity = company_name
            if org.tax_no or org.registration_number:
                parts = []
                if org.registration_number:
                    parts.append(f"registration no. {org.registration_number}")
                if org.tax_no:
                    parts.append(f"tax no. {org.tax_no}")
                legal_entity = f"{company_name} — {', '.join(parts)}"
            return {
                "company_name": company_name,
                "support_email": org.email or "",
                "website": "",
                "logo_url": "",
                "invoice_footer": "",
                "legal_entity": legal_entity,
                "billing_address": org.address or "",
                "billing_phone": org.phone or "",
            }
        finally:
            if own_session:
                db.close()
    except Exception as e:
        logger.warning(f"[email] Could not load branding for organization_id={organization_id}: {e}")
        return dict(_BRANDING_DEFAULTS)


def send_approval_email(
    email: str,
    template_name: str,
    context: dict,
    db=None,
    organization_id=None,
    attachments=None,
    from_email_override=None,
    from_display_name_override=None,
    template_body: str = None,
) -> bool:
    if template_body is not None:
        template = template_body
    else:
        template = _load_template(template_name)
    if not template:
        logger.warning(f"Cannot send email to {email}: template {template_name} not found")
        return False

    branding = _get_org_branding(organization_id, db=db)
    full_context = {**branding, **context}
    body = _render_template(template, full_context)
    smtp = _get_smtp_settings(db=db)

    subject = context.get("subject", "Zoiko Payroll — Notification")
    if "{{" in subject:
        subject = _render_template(subject, full_context)

    envelope_from = smtp["from_email"]
    header_from = from_email_override or envelope_from
    sender_name = from_display_name_override or full_context.get("company_name") or "Zoiko Payroll"
    reply_to = full_context.get("support_email")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{header_from}>"
    msg["To"] = email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(_html_to_text(body), "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))

    if attachments:
        for filename, data in attachments:
            part = MIMEApplication(data, _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    try:
        port = int(smtp["port"])
        use_tls = str(smtp.get("use_tls", "true")).strip().lower() in ("1", "true", "yes")
        context_ssl = ssl.create_default_context(cafile=certifi.where())

        if use_tls and port != 465:
            with smtplib.SMTP(smtp["host"], port, timeout=30) as server:
                server.starttls(context=context_ssl)
                if smtp["username"] and smtp["password"]:
                    server.login(smtp["username"], smtp["password"])
                server.sendmail(envelope_from, email, msg.as_string())
        else:
            with smtplib.SMTP_SSL(smtp["host"], port, context=context_ssl, timeout=30) as server:
                if smtp["username"] and smtp["password"]:
                    server.login(smtp["username"], smtp["password"])
                server.sendmail(envelope_from, email, msg.as_string())

        logger.info(f"[email] Sent to {email} | template={template_name}")
        return True
    except Exception as e:
        logger.error(f"[email] Failed to send to {email} | template={template_name} | error={e}")
        return False


# ── Payroll module emails ───────────────────────────────────────────────────


def _resolve_payroll_send_identity(organization_id, db=None):
    """Per-org from-identity override from PayrollEmailSettings, if configured."""
    if not organization_id:
        return None, None
    try:
        from app.modules.payroll.mail.service import resolve_send_identity

        own_session = False
        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            own_session = True
        try:
            return resolve_send_identity(db, organization_id)
        finally:
            if own_session:
                db.close()
    except Exception as e:
        logger.warning(f"[email] Could not resolve payroll send identity for org={organization_id}: {e}")
        return None, None


def send_payslip_ready_email(
    email: str,
    employee_name: str,
    pay_period: str,
    organization_id=None,
    db=None,
    pdf_bytes: bytes = None,
    pdf_filename: str = None,
) -> bool:
    from_email, from_display_name = _resolve_payroll_send_identity(organization_id, db=db)
    attachments = [(pdf_filename or "payslip.pdf", pdf_bytes)] if pdf_bytes else None
    return send_approval_email(email, "payslip_ready.html", {
        "subject": f"Your Payslip is Ready — {pay_period} | Zoiko Payroll",
        "employee_name": employee_name,
        "pay_period": pay_period,
    }, db=db, organization_id=organization_id, attachments=attachments,
        from_email_override=from_email, from_display_name_override=from_display_name)


def send_payroll_run_approved_email(
    email: str,
    employee_name: str,
    pay_period: str,
    organization_id=None,
    db=None,
) -> bool:
    from_email, from_display_name = _resolve_payroll_send_identity(organization_id, db=db)
    return send_approval_email(email, "payroll_run_approved.html", {
        "subject": f"Payroll Approved — {pay_period} | Zoiko Payroll",
        "employee_name": employee_name,
        "pay_period": pay_period,
    }, db=db, organization_id=organization_id,
        from_email_override=from_email, from_display_name_override=from_display_name)


def send_update_form_invite_email(
    email: str,
    employee_name: str,
    form_name: str,
    form_link: str,
    expires_at_display: str,
    organization_id=None,
    db=None,
) -> bool:
    from_email, from_display_name = _resolve_payroll_send_identity(organization_id, db=db)
    return send_approval_email(email, "update_form_invite.html", {
        "subject": f"{form_name} — Action Requested | Zoiko Payroll",
        "employee_name": employee_name,
        "form_name": form_name,
        "form_link": form_link,
        "expires_at": expires_at_display,
    }, db=db, organization_id=organization_id,
        from_email_override=from_email, from_display_name_override=from_display_name)


_LEAVE_TYPE_LABELS = {
    "paid": "Paid Leave",
    "unpaid": "Unpaid Leave",
    "sick": "Sick Leave",
    "casual": "Casual Leave",
    "comp_off": "Compensatory Off",
    "compOff": "Compensatory Off",
    "other": "Other Leave",
}


def _send_leave_request_status_email(
    email: str,
    employee_name: str,
    status: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: int,
    request_code: str,
    organization_id=None,
    db=None,
) -> bool:
    from_email, from_display_name = _resolve_payroll_send_identity(organization_id, db=db)
    approved = status == "approved"
    template_name = "leave_request_approved.html" if approved else "leave_request_rejected.html"
    action = "Approved" if approved else "Rejected"
    return send_approval_email(email, template_name, {
        "subject": f"Leave Request {action} — {request_code} | Zoiko Payroll",
        "employee_name": employee_name,
        "leave_type": _LEAVE_TYPE_LABELS.get(str(leave_type).lower(), str(leave_type) or "Leave"),
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "plural": int(days or 0) != 1,
        "request_code": request_code,
    }, db=db, organization_id=organization_id,
        from_email_override=from_email, from_display_name_override=from_display_name)


def send_leave_request_approved_email(
    email: str,
    employee_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: int,
    request_code: str,
    organization_id=None,
    db=None,
) -> bool:
    return _send_leave_request_status_email(
        email, employee_name, "approved", leave_type, start_date, end_date, days, request_code,
        organization_id=organization_id, db=db,
    )


def send_leave_request_rejected_email(
    email: str,
    employee_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: int,
    request_code: str,
    organization_id=None,
    db=None,
) -> bool:
    return _send_leave_request_status_email(
        email, employee_name, "rejected", leave_type, start_date, end_date, days, request_code,
        organization_id=organization_id, db=db,
    )


# ── Auth / account emails ───────────────────────────────────────────────────

SECURITY_SENDER = "Zoiko Payroll Security"


def send_user_invite_email(
    email: str,
    first_name: str,
    invite_link: str,
    invited_by: str = "",
    organization_id=None,
    db=None,
) -> bool:
    workspace = _get_org_branding(organization_id, db=db).get("company_name", "your organization")
    return send_approval_email(email, "org_admin_invite.html", {
        "subject": "You have been invited to {{workspace_name}}",
        "first_name": first_name,
        "inviter_name": invited_by or "your administrator",
        "workspace_name": workspace,
        "expires_at_local": "24 hours",
        "timezone": "UTC",
        "action_url": invite_link,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_org_admin_password_reset_email(
    email: str,
    first_name: str,
    reset_link: str,
    organization_id=None,
    db=None,
) -> bool:
    return send_approval_email(email, "org_admin_password_reset.html", {
        "subject": "Reset your Zoiko Payroll password",
        "first_name": first_name,
        "expires_at_local": "24 hours",
        "timezone": "UTC",
        "action_url": reset_link,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_registration_received(email: str, org_name: str, db=None):
    return send_approval_email(email, "registration_received.html", {
        "subject": f"Registration Received — {org_name} | Zoiko Payroll",
        "organization_name": org_name,
    }, db=db)


def send_employee_welcome_email(
    email: str,
    employee_name: str,
    login_url: str = "",
    organization_id=None,
    db=None,
) -> bool:
    return send_approval_email(email, "welcome.html", {
        "subject": f"Welcome to {{{{company_name}}}} — Your Account Is Ready",
        "employee_name": employee_name,
        "login_url": login_url,
    }, db=db, organization_id=organization_id)
