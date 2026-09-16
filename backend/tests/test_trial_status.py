"""
tests/test_trial_status.py
--------------------------
Coverage for GET /auth/me/trial-status (auth.service.get_my_trial_status):

  1. An EVALUATION org with a TRIALING BillingSubscription → trial_status
     "ACTIVE" and trial_expires_at == current_period_end (the banner's only
     date source; no second date field is introduced).
  2. An EVALUATION org with no subscription → all-null trial fields.
  3. A PRODUCTION org (even with a TRIALING-looking subscription) →
     workspace_type "PRODUCTION" and all-null trial fields — the banner
     must only ever render for evaluation workspaces.
  4. Status mapping: ACTIVE/TRIALING → "ACTIVE", PAST_DUE →
     "GRACE_READONLY", SUSPENDED/CANCELLED → "CLOSED".
  5. A missing org row → defaults to "PRODUCTION" (safe, banner stays off).
"""

from datetime import datetime, timedelta

import pytest

from app.modules.auth.service import get_my_trial_status
from app.modules.billing.models import (
    BillingAuthority,
    BillingSubscription,
    SubscriptionStatus,
)
from app.modules.organizations.models import Organization


def _evaluation_org(db, name="Eval Org"):
    org = Organization(
        organization_name=name,
        organization_code="EVALORG",
        workspace_type="EVALUATION",
    )
    db.add(org)
    db.flush()
    return org


def _production_org(db, name="Prod Org"):
    org = Organization(
        organization_name=name,
        organization_code="PRODORG",
        workspace_type="PRODUCTION",
    )
    db.add(org)
    db.flush()
    return org


def _subscription(
    db,
    org,
    status=SubscriptionStatus.TRIALING.value,
    days_left=12,
    plan_version=None,
):
    start = datetime.utcnow() - timedelta(days=30 - days_left)
    sub = BillingSubscription(
        organization_id=org.id,
        plan_version_id=plan_version.id if plan_version is not None else None,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=status,
        current_period_start=start,
        current_period_end=start + timedelta(days=30),
    )
    db.add(sub)
    db.flush()
    return sub


def test_evaluation_trialing_returns_active_and_expiry(db, published_professional_plan):
    org = _evaluation_org(db)
    sub = _subscription(db, org, plan_version=published_professional_plan)

    result = get_my_trial_status(db, org.id)

    assert result.workspace_type == "EVALUATION"
    assert result.trial_status == "ACTIVE"
    assert result.trial_started_at == sub.current_period_start
    assert result.trial_expires_at == sub.current_period_end


def test_evaluation_no_subscription_returns_null_fields(db):
    org = _evaluation_org(db)

    result = get_my_trial_status(db, org.id)

    assert result.workspace_type == "EVALUATION"
    assert result.trial_status is None
    assert result.trial_started_at is None
    assert result.trial_expires_at is None


def test_production_org_never_reports_trial(db, published_professional_plan):
    org = _production_org(db)
    _subscription(db, org, plan_version=published_professional_plan)

    result = get_my_trial_status(db, org.id)

    assert result.workspace_type == "PRODUCTION"
    assert result.trial_status is None
    assert result.trial_started_at is None
    assert result.trial_expires_at is None


@pytest.mark.parametrize(
    "status,expected",
    [
        (SubscriptionStatus.TRIALING.value, "ACTIVE"),
        (SubscriptionStatus.ACTIVE.value, "ACTIVE"),
        (SubscriptionStatus.PAST_DUE.value, "GRACE_READONLY"),
        (SubscriptionStatus.SUSPENDED.value, "CLOSED"),
        (SubscriptionStatus.CANCELLED.value, "CLOSED"),
    ],
)
def test_status_mapping(db, status, expected, published_professional_plan):
    org = _evaluation_org(db, name=f"Eval {status}")
    _subscription(db, org, status=status, plan_version=published_professional_plan)

    result = get_my_trial_status(db, org.id)

    assert result.workspace_type == "EVALUATION"
    assert result.trial_status == expected
    assert result.trial_expires_at is not None


def test_missing_org_defaults_to_production(db):
    result = get_my_trial_status(db, organization_id=999999)

    assert result.workspace_type == "PRODUCTION"
    assert result.trial_status is None
    assert result.trial_expires_at is None