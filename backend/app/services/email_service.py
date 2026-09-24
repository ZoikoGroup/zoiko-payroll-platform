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
from typing import Optional
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

# Canonical blue/white design palette (single source of truth). Every
# payroll-core email renders its accent bar, details panel, links and footer
# from these exact values — no per-file hex drift. Auth/account templates
# predate this palette and keep their own (#F3F8FF/#0B2D5C/#D8E4F5) — see the
# template-palette test in tests/test_auth_email_notifications.py.
PALETTE = {
    "page": "#f0f6ff",
    "card": "#ffffff",
    "border": "#d6e4f7",
    "cta": "#1d4ed8",
    "cta_hover": "#1e40af",
    "heading": "#0b1f3a",
    "body": "#33455e",
    "muted": "#5b7290",
    "panel": "#eaf2ff",
    "success": "#15803d",
    "warning": "#b45309",
    "error": "#b91c1c",
    "footer_bg": "#f0f6ff",
    "footer_text": "#5b7290",
    "brand_accent": "#7dabff",
}

# Shared security advisory, restyled to the canonical palette (the wording —
# SECURITY_ADVISORY_TEXT — is fixed and must never change).
_SECURITY_ADVISORY_HTML = (
    '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
    f'style="background:{PALETTE["panel"]}; border:1px solid {PALETTE["border"]}; border-radius:8px;"><tr>'
    '<td style="padding:14px 16px;">'
    f'<p style="color:{PALETTE["heading"]}; font-size:12px; font-weight:bold; margin:0 0 4px 0;">Security Advisory</p>'
    f'<p style="color:{PALETTE["muted"]}; font-size:12px; line-height:1.6; margin:0;">{SECURITY_ADVISORY_TEXT}</p>'
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


# ── Payroll-core shared layout ─────────────────────────────────────────────
# Canonical palette above + one shared base partial (_base_wrapper.html).
# Templates that are full standalone HTML documents render unchanged; a
# body-only fragment (no leading <!doctype html>) is composed into the
# wrapper so every payroll email shares one shell — header, accent bar,
# details panel, CTA, advisory and footer. This is what makes the
# blue/white design system a single source, not N copies.

_BASE_WRAPPER_NAME = "_base_wrapper.html"


def _frontend_base() -> str:
    from app.config import settings as _cfg

    return (os.environ.get("FRONTEND_BASE_URL", "").rstrip("/") or _cfg.FRONTEND_URL.rstrip("/"))


def _compose_email_html(template: str, context: dict) -> str:
    """Render a template. Full standalone documents render as-is; body-only
    fragments are first rendered, then slotted into the shared wrapper."""
    if re.match(r"(?is)^\s*<!doctype\s+html", template):
        return _render_template(template, context)
    wrapper = _load_template(_BASE_WRAPPER_NAME)
    if not wrapper:
        logger.warning(f"Shared email wrapper not found: {_BASE_WRAPPER_NAME}; rendering template body alone")
        return _render_template(template, context)
    rendered_body = _render_template(template, context)
    composed = wrapper.replace("{{body_slot}}", rendered_body)
    return _render_template(composed, context)


def _details_rows(rows) -> str:
    """Label/value detail rows for the shared details panel. `rows` is an
    iterable of (label, value) pairs. Values are HTML-escaped (they may be
    user-originated)."""
    cells = []
    for label, value in rows:
        cells.append(
            '<tr><td style="color:{muted}; font-size:12px; font-weight:bold; '
            'padding:4px 0; vertical-align:top; white-space:nowrap;">{label}</td>'
            '<td style="color:{heading}; font-size:12px; padding:4px 0 4px 12px; '
            'vertical-align:top;">{value}</td></tr>'.format(
                muted=PALETTE["muted"], heading=PALETTE["heading"],
                label=_html.escape(str(label)), value=_html.escape(str(value)) if value is not None else "—",
            )
        )
    return '<table width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(cells) + "</table>"


def _change_cells(changes) -> str:
    """old → new detail rows for config-change emails. `changes` is an
    iterable of (label, old_value, new_value) triples."""
    cells = []
    for label, old_value, new_value in changes:
        old = _html.escape(str(old_value)) if old_value is not None else "—"
        new = _html.escape(str(new_value)) if new_value is not None else "—"
        cells.append(
            '<tr><td style="color:{muted}; font-size:12px; font-weight:bold; '
            'padding:4px 0; vertical-align:top;">{label}</td>'
            '<td style="color:{warning}; font-size:12px; padding:4px 0 4px 12px; '
            'vertical-align:top;">{old}</td>'
            '<td style="color:{muted}; font-size:12px; padding:4px 8px; '
            'vertical-align:top;">&rarr;</td>'
            '<td style="color:{heading}; font-size:12px; padding:4px 0; '
            'vertical-align:top;">{new}</td></tr>'.format(
                muted=PALETTE["muted"], warning=PALETTE["warning"],
                heading=PALETTE["heading"],
                label=_html.escape(str(label)), old=old, new=new,
            )
        )
    return '<table width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(cells) + "</table>"


def _get_org_contact_email(db, organization_id):
    """Org's own notification/contact address (Organization.email) for the
    admin-facing payroll emails. None when the org has none configured."""
    if not organization_id:
        return None
    try:
        from app.modules.organizations.models import Organization

        own_session = False
        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            own_session = True
        try:
            org = db.query(Organization).filter(Organization.id == organization_id).first()
            return _html.unescape(org.email) if org and org.email else None
        finally:
            if own_session:
                db.close()
    except Exception as exc:
        logger.warning(f"[email] Could not resolve org contact email for org={organization_id}: {exc}")
        return None


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

    from app.config import settings as _staging_cfg

    original_recipient = email
    if _staging_cfg.STAGING_MODE and _staging_cfg.STAGING_SANDBOX_EMAIL:
        # Part 11 — staging must never let a dunning warning, invoice
        # receipt, or any other outbound billing email reach a real
        # customer address. This is the single shared dispatch primitive
        # every send_*_email() wrapper in this module ultimately calls, so
        # redirecting here covers all of them, not just billing-specific ones.
        email = _staging_cfg.STAGING_SANDBOX_EMAIL
        context = {**context, "subject": f"[STAGING → {original_recipient}] {context.get('subject', 'Zoiko Payroll — Notification')}"}

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
    body = _compose_email_html(template, full_context)
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
        "accent_bar": PALETTE["success"],
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
        "preheader": f"Seniority review form {form_name} needs your input.",
        "heading": "Action requested on your payroll details",
        "employee_name": employee_name,
        "form_name": form_name,
        "form_link": form_link,
        "expires_at": expires_at_display,
        "cta_url": form_link,
        "cta_label": "Fill Out Form",
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
        "accent_bar": PALETTE["success"] if approved else PALETTE["error"],
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


# ── Payroll-Core email templates (canonical blue/white, shared wrapper) ────
# All body-only fragments composed through _base_wrapper.html. Senders are
# best-effort: triggers call them inside their own try/except and log, so a
# failed notification never blocks the payroll action it reports.

def _payroll_send(
    email: str, template_name: str, context: dict, organization_id=None, db=None,
    accent: str = "",
) -> bool:
    if not email:
        return False
    from_email, from_display_name = _resolve_payroll_send_identity(organization_id, db=db)
    context.setdefault("accent_bar", accent)
    context.setdefault("support_email", "")
    return send_approval_email(email, template_name, context, db=db, organization_id=organization_id,
                               from_email_override=from_email, from_display_name_override=from_display_name)


def send_employee_created_email(
    email: str, employee_name: str, employee_code: str, department: str = "",
    designation: str = "", date_of_joining: str = "", organization_id=None, db=None,
) -> bool:
    return _payroll_send(email, "employee_created.html", {
        "subject": "You have been onboarded to payroll | Zoiko Payroll",
        "preheader": "Your employee record is active in Zoiko Payroll.",
        "heading": "Welcome to payroll",
        "employee_name": employee_name,
        "details_panel": _details_rows([
            ("Employee code", employee_code),
            ("Department", department),
            ("Designation", designation),
            ("Date of joining", date_of_joining),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["success"])


def send_employee_deleted_email(
    email: str, employee_name: str, employee_code: str, organization_id=None, db=None,
) -> bool:
    return _payroll_send(email, "employee_deleted.html", {
        "subject": "Your payroll record was removed | Zoiko Payroll",
        "preheader": "Your employee record is no longer active in payroll.",
        "heading": "Employee record removed",
        "employee_name": employee_name,
        "details_panel": _details_rows([
            ("Employee code", employee_code),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["error"])


def send_employee_sensitive_fields_changed_email(
    email: str, employee_name: str, changes, organization_id=None, db=None,
) -> bool:
    return _payroll_send(email, "employee_sensitive_fields_changed.html", {
        "subject": "Your payroll details were updated | Zoiko Payroll",
        "preheader": "Sensitive payroll details on your employee record changed.",
        "heading": "Payroll details updated",
        "employee_name": employee_name,
        "details_panel": _change_cells(changes),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


def send_payroll_run_created_email(
    org_email: str, pay_period: str, pay_date: str = "", run_code: str = "",
    employee_count: int = 0, organization_id=None, db=None,
) -> bool:
    cta = _frontend_base()
    return _payroll_send(org_email, "payroll_run_created.html", {
        "subject": f"Payroll run created — {pay_period} | Zoiko Payroll",
        "preheader": f"A new payroll run for {pay_period} was created.",
        "heading": "Payroll run created",
        "pay_period": pay_period,
        "cta_url": cta,
        "cta_label": "Review run",
        "details_panel": _details_rows([
            ("Pay period", pay_period),
            ("Pay date", pay_date),
            ("Run code", run_code),
            ("Employees", employee_count),
        ]),
    }, organization_id=organization_id, db=db)


def send_payroll_run_deleted_email(
    org_email: str, pay_period: str, run_code: str = "", organization_id=None, db=None,
) -> bool:
    return _payroll_send(org_email, "payroll_run_deleted.html", {
        "subject": f"Payroll run deleted — {pay_period} | Zoiko Payroll",
        "preheader": f"A draft payroll run for {pay_period} was deleted.",
        "heading": "Payroll run deleted",
        "pay_period": pay_period,
        "details_panel": _details_rows([
            ("Pay period", pay_period),
            ("Run code", run_code),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


def send_payslip_deleted_email(
    email: str, employee_name: str, payslip_number: str, pay_period: str,
    organization_id=None, db=None,
) -> bool:
    return _payroll_send(email, "payslip_deleted.html", {
        "subject": f"A draft payslip was removed — {pay_period} | Zoiko Payroll",
        "preheader": "A canceled payslip on your record was removed.",
        "heading": "Draft payslip removed",
        "employee_name": employee_name,
        "pay_period": pay_period,
        "details_panel": _details_rows([
            ("Payslip number", payslip_number),
            ("Pay period", pay_period),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


def send_leave_request_submitted_email(
    org_email: str, employee_name: str, leave_type: str, start_date: str, end_date: str,
    days: int, request_code: str, reason: str = "", organization_id=None, db=None,
) -> bool:
    cta = _frontend_base()
    leave_label = _LEAVE_TYPE_LABELS.get(str(leave_type).lower(), str(leave_type) or "Leave")
    return _payroll_send(org_email, "leave_request_submitted.html", {
        "subject": f"Leave request submitted — {request_code} | Zoiko Payroll",
        "preheader": f"{employee_name} submitted {leave_label} from {start_date} to {end_date}.",
        "heading": "Leave request submitted",
        "cta_url": cta,
        "cta_label": "Review request",
        "employee_name": employee_name,
        "leave_type": leave_label,
        "start_date": start_date,
        "end_date": end_date,
        "details_panel": _details_rows([
            ("Employee", employee_name),
            ("Leave type", leave_label),
            ("Dates", f"{start_date} to {end_date}"),
            ("Days", f"{days} day(s)"),
            ("Request code", request_code),
            ("Reason", reason or "—"),
        ]),
    }, organization_id=organization_id, db=db)


def send_elster_filing_status_email(
    org_email: str, status: str, transmission_type: str, period_start: str, period_end: str,
    blocked_reason: str = None, transferticket: str = None, organization_id=None, db=None,
) -> bool:
    """Status-accurate ELSTER notification: a QUEUED/TRANSMITTED/ACKNOWLEDGED
    row is a *submitted* filing; BLOCKED_EXTERNAL/REJECTED is a *blocked* one.
    The template variants never infer the outcome from intent — the product
    status decides which copy is true."""
    submitted = status in ("QUEUED", "TRANSMITTED", "ACKNOWLEDGED")
    template_name = "elster_filing_submitted.html" if submitted else "elster_filing_blocked.html"
    action = "submitted" if submitted else "blocked"
    context = {
        "subject": f"ELSTER filing {action} — {transmission_type} | Zoiko Payroll",
        "preheader": f"Your {transmission_type} ELSTER filing was {action}.",
        "heading": f"ELSTER filing {action}",
        "transmission_type": transmission_type,
        "period_start": period_start,
        "period_end": period_end,
        "status": status,
        "blocked_reason": blocked_reason or "",
        "transferticket": transferticket or "",
    }
    context["details_panel"] = _details_rows([
        ("Filing type", transmission_type),
        ("Period", f"{period_start} to {period_end}"),
        ("Status", status),
        ("Transfer ticket", transferticket or "—"),
        ("Reason", blocked_reason or "—"),
    ])
    accent = PALETTE["success"] if submitted else PALETTE["error"]
    return _payroll_send(org_email, template_name, context,
                         organization_id=organization_id, db=db, accent=accent)


def send_jurisdiction_pack_changed_email(
    org_email: str, pack_id: str, version: str, jurisdiction: str, changes,
    organization_id=None, db=None,
) -> bool:
    cta = _frontend_base()
    return _payroll_send(org_email, "jurisdiction_pack_changed.html", {
        "subject": f"Jurisdiction pack updated — {pack_id} v{version} | Zoiko Payroll",
        "preheader": f"Classification pack {pack_id} v{version} ({jurisdiction}) changed.",
        "heading": "Jurisdiction pack updated",
        "pack_id": pack_id,
        "version": version,
        "jurisdiction": jurisdiction,
        "cta_url": cta,
        "cta_label": "Review pack",
        "details_panel": _change_cells(changes),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


def send_organization_details_changed_email(
    org_email: str, changes, organization_id=None, db=None,
) -> bool:
    return _payroll_send(org_email, "organization_details_changed.html", {
        "subject": "Organization details updated | Zoiko Payroll",
        "preheader": "Registered organization details changed.",
        "heading": "Organization details updated",
        "details_panel": _change_cells(changes),
    }, organization_id=organization_id, db=db)


def send_report_generated_email(
    org_email: str, report_label: str, pay_period: str, report_id: int,
    template_version: str = "", organization_id=None, db=None,
) -> bool:
    cta = _frontend_base()
    return _payroll_send(org_email, "report_generated_ready.html", {
        "subject": f"Report ready — {report_label} | Zoiko Payroll",
        "preheader": f"{report_label} for {pay_period} was generated successfully.",
        "heading": "Report ready",
        "report_label": report_label,
        "pay_period": pay_period,
        "cta_url": cta,
        "cta_label": "View report",
        "details_panel": _details_rows([
            ("Report", report_label),
            ("Pay period", pay_period),
            ("Template version", template_version or "—"),
            ("Report ID", report_id),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["success"])


def send_report_generation_failed_email(
    org_email: str, report_label: str, pay_period: str, reason: str,
    organization_id=None, db=None,
) -> bool:
    return _payroll_send(org_email, "report_generation_failed.html", {
        "subject": f"Report generation failed — {report_label} | Zoiko Payroll",
        "preheader": f"{report_label} for {pay_period} could not be generated.",
        "heading": "Report generation failed",
        "report_label": report_label,
        "pay_period": pay_period,
        "details_panel": _details_rows([
            ("Report", report_label),
            ("Pay period", pay_period),
            ("Reason", reason or "Unknown error. Retry generation."),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["error"])


# ── Enterprise / Policy / Forms / Organizations / Billing / Super-Admin emails ──
# Batch-2 canonical blue/white templates on the same shared wrapper. Senders are
# best-effort: triggers call them inside try/except and log, so a failed
# notification never blocks the underlying Enterprise/Policy/Form/Org action.

def _human_key(key, fallback):
    """CAPS_SNAKE or camelCase config key → a readable label. Fallback when
    empty, plus upper-CAPS -> Title casing for acronym-ish integration keys."""
    if not key:
        return fallback
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", str(key).replace("_", " ")).title()


_FEATURE_LABELS = {
    "assist_seats": "Assist seats",
    "assist_ai_credits": "Assist AI credits",
    "storage_gb": "Storage",
    "api_requests": "API requests",
}


def _entitlement_feature_label(feature_key):
    if not feature_key:
        return "Requested feature"
    if feature_key in _FEATURE_LABELS:
        return _FEATURE_LABELS[feature_key]
    return _human_key(feature_key, "Requested feature")


def send_jurisdiction_added_email(org_email, country_label, country_code, organization_id=None, db=None):
    return _payroll_send(org_email, "jurisdiction_added.html", {
        "subject": f"Jurisdiction added — {country_label} | Zoiko Payroll",
        "preheader": f"{country_label} was added to Enterprise Payroll in draft.",
        "heading": "Jurisdiction added",
        "country_label": country_label,
        "details_panel": _details_rows([
            ("Country", country_label),
            ("Code", country_code),
            ("Status", "Draft"),
        ]),
    }, organization_id=organization_id, db=db)


def send_jurisdiction_config_updated_email(org_email, country_label, changes, status_note="", organization_id=None, db=None):
    return _payroll_send(org_email, "jurisdiction_config_updated.html", {
        "subject": f"Jurisdiction configuration updated — {country_label} | Zoiko Payroll",
        "preheader": f"Configuration for {country_label} changed.",
        "heading": "Configuration updated",
        "country_label": country_label,
        "status_note": status_note,
        "details_panel": _change_cells(changes),
    }, organization_id=organization_id, db=db, accent=PALETTE["cta"])


def send_jurisdiction_verified_email(org_email, country_label, active_switched=False, organization_id=None, db=None):
    return _payroll_send(org_email, "jurisdiction_verified.html", {
        "subject": f"Jurisdiction verified — {country_label} | Zoiko Payroll",
        "preheader": f"{country_label} verified and ready for production payroll.",
        "heading": "Jurisdiction verified",
        "country_label": country_label,
        "active_switched": active_switched,
        "details_panel": _details_rows([
            ("Country", country_label),
            ("Status", "Verified"),
            ("Ready for production payroll", "Yes"),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["success"])


def send_jurisdiction_removed_email(org_email, country_label, organization_id=None, db=None):
    return _payroll_send(org_email, "jurisdiction_removed.html", {
        "subject": f"Jurisdiction removed — {country_label} | Zoiko Payroll",
        "preheader": f"{country_label} was removed from Enterprise Payroll.",
        "heading": "Jurisdiction removed",
        "country_label": country_label,
        "details_panel": _details_rows([
            ("Country", country_label),
            ("Status", "Removed"),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


def send_enterprise_activated_email(org_email, jurisdictions_label, organization_id=None, db=None):
    return _payroll_send(org_email, "enterprise_activated.html", {
        "subject": "Enterprise Payroll activated | Zoiko Payroll",
        "preheader": "Enterprise Payroll is active for your organization.",
        "heading": "Enterprise Payroll active",
        "jurisdictions_label": jurisdictions_label,
        "details_panel": _details_rows([
            ("Mode", "Enterprise"),
            ("Status", "Active"),
            ("Jurisdictions", jurisdictions_label),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["success"])


def send_enterprise_deactivated_email(org_email, organization_id=None, db=None):
    return _payroll_send(org_email, "enterprise_deactivated.html", {
        "subject": "Enterprise Payroll deactivated | Zoiko Payroll",
        "preheader": "Payroll reverted to Standard mode.",
        "heading": "Enterprise Payroll deactivated",
        "details_panel": _details_rows([
            ("Mode", "Standard"),
            ("Status", "Deactivated"),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


def send_payroll_policy_changed_email(org_email, policy_name, changes, organization_id=None, db=None):
    return _payroll_send(org_email, "payroll_policy_changed.html", {
        "subject": f"Payroll policy changed — {policy_name} | Zoiko Payroll",
        "preheader": f"Settings on payroll policy {policy_name} changed.",
        "heading": "Payroll policy changed",
        "policy_name": policy_name,
        "details_panel": _change_cells(changes),
    }, organization_id=organization_id, db=db, accent=PALETTE["cta"])


def send_integration_status_changed_email(org_email, policy_name, provider_key, category, enabled, organization_id=None, db=None):
    provider_label = _human_key(provider_key, "Integration")
    category_label = _human_key(category, "Integration")
    return _payroll_send(org_email, "integration_status_changed.html", {
        "subject": f"Integration {'enabled' if enabled else 'disabled'} — {provider_label} | Zoiko Payroll",
        "preheader": f"{provider_label} integration was {'enabled' if enabled else 'disabled'} on {policy_name}.",
        "heading": f"Integration {'enabled' if enabled else 'disabled'}",
        "policy_name": policy_name,
        "provider_label": provider_label,
        "category_label": category_label,
        "enabled": enabled,
        "disabled": not enabled,
        "state_word": "enabled" if enabled else "disabled",
        "state_color": "15803d" if enabled else "5b7290",
        "details_panel": _details_rows([
            ("Provider", provider_label),
            ("Category", category_label),
            ("Policy", policy_name),
            ("Status", "Enabled" if enabled else "Disabled"),
        ]),
    }, organization_id=organization_id, db=db,
        accent=PALETTE["success"] if enabled else PALETTE["muted"])


def send_form_submission_approved_email(email, employee_name, form_name, organization_id=None, db=None):
    return _payroll_send(email, "form_submission_approved.html", {
        "subject": f"Submission approved — {form_name} | Zoiko Payroll",
        "preheader": f"Your {form_name} submission was approved.",
        "heading": "Submission approved",
        "employee_name": employee_name,
        "form_name": form_name,
    }, organization_id=organization_id, db=db, accent=PALETTE["success"])


def send_form_submission_rejected_email(email, employee_name, form_name, notes="", organization_id=None, db=None):
    return _payroll_send(email, "form_submission_rejected.html", {
        "subject": f"Submission rejected — {form_name} | Zoiko Payroll",
        "preheader": f"Your {form_name} submission was rejected.",
        "heading": "Submission rejected",
        "employee_name": employee_name,
        "form_name": form_name,
        "notes": notes or "",
    }, organization_id=organization_id, db=db, accent=PALETTE["error"])


def send_form_public_submission_confirmation_email(email, employee_name, form_name, organization_id=None, db=None):
    return _payroll_send(email, "form_public_submission_confirmation.html", {
        "subject": f"Form submitted — {form_name} | Zoiko Payroll",
        "preheader": f"Your response to {form_name} was submitted for review.",
        "heading": "Response submitted",
        "employee_name": employee_name,
        "form_name": form_name,
    }, organization_id=organization_id, db=db)


def send_assist_kill_switch_alert_email(enabled, toggled_by, db=None):
    """Internal ops alert for the Assist kill-switch. Recipient is resolved
    from backend settings only (the ops/support inbox or SMTP origin) — never
    a customer organization's admin — so a switch flip is announced on
    Zoiko's own channels, not any org's mailbox."""
    from app.config import settings

    recipient = settings.ASSIST_SUPPORT_EMAIL or settings.SMTP_FROM_EMAIL
    if not recipient:
        return False
    from datetime import datetime, timezone

    return send_approval_email(recipient, "assist_kill_switch_alert.html", {
        "subject": f"Assist kill-switch {'ENABLED' if enabled else 'DISABLED'} — ops alert | Zoiko Payroll",
        "preheader": f"Platform-wide Assist is {'suspended' if enabled else 'available again'}.",
        "heading": "Assist kill-switch",
        "enabled": enabled,
        "disabled": not enabled,
        "state_word": "enabled" if enabled else "disabled",
        "state_color": "b91c1c" if enabled else "15803d",
        "toggled_by": toggled_by or "a Zoiko Payroll operator",
        "timestamp": datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC"),
    }, db=db, from_email_override=settings.SMTP_FROM_EMAIL,
        from_display_name_override="Zoiko Payroll Operations")


def send_organization_suspended_email(org_email, org_name, suspended, reason="", organization_id=None, db=None):
    return _payroll_send(org_email, "organization_suspended.html", {
        "subject": f"Organization {'suspended' if suspended else 'reactivated'} | Zoiko Payroll",
        "preheader": f"{org_name} is {'suspended' if suspended else 'reactivated'}.",
        "heading": f"Organization {'suspended' if suspended else 'reactivated'}",
        "org_name": org_name,
        "suspended": suspended,
        "restored": not suspended,
        "reason": reason or "",
    }, organization_id=organization_id, db=db,
        accent=PALETTE["error"] if suspended else PALETTE["success"])


def send_organization_deleted_email(org_email, org_name, organization_id=None, db=None):
    return _payroll_send(org_email, "organization_deleted.html", {
        "subject": f"Organization data deleted — {org_name} | Zoiko Payroll",
        "preheader": f"{org_name} and all of its data were deleted.",
        "heading": "Organization deleted",
        "org_name": org_name,
    }, organization_id=None, db=db, accent=PALETTE["warning"])


def send_entitlement_override_granted_email(org_email, feature_key, limit_value, reason, expires_at, organization_id=None, db=None):
    feature_label = _entitlement_feature_label(feature_key)
    limit_display = "Unlimited" if limit_value is None else str(limit_value)
    if hasattr(expires_at, "strftime"):
        expires_display = expires_at.strftime("%b %d, %Y")
    else:
        expires_display = str(expires_at or "—")
    return _payroll_send(org_email, "entitlement_override_granted.html", {
        "subject": f"Entitlement granted — {feature_label} | Zoiko Payroll",
        "preheader": f"An override for {feature_label} was granted to your organization.",
        "heading": "Entitlement granted",
        "feature_label": feature_label,
        "limit_display": limit_display,
        "details_panel": _details_rows([
            ("Feature", feature_label),
            ("Limit", limit_display),
            ("Reason", reason or "—"),
            ("Expires", expires_display),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["cta"])


def send_user_status_changed_email(email, user_name, is_active, organization_id=None, db=None):
    return _payroll_send(email, "user_status_changed.html", {
        "subject": f"Your account was {'deactivated' if not is_active else 'reactivated'} | Zoiko Payroll",
        "preheader": f"Your Zoiko Payroll account is {'deactivated' if not is_active else 'active'}.",
        "heading": "Account status changed",
        "user_name": user_name or "there",
        "deactivated": not is_active,
        "activated": is_active,
    }, organization_id=organization_id, db=db,
        accent=PALETTE["error"] if not is_active else PALETTE["success"])


def send_policy_assigned_to_organization_email(org_email, pack_label, version="", country_label="", organization_id=None, db=None):
    return _payroll_send(org_email, "policy_assigned_to_organization.html", {
        "subject": f"Compliance policy assigned — {pack_label} | Zoiko Payroll",
        "preheader": f"The compliance policy {pack_label} was assigned to your organization.",
        "heading": "Compliance policy assigned",
        "pack_label": pack_label,
        "version": version,
        "country_label": country_label,
        "details_panel": _details_rows([
            ("Policy", pack_label),
            ("Version", version or "—"),
            ("Country", country_label or "—"),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["cta"])


def send_organization_currency_changed_email(org_email, org_name, old_currency, new_currency, organization_id=None, db=None):
    return _payroll_send(org_email, "organization_currency_changed.html", {
        "subject": f"Organization currency changed — {old_currency or '—'} to {new_currency or '—'} | Zoiko Payroll",
        "preheader": f"The currency for {org_name} changed from {old_currency or '—'} to {new_currency or '—'}.",
        "heading": "Currency changed",
        "org_name": org_name,
        "old_currency": old_currency or "—",
        "new_currency": new_currency or "—",
        "details_panel": _details_rows([
            ("Organization", org_name),
            ("Previous currency", old_currency or "—"),
            ("New currency", new_currency or "—"),
        ]),
    }, organization_id=organization_id, db=db, accent=PALETTE["warning"])


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


def send_password_changed_email(
    email: str,
    first_name: str,
    changed_at_display: str,
    organization_id=None,
    db=None,
) -> bool:
    """IAM-008 (Class P1): self-service password changed while logged in.
    Pure notice — password is already changed, so no link/token, and per §07
    prohibited-in-email rules no old/new password and no undo link."""
    return send_approval_email(email, "password_changed.html", {
        "subject": "Your Zoiko Payroll password was changed",
        "preheader": "Your password was changed on your account.",
        "first_name": first_name,
        "changed_at_display": changed_at_display,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_password_reset_self_service_email(
    email: str,
    first_name: str,
    changed_at_display: str,
    organization_id=None,
    db=None,
) -> bool:
    """IAM-009 (Class P1): self-service random-password replacement. Same
    security-notice shape as IAM-008 — no link, no token."""
    return send_approval_email(email, "password_reset_self_service.html", {
        "subject": "Your Zoiko Payroll password was replaced",
        "preheader": "A new password was generated for your account.",
        "first_name": first_name,
        "changed_at_display": changed_at_display,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_password_reset_completed_email(
    email: str,
    first_name: str,
    reset_at_display: str,
    organization_id=None,
    db=None,
) -> bool:
    """IAM-010 (Class P1): a password reset (via reset link) just completed.
    Confirmation only — no link, contact support if this wasn't the owner."""
    return send_approval_email(email, "password_reset_completed.html", {
        "subject": "Your Zoiko Payroll password has been reset",
        "preheader": "Your password was successfully reset.",
        "first_name": first_name,
        "reset_at_display": reset_at_display,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_role_changed_email(
    email: str,
    first_name: str,
    old_role_label: str,
    new_role_label: str,
    actor_name: str,
    changed_at_display: str,
    organization_id=None,
    db=None,
) -> bool:
    """IAM-011 (Class P1): the affected user's role changed. Recipient is the
    affected user; broader admin-notify is a flagged follow-up, not built here."""
    return send_approval_email(email, "role_changed.html", {
        "subject": "Your Zoiko Payroll role has changed",
        "preheader": "Your access role changed.",
        "first_name": first_name,
        "old_role_label": old_role_label or "Unknown",
        "new_role_label": new_role_label or "Unknown",
        "actor_name": actor_name or "an organization administrator",
        "changed_at_display": changed_at_display,
        "support_email": "",
    }, db=db, organization_id=organization_id, from_display_name_override=SECURITY_SENDER)


def send_account_deactivated_email(
    email: str,
    first_name: str,
    actor_name: str,
    deactivated_at_display: str,
    organization_id=None,
    db=None,
) -> bool:
    """IAM-012 (Class P1): org-admin self-service deactivation notice. Sent to
    the deactivated user — their email is still a valid delivery target even
    though their account access is revoked (intended, not a bug)."""
    return send_approval_email(email, "account_deactivated.html", {
        "subject": "Your Zoiko Payroll account has been deactivated",
        "preheader": "Your account access was deactivated.",
        "first_name": first_name,
        "actor_name": actor_name or "an organization administrator",
        "deactivated_at_display": deactivated_at_display,
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
    plan_display_name: Optional[str] = None,
    setup_link: str = "",
    organization_id=None,
    db=None,
) -> bool:
    """COM-001 (Class P1): Organization account created notification.
    Sent only to the primary administrator upon organization creation.

    plan_display_name is the real BillingPlan.name (e.g. "Professional"),
    resolved by the caller from the plan_code the customer picked on
    RegisterPage.jsx — checkout hasn't happened yet at send time, so this
    is informational only, not a billing/entitlement source of truth.
    Previously this template received product_route ("standalone_payroll")
    and never rendered it at all — every plan's welcome email was
    byte-identical, naming no plan. None (unresolved code, or a trial/
    Enterprise path this parameter doesn't apply to) omits the line
    entirely rather than showing a blank or a raw code string."""
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
            "heading": "Your Zoiko Payroll organization has been created",
            "recipient_first_name": recipient_first_name or "Admin",
            "organization_name": organization_name,
            "product_route": product_route,
            "plan_display_name": plan_display_name,
            "reference_id": reference_id,
            "cta_url": setup_link,
            "cta_label": "Begin organization setup",
        },
        db=db,
        organization_id=organization_id,
        from_display_name_override=SECURITY_SENDER,
    )


def send_trial_organization_created_email(
    email: str,
    recipient_first_name: str,
    organization_name: str,
    reference_id: str = "",
    evaluation_days: int = 30,
    evaluation_end_date: str = "",
    setup_link: str = "",
    organization_id=None,
    db=None,
) -> bool:
    """COM-003 (Class P1): 30-day Professional Evaluation workspace created.
    Sent only to the primary administrator upon evaluation signup
    (/auth/register-trial). States the evaluation terms explicitly."""
    from app.config import settings
    if not reference_id:
        import uuid
        reference_id = f"TRIAL-{uuid.uuid4().hex[:4].upper()}-INIT"
    if not setup_link:
        frontend_base = os.environ.get("ACTION_BASE_URL", "").rstrip("/") or settings.FRONTEND_URL.rstrip("/")
        setup_link = f"{frontend_base}/login"

    return send_approval_email(
        email,
        "trial_org_created.html",
        {
            "subject": "Your Zoiko Payroll 30-Day Evaluation has been created",
            "preheader": "Explore Zoiko Payroll free for 30 days.",
            "recipient_first_name": recipient_first_name or "Admin",
            "organization_name": organization_name,
            "evaluation_days": evaluation_days,
            "evaluation_end_date": evaluation_end_date,
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
        "preheader": "Your support case was filed and is being reviewed.",
        "heading": "Your support request was received",
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
