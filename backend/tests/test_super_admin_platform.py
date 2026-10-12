"""
tests/test_super_admin_platform.py
------------------------------------
End-to-end coverage for the Super Admin platform section:

  1. Service Health — _service_health_report must report every registered
     background job, including the auth revoked-token cleanup sweep that
     runs at boot but was previously missing from the report (Gap #1).
  2. Integrations — list_integrations now reflects what this deployment
     actually has configured (Stripe/SMTP/Sentry/Assist), instead of an
     honest-but-empty placeholder.
  3. Security & Audit — security_audit_log applies actor/date filters at
     the SQL layer BEFORE paging (the old code filtered only the rows that
     survived `limit(page_size * page)`, so a filtered page could silently
     drop in-range rows), and total/pagination are exact across the four
     merged sources.

The two audit tables from assist/assisted_access must be registered on
Base.metadata BEFORE the `db` fixture runs create_all, so they are imported
at module level here (the fixture itself only imports organizations/auth/
payroll/billing models).
"""

from datetime import date, datetime

from app.config import settings
from app.modules.assist.models import AssistAuditEvent  # noqa: F401  (register table pre-create_all)
from app.modules.assisted_access.models import AssistedAccessAuditEvent  # noqa: F401
from app.modules.billing.models import BillingCommercialAuditEvent
from app.modules.payroll.models import TaxConfigurationAudit
from app.modules.super_admin.command_center_router import (
    _service_health_report,
    list_integrations,
    security_audit_log,
)


def _make_admin(db):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    admin = User(
        email="platform-auditor@example.com",
        hashed_password=hash_password("a-strong-password-1"),
        role=UserRole.SUPER_ADMIN,
        first_name="Super",
        last_name="Admin",
        phone="",
        is_active=True,
        is_verified=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _make_second_user(db):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    other = User(
        email="other-actor@example.com",
        hashed_password=hash_password("a-strong-password-1"),
        role=UserRole.ORG_ADMIN,
        first_name="Other",
        last_name="Actor",
        phone="",
        is_active=True,
        is_verified=True,
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    return other


def _seed_one_per_source(db, admin, org):
    """One row per audit source, at distinct ascending dates,
    so merge behavior and sorting are observable."""
    db.add(
        TaxConfigurationAudit(
            actor_id=admin.id,
            action="update",
            entity_type="tax_slab",
            entity_id=1,
            old_value={"rate": 0.1},
            new_value={"rate": 0.12},
            reason="Rate refresh",
            created_at=datetime(2026, 8, 1, 12, 0, 0),
        )
    )
    db.add(
        BillingCommercialAuditEvent(
            organization_id=org.id,
            actor_user_id=admin.id,
            event_type="subscription.created",
            payload={"plan": "professional"},
            created_at=datetime(2026, 8, 2, 12, 0, 0),
        )
    )
    db.add(
        AssistAuditEvent(
            organization_id=org.id,
            user_id=admin.id,
            event_type="assist.query",
            payload={"intent_id": "INT-1"},
            recorded_at=datetime(2026, 8, 3, 12, 0, 0),
        )
    )
    db.add(
        AssistedAccessAuditEvent(
            assisted_access_session_id=1,
            organization_id=org.id,
            actor_user_id=admin.id,
            event_type="ASSISTED_ACCESS_STARTED",
            method="GET",
            path="/api/v1/employees",
            status_code=200,
            recorded_at=datetime(2026, 8, 4, 12, 0, 0),
        )
    )
    db.commit()


# ── Service Health ─────────────────────────────────────────────────────────

def test_service_health_reports_all_six_jobs(db):
    report = _service_health_report(db)

    assert report["database"]["status"] == "healthy"
    job_names = {job["job"] for job in report["scheduled_jobs"]}
    assert job_names == {
        "trial_expiry_sweep",
        "dunning_sweep",
        "bwm_aggregation",
        "assist_sweep",
        "assisted_access_sweep",
        "token_cleanup_sweep",
    }
    for job in report["scheduled_jobs"]:
        assert job["state"] in {"unknown", "healthy", "error"}


# ── Integrations ───────────────────────────────────────────────────────────

def test_integrations_lists_configured_providers():
    result = list_integrations(_admin=None)

    slugs = {it["slug"] for it in result["integrations"]}
    assert slugs == {"stripe_billing", "email_smtp", "sentry", "assist_model"}
    for it in result["integrations"]:
        assert {"slug", "name", "configured", "status", "description"} <= set(it)
        assert isinstance(it["configured"], bool)
        assert it["status"]

    by_slug = {it["slug"]: it for it in result["integrations"]}
    assert by_slug["stripe_billing"]["configured"] == bool(settings.STRIPE_SECRET_KEY)
    assert by_slug["email_smtp"]["configured"] == bool(settings.SMTP_HOST)
    assert by_slug["sentry"]["configured"] == bool(settings.SENTRY_DSN)
    assert by_slug["assist_model"]["configured"] == bool(settings.ASSIST_MODEL_PROVIDER)

    connected = sum(1 for it in result["integrations"] if it["configured"])
    assert f"{connected} of {len(result['integrations'])}" in result["message"]


# ── Security & Audit ───────────────────────────────────────────────────────

def test_audit_merges_all_sources_sorted_desc(db, organization):
    admin = _make_admin(db)
    _seed_one_per_source(db, admin, organization)

    result = security_audit_log(db=db, _admin=None)

    assert result["total"] == 4
    assert result["returned"] == 4
    sources = {e["source"] for e in result["entries"]}
    assert sources == {"compliance", "billing", "assist", "assisted_access"}

    stamps = [e["timestamp"] for e in result["entries"]]
    assert all(isinstance(ts, datetime) for ts in stamps)
    assert stamps == sorted(stamps, reverse=True)

    ordered = {e["source"]: e for e in result["entries"]}
    assert ordered["compliance"]["action"] == "update"
    assert ordered["assisted_access"]["detail"]["method"] == "GET"


def test_audit_source_filter_narrows(db, organization):
    admin = _make_admin(db)
    _seed_one_per_source(db, admin, organization)

    result = security_audit_log(source="billing", db=db, _admin=None)
    assert result["total"] == 1
    assert result["entries"][0]["source"] == "billing"
    assert result["entries"][0]["action"] == "subscription.created"


def test_audit_actor_filter_matches_across_sources(db, organization):
    admin = _make_admin(db)
    other = _make_second_user(db)
    _seed_one_per_source(db, admin, organization)
    db.add(
        TaxConfigurationAudit(
            actor_id=other.id,
            action="create",
            entity_type="contribution_rate",
            entity_id=2,
            created_at=datetime(2026, 8, 5, 12, 0, 0),
        )
    )
    db.commit()

    result = security_audit_log(actor_id=other.id, db=db, _admin=None)
    assert result["total"] == 1
    assert result["entries"][0]["actor_id"] == other.id
    assert result["entries"][0]["source"] == "compliance"


def test_audit_date_range_is_exact_when_many_out_of_range(db, organization):
    admin = _make_admin(db)
    # 5 rows inside range 08-10..08-12, plus 20 rows on 08-01 (outside).
    for i in range(20):
        db.add(
            TaxConfigurationAudit(
                actor_id=admin.id,
                action="create",
                entity_type="tax_slab",
                entity_id=100 + i,
                created_at=datetime(2026, 8, 1, 9, 0, 0),
            )
        )
    for day in range(10, 13):
        db.add(
            TaxConfigurationAudit(
                actor_id=admin.id,
                action="update",
                entity_type="tax_slab",
                entity_id=day,
                created_at=datetime(2026, 8, day, 9, 0, 0),
            )
        )
    db.commit()

    result = security_audit_log(
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 12),
        db=db,
        _admin=None,
    )
    assert result["total"] == 3
    entry_days = sorted(e["timestamp"].day for e in result["entries"])
    assert entry_days == [10, 11, 12]


def test_audit_pagination_is_exact_over_union(db, organization):
    admin = _make_admin(db)
    for day in range(1, 8):
        db.add(
            TaxConfigurationAudit(
                actor_id=admin.id,
                action="create",
                entity_type="tax_slab",
                entity_id=day,
                created_at=datetime(2026, 7, day, 9, 0, 0),
            )
        )
    db.commit()

    page1 = security_audit_log(page=1, page_size=3, db=db, _admin=None)
    page2 = security_audit_log(page=2, page_size=3, db=db, _admin=None)
    page3 = security_audit_log(page=3, page_size=3, db=db, _admin=None)

    assert page1["total"] == 7
    assert [e["timestamp"].day for e in page1["entries"]] == [7, 6, 5]
    assert [e["timestamp"].day for e in page2["entries"]] == [4, 3, 2]
    assert [e["timestamp"].day for e in page3["entries"]] == [1]

    past_end = security_audit_log(page=3, page_size=5, db=db, _admin=None)
    assert past_end["returned"] == 0
    assert past_end["total"] == 7