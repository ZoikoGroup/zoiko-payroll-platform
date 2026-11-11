"""
tests/privacy/test_payslip_templates_http.py
--------------------------------------------
Payslip templates over HTTP with real JWTs (PDP, auth chain, body/multipart
parsing): the owning tenant can build, publish, assign and render; the other
tenant, the employee persona and the super admin cannot.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def _h(world, who):
    return {"Authorization": f"Bearer {world.token(who)}"}


def _payslip(world):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    db, org, emp = world.db, world.orgs["A"], world.employees["A1"]
    run = PayrollRun(organization_id=org.id, run_code="TPL-HTTP-1", period_label="June 2026",
                     pay_date=date(2026, 6, 30), period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                     status="Draft")
    db.add(run)
    db.flush()
    item = PayslipItem(organization_id=org.id, payroll_run_id=run.id, employee_id=emp.id, employee_name=emp.name,
                       country_code="IN", basic_salary=Decimal("50000"), hra=Decimal("20000"),
                       special_allowance=Decimal("10000"), gross_pay=Decimal("80000"), tds=Decimal("5000"),
                       pf=Decimal("1800"), professional_tax=Decimal("200"), total_deductions=Decimal("7000"),
                       net_pay=Decimal("73000"), status="Pending")
    db.add(item)
    db.commit()
    return item.id


def test_owner_builds_publishes_assigns_and_renders(client, world):
    ta = _h(world, "TA")
    r = client.get("/api/payroll/payslip-templates", headers=ta)
    assert r.status_code == 200, r.text
    assert {s["key"] for s in r.json()["starters"]} == {"CLASSIC_NAVY", "MODERN_EMERALD"}

    r = client.post("/api/payroll/payslip-templates", headers=ta, json={"starter": "CLASSIC_NAVY"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.put(f"/api/payroll/payslip-templates/{tid}", headers=ta,
                   json={"configurationJson": {"primaryColor": "#123456"}})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/payroll/payslip-templates/{tid}/publish", headers=ta).status_code == 200
    r = client.post("/api/payroll/payslip-templates/assignments", headers=ta, json={"templateId": tid, "country": "ALL"})
    assert r.status_code == 200, r.text
    assert r.json()["assignments"][0]["country"] == "ALL"

    pid = _payslip(world)
    r = client.get(f"/api/payroll/payslips/{pid}/rendered", headers=ta)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "73,000.00" in body["renderedHtml"] and "#123456" in body["renderedHtml"]
    assert "EVALUATION ONLY" in body["renderedHtml"]          # world orgs are EVALUATION workspaces
    assert "default-src 'none'" in body["renderedHtml"]

    r = client.post("/api/payroll/payslip-templates/preview", headers=ta,
                    json={"htmlContent": "<p>{{ employee.name }}</p>", "country": "UK"})
    assert r.status_code == 200 and "Sample Employee" in r.json()["renderedHtml"]

    assert client.delete("/api/payroll/payslip-templates/assignments/ALL", headers=ta).status_code == 200
    r = client.get(f"/api/payroll/payslips/{pid}/rendered", headers=ta)
    assert r.status_code == 404


def test_import_parses_multipart_and_refuses_script(client, world):
    ta = _h(world, "TA")
    good = b"<html><head><style>.x{color:#111}</style></head><body><p>{{ employee.name }}</p></body></html>"
    r = client.post("/api/payroll/payslip-templates/import", headers=ta,
                    data={"name": "Imported"}, files={"file": ("slip.html", good, "text/html")})
    assert r.status_code == 201, r.text
    assert ".x{color:#111}" in r.json()["latestVersion"]["cssContent"]
    bad = b"<p>{{ employee.name }}</p><script>alert(1)</script>"
    r = client.post("/api/payroll/payslip-templates/import", headers=ta,
                    data={"name": "Bad"}, files={"file": ("bad.html", bad, "text/html")})
    assert r.status_code == 400


def test_other_tenant_employee_and_super_admin_are_refused(client, world):
    ta = _h(world, "TA")
    tid = client.post("/api/payroll/payslip-templates", headers=ta, json={"starter": "MODERN_EMERALD"}).json()["id"]
    client.post(f"/api/payroll/payslip-templates/{tid}/publish", headers=ta)
    client.post("/api/payroll/payslip-templates/assignments", headers=ta, json={"templateId": tid})
    pid = _payslip(world)

    tb = _h(world, "TB")
    assert client.get(f"/api/payroll/payslip-templates/{tid}", headers=tb).status_code == 404
    assert client.post(f"/api/payroll/payslip-templates/{tid}/publish", headers=tb).status_code in (404, 409)
    assert client.post("/api/payroll/payslip-templates/assignments", headers=tb,
                       json={"templateId": tid}).status_code == 404
    assert client.get(f"/api/payroll/payslips/{pid}/rendered", headers=tb).status_code in (403, 404)
    assert client.get("/api/payroll/payslip-templates", headers=tb).json()["templates"] == []

    for who in ("EA", "SA"):
        h = _h(world, who)
        assert client.get("/api/payroll/payslip-templates", headers=h).status_code in (401, 403), who
        assert client.get(f"/api/payroll/payslips/{pid}/rendered", headers=h).status_code in (401, 403), who
