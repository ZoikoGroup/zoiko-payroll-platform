"""Brazil (ZP-BR-ENG-001) Phase 4b — the CLT employee statutory profile (spec
§7) plus concurrent-employment INSS declarations (BR-009), court-ordered alimony
orders and vale-transporte elections, with per-employee readiness and the
organisation / Super Admin API.

Every identifier and rate here is SYNTHETIC — it proves the mechanics, never a
Brazilian value. `app.*` is imported inside each test / helper (never at module
level) so collecting this file cannot bind the app to the .env database before
conftest's in-memory SQLite fixture is in place."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

ORG_BASE = "/api/payroll/brazil"
SA_BASE = "/api/super-admin/compliance/brazil"
SUPER_ADMIN = SimpleNamespace(id=990, organization_id=None, role="super_admin", is_active=True,
                              email="zzz.throwaway.superadmin@zoiko.internal")


# ── helpers ──────────────────────────────────────────────────────────────────

def _emp_svc():
    from app.modules.payroll import brazil_employee_service

    return brazil_employee_service


def _er_svc():
    from app.modules.payroll import brazil_employer_service

    return brazil_employer_service


def principal(org_id, user_id=801, role="org_admin"):
    return SimpleNamespace(id=user_id, organization_id=org_id, role=role, is_active=True)


@pytest.fixture
def br_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "BR_TENANT_ONBOARDING_ENABLED", True)


@contextmanager
def http(db, who):
    from tests.test_hong_kong_governance import _http as hk_http

    with hk_http(db, who) as client:
        yield client


def _org(db, name="BR Emp Org", code="BREMP", country="BR"):
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import CompanyComplianceDetails

    org = Organization(organization_name=name, organization_code=code)
    db.add(org)
    db.flush()
    if country:
        db.add(CompanyComplianceDetails(organization_id=org.id, name=name, jurisdiction_country=country))
    db.commit()
    return org


def _employee(db, org, code="BR-001", country="BR", **fields):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Emp {code}", country_code=country,
                          **fields)
    db.add(emp)
    db.commit()
    return emp


def _employer(db, org):
    from tests.test_brazil_employer import employer_data

    return _er_svc().create_employer(db, org.id, employer_data(), 801)


def _establishment(db, org, employer_id, **over):
    from tests.test_brazil_employer import establishment_data

    return _er_svc().create_establishment(db, org.id, employer_id, establishment_data(**over), 801)


def _profile(db, org, employee_id, effective_from=date(2026, 1, 1), **fields):
    from app.modules.payroll.models import EmployeeStatutoryProfile

    row = EmployeeStatutoryProfile(organization_id=org.id, employee_id=employee_id, country_code="BR",
                                   effective_from=effective_from, **fields)
    db.add(row)
    db.commit()
    return row


def _configured(db, org):
    """An org with one employee and one establishment — the minimum to have a
    profile that can point at an ACTIVE establishment."""
    emp = _employee(db, org)
    employer = _employer(db, org)
    est = _establishment(db, org, employer["id"])
    return emp, est


# ── statutory_profile_errors (shape only, no DB) ─────────────────────────────

@pytest.mark.parametrize("bad", [
    {"br_esocial_category": "102"},
    {"br_weekly_hours": Decimal("45.00")},
    {"br_contract_type": "PERMANENT"},
    {"br_cbo_code": "12"},
    {"br_irrf_dependents_count": 2},
    {"br_salario_familia_dependents_count": -1},
])
def test_statutory_profile_errors_refuse_bad_facts(bad):
    values = {"br_esocial_category": "101", "br_weekly_hours": Decimal("44.00"),
              "br_contract_type": "INDEFINITE", "br_cbo_code": "212405", "br_irrf_dependents_count": 0,
              "br_salario_familia_dependents_count": 0}
    values.update(bad)
    assert _emp_svc().statutory_profile_errors(SimpleNamespace(**values))


def test_statutory_profile_errors_accept_a_complete_profile():
    data = {"br_esocial_category": "101", "br_weekly_hours": "44.00", "br_contract_type": "INDEFINITE",
            "br_cbo_code": "212405", "br_irrf_dependents_count": 2,
            "br_irrf_dependents_evidence_ref": "Receita dependants statement (test)",
            "br_salario_familia_dependents_count": 0}
    assert _emp_svc().statutory_profile_errors(SimpleNamespace(**data)) == []


# ── statutory_profile_values (carry-forward + FK validation) ─────────────────

def test_profile_values_carry_forward_and_upper_normalise(db, br_on):
    org = _org(db)
    emp, est = _configured(db, org)
    est_id = est["id"]
    first = SimpleNamespace(
        model_fields_set={"br_establishment_id", "br_esocial_category", "br_cbo_code", "br_contract_type",
                          "br_weekly_hours", "br_irrf_dependents_count"},
        effective_from=date(2026, 1, 1), br_establishment_id=est_id, br_esocial_category="101",
        br_cbo_code="212405", br_contract_type="indefinite", br_weekly_hours="44.00",
        br_irrf_dependents_count=0)
    values = _emp_svc().profile_values(db, emp, first, None)
    assert values["br_esocial_category"] == "101"
    assert values["br_contract_type"] == "INDEFINITE"           # upper-cased
    assert values["br_establishment_id"] == est_id

    previous = SimpleNamespace(country_code="BR", br_establishment_id=est_id, br_esocial_category="101",
                               br_cbo_code="212405", br_contract_type="INDEFINITE", br_weekly_hours=44,
                               br_simplified_irrf_opt_out=None, br_irrf_dependents_count=0,
                               br_irrf_dependents_evidence_ref=None, br_salario_familia_dependents_count=0,
                               br_salario_familia_dependents_evidence_ref=None)
    later = SimpleNamespace(model_fields_set={"br_cbo_code"}, effective_from=date(2026, 7, 1), br_cbo_code="212410")
    carried = _emp_svc().profile_values(db, emp, later, previous)
    assert carried["br_cbo_code"] == "212410"                    # sent field overrides
    assert carried["br_establishment_id"] == est_id              # the rest carries forward
    assert carried["br_esocial_category"] == "101"


def test_profile_values_rejects_a_foreign_establishment(db, br_on):
    from app.core.exceptions import BadRequestException

    org_a, org_b = _org(db, "Org A", "BREMPA"), _org(db, "Org B", "BREMPB")
    emp_a = _employee(db, org_a)
    est_b = _establishment(db, org_b, _employer(db, org_b)["id"])
    stray = SimpleNamespace(model_fields_set={"br_establishment_id"}, effective_from=date(2026, 1, 1),
                            br_establishment_id=est_b["id"])
    with pytest.raises(BadRequestException, match="this organisation"):
        _emp_svc().profile_values(db, emp_a, stray, None)


def test_profile_values_rejects_an_establishment_not_active_on_the_date(db, br_on):
    from app.core.exceptions import BadRequestException

    org = _org(db)
    emp, est = _configured(db, org)
    request = SimpleNamespace(model_fields_set={"br_establishment_id"}, effective_from=date(2025, 1, 1),
                              br_establishment_id=est["id"])   # established active_from 2026-01-01
    with pytest.raises(BadRequestException, match="ACTIVE"):
        _emp_svc().profile_values(db, emp, request, None)


# ── views and readiness ──────────────────────────────────────────────────────

def test_employee_record_masks_identifiers_and_returns_children(db, br_on):
    org = _org(db)
    emp, est = _configured(db, org)
    emp.compliance_fields = {"cpf": "52998224725", "pis_nis": "12042827110", "pix_key": "a@bank.com",
                             "bank_account": "12345678"}
    db.commit()
    _profile(db, org, emp.id, br_establishment_id=est["id"], br_esocial_category="101",
             br_cbo_code="212405", br_contract_type="INDEFINITE", br_weekly_hours=Decimal("44.00"))
    view = _emp_svc().employee_record(db, org.id, emp.id)
    assert view["employeeId"] == emp.id
    for key, raw in (("cpf", "52998224725"), ("pis_nis", "12042827110"), ("pix_key", "a@bank.com"),
                     ("bank_account", "12345678")):
        assert view["identifiers"][key] != raw and "*" in view["identifiers"][key]
    assert view["profiles"][0]["brEsocialCategory"] == "101"
    assert view["profiles"][0]["brEstablishmentId"] == est["id"]
    assert view["concurrentInssDeclarations"] == [] and view["alimonyOrders"] == []
    assert view["valeTransporteElections"] == []


def test_employee_readiness_needs_a_profile_then_reports_gaps(db, br_on):
    org = _org(db)
    emp, est = _configured(db, org)
    empty = _emp_svc().employee_readiness(db, org.id, emp.id, date(2026, 6, 1))
    assert empty["liveEligible"] is False
    assert [i["key"] for i in empty["items"]] == ["br_profile"]
    assert empty["items"][0]["status"] == "NOT_STARTED"

    _profile(db, org, emp.id, br_establishment_id=est["id"], br_esocial_category="101",
             br_cbo_code="212405", br_contract_type="INDEFINITE")
    ready = _emp_svc().employee_readiness(db, org.id, emp.id, date(2026, 6, 1))
    statuses = {i["key"]: i["status"] for i in ready["items"]}
    assert statuses["br_establishment"] == "PASS" and statuses["br_category"] == "PASS"
    assert statuses["br_concurrent_inss"] == "NOT_STARTED"      # advisory, not a hard block
    assert statuses["br_engine"] == "BLOCKED"                   # Phase 5/6 engine not built yet
    assert ready["liveEligible"] is False


def test_employee_readiness_rejects_a_missing_date(db, br_on):
    from app.core.exceptions import BadRequestException

    org = _org(db)
    emp = _employee(db, org)
    with pytest.raises(BadRequestException, match="on"):
        _emp_svc().employee_readiness(db, org.id, emp.id, None)


# ── concurrent-employment INSS declarations ──────────────────────────────────

def test_concurrent_inss_records_supersede_the_month(db, br_on):
    from app.core.exceptions import BadRequestException

    org = _org(db)
    emp = _employee(db, org)
    first = _emp_svc().record_concurrent_inss_declaration(
        db, org.id, emp.id, {"competence_month": date(2026, 3, 15), "base_external": "5000.00",
                             "deducted_external": "550.00"}, 801)
    assert first["competenceMonth"] == "2026-03-01"             # normalised to the first of the month
    assert first["status"] == "RECORDED"
    second = _emp_svc().record_concurrent_inss_declaration(
        db, org.id, emp.id, {"competence_month": date(2026, 3, 1), "base_external": "4000.00",
                             "deducted_external": "440.00"}, 801)
    rows = _emp_svc().list_concurrent_inss_declarations(db, org.id, emp.id)
    assert [r["status"] for r in rows] == ["RECORDED", "SUPERSEDED"]
    assert rows[0]["id"] == second["id"]
    with pytest.raises(BadRequestException, match="negative"):
        _emp_svc().record_concurrent_inss_declaration(
            db, org.id, emp.id, {"competence_month": date(2026, 4, 1), "base_external": "-1",
                                 "deducted_external": "0"}, 801)


# ── court-ordered alimony ────────────────────────────────────────────────────

def test_alimony_fixed_and_percentage_lifecycle(db, br_on):
    from app.core.exceptions import BadRequestException

    org = _org(db)
    emp = _employee(db, org)
    fixed = _emp_svc().record_alimony_order(
        db, org.id, emp.id, {"order_reference": "PROC-1234", "method": "FIXED_AMOUNT", "fixed_amount": "800.00",
                             "effective_from": date(2026, 1, 1)}, 801)
    assert fixed["method"] == "FIXED_AMOUNT" and fixed["fixedAmount"] == "800.00"
    pct = _emp_svc().record_alimony_order(
        db, org.id, emp.id, {"order_reference": "PROC-1234", "method": "PERCENTAGE", "percentage": "20.00",
                             "base": "GROSS", "effective_from": date(2026, 6, 1)}, 801)
    history = _emp_svc().list_alimony_orders(db, org.id, emp.id)
    assert {r["status"] for r in history} == {"SUPERSEDED", "ACTIVE"}
    superseded = next(r for r in history if r["status"] == "SUPERSEDED")
    assert superseded["effectiveTo"] == "2026-05-31"            # closed the day before
    closed = _emp_svc().close_alimony_order(db, org.id, pct["id"], {"effective_to": date(2026, 9, 30)}, 801)
    assert closed["status"] == "CLOSED" and closed["effectiveTo"] == "2026-09-30"

    with pytest.raises(BadRequestException, match="method"):
        _emp_svc().record_alimony_order(db, org.id, emp.id, {"order_reference": "X", "method": "NOPE",
                                                             "effective_from": date(2026, 1, 1)}, 801)
    with pytest.raises(BadRequestException, match="percentage"):
        _emp_svc().record_alimony_order(db, org.id, emp.id, {"order_reference": "PROC-9", "method": "PERCENTAGE",
                                                             "percentage": "150", "base": "GROSS",
                                                             "effective_from": date(2026, 1, 1)}, 801)
    with pytest.raises(BadRequestException, match="base"):
        _emp_svc().record_alimony_order(db, org.id, emp.id, {"order_reference": "PROC-9", "method": "PERCENTAGE",
                                                             "percentage": "20", "base": "NOPE",
                                                             "effective_from": date(2026, 1, 1)}, 801)


# ── vale-transporte elections ────────────────────────────────────────────────

def test_vale_transporte_election_supersedes_and_requires_a_cost(db, br_on):
    from app.core.exceptions import BadRequestException

    org = _org(db)
    emp = _employee(db, org)
    elected = _emp_svc().record_vale_transporte_election(
        db, org.id, emp.id, {"elected": True, "daily_cost": "12.00", "effective_from": date(2026, 1, 1)}, 801)
    assert elected["elected"] is True and elected["dailyCost"] == "12.00"
    declined = _emp_svc().record_vale_transporte_election(
        db, org.id, emp.id, {"elected": False, "effective_from": date(2026, 6, 1)}, 801)
    assert declined["elected"] is False and declined["dailyCost"] is None
    rows = _emp_svc().list_concurrent_inss_declarations(db, org.id, emp.id)  # sanity: unrelated list still empty
    assert rows == []
    with pytest.raises(BadRequestException, match="dailyCost"):
        _emp_svc().record_vale_transporte_election(
            db, org.id, emp.id, {"elected": True, "effective_from": date(2026, 7, 1)}, 801)


# ── organisation API (roles, dormancy, tenant isolation) ─────────────────────

def test_employee_routes_are_dormant_unless_the_flag_is_on(db):
    org = _org(db)
    emp = _employee(db, org)
    with http(db, principal(org.id)) as c:
        assert c.get(f"{ORG_BASE}/employees/{emp.id}").status_code == 403


def test_employee_routes_roles_and_tenant_isolation(db, br_on):
    org_a, org_b = _org(db, "Org A", "BREMPA"), _org(db, "Org B", "BREMPB")
    emp_a = _employee(db, org_a)
    emp_b = _employee(db, org_b, code="BR-002")
    with http(db, principal(org_a.id)) as c:
        assert c.get(f"{ORG_BASE}/employees/{emp_a.id}").status_code == 200
        assert c.get(f"{ORG_BASE}/employees/{emp_b.id}").status_code == 404     # tenant isolation
        assert c.get(f"{ORG_BASE}/employees/{emp_a.id}/readiness").status_code == 422   # on is required
        assert c.get(f"{ORG_BASE}/employees/{emp_a.id}/readiness",
                     params={"on": "2026-06-01"}).status_code == 200
        body = {"competenceMonth": "2026-03-01", "baseExternal": "5000.00", "deductedExternal": "550.00"}
        assert c.post(f"{ORG_BASE}/employees/{emp_a.id}/concurrent-inss-declarations", json=body).status_code == 200
        assert c.get(f"{ORG_BASE}/employees/{emp_a.id}/concurrent-inss-declarations").json()[0]["status"] == "RECORDED"
    with http(db, principal(org_a.id, role="payroll_admin")) as c:                 # reads yes, writes no
        assert c.get(f"{ORG_BASE}/employees/{emp_a.id}").status_code == 200
        body = {"competenceMonth": "2026-04-01", "baseExternal": "1000.00", "deductedExternal": "100.00"}
        assert c.post(f"{ORG_BASE}/employees/{emp_a.id}/concurrent-inss-declarations", json=body).status_code == 403


def test_alimony_and_vale_transporte_routes_round_trip(db, br_on):
    org = _org(db)
    emp = _employee(db, org)
    with http(db, principal(org.id)) as c:
        order = c.post(f"{ORG_BASE}/employees/{emp.id}/alimony-orders", json={
            "orderReference": "PROC-9", "method": "PERCENTAGE", "percentage": "15.00", "base": "GROSS",
            "effectiveFrom": "2026-02-01"}).json()
        assert order["status"] == "ACTIVE"
        closed = c.put(f"{ORG_BASE}/alimony-orders/{order['id']}/close", json={"effectiveTo": "2026-08-31"}).json()
        assert closed["status"] == "CLOSED"
        vt = c.post(f"{ORG_BASE}/employees/{emp.id}/vale-transporte-elections", json={
            "elected": True, "dailyCost": "10.50", "effectiveFrom": "2026-02-01"}).json()
        assert vt["dailyCost"] == "10.50"


def test_super_admin_cannot_read_a_brazilian_employee(db, br_on):
    """ZP-PRIV: one employee's statutory profile is worker data — the
    organisation sees its own, Zoiko staff only through an approved Support
    Access grant. The Super Admin route is retired in the route registry (as
    Mexico's), so it is refused uniformly and never leaks the record."""
    org = _org(db)
    emp = _employee(db, org, compliance_fields={"cpf": "52998224725"})
    _profile(db, org, emp.id, br_esocial_category="101", br_cbo_code="212405", br_contract_type="INDEFINITE")
    with http(db, SUPER_ADMIN) as c:
        for params in ({"organization_id": org.id}, {"organization_id": 99999}, {}):
            r = c.get(f"{SA_BASE}/employees/{emp.id}", params=params)
            assert r.status_code == 403, (params, r.status_code)
            assert "52998224725" not in r.text and "212405" not in r.text
