"""Brazil Super Admin API (brazil_router, ZP-BR-ENG-001 Phase 2) over HTTP —
Super Admin only, explicit organisation scoping, statutory pack content
read-only, canonical rubric catalogue, gates and the golden check.

`app.*` is imported inside each test (never at module level) so collecting
this file cannot bind the app to the .env database before conftest's
in-memory SQLite fixture is in place."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

BASE = "/api/super-admin/compliance/brazil"
SA_A = SimpleNamespace(id=971, organization_id=None, role="super_admin", is_active=True)
ORG_ADMIN = SimpleNamespace(id=972, organization_id=1, role="org_admin", is_active=True)

_GET_ROUTES = ("/organizations", "/employees?org_id=1", "/pack-rows?rule_type=BR_INSS_BAND",
               "/rubric-catalogue", "/fpas-table", "/gates", "/readiness")


@contextmanager
def _http(db, principal):
    from tests.test_hong_kong_governance import _http as hk_http

    with hk_http(db, principal) as client:
        yield client


def _org(db, name="Org BR", code="ORGBR"):
    from app.modules.organizations.models import Organization

    org = Organization(organization_name=name, organization_code=code)
    db.add(org)
    db.commit()
    return org


def _employee(db, org, code, country):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Emp {code}", country_code=country)
    db.add(emp)
    db.commit()
    return emp


def _pack(db, status, pack_id="BR-PAYROLL-2026"):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="BR", pack_type="tax", status=status,
                            version="1.0", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(pack)
    db.commit()
    return pack


def _slab(db, pack, rule_type, key, rate, lower, upper=None, organization_id=None, order=1):
    from app.modules.payroll.models import TaxSlab

    db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="BR", organization_id=organization_id,
                   rule_type=rule_type, filing_status=key, rate_pct=Decimal(rate), min_amount=Decimal(lower),
                   max_amount=Decimal(upper) if upper else None, rate_label=f"{rate}%", tax_formula="test",
                   effective_from=date(2026, 1, 1), sort_order=order))
    db.commit()


# ── auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", _GET_ROUTES)
def test_every_read_route_is_super_admin_only(db, route):
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}{route}").status_code == 403


def test_golden_check_is_super_admin_only(db):
    with _http(db, ORG_ADMIN) as c:
        assert c.post(f"{BASE}/golden-check").status_code == 403


# ── organisation scoping ─────────────────────────────────────────────────────

def test_org_scoping_is_explicit(db):
    from app.modules.payroll.models import CompanyComplianceDetails

    br_org, other = _org(db), _org(db, "Org US", "ORGUS")
    _employee(db, br_org, "BR-001", "BR")
    _employee(db, other, "US-001", "US")
    db.add(CompanyComplianceDetails(organization_id=br_org.id, name="Org BR", jurisdiction_country="BR"))
    db.commit()
    with _http(db, SA_A) as c:
        assert [o["id"] for o in c.get(f"{BASE}/organizations").json()] == [br_org.id]
        # ZP-PRIV: the employee list is worker-level data — retired for Super
        # Admin in the route registry (a live JIT support grant is needed).
        for params in ({}, {"org_id": 99999}, {"org_id": br_org.id}):
            assert c.get(f"{BASE}/employees", params=params).status_code == 403


def test_organizations_include_an_employer_profile_without_employees(db):
    from app.modules.payroll.models import PayrollBrEmployerProfile

    org = _org(db)
    db.add(PayrollBrEmployerProfile(organization_id=org.id, version=1, effective_from=date(2026, 1, 1),
                                    cnpj_root="11222333", legal_name="X Ltda",
                                    tax_classification="99", cnae_preponderant="6201501", contact_name="A",
                                    contact_cpf="52998224725", contact_email="a@example.com"))
    db.commit()
    with _http(db, SA_A) as c:
        assert [o["id"] for o in c.get(f"{BASE}/organizations").json()] == [org.id]


# ── statutory pack content — read only ───────────────────────────────────────

def test_pack_rows_reject_unknown_rule_types(db):
    with _http(db, SA_A) as c:
        assert c.get(f"{BASE}/pack-rows", params={"rule_type": "NL_WAGE_TAX"}).status_code == 400


def test_pack_rows_with_no_active_pack_are_empty_not_invented(db):
    _slab(db, _pack(db, "Draft"), "BR_INSS_BAND", "B1", "7.5", "0", "1621.00")   # a Draft pack never shows
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/pack-rows", params={"rule_type": "BR_INSS_BAND", "on": "2026-07-31"}).json()
    assert body["packId"] is None and body["rows"] == [] and body["editable"] is False


def test_pack_rows_show_only_canonical_rows_of_the_active_pack(db):
    pack = _pack(db, "Active")
    _slab(db, pack, "BR_INSS_BAND", "B1", "7.5", "0", "1621.00", order=1)
    _slab(db, pack, "BR_INSS_BAND", "B2", "9", "1621.00", "2902.84", order=2)
    _slab(db, pack, "BR_INSS_BAND", "ORG", "1", "0", organization_id=5, order=3)      # an org copy never shows
    _slab(db, pack, "BR_IRRF_TABLE", "T1", "0", "0", "2428.80")                       # another rule type
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/pack-rows", params={"rule_type": "BR_INSS_BAND", "on": "2026-07-31"}).json()
        outside = c.get(f"{BASE}/pack-rows", params={"rule_type": "BR_INSS_BAND", "on": "2027-01-15"}).json()
        assert c.post(f"{BASE}/pack-rows", json={}).status_code == 405                # no direct edit
    assert body["packId"] == pack.id and body["packCode"] == "BR-PAYROLL-2026" and body["editable"] is False
    assert [r["key"] for r in body["rows"]] == ["B1", "B2"]
    assert body["rows"][1]["rate"] == "9.00" or Decimal(body["rows"][1]["rate"]) == Decimal("9")
    assert outside["packId"] is None and outside["rows"] == []                       # out of the pack's window


# ── rubric catalogue ─────────────────────────────────────────────────────────

def test_rubric_catalogue_serves_the_canonical_rows_without_an_organisation(db):
    from app.modules.payroll.engine.countries import brazil_content

    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/rubric-catalogue").json()
    assert body["catalogueHash"] == brazil_content.CONTENT_HASH
    assert len(body["rubrics"]) == len(brazil_content.STANDARD_SYSTEM_RUBRICS)
    assert {r["source"] for r in body["rubrics"]} == {"canonical"}
    assert "unverified" in body["note"].lower()                                       # BR-K3 stays visible


def test_rubric_catalogue_appends_an_organisations_rows(db):
    from app.modules.payroll.models import PayrollBrRubric

    org = _org(db)
    db.add(PayrollBrRubric(organization_id=org.id, rubric_code="ORG_BONUS", rubric_name="Bonus", nature_code="1099",
                           rubric_type="EARNING", cod_inc_cp="11", cod_inc_irrf="11", cod_inc_fgts="11",
                           valid_from=date(2026, 1, 1)))
    db.commit()
    with _http(db, SA_A) as c:
        assert c.get(f"{BASE}/rubric-catalogue", params={"org_id": 99999}).status_code == 404
        rows = c.get(f"{BASE}/rubric-catalogue", params={"org_id": org.id}).json()["rubrics"]
    org_rows = [r for r in rows if r["source"] == "organization"]
    assert [r["rubric_code"] for r in org_rows] == ["ORG_BONUS"]
    assert org_rows[0]["valid_from"] == "2026-01-01"


# ── FPAS, gates, readiness, golden check ─────────────────────────────────────

def test_fpas_table_is_honestly_unavailable(db):
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/fpas-table").json()
    assert body["available"] is False and "D6" in body["note"]


def test_gates_and_readiness_report_every_gate_open(db):
    with _http(db, SA_A) as c:
        gates = c.get(f"{BASE}/gates").json()
        readiness = c.get(f"{BASE}/readiness").json()
    assert [g["gate"] for g in gates] == [f"G{i}" for i in range(1, 9)]
    assert {g["state"] for g in gates} == {"OPEN"}
    assert readiness["available"] is False and readiness["gates"] == gates


def test_golden_check_runs_br_fixtures(db):
    """Phase 5 added real br_golden fixtures, so the run now executes them
    (they are still PROVISIONAL until G1/D6 sign-off, but must be a PASS)."""
    from app.modules.payroll.models import TestCertificationRun

    with _http(db, SA_A) as c:
        body = c.post(f"{BASE}/golden-check").json()
    assert body["status"] == "PASS" and body["total_cases"] == 3
    run = db.query(TestCertificationRun).filter(TestCertificationRun.id == body["run_id"]).one()
    assert run.jurisdiction_country == "BR" and run.triggered_by_id == SA_A.id
