"""
tests/test_country_entitlement.py
-----------------------------------
Country entitlement (billing/jurisdiction_entitlement.py): an org may add
employees and run payroll only in countries it is entitled to, capped by
max_jurisdictions (Core 1, Professional 3, Business 10, Enterprise
negotiated). The registration country is the primary row and counts.

Hermetic like test_entitlement_enforcement.py: env vars set before
importing app.main, a throwaway on-disk SQLite shared by the TestClient and
this file's own SessionLocal. Runs with BILLING_ENFORCEMENT_MODE=enforce;
individual tests flip it at call time (settings is read per call).
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="country_entitlement_test_")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.sqlite3')}"
os.environ["ENVIRONMENT"] = "development"
os.environ["ASSIST_MODEL_PROVIDER"] = ""
os.environ["ASSIST_MODEL_BASE_URL"] = ""
os.environ["ASSIST_MODEL_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_FROM_EMAIL"] = ""
os.environ["ASSIST_SUPPORT_EMAIL"] = ""
os.environ["ASSIST_SWEEP_ENABLED"] = "false"
os.environ["TRIAL_SWEEP_ENABLED"] = "false"
_ENV_MODE_BEFORE = os.environ.get("BILLING_ENFORCEMENT_MODE")
os.environ["BILLING_ENFORCEMENT_MODE"] = "enforce"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_app_modules = {
    _mod: _module
    for _mod, _module in sys.modules.items()
    if _mod == "app" or _mod.startswith("app.")
}
for _mod in list(_saved_app_modules):
    del sys.modules[_mod]

from contextlib import contextmanager  # noqa: E402
from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.exceptions import BadRequestException, ForbiddenException  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import jurisdiction_entitlement as je  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.feature_keys import (  # noqa: E402
    MAX_BWM, MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES, PAYROLL_RUNS,
)
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority, BillingCommercialAuditEvent, BillingSubscription, EnterpriseOrderForm,
    OrganizationJurisdiction, SubscriptionStatus,
)
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import (  # noqa: E402
    CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem, PayslipStatus,
)

from sqlalchemy.engine import make_url as _make_url  # noqa: E402
from tests._mfa_login import mfa_login  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_country_entitlement must run on its own sqlite DB, got {engine.url}"
)

import sqlalchemy as sa  # noqa: E402


@sa.event.listens_for(engine, "connect")
def _register_pg_advisory_lock(dbapi_connection, connection_record):
    # code_generation.py takes a PostgreSQL-only advisory lock; a no-op on
    # SQLite (same stub as test_bulk_employees.py).
    dbapi_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 1)


engine.dispose()
Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="country-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super", last_name="Admin",
    organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()


def _flags(jurisdictions):
    # Generous BWM/entities so only the country limit is under test.
    return {PAYROLL_RUNS: None, MAX_ENTITIES: 10, MAX_JURISDICTIONS: jurisdictions,
            MAX_SCHEDULES: 10, MAX_BWM: 1000}


def _publish_plan(code, name, flags):
    plan = plan_catalog.create_plan(_db, code, name, actor_user_id=_super.id)
    version = plan_catalog.create_plan_version(
        _db, plan_id=plan.id,
        feature_set={"features": list(flags)},
        scale_limits={k: v for k, v in flags.items() if k in (MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES, MAX_BWM)},
        actor_user_id=_super.id,
    )
    for feature_key, limit_value in flags.items():
        plan_catalog.add_entitlement_flag(_db, version.id, feature_key, limit_value, actor_user_id=_super.id)
    plan_catalog.approve_plan_version(_db, version.id, actor_user_id=_super.id)
    return plan_catalog.publish_plan_version(_db, version.id, published_by_user_id=_super.id)


_core_version = _publish_plan("CORE", "Core", _flags(1))
_professional_version = _publish_plan("PROFESSIONAL", "Professional", _flags(3))
_business_version = _publish_plan("BUSINESS", "Business", _flags(10))


def _org(code, version, country="India", authority=BillingAuthority.STANDALONE.value):
    org = Organization(organization_name=f"{code} Co", organization_code=code,
                       workspace_type="PRODUCTION", country=country)
    _db.add(org)
    _db.flush()
    _db.add(User(
        email=f"{code.lower()}@example.com", hashed_password=hash_password("strong-password"),
        role=UserRole.ORG_ADMIN, first_name="Org", last_name="Admin",
        organization_id=org.id, is_active=True,
    ))
    if version is not None or authority != BillingAuthority.STANDALONE.value:
        _db.add(BillingSubscription(
            organization_id=org.id, plan_version_id=version.id if version else None,
            billing_authority=authority, status=SubscriptionStatus.ACTIVE.value,
            current_period_start=datetime.utcnow() - timedelta(days=5),
            current_period_end=datetime.utcnow() + timedelta(days=25),
        ))
    _db.commit()
    return org


def _employee(org, code, country):
    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Employee {code}",
                          status="Active", country_code=country)
    _db.add(emp)
    _db.commit()
    return emp


def _ledger(org):
    _db.expire_all()
    return {r.country_code: r.status for r in _db.query(OrganizationJurisdiction)
            .filter(OrganizationJurisdiction.organization_id == org.id).all()}


def _set_rows(org, codes):
    """Seed the ledger directly: first code primary, all ACTIVE."""
    for i, code in enumerate(codes):
        _db.add(OrganizationJurisdiction(organization_id=org.id, country_code=code, is_primary=(i == 0),
                                         status="ACTIVE", activated_at=datetime.utcnow() + timedelta(seconds=i)))
    _db.commit()


# The settings objects whose BILLING_ENFORCEMENT_MODE the code under test
# reads: this file's own import, plus (see _runtime_enforce below) the one
# app code imported lazily after the sys.modules swap resolves to.
_SETTINGS = [settings]


@contextmanager
def _mode(value):
    previous = [s.BILLING_ENFORCEMENT_MODE for s in _SETTINGS]
    for s in _SETTINGS:
        s.BILLING_ENFORCEMENT_MODE = value
    try:
        yield
    finally:
        for s, mode in zip(_SETTINGS, previous):
            s.BILLING_ENFORCEMENT_MODE = mode


_core_de = _org("CECORE", _core_version, country="Germany")
_core_api = _org("CECOREAPI", _core_version, country="India")
_core_remove = _org("CECORERM", _core_version, country="India")
_pro = _org("CEPRO", _professional_version, country="India")
_pro_downgrade = _org("CEPRODOWN", _professional_version, country="India")
_pro_verify = _org("CEPROVER", _professional_version, country="India")
_business = _org("CEBIZ", _business_version, country="India")
_legacy = _org("CELEGACY", None, country="India")
_backfill = _org("CEBACKFILL", _core_version, country="India")
_enterprise = _org("CEENT", None, country="India", authority=BillingAuthority.ENTERPRISE_ORDER_FORM.value)
_db.add(EnterpriseOrderForm(
    organization_id=_enterprise.id, contract_reference="ENT-1",
    negotiated_scale_limits={MAX_JURISDICTIONS: 5}, negotiated_price_terms={}, term_start=date.today(),
))
_db.commit()

for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules
# Don't leak "enforce" into test files that build their own settings later.
if _ENV_MODE_BEFORE is None:
    os.environ.pop("BILLING_ENFORCEMENT_MODE", None)
else:
    os.environ["BILLING_ENFORCEMENT_MODE"] = _ENV_MODE_BEFORE


@pytest.fixture(scope="module", autouse=True)
def _runtime_enforce():
    """Modules imported lazily (payroll.service -> billing.
    jurisdiction_entitlement, ...) resolve app.config through the restored
    sys.modules, i.e. possibly another test file's settings object. Force
    "enforce" there too for this module only, then put it back."""
    import app.config as runtime_config

    runtime = runtime_config.settings
    previous = runtime.BILLING_ENFORCEMENT_MODE
    runtime.BILLING_ENFORCEMENT_MODE = "enforce"
    if runtime is not settings:
        _SETTINGS.append(runtime)
    yield
    runtime.BILLING_ENFORCEMENT_MODE = previous
    if runtime in _SETTINGS and runtime is not settings:
        _SETTINGS.remove(runtime)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


_HEADERS: dict = {}


def _headers(client, org):
    """One sign-in per org for the whole module: repeated MFA logins inside
    one 30-second TOTP window run out of valid steps."""
    if org.organization_code in _HEADERS:
        return _HEADERS[org.organization_code]
    login = mfa_login(client, json={"email": f"{org.organization_code.lower()}@example.com",
                                    "password": "strong-password"})
    assert login.status_code == 200, login.text
    _HEADERS[org.organization_code] = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return _HEADERS[org.organization_code]


# HTTP-level checks assert on status and message only. The structured
# `trace` is asserted on the service-level exceptions above/below instead:
# this file's sys.modules swap (shared with test_entitlement_enforcement.py)
# re-imports lazily-imported modules after setup, so an exception raised
# from one carries a different ForbiddenException class than the app's
# registered handler and is serialized without `trace` — a harness
# artifact, not app behavior.


class _Actor:
    """Stand-in for current_user in service-level calls."""

    def __init__(self, org):
        self.organization_id = org.id
        self.id = None
        self.role = UserRole.ORG_ADMIN


# ── Core: one country, three enforcement modes ─────────────────────────────

def test_core_org_employee_in_its_country_allowed_other_country_by_mode():
    je.assert_country_allowed(_db, _core_de.id, "DE")
    assert _ledger(_core_de) == {"DE": "ACTIVE"}  # seeded lazily from the org's country

    with pytest.raises(ForbiddenException) as exc:
        je.assert_country_allowed(_db, _core_de.id, "US")
    trace = exc.value.trace
    assert trace["resource"] == MAX_JURISDICTIONS and trace["reason"] == "country_not_entitled"
    assert trace["entitled"] == ["DE"] and trace["limit_value"] == 1 and trace["plan_code"] == "CORE"
    assert "Your Core plan includes 1 country (Germany)" in exc.value.message
    assert "United States" in exc.value.message

    before = _db.query(BillingCommercialAuditEvent).filter(
        BillingCommercialAuditEvent.event_type == "ENTITLEMENT_WOULD_HAVE_BLOCKED").count()
    with _mode("warn"):
        je.assert_country_allowed(_db, _core_de.id, "US")
    _db.commit()
    events = _db.query(BillingCommercialAuditEvent).filter(
        BillingCommercialAuditEvent.event_type == "ENTITLEMENT_WOULD_HAVE_BLOCKED").all()
    assert len(events) == before + 1
    assert events[-1].payload["feature_key"] == "country_not_entitled"

    with _mode("off"):
        je.assert_country_allowed(_db, _core_de.id, "US")


def test_core_employee_api_blocked_outside_its_country(client):
    headers = _headers(client, _core_api)
    r = client.post("/api/payroll/employees", headers=headers,
                    json={"employee_code": "CA-1", "name": "India Hire"})
    assert r.status_code == 200, r.text
    r = client.post("/api/payroll/employees", headers=headers,
                    json={"employee_code": "CA-2", "name": "US Hire", "country_code": "US"})
    assert r.status_code == 403, r.text
    assert "Your Core plan includes 1 country (India)" in r.text


def test_enterprise_payroll_setup_is_gone(client):
    """Enterprise Payroll setup was removed (2026-10-29): countries are
    managed in the Countries tab and each employee is calculated by their own
    country's engine. Its endpoints no longer exist and the mode can't be chosen."""
    headers = _headers(client, _core_de)
    for method, path in (("get", "/api/payroll/enterprise/jurisdictions"),
                         ("post", "/api/payroll/enterprise/jurisdictions"),
                         ("get", "/api/payroll/enterprise/validation"),
                         ("post", "/api/payroll/enterprise/activate")):
        r = getattr(client, method)(path, headers=headers, **({"json": {"countryCode": "US"}} if method == "post" else {}))
        assert r.status_code in (404, 405), (path, r.status_code)
    r = client.put("/api/payroll/policy/active", headers=headers, json={"calculationMode": "enterprise"})
    assert r.status_code in (400, 422), r.text
    assert _ledger(_core_de) == {"DE": "ACTIVE"}


# ── Professional 3 / Business 10 / Enterprise negotiated ────────────────────

# add_entitled_country's limit check is billing.entitlements.require_scope_limit,
# imported lazily — after this file's sys.modules swap that is a different
# ForbiddenException class object, so these two match on the message instead.
def _swap_out(org, removed_code, added_code):
    """Free `removed_code`'s slot (REMOVED) and fill it with `added_code`
    directly, so the next add of `removed_code` is the (limit+1)th. Germany
    is the country used for adds: it passes the onboarding gate without a
    seeded canonical pack (tax_resolver exempts DE), so only the limit is
    under test."""
    _db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == org.id,
        OrganizationJurisdiction.country_code == removed_code).update({"status": "REMOVED"})
    _db.add(OrganizationJurisdiction(organization_id=org.id, country_code=added_code, status="ACTIVE"))
    _db.commit()


def test_professional_three_countries_allowed_fourth_rejected():
    _set_rows(_pro, ["IN", "US"])
    assert je.add_entitled_country(_db, _Actor(_pro), "DE")["used"] == 3  # 3rd
    for code in ("IN", "US", "DE"):
        je.assert_country_allowed(_db, _pro.id, code)
    _swap_out(_pro, "DE", "UK")
    with pytest.raises(Exception, match="exceed your plan's limit") as exc:
        je.add_entitled_country(_db, _Actor(_pro), "DE")  # 4th
    assert exc.value.trace["limit_value"] == 3 and exc.value.trace["requested_qty"] == 4
    with pytest.raises(ForbiddenException):
        je.assert_country_allowed(_db, _pro.id, "DE")


def test_business_ten_countries_allowed_eleventh_rejected():
    _set_rows(_business, ["IN", "US", "UK", "AU", "CA", "FR", "IE", "SG", "HK"])
    summary = je.add_entitled_country(_db, _Actor(_business), "DE")  # 10th
    assert summary["used"] == 10 and summary["limit"] == 10 and summary["canAdd"] is False
    _swap_out(_business, "DE", "IT")
    with pytest.raises(Exception, match="exceed your plan's limit") as exc:
        je.add_entitled_country(_db, _Actor(_business), "DE")  # 11th
    assert exc.value.trace["limit_value"] == 10 and exc.value.trace["requested_qty"] == 11


def test_enterprise_limit_read_from_negotiated_scale_limits():
    assert je.resolve_country_limit(_db, _enterprise.id) == 5


def test_org_without_subscription_has_no_limit():
    assert je.resolve_country_limit(_db, _legacy.id) is None
    # Nothing to exceed: a new country is recorded, not refused.
    je.assert_country_allowed(_db, _legacy.id, "US")
    _db.commit()
    assert _ledger(_legacy) == {"IN": "ACTIVE", "US": "ACTIVE"}


# ── update_employee / bulk ───────────────────────────────────────────────────

def test_update_employee_country_change_is_gated_unchanged_is_not(client):
    headers = _headers(client, _core_api)
    emp = _employee(_core_api, "CA-UPD", "IN")
    r = client.put(f"/api/payroll/employees/{emp.id}", headers=headers, json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/payroll/employees/{emp.id}", headers=headers, json={"country_code": "US"})
    assert r.status_code == 403, r.text


def test_bulk_create_bad_row_reports_row_error_others_succeed(client):
    headers = _headers(client, _core_api)
    r = client.post("/api/payroll/employees/bulk", headers=headers, json={"employees": [
        {"name": "Bulk India", "email": "bulk-in@example.com", "countryCode": "IN"},
        {"name": "Bulk US", "email": "bulk-us@example.com", "countryCode": "US"},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert len(body["failed"]) == 1
    assert body["failed"][0]["row"]["email"] == "bulk-us@example.com"
    assert "Your Core plan includes 1 country" in body["failed"][0]["reason"]
    assert body["failed"][0]["trace"]["reason"] == "country_not_entitled"


def test_bulk_import_requires_a_specific_country_engine_per_row(client):
    """No fallback to the org's default country on import: the row's country
    picks the payroll engine, so blank / engine-less countries are row errors."""
    headers = _headers(client, _core_api)
    r = client.post("/api/payroll/employees/bulk", headers=headers, json={"employees": [
        {"name": "No Country", "email": "bulk-blank@example.com"},
        {"name": "Nowhere", "email": "bulk-nowhere@example.com", "countryCode": "Narnia"},
        {"name": "Explicit India", "email": "bulk-explicit-in@example.com", "countryCode": "IN"},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["employees"][0]["countryCode"] == "IN"
    reasons = {f["row"]["email"]: f["reason"] for f in body["failed"]}
    assert "Country is required" in reasons["bulk-blank@example.com"]
    assert "has no payroll engine" in reasons["bulk-nowhere@example.com"]


# ── Each employee calculated by their own country ───────────────────────────

def test_mexico_payroll_follows_entitlement_not_the_default_country(monkeypatch):
    """A US-default org entitled to Mexico calculates its Mexican employees
    with the Mexican engine; the old guard required Mexico to be the org's
    single default country and blocked every MX employee otherwise."""
    from app.modules.payroll import mexico_run_service

    org = _org("CEMXMIX", _professional_version, country="United States")
    _set_rows(org, ["US", "MX"])
    emp = _employee(org, "MX-1", "MX")
    monkeypatch.setattr(
        mexico_run_service.mexico_dormancy,
        "onboarding_enabled",
        lambda *_args, **_kwargs: True,
    )

    assert je.org_runs_country(_db, org.id, "MX") is True
    mexico_run_service.guard(_db, emp, None)  # no MX_ORG_NOT_MEXICAN

    _db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == org.id,
        OrganizationJurisdiction.country_code == "MX").update({"status": "OVER_LIMIT"})
    _db.commit()
    assert je.org_runs_country(_db, org.id, "MX") is False
    with pytest.raises(Exception) as exc:
        mexico_run_service.guard(_db, emp, None)
    assert getattr(exc.value, "key", None) == "MX_ORG_NOT_MEXICAN"


# ── Remove / replace ─────────────────────────────────────────────────────────

def test_remove_country_with_employees_blocked():
    _set_rows(_core_remove, ["IN"])
    _db.add(OrganizationJurisdiction(organization_id=_core_remove.id, country_code="US", status="OVER_LIMIT"))
    _db.commit()
    _employee(_core_remove, "RM-US", "US")
    with pytest.raises(je.ConflictException) as exc:
        je.remove_entitled_country(_db, _Actor(_core_remove), "US")
    assert "1 employee" in exc.value.message
    with pytest.raises(je.ConflictException):
        je.remove_entitled_country(_db, _Actor(_core_remove), "IN")  # primary


def test_replace_primary_on_core_with_employees_blocked():
    _employee(_core_remove, "RM-IN", "IN")
    with pytest.raises(je.ConflictException) as exc:
        je.replace_primary_country(_db, _Actor(_core_remove), "DE")
    assert exc.value.trace == {"country_code": "IN", "employee_count": 1}


def test_replace_primary_on_core_without_employees():
    org = _org("CECORESWAP", _core_version, country="India")
    summary = je.replace_primary_country(_db, _Actor(org), "DE")
    assert [c["code"] for c in summary["countries"]] == ["DE"]
    assert _ledger(org) == {"IN": "REMOVED", "DE": "ACTIVE"}
    company = _db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == org.id).first()
    assert company.jurisdiction_country == "DE"


# ── Downgrade / upgrade ─────────────────────────────────────────────────────

def _run(org):
    run = PayrollRun(organization_id=org.id, period_label="Oct 2026", period_start=date(2026, 10, 1),
                     period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31), status="Draft")
    _db.add(run)
    _db.commit()
    return run


def test_downgrade_marks_over_limit_keeps_data_skips_in_runs_and_upgrade_restores():
    org = _pro_downgrade
    _set_rows(org, ["IN", "US", "UK"])
    us_emp = _employee(org, "DG-US", "US")
    sub = _db.query(BillingSubscription).filter(BillingSubscription.organization_id == org.id).first()

    sub.plan_version_id = _core_version.id
    _db.commit()
    je.reconcile_jurisdiction_limit(_db, org.id)
    _db.commit()
    assert _ledger(org) == {"IN": "ACTIVE", "US": "OVER_LIMIT", "UK": "OVER_LIMIT"}
    assert _db.query(PayrollEmployee).filter(PayrollEmployee.id == us_emp.id).first() is not None  # nothing deleted
    with pytest.raises(ForbiddenException) as exc:
        je.assert_country_allowed(_db, org.id, "US")
    assert "paused" in exc.value.message

    # Run generation: the US employee gets a FAILED item, nothing is calculated.
    from app.modules.payroll.service import generate_payslips_for_run

    run = _run(org)
    generate_payslips_for_run(_db, run, organization_id=org.id)
    items = _db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == 1
    assert items[0].employee_id == us_emp.id and items[0].status == PayslipStatus.FAILED
    assert items[0].notes.startswith("[COUNTRY_NOT_ENTITLED]")

    events = _db.query(BillingCommercialAuditEvent).filter(
        BillingCommercialAuditEvent.organization_id == org.id,
        BillingCommercialAuditEvent.event_type == "JURISDICTION_LIMIT_RECONCILED").all()
    assert events and events[-1].payload["over_limit"] == ["US", "UK"]

    sub.plan_version_id = _professional_version.id
    _db.commit()
    je.reconcile_jurisdiction_limit(_db, org.id)
    _db.commit()
    assert _ledger(org) == {"IN": "ACTIVE", "US": "ACTIVE", "UK": "ACTIVE"}
    je.assert_country_allowed(_db, org.id, "US")


def test_trial_conversion_to_core_reconciles():
    from app.modules.billing.trial_lifecycle import convert_trial_to_paid

    org = _org("CETRIAL", _professional_version, country="India")
    sub = _db.query(BillingSubscription).filter(BillingSubscription.organization_id == org.id).first()
    sub.status = SubscriptionStatus.TRIALING.value
    _db.commit()
    _set_rows(org, ["IN", "US"])
    convert_trial_to_paid(_db, org.id, _core_version.id, actor_user_id=_super.id)
    assert _ledger(org) == {"IN": "ACTIVE", "US": "OVER_LIMIT"}


# ── Registration ─────────────────────────────────────────────────────────────

def test_register_trial_creates_primary_row_with_professional_limit():
    from app.modules.auth.schemas import TrialRegisterRequest
    from app.modules.auth.service import register_trial

    register_trial(_db, TrialRegisterRequest(organization="Trial Country Co", name="Tri Al",
                                             email="trial-country@example.com", password="strong-password",
                                             country="Germany"))
    org = _db.query(Organization).filter(Organization.organization_name == "Trial Country Co").first()
    rows = _db.query(OrganizationJurisdiction).filter(OrganizationJurisdiction.organization_id == org.id).all()
    assert [(r.country_code, r.is_primary, r.status) for r in rows] == [("DE", True, "ACTIVE")]
    # Evaluation workspaces run on the Professional plan version: 3 countries, no special case.
    assert je.resolve_country_limit(_db, org.id) == 3


def test_register_enterprise_creates_primary_row():
    from app.modules.auth.schemas import RegisterRequest
    from app.modules.auth.service import register_enterprise

    register_enterprise(_db, RegisterRequest(organization="Registered Country Co", name="Reg Ister",
                                             email="registered-country@example.com", password="strong-password",
                                             country="Germany", terms_accepted=True))
    org = _db.query(Organization).filter(Organization.organization_name == "Registered Country Co").first()
    rows = _db.query(OrganizationJurisdiction).filter(OrganizationJurisdiction.organization_id == org.id).all()
    assert [(r.country_code, r.is_primary) for r in rows] == [("DE", True)]


# ── Backfill ─────────────────────────────────────────────────────────────────

def test_backfill_is_idempotent_and_flags_over_limit():
    from scripts.backfill_organization_jurisdictions import run

    for code, country in (("BF-IN", "IN"), ("BF-US", "US"), ("BF-DE", "DE")):
        _employee(_backfill, code, country)
    _db.commit()

    first = run(_db)
    after_first = _ledger(_backfill)
    assert after_first == {"IN": "ACTIVE", "US": "OVER_LIMIT", "DE": "OVER_LIMIT"}
    assert any(o["id"] == _backfill.id for o in first["orgs_over_limit"])
    primary = _db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == _backfill.id,
        OrganizationJurisdiction.is_primary.is_(True)).one()
    assert primary.country_code == "IN"

    second = run(_db)
    assert second["rows_created"] == 0
    assert _ledger(_backfill) == after_first


def test_org_with_no_resolvable_country_is_told_to_set_it():
    org = _org("CENOCOUNTRY", _core_version, country=None)
    with pytest.raises(BadRequestException) as exc:
        je.assert_country_allowed(_db, org.id, "US")
    assert "Set your organization's country" in exc.value.message


# ── Endpoints ────────────────────────────────────────────────────────────────

def test_entitled_endpoint_shape(client):
    headers = _headers(client, _core_api)
    r = client.get("/api/payroll/jurisdictions/entitled", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["limit"] == 1 and body["used"] == 1 and body["planCode"] == "CORE"
    assert body["canAdd"] is False
    assert body["countries"][0]["code"] == "IN" and body["countries"][0]["isPrimary"] is True
    r = client.post("/api/payroll/jurisdictions/entitled", headers=headers, json={"countryCode": "DE"})
    assert r.status_code == 403, r.text
    assert "max_jurisdictions" in r.text


def test_super_admin_exceptions_and_subscription_columns(client):
    login = mfa_login(client, json={"email": "country-super-admin@example.com", "password": "strong-password"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.get("/api/super-admin/compliance/exceptions", headers=headers)
    assert r.status_code == 200, r.text
    flagged = {row["organization_id"] for row in r.json()["country_limit_exceptions"]}
    assert _backfill.id in flagged
    r = client.get("/api/super-admin/billing/subscriptions", headers=headers, params={"country_limit": "OVER"})
    assert r.status_code == 200, r.text
    rows = r.json()["subscriptions"]
    assert any(row["organization_id"] == _backfill.id and row["countries_over_limit"] == 2 for row in rows)


# ── Billing: overrides and self-heal ────────────────────────────────────────

def test_entitlement_override_restores_paused_countries_and_expiry_self_heals():
    from app.modules.billing.entitlements import create_entitlement_override
    from app.modules.billing.models import BillingEntitlementOverride

    org = _org("CEOVERRIDE", _core_version, country="India")
    _set_rows(org, ["IN"])
    _db.add(OrganizationJurisdiction(organization_id=org.id, country_code="US", status="OVER_LIMIT"))
    _db.commit()

    create_entitlement_override(_db, org.id, MAX_JURISDICTIONS, 2, _super.id, "temporary US payroll",
                                datetime.utcnow() + timedelta(days=30))
    assert _ledger(org) == {"IN": "ACTIVE", "US": "ACTIVE"}

    # Expiry raises no event: the next ledger read pauses the extra country.
    _db.query(BillingEntitlementOverride).filter(BillingEntitlementOverride.organization_id == org.id).update(
        {"expires_at": datetime.utcnow() - timedelta(minutes=1)})
    _db.commit()
    je.ensure_ledger(_db, org.id)
    _db.commit()
    assert _ledger(org) == {"IN": "ACTIVE", "US": "OVER_LIMIT"}


def test_any_payroll_country_can_be_added_setup_pending_is_noted():
    """The picker offers the fixed list of payroll countries. A country whose
    statutory set-up isn't complete (no Active pack here) is still added —
    within the plan limit — and comes back with a set-up note; a country
    with no payroll engine at all is refused."""
    org = _org("CESETUP", _professional_version, country="India")
    summary = je.entitlement_summary(_db, org.id)
    catalog = {c["code"]: c for c in summary["catalog"]}
    assert "US" in catalog and catalog["US"]["available"] is True
    assert summary["remaining"] == 2

    summary = je.add_entitled_country(_db, _Actor(org), "US")
    us = next(c for c in summary["countries"] if c["code"] == "US")
    assert us["status"] == "ACTIVE"
    assert us["setupNote"]  # no Active US pack in this test database
    assert summary["remaining"] == 1

    with pytest.raises(Exception, match="not a country Zoiko runs payroll for"):
        je.add_entitled_country(_db, _Actor(org), "NZ")
