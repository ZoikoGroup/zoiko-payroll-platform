"""
tests/test_order_form_eligibility.py
--------------------------------------
Coverage for the Order Forms page's eligibility computation: an org must
not be offered in the picker if record_order_form would refuse it. The
endpoint and page use exactly the same two refusal paths as the guard in
record_order_form / entitlements.assert_no_overlapping_billable_ownership.
"""

from datetime import date, datetime, timedelta

from app.modules.billing.enterprise_order_form import list_order_form_eligibility, record_order_form
from app.modules.billing.models import (
    BillingAuthority,
    BillingSubscription,
    EnterpriseOrderForm,
    SubscriptionStatus,
)


def _snapshot(db):
    return {item["organization_id"]: item for item in list_order_form_eligibility(db)}


def test_org_with_no_billing_relationship_is_eligible(db, organization):
    entry = _snapshot(db)[organization.id]
    assert entry["eligible"] is True
    assert entry["block_reason"] is None


def test_org_with_standalone_subscription_is_ineligible(db, organization):
    db.add(
        BillingSubscription(
            organization_id=organization.id,
            plan_version_id=None,
            billing_authority=BillingAuthority.STANDALONE.value,
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=datetime.utcnow() - timedelta(days=2),
            current_period_end=datetime.utcnow() + timedelta(days=28),
        )
    )
    db.commit()

    entry = _snapshot(db)[organization.id]
    assert entry["eligible"] is False
    assert "STANDALONE" in entry["block_reason"]


def test_org_with_existing_order_form_is_ineligible(db, organization):
    from app.modules.auth.models import User, UserRole
    from app.core.security import hash_password

    actor = User(
        email="eof-actor@example.com",
        hashed_password=hash_password("a-strong-password-1"),
        role=UserRole.SUPER_ADMIN,
        first_name="Super",
        last_name="Admin",
        phone="",
        is_active=True,
        is_verified=True,
    )
    db.add(actor)
    db.flush()

    record_order_form(
        db,
        organization_id=organization.id,
        contract_reference="OF-TEST-0001",
        negotiated_scale_limits={"max_entities": 5},
        negotiated_price_terms={"annual_usd": 50000},
        term_start=date(2026, 9, 1),
        term_end=None,
        signed_by_user_id=actor.id,
    )

    entry = _snapshot(db)[organization.id]
    assert entry["eligible"] is False
    assert "already has an enterprise order form" in entry["block_reason"].lower()


def test_org_with_enterprise_route_sub_but_no_form_is_eligible(db, organization):
    """Mirrors record_order_form's update-branch: a subscription already
    on the ENTERPRISE_ORDER_FORM route (without an Order Form row) is not a
    refusal — the create endpoint would simply update it."""
    db.add(
        BillingSubscription(
            organization_id=organization.id,
            plan_version_id=None,
            billing_authority=BillingAuthority.ENTERPRISE_ORDER_FORM.value,
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=datetime.utcnow() - timedelta(days=2),
            current_period_end=datetime.utcnow() + timedelta(days=28),
        )
    )
    db.commit()

    entry = _snapshot(db)[organization.id]
    assert entry["eligible"] is True
    assert entry["block_reason"] is None