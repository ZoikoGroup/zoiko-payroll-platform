"""
modules/billing/enterprise_order_form.py
-------------------------------------------
Part 12 — recording a signed Enterprise Order Form. The ONE path that
directly sets an org billable by human decision, mirroring how this whole
ledger already treats Enterprise as outside self-service entirely.
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import AlreadyExistsException
from app.modules.billing.models import (
    BillingAuthority,
    BillingCommercialAuditEvent,
    BillingSubscription,
    EnterpriseOrderForm,
    SubscriptionStatus,
)


def record_order_form(
    db: Session,
    organization_id: int,
    contract_reference: str,
    negotiated_scale_limits: dict,
    negotiated_price_terms: dict,
    term_start: date,
    term_end: Optional[date],
    signed_by_user_id: int,
) -> EnterpriseOrderForm:
    """Records a signed Order Form and, in the same transaction:
      - sets Organization.commercial_route = ENTERPRISE_ORDER_FORM,
        billing_classification = COMMERCIAL_ACTIVE, charge_enabled = True
      - creates/updates the matching BillingSubscription with
        billing_authority = ENTERPRISE_ORDER_FORM (no plan_version_id — see
        BillingSubscription.plan_version_id's own nullable requirement note
        below; Enterprise orgs are never plan-versioned)
      - sets service_commencement_at = term_start (Part 2 — an Enterprise
        deal's commencement is whatever the contract says, not "now")
    """
    from app.modules.organizations.models import Organization

    existing = db.query(EnterpriseOrderForm).filter(EnterpriseOrderForm.organization_id == organization_id).first()
    if existing is not None:
        raise AlreadyExistsException("Enterprise Order Form", "organization_id")

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Organization", organization_id)

    order_form = EnterpriseOrderForm(
        organization_id=organization_id,
        contract_reference=contract_reference,
        negotiated_scale_limits=negotiated_scale_limits,
        negotiated_price_terms=negotiated_price_terms,
        term_start=term_start,
        term_end=term_end,
        signed_by=signed_by_user_id,
    )
    db.add(order_form)

    org.commercial_route = BillingAuthority.ENTERPRISE_ORDER_FORM.value
    org.billing_classification = "COMMERCIAL_ACTIVE"
    org.charge_enabled = True
    from datetime import datetime as _dt

    org.service_commencement_at = _dt.combine(term_start, _dt.min.time())
    db.add(org)

    sub = db.query(BillingSubscription).filter(BillingSubscription.organization_id == organization_id).first()
    period_end = _dt.combine(term_end, _dt.min.time()) if term_end else _dt.combine(term_start.replace(year=term_start.year + 100), _dt.min.time())
    if sub is None:
        sub = BillingSubscription(
            organization_id=organization_id,
            plan_version_id=None,
            billing_authority=BillingAuthority.ENTERPRISE_ORDER_FORM.value,
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=_dt.combine(term_start, _dt.min.time()),
            current_period_end=period_end,
        )
        db.add(sub)
    else:
        sub.billing_authority = BillingAuthority.ENTERPRISE_ORDER_FORM.value
        sub.plan_version_id = None
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.current_period_start = _dt.combine(term_start, _dt.min.time())
        sub.current_period_end = period_end
        db.add(sub)

    db.add(
        BillingCommercialAuditEvent(
            organization_id=organization_id,
            actor_user_id=signed_by_user_id,
            event_type="ENTERPRISE_ORDER_FORM_RECORDED",
            payload={"contract_reference": contract_reference, "term_start": term_start.isoformat()},
        )
    )
    db.commit()
    db.refresh(order_form)
    return order_form
