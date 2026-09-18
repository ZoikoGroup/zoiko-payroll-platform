"""
tests/test_step3_invoice_reconciliation.py
--------------------------------------------
Step 3 — Populate BillingInvoice/BillingInvoiceLine, then BWM
reconciliation (closes blocker #16).

Covers:
  - _infer_component_type: RECURRING_BASE default, BWM for metered usage_type
  - GET /billing/my-subscription/invoices — org-scoped, newest first
  - GET /billing/my-subscription/invoice-explanation/{invoice_id} — org-scoped
    404 for another org's invoice; real employee breakdown for one's own
  - GET /super-admin/compliance/exceptions — bwm_invoice_mismatches surfaces
    a real invoice/BWM discrepancy (a BillingWorkerMonthRecord flipped after
    the invoice was written)

Hermetic SQLite pattern, same as test_commercial_billing_standard.py.
"""

import os
import sys
import tempfile
from types import SimpleNamespace

_TMP = tempfile.mkdtemp(prefix="step3_invoice_test_")
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
os.environ["DUNNING_SWEEP_ENABLED"] = "false"
os.environ["BILLING_ENFORCEMENT_MODE"] = "off"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_FAKE"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_FAKEFAKEFAKE"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_app_modules = {
    _mod: _module
    for _mod, _module in sys.modules.items()
    if _mod == "app" or _mod.startswith("app.")
}
for _mod in list(_saved_app_modules):
    del sys.modules[_mod]

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.models import BillingAuthority, BillingInvoice, BillingInvoiceLine, BillingSubscription, BillingWorkerMonthRecord, SubscriptionStatus  # noqa: E402
from app.modules.billing.router import _infer_component_type  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import PayrollEmployee  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_step3_invoice_reconciliation must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="step3-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super", last_name="Admin",
    organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()

_plan = plan_catalog.create_plan(_db, "PROFESSIONAL", "Professional", actor_user_id=_super.id)
_version = plan_catalog.create_plan_version(
    _db, plan_id=_plan.id, feature_set={"features": ["payroll_runs"]}, scale_limits={}, actor_user_id=_super.id,
)
plan_catalog.approve_plan_version(_db, _version.id, actor_user_id=_super.id)
plan_catalog.publish_plan_version(_db, _version.id, published_by_user_id=_super.id)

# ── Org A — has one invoice + a matching BWM record set (no discrepancy) ──
_org_a = Organization(
    organization_name="Invoice Test Co A", organization_code="INVTESTA",
    workspace_type="PRODUCTION", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True,
)
_db.add(_org_a)
_db.flush()
_db.add(User(
    email="invtesta@example.com", hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN, first_name="Org", last_name="Admin",
    organization_id=_org_a.id, is_active=True,
))
_sub_a = BillingSubscription(
    organization_id=_org_a.id, plan_version_id=_version.id,
    billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
    current_period_start=datetime.utcnow() - timedelta(days=10),
    current_period_end=datetime.utcnow() + timedelta(days=20),
)
_db.add(_sub_a)
_db.flush()

_billing_month = date.today().replace(day=1)
_issued_at = datetime.utcnow() - timedelta(days=1)

_invoice_a = BillingInvoice(
    organization_id=_org_a.id, subscription_id=_sub_a.id, stripe_invoice_id="in_TESTA001",
    status="PAID", total=299, tax_amount=0, currency="USD", issued_at=_issued_at,
)
_db.add(_invoice_a)
_db.flush()
_db.add(BillingInvoiceLine(
    invoice_id=_invoice_a.id, description="Professional plan — base", component_type="RECURRING_BASE",
    quantity=1, unit_amount=199, line_total=199,
))
_bwm_line_a = BillingInvoiceLine(
    invoice_id=_invoice_a.id, description="Billable worker-months", component_type="BWM",
    quantity=2, unit_amount=50, line_total=100,
)
_db.add(_bwm_line_a)
_db.flush()

_emp_1 = PayrollEmployee(organization_id=_org_a.id, employee_code="E1", name="Alice")
_emp_2 = PayrollEmployee(organization_id=_org_a.id, employee_code="E2", name="Bob")
_emp_3 = PayrollEmployee(organization_id=_org_a.id, employee_code="E3", name="Cara")
_db.add_all([_emp_1, _emp_2, _emp_3])
_db.flush()

_bwm_1 = BillingWorkerMonthRecord(organization_id=_org_a.id, payroll_employee_id=_emp_1.id, billing_month=_billing_month, counted=True)
_bwm_2 = BillingWorkerMonthRecord(organization_id=_org_a.id, payroll_employee_id=_emp_2.id, billing_month=_billing_month, counted=True)
_bwm_3 = BillingWorkerMonthRecord(organization_id=_org_a.id, payroll_employee_id=_emp_3.id, billing_month=_billing_month, counted=False, reason_code="TERMINATED_MID_MONTH")
_db.add_all([_bwm_1, _bwm_2, _bwm_3])
_db.commit()

# ── Org B — a second org, used only to prove invoice listing is org-scoped ──
_org_b = Organization(
    organization_name="Invoice Test Co B", organization_code="INVTESTB",
    workspace_type="PRODUCTION", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True,
)
_db.add(_org_b)
_db.flush()
_db.add(User(
    email="invtestb@example.com", hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN, first_name="Org", last_name="Admin",
    organization_id=_org_b.id, is_active=True,
))
_sub_b = BillingSubscription(
    organization_id=_org_b.id, plan_version_id=_version.id,
    billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
    current_period_start=datetime.utcnow() - timedelta(days=10),
    current_period_end=datetime.utcnow() + timedelta(days=20),
)
_db.add(_sub_b)
_db.commit()

_invoice_a_id = _invoice_a.id
_bwm_line_a_id = _bwm_line_a.id
_bwm_3_id = _bwm_3.id
_org_a_id = _org_a.id

_db.close()

for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _headers(client, email):
    login = client.post("/api/auth/login", json={"email": email, "password": "strong-password"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(scope="module")
def org_a_headers(client):
    return _headers(client, "invtesta@example.com")


@pytest.fixture(scope="module")
def org_b_headers(client):
    return _headers(client, "invtestb@example.com")


@pytest.fixture(scope="module")
def super_admin_headers(client):
    return _headers(client, "step3-super-admin@example.com")


# ── _infer_component_type ───────────────────────────────────────────────
# Takes the Price object itself (current Stripe API versions no longer
# nest an expandable price on the invoice line — see router.py's own
# docstring on this function for why).

def test_infer_component_type_defaults_to_recurring_base():
    price = SimpleNamespace(recurring=None)
    assert _infer_component_type(price) == "RECURRING_BASE"
    assert _infer_component_type(None) == "RECURRING_BASE"


def test_infer_component_type_bwm_for_metered_usage():
    price = SimpleNamespace(recurring=SimpleNamespace(usage_type="metered"))
    assert _infer_component_type(price) == "BWM"

    licensed_price = SimpleNamespace(recurring=SimpleNamespace(usage_type="licensed"))
    assert _infer_component_type(licensed_price) == "RECURRING_BASE"


# ── GET /billing/my-subscription/invoices ──────────────────────────────

def test_list_my_invoices_returns_own_org_invoice(client, org_a_headers):
    r = client.get("/api/billing/my-subscription/invoices", headers=org_a_headers)
    assert r.status_code == 200, r.text
    invoices = r.json()["invoices"]
    assert len(invoices) == 1
    assert invoices[0]["id"] == _invoice_a_id
    assert invoices[0]["status"] == "PAID"


def test_list_my_invoices_is_org_scoped(client, org_b_headers):
    r = client.get("/api/billing/my-subscription/invoices", headers=org_b_headers)
    assert r.status_code == 200, r.text
    assert r.json()["invoices"] == []


# ── GET /billing/my-subscription/invoice-explanation/{invoice_id} ─────────

def test_invoice_explanation_shows_counted_and_excluded_employees(client, org_a_headers):
    r = client.get(f"/api/billing/my-subscription/invoice-explanation/{_invoice_a_id}", headers=org_a_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bwm_data_available"] is True
    assert len(body["employees_counted"]) == 2
    assert len(body["employees_excluded"]) == 1
    assert body["employees_excluded"][0]["reason_code"] == "TERMINATED_MID_MONTH"


def test_invoice_explanation_404s_for_another_orgs_invoice(client, org_b_headers):
    r = client.get(f"/api/billing/my-subscription/invoice-explanation/{_invoice_a_id}", headers=org_b_headers)
    assert r.status_code == 404, r.text


# ── GET /super-admin/compliance/exceptions — bwm_invoice_mismatches ───────

def test_exceptions_page_shows_no_mismatch_when_counts_agree(client, super_admin_headers):
    r = client.get("/api/super-admin/compliance/exceptions", headers=super_admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "bwm_invoice_mismatches" in body
    assert all(m["invoice_id"] != _invoice_a_id for m in body["bwm_invoice_mismatches"])


def test_exceptions_page_surfaces_mismatch_after_bwm_record_flipped(client, super_admin_headers):
    """The literal Step 3 verify scenario: flip one BillingWorkerMonthRecord.counted
    after the invoice already exists — the discrepancy must surface here."""
    db = SessionLocal()
    try:
        rec = db.query(BillingWorkerMonthRecord).filter(BillingWorkerMonthRecord.id == _bwm_3_id).first()
        rec.counted = True  # now 3 counted vs. invoice's billed quantity of 2
        db.commit()
    finally:
        db.close()

    r = client.get("/api/super-admin/compliance/exceptions", headers=super_admin_headers)
    assert r.status_code == 200, r.text
    mismatches = r.json()["bwm_invoice_mismatches"]
    match = next((m for m in mismatches if m["invoice_id"] == _invoice_a_id), None)
    assert match is not None, f"expected invoice {_invoice_a_id} in bwm_invoice_mismatches, got {mismatches}"
    assert match["organization_name"] == "Invoice Test Co A"
    assert match["invoiced_quantity"] == 2
    assert match["actual_bwm_count"] == 3
    assert match["difference"] == 1

    # restore, so this test is order-independent of any later assertions
    db = SessionLocal()
    try:
        rec = db.query(BillingWorkerMonthRecord).filter(BillingWorkerMonthRecord.id == _bwm_3_id).first()
        rec.counted = False
        db.commit()
    finally:
        db.close()
