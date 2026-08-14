"""
modules/payroll/mail/service.py
----------------------------------
Business logic for Payroll email settings (per-tenant SMTP send identity +
notification toggles).

Tenant isolation follows the exact convention already used everywhere else
in this module. Nothing here touches SMTP credentials except to read
whatever an org admin has already entered through the settings endpoint
this same submodule exposes.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.payroll.mail.models import PayrollEmailSettings
from app.modules.payroll.mail.schemas import PayrollEmailSettingsUpdate
from app.modules.payroll.models import ActivityStatus
from app.modules.payroll.service import log_activity

logger = logging.getLogger("zoiko")


# ── Email settings (per-tenant send identity) ────────────────────────────

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

    for field, value in updates.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    log_activity(
        db, organization_id, "Payroll email sender identity updated.",
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
