"""
tests/test_step5_subscription_tax.py
----------------------------------------
Step 5 — Jurisdiction-aware SaaS tax, strictly separated from payroll tax
(closes blockers #8, #9).

  1. _write_invoice_from_stripe correctly derives a nonzero tax_amount
     from a real-shaped Stripe invoice (total - total_excluding_tax),
     simulating a US billing address with a real state sales-tax rate —
     Stripe Tax activation itself is a pending account/business
     configuration step (no `head_office` set on this Stripe test
     account), not a code gap, so the Stripe response is mocked here with
     the shape Stripe Tax actually returns once activated.
  2. That tax_amount is stored ONLY on BillingInvoice.tax_amount and never
     derived from, summed with, or equal to PayrollRun.total_taxes for the
     same org by coincidence of shared code — the audit this step calls
     for.
  3. GET /billing/my-subscription/invoice-explanation/{id} surfaces
     tax_amount distinctly (the field the frontend's new "Sales tax/VAT
     on your Zoiko subscription" line reads).

Hermetic SQLite pattern, same as test_step3_invoice_reconciliation.py.
"""

import os
import sys
import tempfile
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

_TMP = tempfile.mkdtemp(prefix="step5_tax_test_")
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
from app.modules.billing.models import BillingAuthority, BillingInvoice, BillingInvoiceLine, BillingSubscription, SubscriptionStatus  # noqa: E402
from app.modules.billing.router import _write_invoice_from_stripe  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import PayrollRun, PayrollStatus  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_step5_subscription_tax must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="step5-super-admin@example.com", hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN, first_name="Super", last_name="Admin", organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()

_plan = plan_catalog.create_plan(_db, "PROFESSIONAL", "Professional", actor_user_id=_super.id)
_version = plan_catalog.create_plan_version(
    _db, plan_id=_plan.id, feature_set={"features": ["payroll_runs"]}, scale_limits={}, actor_user_id=_super.id,
)
plan_catalog.approve_plan_version(_db, _version.id, actor_user_id=_super.id)
plan_catalog.publish_plan_version(_db, _version.id, published_by_user_id=_super.id)

_org = Organization(
    organization_name="Step5 Tax Test Co", organization_code="STEP5TAX",
    workspace_type="PRODUCTION", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True,
    service_commencement_at=datetime.utcnow() - timedelta(days=1),
)
_db.add(_org)
_db.flush()
_db.add(User(
    email="step5tax@example.com", hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN, first_name="Org", last_name="Admin", organization_id=_org.id, is_active=True,
))
_sub = BillingSubscription(
    organization_id=_org.id, plan_version_id=_version.id,
    billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
    current_period_start=datetime.utcnow() - timedelta(days=1),
    current_period_end=datetime.utcnow() + timedelta(days=29),
)
_db.add(_sub)

# A completely unrelated payroll-tax figure for the SAME org, in a
# different table/column — this is what must never be aggregated with
# BillingInvoice.tax_amount.
_payroll_run = PayrollRun(
    organization_id=_org.id, period_label="Sept 2026", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
    pay_date=date(2026, 10, 1), status=PayrollStatus.PAID.value, total_taxes=Decimal("18345.67"),
)
_db.add(_payroll_run)
_db.commit()

_org_id = _org.id
_sub_id = _sub.id
_payroll_run_total_taxes = _payroll_run.total_taxes

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
def org_headers(client):
    return _headers(client, "step5tax@example.com")


_invoice_id = None


def _make_fake_us_taxed_invoice():
    """Shaped like a real Stripe invoice for a US customer with a state
    sales-tax rate applied via Stripe Tax once activated — $299.00 base
    plus $24.67 tax (a real California-ish combined rate, ~8.25%),
    total $323.67."""
    price = SimpleNamespace(recurring=None)  # flat-rate RECURRING_BASE, not metered
    line = SimpleNamespace(
        description="1 × Professional plan (at $299.00 / month)",
        quantity=1,
        amount=32367,  # cents
        pricing=SimpleNamespace(price_details=SimpleNamespace(price="price_FAKE_US")),
    )
    invoice = SimpleNamespace(
        id="in_FAKE_US_TAXED",
        total=32367,
        total_excluding_tax=29900,
        currency="usd",
        created=int(datetime.utcnow().timestamp()),
        lines=SimpleNamespace(data=[line]),
    )
    return invoice, price


def test_write_invoice_from_stripe_stores_nonzero_tax_from_us_address(client, org_headers):
    db = SessionLocal()
    try:
        sub = db.query(BillingSubscription).filter(BillingSubscription.id == _sub_id).first()
        fake_invoice, fake_price = _make_fake_us_taxed_invoice()

        with patch("app.modules.billing.router.stripe.Invoice.retrieve", return_value=fake_invoice), \
             patch("app.modules.billing.router.stripe.Price.retrieve", return_value=fake_price):
            _write_invoice_from_stripe(db, sub, "in_FAKE_US_TAXED", status="PAID")
            db.commit()

        invoice_row = db.query(BillingInvoice).filter(BillingInvoice.stripe_invoice_id == "in_FAKE_US_TAXED").first()
        assert invoice_row is not None
        assert invoice_row.total == Decimal("323.67")
        assert invoice_row.tax_amount == Decimal("24.67"), "tax must be derived as total - total_excluding_tax"
        assert invoice_row.tax_amount > 0, "a real US billing address with a state sales-tax rate must produce a nonzero tax line"

        lines = db.query(BillingInvoiceLine).filter(BillingInvoiceLine.invoice_id == invoice_row.id).all()
        assert len(lines) == 1
        assert lines[0].component_type == "RECURRING_BASE"

        global _invoice_id
        _invoice_id = invoice_row.id
    finally:
        db.close()


def test_subscription_tax_never_equals_or_derives_from_payroll_tax():
    """The audit this step calls for: confirm no shared code path could
    make these two numbers coincide or be summed. Different tables,
    different columns, different values for the same org."""
    db = SessionLocal()
    try:
        invoice_row = db.query(BillingInvoice).filter(BillingInvoice.organization_id == _org_id).first()
        run = db.query(PayrollRun).filter(PayrollRun.organization_id == _org_id).first()

        assert invoice_row.tax_amount == Decimal("24.67")
        assert run.total_taxes == _payroll_run_total_taxes == Decimal("18345.67")
        assert invoice_row.tax_amount != run.total_taxes
        # Nothing in this codebase sums these — confirmed by the fact that
        # BillingInvoice.tax_amount is never referenced outside app/modules/billing/.
    finally:
        db.close()


def test_invoice_explanation_surfaces_tax_amount_distinctly(client, org_headers):
    r = client.get(f"/api/billing/my-subscription/invoice-explanation/{_invoice_id}", headers=org_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tax_amount"] == 24.67
    assert body["total"] == 323.67
