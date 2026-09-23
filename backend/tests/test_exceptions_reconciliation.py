"""
tests/test_exceptions_reconciliation.py
------------------------------------------
End-to-end coverage for the Super Admin "Exceptions & Reconciliation"
section's two billing-backed buckets:

  1. BWM aggregation pipeline — aggregate_all_billing_months() (the batch
     the background scheduler and POST /super-admin/billing/aggregate-bwm
     both call) actually populates billing_worker_month_records and is
     idempotent. Previously aggregate_billing_month had no caller at all,
     so this table was permanently empty and bwm_invoice_mismatches could
     never disagree with anything.
  2. bwm_scale_limit_overages — the endpoint's _load_bwm_scale_limit_overages
     helper counts billable workers live and resolves the plan limit through
     entitlements (feature_keys.MAX_BWM vocabulary), instead of the old
     implementation that read a never-populated table against a wrong-key
     scale_limits lookup.
"""

from datetime import date, datetime, timedelta

from app.modules.billing import bwm as bwm_service
from app.modules.billing import plan_catalog
from app.modules.billing.feature_keys import MAX_BWM
from app.modules.billing.models import (
    BillingAuthority,
    BillingSubscription,
    BillingWorkerMonthRecord,
    SubscriptionStatus,
)
from app.modules.payroll.models import PayrollEmployee, PayrollScopeStatus
from app.modules.super_admin.command_center_router import _load_bwm_scale_limit_overages


def _make_employee(db, org, code, scope_status=PayrollScopeStatus.ACTIVE.value):
    emp = PayrollEmployee(
        organization_id=org.id,
        employee_code=code,
        name=f"Employee {code}",
        status="Active",
        payroll_scope_status=scope_status,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _publish_plan_with_bwm_limit(db, code, name, bwm_limit):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    actor = User(
        email=f"{code.lower()}-actor@example.com",
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

    plan = plan_catalog.create_plan(db, code, name, actor_user_id=actor.id)
    version = plan_catalog.create_plan_version(
        db,
        plan_id=plan.id,
        feature_set={"features": ["payroll_runs", MAX_BWM]},
        scale_limits={MAX_BWM: bwm_limit},
        actor_user_id=actor.id,
    )
    plan_catalog.add_entitlement_flag(
        db, plan_version_id=version.id, feature_key=MAX_BWM, limit_value=bwm_limit, actor_user_id=actor.id
    )
    plan_catalog.approve_plan_version(db, version.id, actor_user_id=actor.id)
    plan_catalog.publish_plan_version(db, version.id, published_by_user_id=actor.id)
    db.refresh(version)
    return version


def _subscribe(db, org, version):
    sub = BillingSubscription(
        organization_id=org.id,
        plan_version_id=version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow() - timedelta(days=5),
        current_period_end=datetime.utcnow() + timedelta(days=25),
    )
    db.add(sub)
    db.commit()
    return sub


def test_aggregate_all_billing_months_populates_and_is_idempotent(db, organization):
    _make_employee(db, organization, "A1")
    _make_employee(db, organization, "A2")
    month = date(2026, 5, 1)

    result = bwm_service.aggregate_all_billing_months(db, billing_month=month)

    assert result["billing_month"] == month
    assert result["organizations_processed"] == 1
    assert result["organizations"][0]["counted"] == 2

    records = (
        db.query(BillingWorkerMonthRecord)
        .filter(
            BillingWorkerMonthRecord.organization_id == organization.id,
            BillingWorkerMonthRecord.billing_month == month,
        )
        .all()
    )
    assert len(records) == 2
    assert all(record.counted is True for record in records)

    second = bwm_service.aggregate_all_billing_months(db, billing_month=month)
    assert second["organizations"][0]["created"] == 0
    assert second["organizations"][0]["updated"] == 2


def test_bwm_overage_surfaces_when_count_exceeds_plan_limit(db, organization):
    version = _publish_plan_with_bwm_limit(db, "OVERLIM", "Over Limit Co", bwm_limit=2)
    _subscribe(db, organization, version)
    for i in range(4):
        _make_employee(db, organization, f"OV{i}")
    month = date(2026, 5, 1)

    overages = _load_bwm_scale_limit_overages(db, month)
    assert len(overages) == 1
    overage = overages[0]
    assert overage["organization_id"] == organization.id
    assert overage["organization_name"] == organization.organization_name
    assert overage["bwm_count"] == 4
    assert overage["plan_limit"] == 2
    assert overage["over_by"] == 2


def test_no_overage_within_limit(db, organization):
    version = _publish_plan_with_bwm_limit(db, "WITHIN", "Within Limit Co", bwm_limit=10)
    _subscribe(db, organization, version)
    _make_employee(db, organization, "W1")
    _make_employee(db, organization, "W2")

    overages = _load_bwm_scale_limit_overages(db, date(2026, 5, 1))
    assert overages == []


def test_unsubscribed_org_is_skipped_not_flagged(db, organization):
    _make_employee(db, organization, "U1")

    overages = _load_bwm_scale_limit_overages(db, date(2026, 5, 1))
    assert overages == []


def test_excluded_statuses_do_not_count_toward_overage(db, organization):
    version = _publish_plan_with_bwm_limit(db, "EXCL", "Exclusion Co", bwm_limit=1)
    _subscribe(db, organization, version)
    _make_employee(db, organization, "X1", scope_status=PayrollScopeStatus.ACTIVE.value)
    _make_employee(db, organization, "X2", scope_status=PayrollScopeStatus.TEST.value)
    _make_employee(db, organization, "X3", scope_status=PayrollScopeStatus.DEMO.value)

    overages = _load_bwm_scale_limit_overages(db, date(2026, 5, 1))
    assert overages == []  # 1 counted <= limit 1