"""Netherlands organisation API (netherlands_org_router, /api/payroll/netherlands)
over HTTP — own-organisation scoping, tenant isolation, role gates, no typed-in
statutory facts, four-eyes, and the G3 transport lock. Built on the Phase 5–7
integration fixture (in-memory SQLite; SYNTHETIC wage-tax rows)."""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.modules.payroll import service
from tests.test_hong_kong_governance import _http
from tests.test_netherlands_service_integration import _approve, _run, nlx  # noqa: F401

BASE = "/api/payroll/netherlands"
http = _http


def _principal(org_id, user_id=801, role="org_admin"):
    return SimpleNamespace(id=user_id, organization_id=org_id, role=role, is_active=True)


def _other_org(db):
    """A second tenant with its own Netherlands employee."""
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    org = Organization(organization_name="Other Org", organization_code="OTHERORG")
    db.add(org)
    db.flush()
    emp = PayrollEmployee(organization_id=org.id, employee_code="NL-900", name="Ander Persoon", country_code="NL",
                          ctc=D("40000"), basic=D("40000"), hra=D("0"), date_of_birth=date(1985, 1, 1),
                          date_of_joining=date(2025, 1, 1), pay_frequency="Monthly",
                          compliance_fields={"bsn": "111222333"})
    db.add(emp)
    db.commit()
    return org, emp


def test_super_admin_and_employee_roles_are_refused(db, nlx):
    with http(db, SimpleNamespace(id=1, organization_id=None, role="super_admin", is_active=True)) as c:
        assert c.get(f"{BASE}/employer-profile").status_code == 403          # no organisation of its own
    with http(db, _principal(nlx.org.id, role="employee")) as c:
        assert c.get(f"{BASE}/employer-profile").status_code == 403


def test_employer_registration_is_own_org_and_org_admin_only(db, nlx):
    with http(db, _principal(nlx.org.id)) as c:
        profile = c.get(f"{BASE}/employer-profile").json()
        assert profile["organizationId"] == nlx.org.id and profile["loonheffingennummer"] == "123456789L01"
        r = c.post(f"{BASE}/employer-profile", json={"effectiveFrom": "2026-07-01", "legalName": "TEST BV v2",
                                                      "loonheffingennummer": "123456789L01"})
        assert r.status_code == 200 and r.json()["version"] == 2
        assert c.post(f"{BASE}/employer-profile", json={"legalName": "no date"}).status_code == 400
        ready = c.get(f"{BASE}/readiness").json()
        assert ready["employer"]["sections"] and {g["gate"] for g in ready["gates"]} >= {"G1", "G3"}
    with http(db, _principal(nlx.org.id, role="payroll_admin")) as c:
        assert c.get(f"{BASE}/employer-profile").status_code == 200
        assert c.post(f"{BASE}/employer-profile", json={"effectiveFrom": "2026-08-01",
                                                         "legalName": "x"}).status_code == 403


def test_tenant_isolation(db, nlx):
    other_org, other_emp = _other_org(db)
    with http(db, _principal(other_org.id, user_id=950)) as c:
        assert c.get(f"{BASE}/employer-profile").json() is None              # never another tenant's profile
        assert c.get(f"{BASE}/employees/{nlx.emp.id}").status_code == 404
        assert c.post(f"{BASE}/employees/{nlx.emp.id}/contracts",
                      json={"contractTerm": "FIXED", "startDate": "2026-07-01"}).status_code == 404
        assert c.get(f"{BASE}/loonaangifte").json() == []
    run = _run(db, nlx.org, 3)
    with http(db, _principal(other_org.id, user_id=950)) as c:
        assert c.get(f"{BASE}/runs/{run.id}/preflight").status_code == 404
        assert c.get(f"{BASE}/runs/{run.id}/fingerprint").status_code == 404
    with http(db, _principal(nlx.org.id)) as c:
        assert c.get(f"{BASE}/employees/{other_emp.id}").status_code == 404


def test_employee_record_and_non_nl_employee(db, nlx):
    from app.modules.payroll.models import PayrollEmployee

    other = PayrollEmployee(organization_id=nlx.org.id, employee_code="IN-1", name="Not Dutch", country_code="IN",
                            ctc=D("1"), basic=D("1"), hra=D("0"), date_of_joining=date(2025, 1, 1))
    db.add(other)
    db.commit()
    with http(db, _principal(nlx.org.id)) as c:
        rec = c.get(f"{BASE}/employees/{nlx.emp.id}").json()
        assert rec["employee"]["bsnRecorded"] is True and "bsn" not in rec["employee"]   # never the BSN itself
        assert rec["statutoryFields"]["tableColor"] == "WHITE"
        assert len(rec["contracts"]) == 1 and len(rec["taxCreditInstructions"]) == 1
        assert c.get(f"{BASE}/employees/{other.id}").status_code == 400


def test_contracts_are_new_versions_with_derived_awf_class(db, nlx):
    with http(db, _principal(nlx.org.id)) as c:
        r = c.post(f"{BASE}/employees/{nlx.emp.id}/contracts",
                   json={"contractTerm": "FIXED", "writtenRecord": True, "startDate": "2026-07-01",
                         "derivedAwfClass": "LOW"})                          # a client-sent class is ignored
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["version"] == 2 and body["derivedAwfClass"] == "HIGH" and body["awfDerivationReason"]
        assert c.put(f"{BASE}/contracts/{body['id']}", json={"derivedAwfClass": "LOW"}).status_code in (404, 405)


def test_tax_credit_instruction_takes_no_amount(db, nlx):
    with http(db, _principal(nlx.org.id)) as c:
        r = c.post(f"{BASE}/employees/{nlx.emp.id}/tax-credit-instructions",
                   json={"applyTaxCredit": False, "signedAt": "2026-06-20T10:00:00", "effectiveFrom": "2026-07-01",
                         "creditAmount": "3000"})
        assert r.status_code == 200, r.text
        assert r.json()["applyTaxCredit"] is False and "creditAmount" not in r.json()
        rec = c.get(f"{BASE}/employees/{nlx.emp.id}").json()
        assert sorted(i["supersededById"] is None for i in rec["taxCreditInstructions"]) == [False, True]


def test_income_relationship_open_and_close(db, nlx):
    with http(db, _principal(nlx.org.id)) as c:
        r = c.post(f"{BASE}/employees/{nlx.emp.id}/income-relationships",
                   json={"ikvNumber": "1", "incomeRelationCode": "15", "payrollPeriod": "MONTH",
                         "startDate": "2025-01-01"})
        assert r.status_code == 200, r.text
        ikv = r.json()["id"]
        assert c.put(f"{BASE}/income-relationships/{ikv}/close", json={"endDate": "2026-12-31"}).status_code == 400
        closed = c.put(f"{BASE}/income-relationships/{ikv}/close",
                       json={"endDate": "2026-12-31", "closedReason": "resigned"}).json()
        assert closed["status"] == "CLOSED" and closed["endDate"] == "2026-12-31"


def test_termination_settlement_four_eyes(db, nlx):
    body = {"termination_date": "2026-09-30", "reason": "redundancy", "initiated_by": "EMPLOYER",
            "service_months": 20, "monthly_salary": "5000", "annual_salary": "60000",
            "unused_leave_hours": "16", "hourly_wage": "28.85"}
    with http(db, _principal(nlx.org.id, user_id=801)) as c:
        r = c.post(f"{BASE}/employees/{nlx.emp.id}/termination-settlements", json=body)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert r.json()["status"] == "DRAFT" and r.json()["prepared_by"] == 801
        assert c.put(f"{BASE}/termination-settlements/{sid}/approve").status_code == 400   # preparer cannot approve
    with http(db, _principal(nlx.org.id, user_id=802)) as c:
        r = c.put(f"{BASE}/termination-settlements/{sid}/approve")
        assert r.status_code == 200 and r.json()["status"] == "APPROVED", r.text


def test_sickness_event_and_absence_policy(db, nlx):
    with http(db, _principal(nlx.org.id)) as c:
        pol = c.post(f"{BASE}/absence-pay-policies", json={"effective_from": "2026-01-01", "year1_pct": "70",
                                                           "year2_pct": "70"}).json()
        assert [p["id"] for p in c.get(f"{BASE}/absence-pay-policies").json()] == [pol["id"]]
        ev = c.post(f"{BASE}/employees/{nlx.emp.id}/sickness-events",
                    json={"first_sick_day": "2026-05-04", "policy_id": pol["id"]})
        assert ev.status_code == 200, ev.text
        closed = c.put(f"{BASE}/sickness-events/{ev.json()['id']}/close", json={"recovery_date": "2026-05-20"})
        assert closed.status_code == 200 and closed.json()["recovery_date"] == "2026-05-20"


def test_run_preflight_fingerprint_and_returns(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    with http(db, _principal(nlx.org.id)) as c:
        pre = c.get(f"{BASE}/runs/{run.id}/preflight").json()
        assert pre["status"] in ("OK", "WARN") and not [x for x in pre["checks"] if x["severity"] == "BLOCK"]
        fp = c.get(f"{BASE}/runs/{run.id}/fingerprint").json()
        assert fp["payslips"] == 1 and fp["fingerprint"] and fp["stored"] is None
        # Nothing committed yet: a REGULAR return refuses.
        assert c.post(f"{BASE}/loonaangifte/build", json={"tax_year": 2026, "period_code": "202603"}).status_code == 400
    _approve(db, run, nlx.org)
    with http(db, _principal(nlx.org.id)) as c:
        r = c.post(f"{BASE}/loonaangifte/build", json={"tax_year": 2026, "period_code": "202603"})
        assert r.status_code == 200, r.text
        ret = r.json()
        assert ret["status"] and "payload" not in ret
        detail = c.get(f"{BASE}/loonaangifte/{ret['id']}").json()
        assert len(detail["lines"]) == 1 and detail["lines"][0]["employee_id"] == nlx.emp.id
        assert c.put(f"{BASE}/loonaangifte/{ret['id']}/reconcile").status_code == 200
        assert "locked until gate G3" in c.post(f"{BASE}/loonaangifte/{ret['id']}/file").json()["detail"]
        assert c.post(f"{BASE}/authority-payments/prepare").status_code == 400


def test_wkr_is_read_only_and_own_org(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    other_org, _ = _other_org(db)
    with http(db, _principal(nlx.org.id)) as c:
        wkr = c.get(f"{BASE}/wkr", params={"tax_year": 2026}).json()
        assert wkr["taxYear"] == 2026 and wkr["settlements"] == []
        assert wkr["latest"] is None or wkr["latest"]["organization_id"] == nlx.org.id
        assert c.post(f"{BASE}/wkr", json={}).status_code == 405
    with http(db, _principal(other_org.id, user_id=950)) as c:
        assert c.get(f"{BASE}/wkr", params={"tax_year": 2026}).json()["revisions"] == []


def test_annual_statement_generate_and_issue(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    with http(db, _principal(nlx.org.id)) as c:
        r = c.post(f"{BASE}/annual-statements/generate", json={"employee_id": nlx.emp.id, "tax_year": 2026})
        assert r.status_code == 200, r.text
        st = r.json()
        assert st["status"] == "DRAFT" and "idempotency_key" not in st
        issued = c.put(f"{BASE}/annual-statements/{st['id']}/issue")
        assert issued.status_code == 200 and issued.json()["status"] != "DRAFT", issued.text
        assert [s["id"] for s in c.get(f"{BASE}/annual-statements", params={"tax_year": 2026}).json()] == [st["id"]]
