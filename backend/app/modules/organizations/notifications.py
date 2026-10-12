"""
modules/organizations/notifications.py
--------------------------------------
Organization-lifecycle notices routed through the shared communications
dispatcher. Used by the Super Admin organization endpoints and by auth's
self-serve registration (ADM-001 alert), so both paths audit identically.
"""

from app.modules.communications.service import idempotency_key, queue_email, snapshot

ORG_CREATED_EVENT = "commercial.organization_created"
ORG_CREATED_TEMPLATE_ID = "COM-001"
# ADM-001 — cited by send_super_admin_org_created_notification_email's own
# governance docstring.
ORG_CREATED_ALERT_EVENT = "platform.organization_created_alert"
ORG_CREATED_ALERT_TEMPLATE_ID = "ADM-001"

_ORG_ALERT_FIELDS = (
    "id", "organization_name", "organization_code", "city", "state", "country",
    "industry", "company_type", "tax_no", "registration_number", "email", "phone", "created_at",
)
_ADMIN_ALERT_FIELDS = ("first_name", "last_name", "email", "phone")


def queue_super_admin_org_created_alerts(db, org, admin_user=None, *, module: str, actor_user_id=None) -> None:
    """ADM-001: one audited send per Super Admin recipient. Keyed on the
    organization — a new org is announced exactly once per recipient."""
    from app.services.email_service import (
        resolve_super_admin_alert_recipients,
        send_super_admin_org_created_notification_email,
    )

    org_snap = snapshot(org, *_ORG_ALERT_FIELDS)
    admin_snap = snapshot(admin_user, *_ADMIN_ALERT_FIELDS)
    reference_id = f"ADM-ORG-{org_snap.id:04d}"
    for recipient in resolve_super_admin_alert_recipients(db):
        queue_email(
            module, ORG_CREATED_ALERT_EVENT, ORG_CREATED_ALERT_TEMPLATE_ID, recipient,
            idempotency_key(org_snap.id, ORG_CREATED_ALERT_EVENT, recipient, ORG_CREATED_ALERT_TEMPLATE_ID, f"org:{org_snap.id}"),
            send_super_admin_org_created_notification_email,
            send_kwargs=dict(org=org_snap, admin_user=admin_snap, reference_id=reference_id, recipient_email=recipient),
            organization_id=org_snap.id,
            actor_user_id=actor_user_id,
            db=db,
        )
