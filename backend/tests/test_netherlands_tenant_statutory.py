"""Netherlands tenant-run statutory configuration (tenant_statutory_router,
/api/payroll/netherlands/...): premium decisions, 30% facility decisions,
earning-classification overrides and pension schemes.

ZP-PRIV moved these out of Super Admin, so the organisation records AND
approves them. These tests pin the controls that make that safe:
  * four-eyes — the creator of a premium decision cannot activate it, and the
    person who recorded a 30% decision cannot verify it (NL-017 / NL-026);
  * the decision letter must be the organisation's OWN document;
  * only a PENDING 30% decision can be verified (a revoked one never returns);
  * a decision recorded before the recorder was tracked fails closed;
  * everything is scoped to the caller's organisation.
In-memory SQLite, SYNTHETIC wage-tax rows (the Phase 5–7 integration fixture).
"""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from tests.test_hong_kong_governance import _http
from tests.test_netherlands_service_integration import nlx  # noqa: F401

BASE = "/api/payroll/netherlands"
http = _http

EXPAT = {"decision_reference": "BD-30-2026-001", "decision_date": "2026-01-05", "granted_from": "2026-01-01",
         "method": "FACILITY_30PCT", "threshold_category": "STANDARD", "allowance_pct": "30"}
PREMIUM = {"tax_year": 2026, "aof_size_class": "LARGE", "aof_basis_year": 2024, "aof_basis_premium_wage": "1",
           "decision_reference": "BD-WHK-2026-07", "decision_date": "2026-06-01", "effective_from": "2026-07-01",
           "whk_wga_pct": "0.6", "whk_zw_flex_pct": "0.3"}


def _user(org_id, user_id, role="org_admin"):
    return SimpleNamespace(id=user_id, organization_id=org_id, role=role, is_active=True)


def _document(db, org_id, title="Belastingdienst 30%-beschikking"):
    from app.modules.payroll.models import ComplianceDocument

    doc = ComplianceDocument(organization_id=org_id, title=title, file_path="evidence/beschikking.pdf",
                             file_name="beschikking.pdf")
    db.add(doc)
    db.commit()
    return doc


def _other_org(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    org = Organization(organization_name="Other Org", organization_code="OTHERORG")
    db.add(org)
    db.flush()
    emp = PayrollEmployee(organization_id=org.id, employee_code="NL-900", name="Ander Persoon", country_code="NL",
                          ctc=D("40000"), basic=D("40000"), hra=D("0"), date_of_birth=date(1985, 1, 1),
                          date_of_joining=date(2025, 1, 1), pay_frequency="Monthly")
    db.add(emp)
    db.commit()
    return org, emp


def _record(c, nlx, **extra):
    r = c.post(f"{BASE}/expat-decisions", json={**EXPAT, "employee_id": nlx.emp.id, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ── premium decisions (NL-017) ───────────────────────────────────────────────

class TestPremiumDecisions:
    def test_four_eyes_activation(self, db, nlx):
        with http(db, _user(nlx.org.id, 801)) as c:
            d = c.post(f"{BASE}/premium-decisions", json=PREMIUM).json()
            assert d["status"] == "DRAFT"
            assert c.put(f"{BASE}/premium-decisions/{d['id']}/activate").status_code == 400   # creator
        with http(db, _user(nlx.org.id, 802)) as c:
            r = c.put(f"{BASE}/premium-decisions/{d['id']}/activate")
            assert r.status_code == 200 and r.json()["status"] == "ACTIVE", r.text
            statuses = sorted(x["status"] for x in c.get(f"{BASE}/premium-decisions").json())
            assert statuses == ["ACTIVE", "SUPERSEDED"]          # the fixture's decision is superseded

    def test_other_tenant_cannot_see_or_activate(self, db, nlx):
        other, _ = _other_org(db)
        with http(db, _user(nlx.org.id, 801)) as c:
            d = c.post(f"{BASE}/premium-decisions", json=PREMIUM).json()
        with http(db, _user(other.id, 950)) as c:
            assert c.get(f"{BASE}/premium-decisions").json() == []
            assert c.put(f"{BASE}/premium-decisions/{d['id']}/activate").status_code == 404


# ── 30% facility decisions (NL-026) ──────────────────────────────────────────

class TestExpatDecisions:
    def test_recorder_cannot_verify_a_second_person_can(self, db, nlx):
        doc = _document(db, nlx.org.id)
        with http(db, _user(nlx.org.id, 801)) as c:
            d = _record(c, nlx, evidence_artifact_id=doc.id)
            assert d["status"] == "PENDING" and d["recorded_by"] == 801
            r = c.put(f"{BASE}/expat-decisions/{d['id']}/verify")
            assert r.status_code == 400 and "four-eyes" in r.text
        with http(db, _user(nlx.org.id, 802)) as c:
            r = c.put(f"{BASE}/expat-decisions/{d['id']}/verify")
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "VERIFIED" and r.json()["verified_by"] == 802

    def test_verification_needs_the_decision_letter(self, db, nlx):
        with http(db, _user(nlx.org.id, 801)) as c:
            d = _record(c, nlx)
        with http(db, _user(nlx.org.id, 802)) as c:
            r = c.put(f"{BASE}/expat-decisions/{d['id']}/verify")
            assert r.status_code == 400 and "document must be attached" in r.text

    def test_another_organisations_document_is_refused(self, db, nlx):
        other, _ = _other_org(db)
        foreign = _document(db, other.id, title="someone else's letter")
        with http(db, _user(nlx.org.id, 801)) as c:
            r = c.post(f"{BASE}/expat-decisions", json={**EXPAT, "employee_id": nlx.emp.id,
                                                        "evidence_artifact_id": foreign.id})
            assert r.status_code == 400 and "your organisation" in r.text

    def test_a_revoked_decision_can_never_be_verified_again(self, db, nlx):
        doc = _document(db, nlx.org.id)
        with http(db, _user(nlx.org.id, 801)) as c:
            d = _record(c, nlx, evidence_artifact_id=doc.id)
            assert c.put(f"{BASE}/expat-decisions/{d['id']}/revoke").json()["status"] == "REVOKED"
        with http(db, _user(nlx.org.id, 802)) as c:
            r = c.put(f"{BASE}/expat-decisions/{d['id']}/verify")
            assert r.status_code == 400 and "only a PENDING" in r.text

    def test_a_decision_without_a_recorder_fails_closed(self, db, nlx):
        from app.modules.payroll.models import PayrollNlExpatDecision

        doc = _document(db, nlx.org.id)
        legacy = PayrollNlExpatDecision(organization_id=nlx.org.id, employee_id=nlx.emp.id,
                                        decision_reference="BD-LEGACY", decision_date=date(2025, 12, 1),
                                        granted_from=date(2026, 1, 1), method="FACILITY_30PCT",
                                        threshold_category="STANDARD", allowance_pct=D("30"),
                                        evidence_artifact_id=doc.id, status="PENDING")      # no recorded_by
        db.add(legacy)
        db.commit()
        with http(db, _user(nlx.org.id, 802)) as c:
            r = c.put(f"{BASE}/expat-decisions/{legacy.id}/verify")
            assert r.status_code == 400 and "record it again" in r.text

    def test_other_tenant_cannot_see_or_verify(self, db, nlx):
        other, _ = _other_org(db)
        doc = _document(db, nlx.org.id)
        with http(db, _user(nlx.org.id, 801)) as c:
            d = _record(c, nlx, evidence_artifact_id=doc.id)
        with http(db, _user(other.id, 950)) as c:
            assert c.get(f"{BASE}/expat-decisions").json() == []
            assert c.put(f"{BASE}/expat-decisions/{d['id']}/verify").status_code == 404
            assert c.put(f"{BASE}/expat-decisions/{d['id']}/revoke").status_code == 404

    def test_only_a_second_persons_verification_reaches_the_payslip(self, db, nlx):
        """PENDING is never applied; after the second person verifies, the
        next calculation applies the facility."""
        from app.modules.payroll import service
        from app.modules.payroll.models import PayslipItem
        from tests.test_netherlands_service_integration import _run

        doc = _document(db, nlx.org.id)
        with http(db, _user(nlx.org.id, 801)) as c:
            d = _record(c, nlx, evidence_artifact_id=doc.id)
        run = _run(db, nlx.org, 3)
        service.generate_payslips_for_run(db, run, nlx.org.id)
        item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
        assert item.nl_calculation_snapshot["expat"]["applied"] is False      # PENDING: ignored

        with http(db, _user(nlx.org.id, 802)) as c:
            assert c.put(f"{BASE}/expat-decisions/{d['id']}/verify").status_code == 200
        run4 = _run(db, nlx.org, 4)
        service.generate_payslips_for_run(db, run4, nlx.org.id)
        item4 = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run4.id).one()
        assert item4.nl_calculation_snapshot["expat"]["applied"] is True       # verified by a second person


# ── earning-classification overrides & pension schemes ───────────────────────

CLASSIFICATION = {"earning_code": "base_salary", "effective_from": "2026-07-01", "remuneration_type": "REGULAR",
                  "wage_tax": True, "employee_insurance_wage": True, "zvw_wage": True, "pensionable": False,
                  "wkr_treatment": "WAGE", "vacation_allowance_basis": True, "minimum_wage_reckonable": True}
SCHEME = {"fund_name": "Eigen pensioenregeling", "scheme_code": "OWN-1", "effective_from": "2026-01-01",
          "basis_rule": "GROSS_MINUS_FRANCHISE", "employee_pct": "5", "employer_pct": "10"}


class TestCatalogOverrides:
    def test_classification_is_always_the_tenants_own(self, db, nlx):
        with http(db, _user(nlx.org.id, 801)) as c:
            r = c.post(f"{BASE}/earning-classifications", json={**CLASSIFICATION, "organization_id": None})
            assert r.status_code == 200, r.text
            assert r.json()["organization_id"] == nlx.org.id          # never the platform catalog
            owners = {x["organization_id"] for x in c.get(f"{BASE}/earning-classifications").json()}
            assert owners == {None, nlx.org.id}

    def test_pension_scheme_is_the_tenants_own_and_invisible_to_others(self, db, nlx):
        other, _ = _other_org(db)
        with http(db, _user(nlx.org.id, 801)) as c:
            r = c.post(f"{BASE}/pension-schemes", json={**SCHEME, "organization_id": None})
            assert r.status_code == 200, r.text
            assert r.json()["organization_id"] == nlx.org.id
        with http(db, _user(other.id, 950)) as c:
            owners = {x["organization_id"] for x in c.get(f"{BASE}/pension-schemes").json()}
            assert nlx.org.id not in owners

    def test_employee_role_cannot_write(self, db, nlx):
        with http(db, _user(nlx.org.id, 801, role="employee")) as c:
            assert c.post(f"{BASE}/earning-classifications", json=CLASSIFICATION).status_code == 403
            assert c.post(f"{BASE}/expat-decisions", json={**EXPAT, "employee_id": nlx.emp.id}).status_code == 403
