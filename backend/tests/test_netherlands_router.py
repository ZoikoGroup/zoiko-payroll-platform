"""Netherlands Super Admin API (netherlands_router) over HTTP — auth, explicit
organisation scoping, four-eyes, read-only statutory pack content, and the
G3 transport lock. Built on the Phase 5–7 integration fixture (in-memory
SQLite; SYNTHETIC wage-tax rows)."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.payroll import service
from tests.test_hong_kong_governance import _http
from tests.test_netherlands_service_integration import _approve, _run, nlx  # noqa: F401

BASE = "/api/super-admin/compliance/netherlands"
# ZP-PRIV decision 3: employer registration, premium decisions, 30% decisions,
# organisation overrides and loonaangifte are tenant-run (/api/payroll/...).
TENANT = "/api/payroll/netherlands"
SA_A = SimpleNamespace(id=901, organization_id=None, role="super_admin", is_active=True)
SA_B = SimpleNamespace(id=902, organization_id=None, role="super_admin", is_active=True)
ORG_ADMIN = SimpleNamespace(id=903, organization_id=1, role="org_admin", is_active=True)
ORG_ADMIN_2 = SimpleNamespace(id=904, organization_id=1, role="org_admin", is_active=True)

http = _http


def _committed_march(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    return run


def test_super_admin_only(db, nlx):
    with http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/organizations").status_code == 403


def test_org_scoping_is_explicit(db, nlx):
    with http(db, SA_A) as c:
        # Organisation registry metadata only; the employee list is worker
        # data and is refused for Super Admin (ZP-PRIV B.1).
        orgs = c.get(f"{BASE}/organizations").json()
        assert [o["id"] for o in orgs] == [nlx.org.id]
        assert c.get(f"{BASE}/employees", params={"org_id": nlx.org.id}).status_code == 403


def test_employer_profile_and_readiness(db, nlx):
    with http(db, SA_A) as c:
        assert c.get(f"{BASE}/employer-profile", params={"org_id": nlx.org.id}).status_code == 403
        card = c.get(f"{BASE}/employer-profile/readiness", params={"org_id": nlx.org.id}).json()
        assert card["sections"]                                   # readiness status stays visible
    with http(db, ORG_ADMIN) as c:
        profile = c.get(f"{TENANT}/employer-profile").json()
        assert profile["loonheffingennummer"] == "123456789L01"
        r = c.post(f"{TENANT}/employer-profile",
                   json={"effectiveFrom": "2026-07-01", "legalName": "TEST BV v2", "loonheffingennummer": "123456789L01"})
        assert r.status_code == 200 and r.json()["version"] == 2, r.text


def test_statutory_pack_content_is_read_only(db, nlx):
    with http(db, SA_A) as c:
        mw = c.get(f"{BASE}/minimum-wage", params={"on": "2026-07-31"}).json()
        assert mw["editable"] is False and mw["packId"] == nlx.pack.id
        assert {r["key"] for r in mw["rows"]} >= {"AGE_21_PLUS"}
        assert c.get(f"{BASE}/wkr-bands").json()["rows"]
        assert c.post(f"{BASE}/minimum-wage", json={}).status_code == 405       # no direct edit
        assert c.post(f"{BASE}/wkr-bands", json={}).status_code == 405


def test_tax_table_import_and_four_eyes(db, nlx):
    # One principal per block: _http overrides the app's dependencies globally.
    csv = b"wage_from,wage_to,aow_cohort,with_tax_credit,withholding_amount\n0,,BELOW_AOW,true,100.00\n"
    with http(db, SA_A) as a:
        r = a.post(f"{BASE}/tax-tables/import", files={"file": ("synthetic.csv", csv, "text/csv")},
                   data={"jurisdiction_pack_id": nlx.pack.id, "tax_year": 2027, "table_color": "WHITE",
                         "table_kind": "PERIOD", "period": "MONTH", "residence_variant": "NL"})
        assert r.status_code == 200, r.text
        fid = r.json()["id"]
        assert r.json()["status"] == "IMPORTED"
        assert a.put(f"{BASE}/tax-tables/{fid}/validate").json()["status"] == "VALIDATED"
        assert a.put(f"{BASE}/tax-tables/{fid}/approve").status_code == 400        # importer cannot approve
    with http(db, SA_B) as b:
        r = b.put(f"{BASE}/tax-tables/{fid}/approve")
        assert r.status_code == 200 and r.json()["status"] == "APPROVED", r.text
        assert b.put(f"{BASE}/tax-tables/{fid}/activate").status_code == 400       # approver cannot activate
        assert b.put(f"{BASE}/tax-tables/{fid}/reject", json={}).status_code == 400  # reason required
    with http(db, SA_A) as a:
        r = a.put(f"{BASE}/tax-tables/{fid}/activate")
        assert r.status_code == 200 and r.json()["status"] == "ACTIVE", r.text


def test_premium_decision_four_eyes(db, nlx):
    body = {"tax_year": 2026, "aof_size_class": "LARGE", "aof_basis_year": 2024, "aof_basis_premium_wage": "1",
            "decision_reference": "BD-2", "decision_date": "2026-06-01", "effective_from": "2026-07-01",
            "whk_wga_pct": "0.6", "whk_zw_flex_pct": "0.3"}
    with http(db, SA_A) as c:
        assert c.post(f"{BASE}/premium-decisions", params={"org_id": nlx.org.id}, json=body).status_code == 403
    with http(db, ORG_ADMIN) as a:
        d = a.post(f"{TENANT}/premium-decisions", json=body).json()
        assert d["status"] == "DRAFT"
        assert a.put(f"{TENANT}/premium-decisions/{d['id']}/activate").status_code == 400
    with http(db, ORG_ADMIN_2) as b:
        r = b.put(f"{TENANT}/premium-decisions/{d['id']}/activate")
        assert r.status_code == 200 and r.json()["status"] == "ACTIVE", r.text
        rows = b.get(f"{TENANT}/premium-decisions").json()
        assert sorted(r["status"] for r in rows) == ["ACTIVE", "SUPERSEDED"]


def test_vcr_inspector_after_commit(db, nlx):
    _committed_march(db, nlx)
    with http(db, SA_A) as c:
        # Per-employee cumulative wages are worker data (ZP-PRIV B.1).
        r = c.get(f"{BASE}/vcr", params={"org_id": nlx.org.id, "employee_id": nlx.emp.id, "tax_year": 2026})
        assert r.status_code == 403


def test_earning_classification_supersedes(db, nlx):
    body = {"earning_code": "base_salary", "effective_from": "2026-07-01",
            "remuneration_type": "REGULAR", "wage_tax": True, "employee_insurance_wage": True, "zvw_wage": True,
            "pensionable": False, "wkr_treatment": "WAGE", "vacation_allowance_basis": True,
            "minimum_wage_reckonable": True}
    with http(db, SA_A) as c:
        # Super Admin keeps the platform catalog; organisation overrides are tenant-run.
        assert c.post(f"{BASE}/earning-classifications",
                      json={**body, "organization_id": nlx.org.id}).status_code == 400
    with http(db, ORG_ADMIN) as c:
        assert c.post(f"{TENANT}/earning-classifications", json=body).status_code == 200
        assert c.post(f"{TENANT}/earning-classifications", json={**body, "wkr_treatment": "EXPENSE"}).status_code == 400
        rows = c.get(f"{TENANT}/earning-classifications").json()
        assert {(r["organization_id"], r["status"]) for r in rows} == {(None, "ACTIVE"), (nlx.org.id, "ACTIVE")}


def test_expat_decision_verify_needs_evidence_and_can_be_revoked(db, nlx):
    body = {"employee_id": nlx.emp.id, "decision_reference": "BD-30", "decision_date": "2026-01-05",
            "granted_from": "2026-01-01", "method": "FACILITY_30PCT", "threshold_category": "STANDARD",
            "allowance_pct": "30"}
    with http(db, SA_A) as c:
        assert c.post(f"{BASE}/expat-decisions", params={"org_id": nlx.org.id}, json=body).status_code == 403
    with http(db, ORG_ADMIN) as c:
        d = c.post(f"{TENANT}/expat-decisions", json=body).json()
        assert d["status"] == "PENDING"
        assert c.put(f"{TENANT}/expat-decisions/{d['id']}/verify").status_code == 400
        assert c.put(f"{TENANT}/expat-decisions/{d['id']}/revoke").json()["status"] == "REVOKED"
        assert c.get(f"{TENANT}/expat-decisions").json()[0]["employee_name"] == nlx.emp.name


def test_pension_scheme_catalog(db, nlx):
    with http(db, SA_A) as c:
        r = c.post(f"{BASE}/pension-schemes", json={"organization_id": None, "fund_name": "PFZW-TEST",
                                                     "scheme_code": "PFZW", "effective_from": "2026-01-01",
                                                     "basis_rule": "GROSS_MINUS_FRANCHISE", "employee_pct": "7.5",
                                                     "employer_pct": "15", "franchise_amount": "18000"})
        assert r.status_code == 200, r.text
        assert [s["scheme_code"] for s in c.get(f"{BASE}/pension-schemes").json()] == ["PFZW"]


def test_readiness_gates(db, nlx):
    with http(db, SA_A) as c:
        gates = c.get(f"{BASE}/readiness").json()["gates"]
        assert [g["gate"] for g in gates] == [f"G{i}" for i in range(1, 9)]


def test_loonaangifte_build_reconcile_and_transport_lock(db, nlx):
    _committed_march(db, nlx)
    with http(db, SA_A) as c:
        for method, path in (("post", "/loonaangifte/build"), ("get", "/loonaangifte"),
                             ("post", "/digipoort/submit"), ("post", "/authority-payments/prepare")):
            assert getattr(c, method)(f"{BASE}{path}", params={"org_id": nlx.org.id}).status_code == 403, path
    with http(db, ORG_ADMIN) as c:
        ret = c.post(f"{TENANT}/loonaangifte/build", json={"tax_year": 2026, "period_code": "202603"})
        assert ret.status_code == 200, ret.text
        ret = ret.json()
        assert ret["status"] == "READY" and ret["total_wage_tax"] == "1325.08"
        detail = c.get(f"{TENANT}/loonaangifte/{ret['id']}").json()
        assert len(detail["lines"]) == 1 and detail["lines"][0]["wage_lb_phf"] == "5000.00"
        assert c.put(f"{TENANT}/loonaangifte/{ret['id']}/reconcile").json()["status"] == "RECONCILED"
        r = c.post(f"{TENANT}/loonaangifte/{ret['id']}/file")
        assert r.status_code == 400 and "G3" in r.json()["detail"]


