"""Belgium (ZP-BE-ENG-001) Option 2, owner decision 2026-11-16: a canary organisation may enter a PLANNED Belgium.

An EXISTING organisation on BE_CANARY_ORG_IDS can change its country to Belgium while Belgium's service registry
row is PLANNED, so its setup is prepared before the gates. Everything else stays refused (new registration, any
other organisation, the global flag alone, an absent or NOT_AVAILABLE registry row, other PLANNED countries), and
payroll itself stays blocked by the content gate. SYNTHETIC data only.
"""
from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture
def be_off(monkeypatch):
    from app.config import settings

    for name, value in (("BE_TENANT_ONBOARDING_ENABLED", False), ("BE_CANARY_ORG_IDS", ""),
                        ("BE_DEMO_PACKS_ENABLED", False), ("BE_DEMO_ORG_IDS", "")):
        monkeypatch.setattr(settings, name, value)
    return settings


def _registry(db, availability):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import belgium_service as be

    be.ensure_be_service_registry_row(db)
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").one()
    row.availability = availability
    db.commit()


def _move(db, org_id, country="Belgium"):
    from types import SimpleNamespace

    from tests._mx_employer_helpers import SUPER_ADMIN, http

    actor = SimpleNamespace(**vars(SUPER_ADMIN), email="super-admin@canary.example")   # the route logs the email
    with http(db, actor) as client:
        return client.put(f"/api/organizations/{org_id}", json={"country": country})


def _org(db, code):
    """A new organisation as an operator creates it: a non-Belgian country, Compliance page not yet saved."""
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name=f"Canary {code} BV", code=code, admins=2, country=None)
    t.org.country = "United Kingdom"
    db.commit()
    return t


def test_a_canary_organisation_enters_a_planned_belgium_and_its_setup_opens(db, be_off, monkeypatch):
    from app.modules.organizations.models import Organization
    from tests._mx_employer_helpers import http, principal

    _registry(db, "PLANNED")
    t = _org(db, "BECAN1")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", str(t.org.id))
    res = _move(db, t.org.id)
    assert res.status_code == 200, res.text
    db.expire_all()
    from app.core.jurisdiction import get_jurisdiction_code

    assert get_jurisdiction_code(db.get(Organization, t.org.id).country) == "BE"
    with http(db, principal(t.org.id, t.users[0].id)) as client:
        from app.modules.payroll.service import get_company_details

        # The Compliance page back-fills its blank country from the organisation: it is Belgian already.
        assert get_jurisdiction_code(get_company_details(db, t.org.id).jurisdiction_country) == "BE"
        made = client.post("/api/payroll/belgium/employer-registrations", json={
            "effective_from": "2026-01-01", "legal_name": "Canary BECAN1 BV", "enterprise_number": "0999999999",
            "employer_category_code": "000", "reason": "TEST ONLY"})
        assert made.status_code in (200, 201), made.text
        listed = client.get("/api/payroll/belgium/employer-registrations")
        assert listed.status_code == 200 and listed.json(), listed.text


def test_payroll_stays_blocked_for_the_canary_after_the_move(db, be_off, monkeypatch):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll
    from scripts.seed_belgium_canonical_packs import seed_belgium

    seed_belgium(db)                                         # the real Draft pack: every row [PENDING G1]
    t = _org(db, "BECAN2")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", str(t.org.id))
    assert _move(db, t.org.id).status_code == 200
    for mode in ("standard", "simple"):
        with pytest.raises(MissingComplianceConfigurationError):
            calculate_payroll(PayrollContext(country="BE", gross=Decimal("3800"), basic=Decimal("3800"),
                                             pay_date=date(2026, 9, 30)), mode)


@pytest.mark.parametrize("availability", [None, "NOT_AVAILABLE"])
def test_the_canary_is_refused_without_a_planned_registry_row(db, be_off, monkeypatch, availability):
    if availability:
        _registry(db, availability)
    t = _org(db, "BECAN3")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", str(t.org.id))
    res = _move(db, t.org.id)
    assert res.status_code >= 400 and "not yet available" in res.text, res.text


def test_an_organisation_off_the_canary_list_is_refused(db, be_off, monkeypatch):
    _registry(db, "PLANNED")
    t, other = _org(db, "BECAN4"), _org(db, "BECAN5")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", str(other.org.id))
    res = _move(db, t.org.id)
    assert res.status_code >= 400, res.text


def test_the_global_flag_alone_does_not_open_a_planned_belgium(db, be_off, monkeypatch):
    _registry(db, "PLANNED")
    t = _org(db, "BECAN6")
    monkeypatch.setattr(be_off, "BE_TENANT_ONBOARDING_ENABLED", True)
    res = _move(db, t.org.id)
    assert res.status_code >= 400 and "not yet available" in res.text, res.text


def test_new_registration_into_belgium_stays_refused_for_everyone(db, be_off, monkeypatch):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    _registry(db, "PLANNED")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", "1,2,3")
    assert get_jurisdiction_onboarding_block_reason(db, "Belgium")


def test_the_belgian_canary_opens_no_other_planned_country(db, be_off, monkeypatch):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason
    from app.modules.payroll import malaysia_dormancy  # noqa: F401 — Malaysia keeps its own rules

    _registry(db, "PLANNED")
    t = _org(db, "BECAN7")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", str(t.org.id))
    for country in ("Netherlands", "Malaysia", "Poland", "Singapore"):
        assert get_jurisdiction_change_block_reason(db, "GB", country, t.org.id), country


def test_a_non_canary_organisation_cannot_choose_belgium_on_its_compliance_page(db, be_off, monkeypatch):
    from tests._mx_employer_helpers import http, principal

    _registry(db, "PLANNED")
    t, other = _org(db, "BECAN8"), _org(db, "BECAN9")
    monkeypatch.setattr(be_off, "BE_CANARY_ORG_IDS", str(other.org.id))
    with http(db, principal(t.org.id, t.users[0].id)) as client:
        res = client.put("/api/payroll/compliance/company-details", json={"jurisdictionCountry": "Belgium"})
    assert res.status_code >= 400, res.text
