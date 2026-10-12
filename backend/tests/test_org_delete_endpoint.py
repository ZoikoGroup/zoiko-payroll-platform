"""
tests/test_org_delete_endpoint.py
-----------------------------------
Coverage for the real Super Admin organization delete endpoint
(DELETE /api/organizations/{id}) exercised through the actual API,
not a hand-copied replica of its cascade-delete order.

Promoted 2026-09-18 (platform infrastructure fix plan, Tier 1.5) from a
standalone root-level script (`_test_org_delete_endpoint.py`). Updated to
pass country="IN" on creation -- create_organization now calls
get_jurisdiction_onboarding_block_reason(), which rejects a country-less
org (added after the original script was written).
"""

import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "test_org_delete_api.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

_saved_app_modules = {
    key: mod for key, mod in sys.modules.items()
    if key == "app" or key.startswith("app.")
}
for key in list(_saved_app_modules):
    del sys.modules[key]

from sqlalchemy import text  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.dependencies import get_current_super_admin  # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from decimal import Decimal  # noqa: E402
from app.modules.payroll.models import JurisdictionPack, ContributionRate  # noqa: E402
from app.modules.payroll.policy.models import PayrollPolicy  # noqa: E402

Base.metadata.create_all(bind=engine)

# create_organization now calls get_jurisdiction_onboarding_block_reason(),
# which requires a real Active tax pack WITH at least one rate/slab row for
# the country -- seed one so IN is a supported jurisdiction in this fresh
# test database (same pattern test_registration_jurisdiction_gate.py uses).
_seed_db = SessionLocal()
_pack = JurisdictionPack(
    pack_id="IN-TEST", jurisdiction_country="IN", pack_type="tax", version="1.0", status="Active",
)
_seed_db.add(_pack)
_seed_db.commit()
_seed_db.refresh(_pack)
_seed_db.add(ContributionRate(
    organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=_pack.id,
    component_key="pf", label="PF", employee_share="—", employer_share="—", total="—",
    employee_rate_pct=Decimal("12.00"),
))
_seed_db.commit()
_seed_db.close()


class FakeSuperAdmin:
    id = 1
    email = "sa@zoiko.dev"
    role = "super_admin"
    organization_id = None


app.dependency_overrides[get_current_super_admin] = lambda: FakeSuperAdmin()

client = TestClient(app)
db = SessionLocal()

# Restore pre-purge app modules so other test files don't bind to this
# file's private app/engine objects (same pattern test_checkout_flow.py
# uses) -- this file's own names above already hold direct references to
# its own objects, so this only affects modules imported AFTER this point.
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


def test_org_delete_endpoint_cascades_and_is_idempotent_404():
    # Create org through the real API.
    r = client.post("/api/organizations/", json={"organization_name": "Acme Widgets", "country": "IN"})
    assert r.status_code == 200, r.text
    oid = r.json()["id"]

    # Seed a few org-scoped rows directly.
    db.execute(text("INSERT INTO payroll_employees (organization_id, employee_code, name, status, employment_type) "
                    "VALUES (:o,:c,:n,:s,:et)"), {"o": oid, "c": "E1", "n": "One", "s": "active", "et": "full_time"})
    from datetime import date
    db.add(PayrollPolicy(organization_id=oid, name="P", status="active", is_default=True,
                          effective_date=date(2026, 1, 1)))
    db.commit()

    # Delete through the real endpoint.
    r = client.delete(f"/api/organizations/{oid}")
    assert r.status_code == 200, r.text
    assert "deleted" in r.json()["message"], r.json()

    # Nothing left.
    for t in ["organizations", "payroll_employees", "payroll_policies"]:
        n = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        assert n == 0, f"{t} still has {n} rows"

    # Second delete -> 404.
    r = client.delete(f"/api/organizations/{oid}")
    assert r.status_code == 404, r.text
