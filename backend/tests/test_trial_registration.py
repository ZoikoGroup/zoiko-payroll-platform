"""
tests/test_trial_registration.py
---------------------------------
Coverage for the 30-day Professional Evaluation registration path
(/auth/register-trial):

  1. An allow-listed country with NO active canonical compliance pack —
     rejected by production /auth/register (see
     test_registration_jurisdiction_gate.py) — still onboarded by
     register_trial with workspace_type="EVALUATION".
  2. A country outside REGISTRATION_COUNTRIES is rejected.
  3. Tax fields (tax_no / tax_identifiers) are rejected at the schema level:
     TrialRegisterRequest forbids extra fields, so a client submitting them
     gets a ValidationError, never a silently-discarded payload.
  4. A successfully created evaluation org does not persist any tax columns.
  5. A successful signup creates a TRIALING BillingSubscription against the
     PUBLISHED PROFESSIONAL plan version plus a TRIAL_SUBSCRIPTION_CREATED
     billing_commercial_audit_events row.
  6. If no PUBLISHED PROFESSIONAL plan version exists the signup is rejected
     and nothing is committed.
"""

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestException
from app.modules.auth.schemas import TrialRegisterRequest
from app.modules.auth.service import register_trial
from app.modules.auth.models import User
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    BillingSubscription,
    SubscriptionStatus,
)
from app.modules.organizations.models import Organization


def _trial_data(country, email="trial-admin@example.com", **overrides):
    fields = dict(
        organization="Trial Co", name="Tia Trial", email=email, password="a-strong-password-1",
        country=country,
    )
    fields.update(overrides)
    return TrialRegisterRequest(**fields)


def test_trial_registration_succeeds_where_production_is_blocked(db, published_professional_plan):
    # Australia has no Active canonical compliance pack in the bare fixture DB
    # — production registration rejects it, the evaluation path must not.
    result = register_trial(db, _trial_data("Australia"))
    assert result is not None
    org = db.query(Organization).filter(Organization.country == "Australia").first()
    assert org is not None
    assert org.workspace_type == "EVALUATION"
    admin = db.query(User).filter(User.email == "trial-admin@example.com").first()
    assert admin is not None
    assert admin.is_active and admin.is_verified

    subscription = db.query(BillingSubscription).filter(
        BillingSubscription.organization_id == org.id
    ).first()
    assert subscription is not None
    assert subscription.plan_version_id == published_professional_plan.id
    assert subscription.status == SubscriptionStatus.TRIALING.value
    assert subscription.billing_authority == "STANDALONE"
    assert subscription.current_period_start is not None
    assert subscription.current_period_end is not None
    assert (subscription.current_period_end - subscription.current_period_start).days == 30

    event = (
        db.query(BillingCommercialAuditEvent)
        .filter(
            BillingCommercialAuditEvent.organization_id == org.id,
            BillingCommercialAuditEvent.event_type == "TRIAL_SUBSCRIPTION_CREATED",
        )
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin.id
    assert event.payload["plan_code"] == "PROFESSIONAL"
    assert event.payload["subscription_id"] == subscription.id


def test_trial_registration_rejects_unlisted_country(db):
    with pytest.raises(BadRequestException):
        register_trial(db, _trial_data("Nonexistria"))
    assert db.query(Organization).count() == 0
    assert db.query(User).count() == 0


def test_trial_registration_rejects_tax_fields_at_schema_level(db):
    with pytest.raises(ValidationError):
        _trial_data("India", tax_no="36AAACI1234F1Z9")
    with pytest.raises(ValidationError):
        _trial_data("India", tax_identifiers={"gstin": "36AAACI1234F1Z9"})
    assert db.query(Organization).count() == 0


def test_trial_registration_persists_no_tax_columns(db, published_professional_plan):
    register_trial(db, _trial_data("India"))
    org = db.query(Organization).filter(Organization.organization_name == "Trial Co").first()
    assert org is not None
    assert org.tax_no is None
    assert org.tax_identifiers is None
    assert org.registration_number is None
    assert org.workspace_type == "EVALUATION"


def test_trial_registration_rolls_back_when_no_published_plan(db):
    with pytest.raises(BadRequestException):
        register_trial(db, _trial_data("India"))
    assert db.query(Organization).count() == 0
    assert db.query(User).count() == 0