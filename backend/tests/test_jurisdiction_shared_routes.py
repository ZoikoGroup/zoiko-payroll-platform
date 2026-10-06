"""
tests/test_jurisdiction_shared_routes.py
----------------------------------------
Architecture convergence (2026-10-05): the governed service-registry step and
the statutory summary are ONE country-parameterised Super Admin route each
(/compliance/jurisdictions/{country}/...). The per-country URLs the frontend
calls (/compliance/singapore/..., /compliance/hong-kong/...) are thin aliases
and must answer exactly the same.

app.* imports are lazy (tests/_db_safety.py).
"""

from types import SimpleNamespace

import pytest

SA = SimpleNamespace(id=101, organization_id=None, role="super_admin", is_active=True)
BASE = "/api/super-admin/compliance"


@pytest.fixture
def both(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all
    from scripts.seed_singapore_canonical_pack import seed_singapore

    seed_singapore(db)
    seed_hong_kong_all(db)
    for country in ("SG", "HK"):
        if db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == country).first() is None:
            db.add(JurisdictionServiceRegistry(country=country, availability="PLANNED"))
    db.commit()


@pytest.mark.parametrize("country,alias", [("SG", "singapore"), ("HK", "hong-kong")])
def test_registry_step_answers_the_same_on_the_shared_route_and_its_alias(db, both, country, alias):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from tests.test_hong_kong_governance import _http

    body = {"availability": "AVAILABLE", "reason": "TEST open"}
    with _http(db, SA) as c:
        shared = c.post(f"{BASE}/jurisdictions/{country}/service-registry", json=body)
        aliased = c.post(f"{BASE}/{alias}/service-registry", json=body)
        lower = c.post(f"{BASE}/jurisdictions/{country.lower()}/service-registry", json=body)
    assert shared.status_code == aliased.status_code == lower.status_code == 400     # readiness unmet: refused
    assert shared.json() == aliased.json() == lower.json()
    assert db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == country).one().availability == "PLANNED"


def test_registry_route_refuses_an_ungoverned_country_and_extra_fields(db, both):
    from tests.test_hong_kong_governance import _http

    with _http(db, SA) as c:
        assert c.post(f"{BASE}/jurisdictions/US/service-registry",
                      json={"availability": "AVAILABLE", "reason": "x"}).status_code == 404
        assert c.post(f"{BASE}/jurisdictions/HK/service-registry",
                      json={"availability": "AVAILABLE", "reason": "x", "force": True}).status_code == 422


def test_registry_route_is_super_admin_only(db, both):
    from tests.test_hong_kong_governance import _http

    operator = SimpleNamespace(id=7, organization_id=1, role="payroll_admin", is_active=True)
    with _http(db, operator) as c:
        assert c.post(f"{BASE}/jurisdictions/HK/service-registry",
                      json={"availability": "AVAILABLE", "reason": "x"}).status_code == 403


@pytest.mark.parametrize("country,alias", [("SG", "singapore"), ("HK", "hong-kong")])
def test_statutory_summary_is_identical_on_the_shared_route_and_its_alias(db, both, country, alias):
    from tests.test_hong_kong_governance import _http

    with _http(db, SA) as c:
        shared = c.get(f"{BASE}/jurisdictions/{country}/statutory-summary")
        aliased = c.get(f"{BASE}/{alias}/statutory-summary")
    assert shared.status_code == aliased.status_code == 200
    assert shared.json() == aliased.json()
    with _http(db, SA) as c:
        assert c.get(f"{BASE}/jurisdictions/FR/statutory-summary").status_code == 404


def test_both_shared_routes_refuse_anonymous_and_non_super_admin_callers(db, both):
    from tests.test_hong_kong_governance import _http

    operator = SimpleNamespace(id=7, organization_id=1, role="payroll_admin", is_active=True)
    body = {"availability": "AVAILABLE", "reason": "x"}
    for principal, allowed in ((None, (401, 403)), (operator, (403,))):
        with _http(db, principal) as c:
            for country in ("SG", "HK"):
                assert c.post(f"{BASE}/jurisdictions/{country}/service-registry", json=body).status_code in allowed
                assert c.get(f"{BASE}/jurisdictions/{country}/statutory-summary").status_code in allowed


def test_a_registry_step_touches_and_audits_only_its_own_jurisdiction(db, both):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.models import TaxConfigurationAudit
    from tests.test_hong_kong_governance import _http

    with _http(db, SA) as c:
        assert c.post(f"{BASE}/jurisdictions/HK/service-registry",
                      json={"availability": "AVAILABLE", "reason": "TEST"}).status_code == 400
    refusal = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_service_registry")
               .order_by(TaxConfigurationAudit.id.desc()).first())
    assert refusal.action == "refused" and refusal.old_value["country"] == "HK"
    rows = {r.country: r.availability for r in db.query(JurisdictionServiceRegistry)
            .filter(JurisdictionServiceRegistry.country.in_(("SG", "HK")))}
    assert rows == {"SG": "PLANNED", "HK": "PLANNED"}
