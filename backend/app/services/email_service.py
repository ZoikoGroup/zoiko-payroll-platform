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

# Fixed anti-phishing notice — single source of truth (§10 copy standard).
# Templates embed it via the {{security_advisory_block}} placeholder so the
# wording is never duplicated (or allowed to drift) across template files.
SECURITY_ADVISORY_TEXT = (
    "Zoiko Payroll will never ask you to send your password, multifactor "
    "authentication code, bank details, tax identifiers or payroll files by email."
)
_SECURITY_ADVISORY_HTML = (
    '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
    'style="background:rgba(49,46,129,0.2); border:1px solid #312e81; border-radius:8px;"><tr>'
    '<td style="padding:14px 16px;">'
    '<p style="color:#e2e8f0; font-size:12px; font-weight:bold; margin:0 0 4px 0;">Security Advisory</p>'
    f'<p style="color:#94a3b8; font-size:12px; line-height:1.6; margin:0;">{SECURITY_ADVISORY_TEXT}</p>'
    "</td></tr></table>"
)

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
    except Exception:
        # A genuinely unexpected failure (DB connectivity, a coding bug) —
        # NOT "no override configured" (that's the mapping.get(...) defaults
        # above, which never raises). Logged at error level with a full
        # traceback so a real outage here doesn't quietly blend into normal
        # "using defaults" noise. Still degrades gracefully — a failed SMTP
        # override lookup shouldn't crash whatever's trying to send an email.
        logger.exception("[email] Could not load SMTP settings from DB, using env defaults")
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
    except Exception:
        # The expected "org not found" case is already handled explicitly
        # above (returns early, never reaches here) — anything landing in
        # this except is a genuinely unexpected failure, logged loudly
        # rather than as a quiet warning indistinguishable from routine
        # missing-branding cases. Still returns generic branding rather
        # than crashing whatever email is being rendered.
        logger.exception(f"[email] Could not load branding for organization_id={organization_id}")
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
    # Logo fallback: absolute URL to the SPA-hosted brand asset (public/ dir),
    # used by any template referencing {{logo_url}} / {{frontend_url}} when the
    # org has no configured logo.
    if not full_context.get("logo_url") or not str(full_context.get("logo_url", "")).startswith("http"):
        from app.config import settings as _cfg

        frontend_base = os.environ.get("FRONTEND_BASE_URL", "").rstrip("/") or _cfg.FRONTEND_URL.rstrip("/")
        full_context["logo_url"] = f"{frontend_base}/zoikopayroll-logo-light.png"
        full_context["frontend_url"] = frontend_base
    full_context.setdefault("security_advisory_block", _SECURITY_ADVISORY_HTML)
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

    if not smtp["host"]:
        logger.info(f"[email] SMTP_HOST not configured. Mock sending email to {email} | subject='{subject}' | template={template_name}")
        logger.debug(f"[email] Body content:\n{_html_to_text(body)}")
        return True

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
    inviter_name: str = "",
    role_name: str = "Payroll Administrator",
    organization_name: str = "",
    expires_at_local: str = "",
    reference_id: str = "",
    organization_id=None,
    db=None,
) -> bool:
    """IAM-002 (Class P1): user invitation. organization_name/role_name/
    expires_at_local/reference_id are rendered explicitly — never relative
    expiry strings (§10)."""
    workspace = organization_name or _get_org_branding(organization_id, db=db).get("company_name", "your organization")
    return send_approval_email(email, "org_admin_invite.html", {
        "subject": "You have been invited to Zoiko Payroll",
        "preheader": f"Accept the invitation to access {workspace}.",
        "first_name": first_name,
        "inviter_name": inviter_name or "your administrator",
        "organization_name": workspace,
        "role_name": role_name,
        "expires_at_local": expires_at_local,
        "reference_id": reference_id,
        "action_url": invite_link,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_org_admin_password_reset_email(
    email: str,
    first_name: str,
    reset_link: str,
    expires_at_local: str = "",
    reference_id: str = "",
    organization_id=None,
    db=None,
) -> bool:
    """IAM-007 (Class P1): password reset requested. `expires_at_local` must be
    an absolute date/time with named time zone, preformatted by the caller."""
    return send_approval_email(email, "org_admin_password_reset.html", {
        "subject": "Reset your Zoiko Payroll password",
        "preheader": "Use the secure link only if you requested a reset.",
        "first_name": first_name,
        "expires_at_local": expires_at_local,
        "reference_id": reference_id,
        "action_url": reset_link,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_registration_received(email: str, org_name: str, db=None):
    return send_approval_email(email, "registration_received.html", {
        "subject": f"Registration Received — {org_name} | Zoiko Payroll",
        "organization_name": org_name,
    }, db=db)


def send_organization_created_email(
    email: str,
    recipient_first_name: str,
    organization_name: str,
    reference_id: str = "",
    product_route: str = "standalone_payroll",
    setup_link: str = "",
    organization_id=None,
    db=None,
) -> bool:
    """COM-001 (Class P1): Organization account created notification.
    Sent only to the primary administrator upon organization creation."""
    from app.config import settings
    if not reference_id:
        import uuid
        reference_id = f"ORG-{uuid.uuid4().hex[:4].upper()}-INIT"
    if not setup_link:
        frontend_base = os.environ.get("ACTION_BASE_URL", "").rstrip("/") or settings.FRONTEND_URL.rstrip("/")
        setup_link = f"{frontend_base}/login"

    return send_approval_email(
        email,
        "org_created.html",
        {
            "subject": "Your Zoiko Payroll organization has been created",
            "preheader": "Complete administrative and security setup.",
            "recipient_first_name": recipient_first_name or "Admin",
            "organization_name": organization_name,
            "product_route": product_route,
            "reference_id": reference_id,
            "action_url": setup_link,
        },
        db=db,
        organization_id=organization_id,
        from_display_name_override=SECURITY_SENDER,
    )


def send_super_admin_org_created_notification_email(
    org: object,
    admin_user: object = None,
    reference_id: str = "",
    db=None,
) -> bool:
    """ADM-001: Operational alert sent to Super Admins whenever a new organization
    is created in the platform, containing complete organization and admin metadata."""
    from app.config import settings
    from datetime import datetime

    # 1. Resolve Super Admin recipients from DB
    recipients = []
    if db is not None:
        try:
            from app.modules.auth.models import User, UserRole
            super_admins = db.query(User).filter(
                User.role == UserRole.SUPER_ADMIN,
                User.is_active == True,
            ).all()
            recipients = [u.email for u in super_admins if u.email]
        except Exception:
            # Genuinely unexpected (DB issue, a coding bug) — not "no Super
            # Admins exist yet" (an empty query result, handled below without
            # raising). Logged loudly so a real failure here isn't silently
            # indistinguishable from that routine case.
            logger.exception("[email] Failed querying Super Admins for notification")

    # Fallback to configured support email or SMTP from email if no Super Admins found
    if not recipients:
        fallback = settings.ASSIST_SUPPORT_EMAIL or settings.SMTP_FROM_EMAIL
        if fallback:
            recipients = [fallback]

    if not recipients:
        logger.warning("[email] No Super Admin recipients or fallback email configured; skipping org creation notification")
        return False

    if not reference_id:
        reference_id = f"ADM-ORG-{getattr(org, 'id', 0):04d}"

    frontend_base = os.environ.get("ACTION_BASE_URL", "").rstrip("/") or settings.FRONTEND_URL.rstrip("/")
    action_url = f"{frontend_base}/super-admin/organizations"

    # Format location summary
    location_parts = [p for p in [getattr(org, "city", None), getattr(org, "state", None), getattr(org, "country", None)] if p]
    location_summary = ", ".join(location_parts) if location_parts else ""

    created_at = getattr(org, "created_at", None)
    created_at_display = created_at.strftime("%d %b %Y, %H:%M UTC") if created_at else datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

    context = {
        "subject": f"[Platform Alert] New Organization Created — {getattr(org, 'organization_name', 'Org')}",
        "preheader": f"New organization {getattr(org, 'organization_name', '')} ({getattr(org, 'organization_code', '')}) created.",
        "organization_name": getattr(org, "organization_name", ""),
        "organization_code": getattr(org, "organization_code", ""),
        "admin_name": f"{getattr(admin_user, 'first_name', '')} {getattr(admin_user, 'last_name', '')}".strip() if admin_user else "",
        "admin_email": getattr(admin_user, "email", None) or getattr(org, "email", ""),
        "admin_phone": getattr(admin_user, "phone", None) or getattr(org, "phone", ""),
        "country": getattr(org, "country", ""),
        "industry": getattr(org, "industry", ""),
        "company_type": getattr(org, "company_type", ""),
        "tax_no": getattr(org, "tax_no", "") or getattr(org, "registration_number", ""),
        "location_summary": location_summary,
        "created_at_display": created_at_display,
        "reference_id": reference_id,
        "action_url": action_url,
    }

    success = True
    for recipient_email in recipients:
        ok = send_approval_email(
            recipient_email,
            "super_admin_org_created.html",
            context,
            db=db,
            organization_id=getattr(org, "id", None),
            from_display_name_override="Zoiko Platform Alert",
        )
        if not ok:
            success = False
    return success




# ── Assist handoff (support escalation) emails ──────────────────────────────

_HANDOFF_DESTINATION_LABELS = {
    "PAYROLL_SUPPORT": "Payroll Support",
    "COMPLIANCE_LOCAL_PAYROLL": "Compliance",
}


def send_handoff_confirmation_email(
    email: str,
    requester_name: str,
    case_id: str,
    summary: str,
    destination: str,
    sla_reference: str = "",
    organization_id=None,
    db=None,
) -> bool:
    """Sent to the user who escalated a chat conversation, confirming the
    case was filed and giving them a reference to follow up with."""
    from app.config import settings

    destination_label = _HANDOFF_DESTINATION_LABELS.get(destination, destination.replace("_", " ").title())
    context = {
        "subject": f"Support request received — {case_id} | Zoiko Payroll Assist",
        "requester_name": requester_name or "there",
        "case_id": case_id,
        "summary": summary,
        "destination_label": destination_label,
        "sla_reference": sla_reference,
    }
    # Only override the org's own branding-resolved Reply-To when a
    # dedicated support inbox is actually configured — an explicit None/""
    # here would otherwise blank out that default, not just leave it alone.
    if settings.ASSIST_SUPPORT_EMAIL:
        context["support_email"] = settings.ASSIST_SUPPORT_EMAIL
    return send_approval_email(email, "assist_handoff_confirmation.html", context, db=db, organization_id=organization_id)


def send_handoff_support_notification_email(
    requester_name: str,
    requester_email: str,
    case_id: str,
    summary: str,
    destination: str,
    reason_code: str,
    organization_id=None,
    db=None,
) -> bool:
    """Sent to the support-team inbox whenever a chat conversation is
    escalated. Falls back to SMTP_FROM_EMAIL if ASSIST_SUPPORT_EMAIL isn't
    configured, so this works as soon as SMTP is set up."""
    from app.config import settings

    support_email = settings.ASSIST_SUPPORT_EMAIL or settings.SMTP_FROM_EMAIL
    if not support_email:
        logger.warning(f"[email] No support-team inbox configured; skipping handoff notification for case {case_id}")
        return False

    destination_label = _HANDOFF_DESTINATION_LABELS.get(destination, destination.replace("_", " ").title())
    reason_label = reason_code.replace("_", " ").title() if reason_code else "Not specified"
    return send_approval_email(support_email, "assist_handoff_support_notification.html", {
        "subject": f"[Assist] New {destination_label} case — {case_id}",
        "requester_name": requester_name or "Unknown user",
        "requester_email": requester_email or "",
        "case_id": case_id,
        "summary": summary,
        "destination_label": destination_label,
        "reason_label": reason_label,
        "support_email": requester_email or None,
    }, db=db, organization_id=organization_id, from_display_name_override="Zoiko Payroll Assist")


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
