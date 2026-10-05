"""
tests/test_hong_kong_governance.py
----------------------------------
Final jurisdiction completion program — Hong Kong Super Admin governance:

* W1 the governed HK registry transition (PLANNED ↔ AVAILABLE): HTTP no-auth /
  wrong role / refused-with-audit / allowed only with every requirement met /
  suspension always allowed;
* W2 HK template activation needs reviewed source evidence and an activator
  other than the approver; other countries are unaffected;
* W3 HK template comparison; W4 summary readiness + coverage;
* W5 XML adversarial vectors; W6 historical replay is unaffected by a later
  pack change.
Users 9 / 101 / 202 exist in the PostgreSQL harness (foreign keys).
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _profile  # noqa: F401

SA_A = SimpleNamespace(id=101, organization_id=None, role="super_admin", is_active=True)
SA_B = SimpleNamespace(id=202, organization_id=None, role="super_admin", is_active=True)


@contextmanager
def _http(db, principal):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription

    saved = dict(app.dependency_overrides)
    overrides = {get_db: lambda: db, require_active_subscription: lambda: None}
    if principal is not None:
        overrides.update({get_current_user: lambda: principal, get_current_org_scoped_principal: lambda: principal})
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _registry(db, availability="PLANNED"):
    from app.modules.billing.models import JurisdictionServiceRegistry

    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "HK").first()
    if row is None:                                  # the HK seed normally creates it (PLANNED)
        row = JurisdictionServiceRegistry(country="HK", availability=availability)
        db.add(row)
    assert row.availability == availability
    db.commit()
    return row


def _artifact(db, form_number, uploader=101, reviewer=202, file_path="evidence.pdf"):
    from app.modules.payroll.models import SourceArtifact

    a = SourceArtifact(agency="Zoiko test", title=f"TEST evidence {form_number}", form_number=form_number,
                       checksum_sha256="0" * 64, file_path=file_path, created_by_id=uploader, reviewer_id=reviewer)
    db.add(a)
    db.commit()
    return a


def _all_gates(db):
    for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        _artifact(db, f"HK-GATE-{g}")                     # TEST-ONLY evidence rows (never production evidence)


def _activate_all_templates(db):
    """TEST-ONLY: every seeded HK template Active with reviewed source evidence."""
    from app.modules.payroll.models import ReportTemplate
    from scripts.seed_statutory_report_templates import seed_hong_kong

    seed_hong_kong(db)
    src = _artifact(db, "HK-TEMPLATE-SOURCE-TEST")
    for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "HK"):
        t.status, t.source_document_id = "Active", src.id
        t.approved_by_id, t.updated_by_id = 202, 101                 # independent approval (approver != last editor)
    db.commit()


# ── W1 registry ─────────────────────────────────────────────────────────

def test_registry_route_refuses_no_auth_and_non_super_admin(db, hk):
    _registry(db)
    body = {"availability": "AVAILABLE", "reason": "launch"}
    with _http(db, None) as c:
        assert c.post("/api/super-admin/compliance/hong-kong/service-registry", json=body).status_code in (401, 403)
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, operator) as c:
        assert c.post("/api/super-admin/compliance/hong-kong/service-registry", json=body).status_code == 403
    with _http(db, SA_A) as c:                                   # extra fields are refused (mass assignment)
        assert c.post("/api/super-admin/compliance/hong-kong/service-registry",
                      json={**body, "country": "SG"}).status_code == 422


def test_available_is_refused_over_http_while_gates_are_missing_and_the_refusal_is_audited(db, hk):
    from app.modules.payroll.models import TaxConfigurationAudit

    row = _registry(db)
    with _http(db, SA_A) as c:
        res = c.post("/api/super-admin/compliance/hong-kong/service-registry",
                     json={"availability": "AVAILABLE", "reason": "launch"})
    assert res.status_code == 400 and "cannot be made AVAILABLE" in res.text and "G1 evidence" in res.text
    db.refresh(row)
    assert row.availability == "PLANNED"
    refusal = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_service_registry",
                                                      TaxConfigurationAudit.action == "refused").one())
    assert refusal.actor_id == SA_A.id and "GATE_G1" in refusal.new_value["unmet"]


def test_available_only_when_every_requirement_is_met_then_suspension_is_always_allowed(db, hk):
    from app.modules.payroll import hk_governance
    from app.modules.payroll.models import TaxConfigurationAudit

    row = _registry(db)
    on = date(2026, 1, 15)                                       # YA 2025/26 + calendar 2026: the seeded template years
    _all_gates(db)
    readiness = hk_governance.activation_readiness(db, on)
    assert not readiness["canOpen"] and any(r["key"].startswith("TEMPLATE_") and not r["met"]
                                            for r in readiness["requirements"])
    _activate_all_templates(db)
    readiness = hk_governance.activation_readiness(db, on)
    assert not readiness["canOpen"] and [r["key"] for r in readiness["requirements"] if not r["met"]] == [
        "PRODUCTION_VERIFICATION"]                                     # production evidence is mandatory too
    _artifact(db, "HK-PRODUCTION-VERIFICATION")                        # TEST-ONLY evidence row
    readiness = hk_governance.activation_readiness(db, on)
    assert readiness["canOpen"], [r for r in readiness["requirements"] if not r["met"]]
    with pytest.raises(Exception, match="reason"):
        hk_governance.transition_hk_service_registry(db, "AVAILABLE", "", actor_id=SA_A.id, as_of=on)
    hk_governance.transition_hk_service_registry(db, "AVAILABLE", "owner launch decision (test)", actor_id=SA_A.id, as_of=on)
    db.refresh(row)
    assert row.availability == "AVAILABLE"
    with pytest.raises(Exception, match="already AVAILABLE"):
        hk_governance.transition_hk_service_registry(db, "AVAILABLE", "again", actor_id=SA_A.id, as_of=on)
    hk_governance.transition_hk_service_registry(db, "PLANNED", "emergency suspension (test)", actor_id=SA_B.id)
    db.refresh(row)
    assert row.availability == "PLANNED"
    hk_governance.transition_hk_service_registry(db, "AVAILABLE", "re-open after incident (test)", actor_id=SA_A.id, as_of=on)
    db.refresh(row)
    assert row.availability == "AVAILABLE"                              # re-open re-checks every requirement
    hk_governance.transition_hk_service_registry(db, "PLANNED", "close again (test)", actor_id=SA_A.id)
    changes = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_service_registry",
                                                      TaxConfigurationAudit.action == "status_change")
               .order_by(TaxConfigurationAudit.id).all())
    assert [c.new_value["availability"] for c in changes] == ["AVAILABLE", "PLANNED", "AVAILABLE", "PLANNED"]
    assert changes[0].new_value["evidence"]["GATE_G7"] == "PASS"            # the evidence snapshot it rested on


def test_registry_refuses_unknown_targets_and_unidentified_actors(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_governance

    _registry(db)
    with pytest.raises(BadRequestException, match="identified Super Admin"):
        hk_governance.transition_hk_service_registry(db, "AVAILABLE", "x", actor_id=None)
    for target in ("ACTIVE", "LIMITED_AVAILABILITY", ""):
        with pytest.raises(BadRequestException, match="can only be"):
            hk_governance.transition_hk_service_registry(db, target, "x", actor_id=SA_A.id)


# ── W2 template activation evidence ────────────────────────────────────

def _released_template(db, report_type="HK_IR56B"):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate
    from scripts.seed_statutory_report_templates import seed_hong_kong

    seed_hong_kong(db)
    t = db.query(ReportTemplate).filter(ReportTemplate.report_type == report_type).one()
    service.set_report_template_approver(db, t.id, actor_id=SA_B.id)              # approver B
    service.set_report_template_status(db, t.id, "Published", actor_id=SA_A.id)   # publisher A
    return t


def test_hk_template_activation_needs_reviewed_source_evidence_and_a_distinct_activator(db, hk):
    from app.modules.payroll.models import TaxConfigurationAudit

    t = _released_template(db)
    url = f"/api/super-admin/report-templates/{t.id}/status"
    with _http(db, SA_A) as c:
        res = c.put(url, json={"status": "Active"})
        assert res.status_code == 400 and "no source evidence" in res.text
        unreviewed = _artifact(db, "HK-TEMPLATE-SOURCE:HK_IR56B:2025/26", reviewer=None)
        t.source_document_id = unreviewed.id
        db.commit()
        assert "not been reviewed" in c.put(url, json={"status": "Active"}).text
        self_reviewed = _artifact(db, "HK-TEMPLATE-SOURCE:HK_IR56B:2025/26", uploader=202, reviewer=202)
        t.source_document_id = self_reviewed.id
        db.commit()
        assert "not been reviewed" in c.put(url, json={"status": "Active"}).text
        good = _artifact(db, "HK-TEMPLATE-SOURCE:HK_IR56B:2025/26", uploader=101, reviewer=202)
        t.source_document_id = good.id
        db.commit()
    with _http(db, SA_B) as c:                                       # B approved it: B may not activate it
        assert "other than its approver" in c.put(url, json={"status": "Active"}).text
    with _http(db, SA_A) as c:
        res = c.put(url, json={"status": "Active"})
        assert res.status_code == 200 and res.json()["status"] == "Active"
    refusals = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "report_template",
                                                      TaxConfigurationAudit.action == "refused").count()
    assert refusals == 4                                             # every refused activation is audited


def test_the_hk_template_gate_does_not_affect_another_country(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key="XX-TEST", name="x", report_type="XX_TEST", jurisdiction_country="IN",
                       reporting_year="2026-27", version="1.0", status="Draft", document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    service.set_report_template_approver(db, t.id, actor_id=SA_B.id)
    service.set_report_template_status(db, t.id, "Published", actor_id=SA_A.id)
    assert service.set_report_template_status(db, t.id, "Active", actor_id=SA_B.id).status == "Active"   # unchanged rules


# ── W3 compare / W4 summary ────────────────────────────────────────────

def test_hk_template_compare_over_http(db, hk):
    from app.modules.payroll.models import ReportTemplate
    from scripts.seed_statutory_report_templates import seed_hong_kong

    seed_hong_kong(db)
    ir56b = db.query(ReportTemplate).filter(ReportTemplate.report_type == "HK_IR56B").one()
    ir56e = db.query(ReportTemplate).filter(ReportTemplate.report_type == "HK_IR56E").one()
    url = "/api/super-admin/compliance/hong-kong/report-templates/compare"
    with _http(db, SA_A) as c:
        same = c.get(url, params={"from": ir56b.id, "to": ir56b.id}).json()
        assert same["identical"] is True and same["added"] == same["removed"] == []
        diff = c.get(url, params={"from": ir56b.id, "to": ir56e.id}).json()
        assert diff["sameReportType"] is False and "remuneration.ird_salary_wages" in diff["removed"]
        assert diff["metadata"]["report_type"] == {"from": "HK_IR56B", "to": "HK_IR56E"}
        other = ReportTemplate(template_key="IN-X", name="x", report_type="X", jurisdiction_country="IN",
                               reporting_year="2026-27", version="1.0", status="Draft", document_scope="AGGREGATE")
        db.add(other)
        db.commit()
        assert c.get(url, params={"from": ir56b.id, "to": other.id}).status_code == 400
        assert c.get(url, params={"from": ir56b.id, "to": 999999}).status_code == 404
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, operator) as c:
        assert c.get(url, params={"from": ir56b.id, "to": ir56e.id}).status_code == 403


def test_summary_shows_activation_readiness_and_template_coverage(db, hk):
    from scripts.seed_statutory_report_templates import seed_hong_kong

    _registry(db)
    seed_hong_kong(db)
    with _http(db, SA_A) as c:
        s = c.get("/api/super-admin/compliance/hong-kong/statutory-summary").json()
    readiness = s["activationReadiness"]
    assert readiness["canOpen"] is False and readiness["total"] == 7 + 1 + 2 + 8
    assert {r["key"] for r in readiness["requirements"]} >= {"GATE_G1", "GATE_G7", "ACTIVE_PACK", "GOLDEN", "TEMPLATE_HK_IR56B"}
    cov = s["templateCoverage"]
    assert len(cov) == 16 and {c["period"] for c in cov} == {"current", "next"}
    assert all(c["state"] in ("ACTIVE", "DRAFT", "MISSING") for c in cov)


# ── W5 XML adversarial vectors ─────────────────────────────────────────

def test_xml_adversarial_vectors_are_refused_without_crashing(tmp_path, monkeypatch):
    from app.modules.payroll import hk_ird_schema

    xsd = tmp_path / "t.xsd"            # SYNTHETIC test-only schema — not an IRD schema
    xsd.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="R" type="xs:string"/></xs:schema>')
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    doctype = ["a DOCTYPE / entity declaration is not accepted in an IRD submission"]
    vectors = {
        "parameter entity": b'<?xml version="1.0"?><!DOCTYPE R [<!ENTITY % p "x"> %p;]><R>x</R>',
        "local file entity": f'<?xml version="1.0"?><!DOCTYPE R [<!ENTITY f SYSTEM "{secret.as_uri()}">]><R>&f;</R>'.encode(),
        "network entity": b'<?xml version="1.0"?><!DOCTYPE R [<!ENTITY n SYSTEM "http://example.invalid/x">]><R>&n;</R>',
        "nested entities": b'<?xml version="1.0"?><!DOCTYPE R [<!ENTITY a "1"><!ENTITY b "&a;&a;">]><R>&b;</R>',
    }
    for name, payload in vectors.items():
        errors = hk_ird_schema.validate(payload, str(xsd))
        assert errors and not any("TOP-SECRET" in e for e in errors), name
        assert errors == doctype or errors[0].startswith("not well-formed"), (name, errors)
    assert hk_ird_schema.validate(b"<R><unclosed></R>", str(xsd))[0].startswith("not well-formed")       # malformed
    deep = b"<R>" + b"<a>" * 5000 + b"</a>" * 5000 + b"</R>"
    assert hk_ird_schema.validate(deep, str(xsd))                                                     # deeply nested: errors, no crash
    bad_encoding = b'<?xml version="1.0" encoding="UTF-8"?><R>\xff\xfe\xfa</R>'
    assert hk_ird_schema.validate(bad_encoding, str(xsd))[0].startswith("not well-formed")         # invalid encoding
    monkeypatch.setattr(hk_ird_schema, "MAX_XML_BYTES", 64)
    assert "limit" in hk_ird_schema.validate(b"<R>" + b"x" * 100 + b"</R>", str(xsd))[0]           # oversized


# ── W6 historical replay ───────────────────────────────────────────────

def test_a_later_pack_change_never_changes_a_replay_of_an_earlier_period(db, hk):
    from app.modules.payroll.models import ContributionRate

    emp = _employee(db, hk.org.id, "HKREPLAY", date_of_joining=date(2024, 1, 2))
    _profile(db, emp, hk.org.id, "2024-01-02")
    first = _item(db, _month(db, hk.org, 5, year=2025), emp)
    before = (str(first.employee_pension), str(first.employer_pension), str(first.net_pay), first.tax_policy_pack_id)
    rate = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == hk.packs[1].id,
                                              ContributionRate.component_key == "mpf_employee_rate").one())
    rate.employee_rate_pct = D("0.0600")                                 # TEST-ONLY change to the LATER (2026/27) pack
    db.commit()
    replay = _item(db, _month(db, hk.org, 5, year=2025), emp)            # a second run of May 2025
    after = (str(replay.employee_pension), str(replay.employer_pension), str(replay.net_pay), replay.tax_policy_pack_id)
    assert after == before and before[3] == hk.packs[0].id               # pinned to the 2025/26 pack, unchanged
    later = _item(db, _month(db, hk.org, 5, year=2026), emp)
    assert D(str(later.employee_pension)) > D(before[0])                 # the change is real for its own period


# ── certification-readiness program ────────────────────────────────────

def test_readiness_refuses_an_active_template_without_an_independent_approval(db, hk):
    from app.modules.payroll import hk_governance
    from app.modules.payroll.models import ReportTemplate

    _all_gates(db)
    _artifact(db, "HK-PRODUCTION-VERIFICATION")
    _activate_all_templates(db)
    t = db.query(ReportTemplate).filter(ReportTemplate.report_type == "HK_IR56B").one()
    t.approved_by_id = t.updated_by_id = 101                           # status set outside the governed path, self-approved
    db.commit()
    readiness = hk_governance.activation_readiness(db, date(2026, 1, 15))
    req = next(r for r in readiness["requirements"] if r["key"] == "TEMPLATE_HK_IR56B")
    assert readiness["canOpen"] is False and req["met"] is False and req["detail"] == "independent approval missing"


def test_owner_decisions_and_external_dependencies_are_visible_and_need_reviewed_evidence(db, hk):
    from app.modules.payroll import hk_governance

    decisions = {d["key"]: d for d in hk_governance.owner_decisions(db)}
    assert len(decisions) == 14 and all(d["state"] == "OPEN" for d in decisions.values())
    assert decisions["D-1"]["blocksLaunch"] and not decisions["D-12"]["blocksLaunch"]
    _artifact(db, "HK-DECISION-D-1", uploader=101, reviewer=101)        # self-reviewed: not recorded
    assert {d["key"]: d for d in hk_governance.owner_decisions(db)}["D-1"]["state"] == "SUBMITTED"
    _artifact(db, "HK-DECISION-D-1", uploader=101, reviewer=202)
    assert {d["key"]: d for d in hk_governance.owner_decisions(db)}["D-1"]["state"] == "RECORDED"
    deps = hk_governance.external_dependencies(db)
    assert [d["key"] for d in deps] == [f"X-{i}" for i in range(1, 11)]
    assert all(d["gateState"] == "EVIDENCE_REQUIRED" for d in deps)
    with _http(db, SA_A) as c:
        s = c.get("/api/super-admin/compliance/hong-kong/statutory-summary").json()
    assert len(s["ownerDecisions"]) == 14 and len(s["externalDependencies"]) == 10


def test_template_content_hash_is_stable_and_changes_with_content(db):
    from app.modules.payroll import hk_governance
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponentField
    from scripts.seed_statutory_report_templates import seed_hong_kong

    seed_hong_kong(db)
    t = db.query(ReportTemplate).filter(ReportTemplate.report_type == "HK_IR56B").one()
    h1 = hk_governance.template_content_hash(db, t)
    assert h1 == hk_governance.template_content_hash(db, t) and len(h1) == 64
    f = db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.field_key == "ird_salary_wages").first()
    f.label = "changed"
    db.commit()
    assert hk_governance.template_content_hash(db, t) != h1
    cmp = hk_governance.compare_report_templates(db, t.id, t.id)
    assert cmp["from"]["contentHash"] == cmp["to"]["contentHash"]


def test_shared_super_admin_mutation_routes_used_by_hk_governance_are_role_gated_over_http(db, hk):
    from app.modules.payroll.models import ReportTemplate
    from scripts.seed_statutory_report_templates import seed_hong_kong

    seed_hong_kong(db)
    t = db.query(ReportTemplate).filter(ReportTemplate.report_type == "HK_IR56B").one()
    pack = hk.packs[1]
    a = _artifact(db, "HK-GATE-G4", uploader=101, reviewer=None)
    routes = [("PUT", f"/api/super-admin/compliance/policies/{pack.id}/approve", None),
              ("PUT", f"/api/super-admin/compliance/policies/{pack.id}/status", {"status": "Retired"}),
              ("PUT", f"/api/super-admin/report-templates/{t.id}/approve", None),
              ("PUT", f"/api/super-admin/report-templates/{t.id}/status", {"status": "Active"}),
              ("POST", "/api/super-admin/compliance/source-artifacts", {"agency": "x", "title": "x"}),
              ("PUT", f"/api/super-admin/compliance/source-artifacts/{a.id}/review", None),
              ("POST", "/api/super-admin/compliance/hong-kong/service-registry", {"availability": "AVAILABLE", "reason": "x"})]
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    for who, expected in ((None, (401, 403)), (operator, (403,))):
        with _http(db, who) as c:
            for method, url, body in routes:
                assert c.request(method, url, json=body or {}).status_code in expected, (who, url)
    with _http(db, SA_B) as c:                                          # right role: authorized (business rules may refuse)
        statuses = {url: c.request(method, url, json=body or {}).status_code for method, url, body in routes}
    assert all(code not in (401, 403) for code in statuses.values()), statuses
    assert statuses[f"/api/super-admin/compliance/source-artifacts/{a.id}/review"] == 200     # reviewer != uploader


def test_every_hk_route_authorizes_the_right_role(db, hk):
    """The positive half of the 49-route sweep: the right principal is never refused
    by authorization (404 / 400 / 422 from business validation is fine)."""
    import re

    from app.main import app

    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    routes = sorted((m, r.path) for r in app.routes if hasattr(r, "methods") and "hong-kong" in r.path
                    for m in r.methods - {"HEAD", "OPTIONS"})
    refused = []
    for principal, prefix in ((operator, "/api/payroll/"), (SA_A, "/api/super-admin/")):
        with _http(db, principal) as c:
            for m, p in routes:
                if p.startswith(prefix):
                    res = c.request(m, re.sub(r"\{[^}]+\}", "1", p), json={})
                    if res.status_code in (401, 403):
                        refused.append((m, p, res.status_code))
    assert len(routes) == 65 and refused == []


def test_a_future_year_cannot_activate_without_vectors_and_never_reaches_current_payroll(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    _all_gates(db)                                                     # even with every gate PASS
    future = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId="HK-PAYROLL-2027", jurisdictionCountry="HK", packType="tax", version="1.0", status="Draft",
        effectiveFrom=date(2027, 4, 1), effectiveTo=date(2028, 3, 31)), actor_id=101)
    assert future.status == "Draft"
    service.set_jurisdiction_pack_approver(db, future.id, actor_id=202)
    with pytest.raises(BadRequestException):                           # no golden vector in its window -> refused
        service.set_jurisdiction_pack_status(db, future.id, "Active", actor_id=101)
    db.rollback()
    assert db.get(JurisdictionPack, future.id).status != "Active"
    item = _item(db, _month(db, hk.org, 5, year=2026), hk.emp)          # current payroll: the 2026/27 pack, untouched
    assert item.tax_policy_pack_id == hk.packs[1].id
