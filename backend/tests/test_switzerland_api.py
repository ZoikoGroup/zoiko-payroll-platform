"""
tests/test_switzerland_api.py
-----------------------------
CH Step 5 — employer schemes, entity profile, earning classification and wage
floors, over HTTP and at the service/ORM layer:

* per-scheme_type `rules` validation (incl. BVG employer share >= 50 %),
  server-side rules_sha256, versioning, DRAFT-only edits, LIVE immutability,
  four-eyes approve / activate, org isolation from the platform catalog;
* the versioned entity profile (new row, previous closed) with readiness
  derived server-side only;
* CH TaxabilityRule: Draft rules never govern, Approved ones do, legacy rows of
  other countries are unaffected, the legacy CRUD cannot write CH;
* CH wage floors on CollectiveAgreement;
* the Idempotency-Key / X-Correlation-ID write helper;
* migration 376bb8637603 (versioned entity profile + idempotency table).

Every scheme rate, UID and wage figure here is SYNTHETIC test data.
"""

import importlib.util
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from tests.test_hong_kong_governance import SA_A, SA_B, _artifact, _http

ORG = "/api/payroll/switzerland"
SA = "/api/super-admin/compliance/switzerland"

COMP_RULES = {"admin_cost_pct": "1.5"}
FAK_RULES = {"employer_pct": "1.2"}
BVG_RULES = {
    "entry_rules": {"min_age": 25}, "insured_salary_def": "annual AHV salary less coordination deduction",
    "coordination": {"mode": "STATUTORY"},
    "bands": [
        {"age_from": 25, "age_to": 34, "employee_pct": "3.5", "employer_pct": "3.5", "component": "MANDATORY"},
        {"age_from": 35, "age_to": 44, "employee_pct": "5", "employer_pct": "6", "component": "MANDATORY"},
        {"age_from": 25, "age_to": 65, "salary_from": "90000", "employee_amount": "100", "employer_amount": "150",
         "component": "EXTRA_MANDATORY"},
    ],
}
UVG_RULES = {"insurer": "Test Insurer", "risk_classes": [
    {"code": "A1", "bu_employer_pct": "0.5", "nbu_pct": "1.2", "nbu_employee_share_pct": "100"}]}
KTG_RULES = {"rate_pct": "1.1", "employee_share_pct": "50", "base_def": "AHV salary"}
RULES = {"COMPENSATION_OFFICE": COMP_RULES, "FAK": FAK_RULES, "BVG_PLAN": BVG_RULES, "UVG_POLICY": UVG_RULES,
         "KTG_POLICY": KTG_RULES}


def _h(key=None, cid=None):
    headers = {"Idempotency-Key": key or uuid.uuid4().hex}
    if cid:
        headers["X-Correlation-ID"] = cid
    return headers


def _scheme_body(scheme_type="FAK", code="FAK-TEST", version="1.0", rules=None, **extra):
    return {"schemeType": scheme_type, "schemeCode": code, "name": f"{scheme_type} test", "version": version,
            "rules": rules if rules is not None else RULES[scheme_type], "effectiveFrom": "2026-01-01", **extra}


@pytest.fixture()
def orgs(db, organization):
    from app.modules.organizations.models import Organization

    other = Organization(organization_name="Other Org", organization_code="OTHERORG")
    db.add(other)
    db.commit()
    return SimpleNamespace(
        a=organization, b=other,
        admin=SimpleNamespace(id=501, organization_id=organization.id, role="org_admin", is_active=True),
        payroll=SimpleNamespace(id=502, organization_id=organization.id, role="payroll_admin", is_active=True),
        third=SimpleNamespace(id=503, organization_id=organization.id, role="org_admin", is_active=True),
        other_admin=SimpleNamespace(id=601, organization_id=other.id, role="org_admin", is_active=True),
    )


def _audit_actions(db, entity_type, entity_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return [(a.action, a.actor_id) for a in db.query(TaxConfigurationAudit).filter(
        TaxConfigurationAudit.entity_type == entity_type, TaxConfigurationAudit.entity_id == entity_id)
        .order_by(TaxConfigurationAudit.id)]


def _live_org_scheme(db, orgs, scheme_type, code=None, **extra):
    """Create (admin) -> approve (payroll) -> activate (admin) over HTTP."""
    with _http(db, orgs.admin) as c:
        sid = c.post(f"{ORG}/schemes", json=_scheme_body(scheme_type, code or f"{scheme_type}-1", **extra),
                     headers=_h()).json()["id"]
    with _http(db, orgs.payroll) as c:
        assert c.post(f"{ORG}/schemes/{sid}/approve", headers=_h()).json()["status"] == "APPROVED"
    with _http(db, orgs.admin) as c:
        assert c.post(f"{ORG}/schemes/{sid}/activate", headers=_h()).json()["status"] == "LIVE"
    return sid


# ── scheme rules validation ─────────────────────────────────────────────

@pytest.mark.parametrize("scheme_type", sorted(RULES))
def test_each_scheme_type_accepts_its_rules_and_hashes_them_server_side(db, orgs, scheme_type):
    import hashlib
    import json

    with _http(db, orgs.admin) as c:
        res = c.post(f"{ORG}/schemes", json=_scheme_body(scheme_type, canton="CH-ZH"), headers=_h())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "DRAFT" and body["organizationId"] == orgs.a.id and body["catalog"] is False
    canonical = json.dumps(body["rules"], sort_keys=True, separators=(",", ":"))
    assert body["rulesSha256"] == hashlib.sha256(canonical.encode()).hexdigest()


@pytest.mark.parametrize("scheme_type, rules, expected", [
    ("COMPENSATION_OFFICE", {"admin_cost_pct": "101"}, "less than or equal to 100"),
    ("COMPENSATION_OFFICE", {"admin_cost_pct": "1", "typo": 1}, "Extra inputs are not permitted"),
    ("FAK", {"employee_pct": "1"}, "employer_pct"),
    ("UVG_POLICY", {"insurer": "X", "risk_classes": []}, "at least 1"),
    ("UVG_POLICY", {"insurer": "X", "risk_classes": [UVG_RULES["risk_classes"][0]] * 2}, "unique"),
    ("KTG_POLICY", {"rate_pct": "1", "employee_share_pct": "50"}, "base_def"),
    ("BVG_PLAN", {**BVG_RULES, "coordination": {"mode": "MAGIC"}}, "coordination.mode"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [{**BVG_RULES["bands"][0], "employer_pct": "3.4"}]},
     "employer share 3.4 is below 50% of the total 6.9"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [{**BVG_RULES["bands"][2], "employer_amount": "99"}]},
     "below 50% of the total"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [{**BVG_RULES["bands"][0], "employer_pct": None, "employer_amount": "9"}]},
     "same basis"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [{**BVG_RULES["bands"][0], "employee_amount": "1"}]},
     "exactly one of employee_pct / employee_amount"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [BVG_RULES["bands"][0], {**BVG_RULES["bands"][0], "age_from": 30}]},
     "overlap"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [{**BVG_RULES["bands"][0], "age_to": 20}]}, "age_to 20 is below"),
    ("BVG_PLAN", {**BVG_RULES, "bands": [{**BVG_RULES["bands"][0], "component": "VOLUNTARY"}]}, "component"),
])
def test_invalid_rules_are_refused_with_the_reason_and_nothing_is_written(db, orgs, scheme_type, rules, expected):
    from app.modules.payroll.models import ChIdempotencyRecord, ChSchemeProfile

    with _http(db, orgs.admin) as c:
        res = c.post(f"{ORG}/schemes", json=_scheme_body(scheme_type, rules=rules), headers=_h())
    assert res.status_code == 400 and expected in res.text, res.text
    assert db.query(ChSchemeProfile).count() == 0 and db.query(ChIdempotencyRecord).count() == 0


def test_client_cannot_send_a_hash_or_status(db, orgs):
    with _http(db, orgs.admin) as c:
        assert c.post(f"{ORG}/schemes", json={**_scheme_body(), "rulesSha256": "0" * 64}, headers=_h()).status_code == 422
        assert c.post(f"{ORG}/schemes", json={**_scheme_body(), "status": "LIVE"}, headers=_h()).status_code == 422


def test_bvg_bands_split_by_salary_range_do_not_overlap(db, orgs):
    bands = [{**BVG_RULES["bands"][0], "salary_to": "50000"}, {**BVG_RULES["bands"][0], "salary_from": "50000.01"}]
    with _http(db, orgs.admin) as c:
        res = c.post(f"{ORG}/schemes", json=_scheme_body("BVG_PLAN", rules={**BVG_RULES, "bands": bands}), headers=_h())
    assert res.status_code == 200, res.text


# ── scheme versioning, editing, immutability, four-eyes ──────────────────

def test_new_version_is_a_new_row_chained_to_the_previous_one(db, orgs):
    with _http(db, orgs.admin) as c:
        v1 = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h()).json()
        v2 = c.post(f"{ORG}/schemes", json=_scheme_body(version="2.0"), headers=_h()).json()
        dup = c.post(f"{ORG}/schemes", json=_scheme_body(version="2.0"), headers=_h())
    assert v2["id"] != v1["id"] and v2["previousVersionId"] == v1["id"]
    assert dup.status_code == 400 and "already exists" in dup.text


def test_only_a_draft_is_editable_and_an_edit_rehashes_the_rules(db, orgs):
    with _http(db, orgs.admin) as c:
        s = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h()).json()
        res = c.put(f"{ORG}/schemes/{s['id']}", json={"rules": {"employer_pct": "2.5"}}, headers=_h())
        assert res.status_code == 200 and res.json()["rulesSha256"] != s["rulesSha256"]
        assert res.json()["rules"] == {"employer_pct": "2.5"}
        bad = c.put(f"{ORG}/schemes/{s['id']}", json={"rules": {"employer_pct": "200"}}, headers=_h())
        assert bad.status_code == 400
        assert c.put(f"{ORG}/schemes/{s['id']}", json={"schemeCode": "X"}, headers=_h()).status_code == 422
    with _http(db, orgs.payroll) as c:
        c.post(f"{ORG}/schemes/{s['id']}/approve", headers=_h())
    with _http(db, orgs.admin) as c:
        res = c.put(f"{ORG}/schemes/{s['id']}", json={"name": "renamed"}, headers=_h())
        assert res.status_code == 400 and "only a DRAFT can be edited" in res.text
        assert c.delete(f"{ORG}/schemes/{s['id']}", headers=_h()).status_code == 400


def test_live_scheme_is_immutable_at_the_orm_layer(db, orgs):
    from app.modules.payroll.models import ChSchemeProfile

    sid = _live_org_scheme(db, orgs, "FAK")
    row = db.get(ChSchemeProfile, sid)
    row.rules = {"employer_pct": "9"}
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()
    row = db.get(ChSchemeProfile, sid)
    db.delete(row)
    with pytest.raises(ValueError, match="only a DRAFT can be deleted"):
        db.flush()
    db.rollback()
    row = db.get(ChSchemeProfile, sid)
    row.status = "RETIRED"                                    # the one permitted change
    db.flush()
    row.status = "LIVE"
    with pytest.raises(ValueError, match="RETIRED and immutable"):
        db.flush()
    db.rollback()


def test_four_eyes_author_and_editors_cannot_approve_approver_cannot_activate(db, orgs):
    with _http(db, orgs.admin) as c:
        sid = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h()).json()["id"]
        res = c.post(f"{ORG}/schemes/{sid}/approve", headers=_h())
        assert res.status_code == 400 and "other than its author or editors" in res.text
    with _http(db, orgs.payroll) as c:                        # payroll edits -> becomes an editor
        assert c.put(f"{ORG}/schemes/{sid}", json={"name": "edited"}, headers=_h()).status_code == 200
        assert c.post(f"{ORG}/schemes/{sid}/approve", headers=_h()).status_code == 400
        assert c.post(f"{ORG}/schemes/{sid}/activate", headers=_h()).status_code == 400   # not approved yet
    with _http(db, orgs.third) as c:
        assert c.post(f"{ORG}/schemes/{sid}/approve", json={"reason": "checked"}, headers=_h()).status_code == 200
        res = c.post(f"{ORG}/schemes/{sid}/activate", headers=_h())
        assert res.status_code == 400 and "other than its approver" in res.text
    with _http(db, orgs.admin) as c:
        assert c.post(f"{ORG}/schemes/{sid}/activate", headers=_h()).json()["status"] == "LIVE"
    assert [a for a, _ in _audit_actions(db, "ch_scheme_profile", sid)] == [
        "create", "update", "approve", "activate"]


def test_activation_retires_the_overlapping_live_version_only(db, orgs):
    from app.modules.payroll.models import ChSchemeProfile

    v1 = _live_org_scheme(db, orgs, "FAK", code="FAK-X")
    other_code = _live_org_scheme(db, orgs, "FAK", code="FAK-Y")
    v2 = _live_org_scheme(db, orgs, "FAK", code="FAK-X", version="2.0")
    assert db.get(ChSchemeProfile, v1).status == "RETIRED"
    assert db.get(ChSchemeProfile, other_code).status == "LIVE" and db.get(ChSchemeProfile, v2).status == "LIVE"
    assert _audit_actions(db, "ch_scheme_profile", v1)[-1][0] == "retire"


def test_delete_only_an_unreferenced_draft(db, orgs):
    from app.modules.payroll.models import ChSchemeProfile

    with _http(db, orgs.admin) as c:
        a = c.post(f"{ORG}/schemes", json=_scheme_body(code="FAK-DEL"), headers=_h()).json()["id"]
        b = c.post(f"{ORG}/schemes", json=_scheme_body(code="FAK-REF"), headers=_h()).json()["id"]
        assert c.put(f"{ORG}/entity-profile", json={"effectiveFrom": "2026-01-01", "fakSchemeId": b},
                     headers=_h()).status_code == 200
        assert c.delete(f"{ORG}/schemes/{a}", headers=_h()).json()["deleted"] is True
        res = c.delete(f"{ORG}/schemes/{b}", headers=_h())
        assert res.status_code == 400 and "referenced" in res.text
    assert db.get(ChSchemeProfile, a) is None
    assert [x for x, _ in _audit_actions(db, "ch_scheme_profile", a)] == ["create", "delete"]


def test_org_isolation_and_catalog_visibility(db, orgs):
    with _http(db, SA_A) as c:
        cat = c.post(f"{SA}/schemes", json=_scheme_body("COMPENSATION_OFFICE", "SVA-TEST"), headers=_h()).json()
    assert cat["catalog"] is True and cat["organizationId"] is None
    with _http(db, orgs.admin) as c:
        mine = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h()).json()
        listed = {s["id"] for s in c.get(f"{ORG}/schemes").json()}
        assert listed == {cat["id"], mine["id"]}
        assert c.get(f"{ORG}/schemes/{cat['id']}").status_code == 200           # catalog is readable
        assert c.post(f"{ORG}/schemes/{cat['id']}/approve", headers=_h()).status_code == 404   # never writable
        assert c.put(f"{ORG}/schemes/{cat['id']}", json={"name": "x"}, headers=_h()).status_code == 404
    with _http(db, orgs.other_admin) as c:
        assert c.get(f"{ORG}/schemes/{mine['id']}").status_code == 404
        assert {s["id"] for s in c.get(f"{ORG}/schemes").json()} == {cat["id"]}
    with _http(db, SA_A) as c:
        assert {s["id"] for s in c.get(f"{SA}/schemes").json()} == {cat["id"]}   # platform sees catalog only
        assert c.post(f"{SA}/schemes/{mine['id']}/approve", headers=_h()).status_code == 404


def test_catalog_four_eyes_between_super_admins(db):
    with _http(db, SA_A) as c:
        sid = c.post(f"{SA}/schemes", json=_scheme_body("KTG_POLICY", "KTG-CAT"), headers=_h()).json()["id"]
        assert c.post(f"{SA}/schemes/{sid}/approve", headers=_h()).status_code == 400
    with _http(db, SA_B) as c:
        assert c.post(f"{SA}/schemes/{sid}/approve", headers=_h()).json()["status"] == "APPROVED"
        assert c.post(f"{SA}/schemes/{sid}/activate", headers=_h()).status_code == 400
    with _http(db, SA_A) as c:
        assert c.post(f"{SA}/schemes/{sid}/activate", headers=_h()).json()["status"] == "LIVE"


def test_routes_are_role_gated(db, orgs):
    employee = SimpleNamespace(id=777, organization_id=orgs.a.id, role="employee", is_active=True)
    with _http(db, employee) as c:
        assert c.get(f"{ORG}/schemes").status_code == 403
        assert c.put(f"{ORG}/entity-profile", json={"effectiveFrom": "2026-01-01"}, headers=_h()).status_code == 403
    with _http(db, orgs.admin) as c:
        assert c.get(f"{SA}/schemes").status_code == 403


# ── entity profile ──────────────────────────────────────────────────────

def _profile(**over):
    return {"uid": "CHE-123.456.789", "seatCanton": "CH-ZH", "effectiveFrom": "2026-01-01",
            "cantonRegistrations": [{"canton": "CH-ZH", "qstDebtorNumber": "TEST-1"}], **over}


def test_readiness_is_derived_server_side_and_never_accepted_from_the_client(db, orgs):
    with _http(db, orgs.admin) as c:
        assert c.put(f"{ORG}/entity-profile", json={**_profile(), "readinessStatus": "LIVE"},
                     headers=_h()).status_code == 422
        res = c.put(f"{ORG}/entity-profile", json=_profile(), headers=_h())
    body = res.json()
    assert res.status_code == 200 and body["readinessStatus"] == "NOT_READY"
    failed = {ch["key"] for ch in body["readinessEvidence"]["checks"] if not ch["passed"]}
    assert failed == {"compensation_office", "fak"}


def test_profile_becomes_ready_only_with_live_schemes_in_force(db, orgs):
    comp = _live_org_scheme(db, orgs, "COMPENSATION_OFFICE")
    with _http(db, orgs.admin) as c:
        draft_fak = c.post(f"{ORG}/schemes", json=_scheme_body(code="FAK-DRAFT"), headers=_h()).json()["id"]
        res = c.put(f"{ORG}/entity-profile", json=_profile(compensationOfficeSchemeId=comp, fakSchemeId=draft_fak),
                    headers=_h()).json()
    assert res["readinessStatus"] == "NOT_READY"
    assert any("DRAFT, not LIVE" in ch["detail"] for ch in res["readinessEvidence"]["checks"])
    fak = _live_org_scheme(db, orgs, "FAK")
    with _http(db, orgs.admin) as c:
        res = c.put(f"{ORG}/entity-profile", json=_profile(effectiveFrom="2026-02-01", compensationOfficeSchemeId=comp,
                                                            fakSchemeId=fak), headers=_h()).json()
        assert res["readinessStatus"] == "READY"
        res = c.put(f"{ORG}/entity-profile", json=_profile(effectiveFrom="2026-03-01", compensationOfficeSchemeId=comp,
                                                            fakSchemeId=fak, cantonRegistrations=[]), headers=_h())
        assert res.json()["readinessStatus"] == "NOT_READY"              # seat canton not registered


def test_new_version_closes_the_previous_one_and_versions_are_never_rewritten(db, orgs):
    from app.modules.payroll.models import ChEntityProfile

    with _http(db, orgs.admin) as c:
        v1 = c.put(f"{ORG}/entity-profile", json=_profile(), headers=_h()).json()
        v2 = c.put(f"{ORG}/entity-profile", json=_profile(effectiveFrom="2026-07-01", seatCanton="CH-BE",
                                                           cantonRegistrations=[{"canton": "CH-BE"}]),
                   headers=_h()).json()
        same_day = c.put(f"{ORG}/entity-profile", json=_profile(effectiveFrom="2026-07-01"), headers=_h())
        earlier = c.put(f"{ORG}/entity-profile", json=_profile(effectiveFrom="2026-03-01"), headers=_h())
        view_jan = c.get(f"{ORG}/entity-profile", params={"on": "2026-03-15"}).json()
        view_aug = c.get(f"{ORG}/entity-profile", params={"on": "2026-08-01"}).json()
    assert v2["previousVersionId"] == v1["id"]
    assert db.get(ChEntityProfile, v1["id"]).effective_to == date(2026, 6, 30)
    assert same_day.status_code == 400 and earlier.status_code == 400 and "never rewritten" in earlier.text
    assert view_jan["current"]["id"] == v1["id"] and view_aug["current"]["id"] == v2["id"]
    assert [v["id"] for v in view_aug["versions"]] == [v1["id"], v2["id"]]
    assert view_aug["readinessNow"]["asOf"] == "2026-08-01"
    assert [a for a, _ in _audit_actions(db, "ch_entity_profile", v1["id"])] == ["create", "close"]
    row = db.get(ChEntityProfile, v1["id"])
    row.uid = "CHE-999.999.999"
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_profile_scheme_assignments_are_type_and_org_checked(db, orgs):
    with _http(db, orgs.other_admin) as c:
        foreign = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h()).json()["id"]
    with _http(db, orgs.admin) as c:
        ktg = c.post(f"{ORG}/schemes", json=_scheme_body("KTG_POLICY", "KTG-1"), headers=_h()).json()["id"]
        res = c.put(f"{ORG}/entity-profile", json=_profile(fakSchemeId=ktg), headers=_h())
        assert res.status_code == 400 and "must be a FAK scheme" in res.text
        assert c.put(f"{ORG}/entity-profile", json=_profile(fakSchemeId=foreign), headers=_h()).status_code == 404
        res = c.put(f"{ORG}/entity-profile", json=_profile(uid="123"), headers=_h())
        assert res.status_code == 400 and "CHE-123.456.789" in res.text
        assert c.put(f"{ORG}/entity-profile", json=_profile(seatCanton="ZH"), headers=_h()).status_code == 422


# ── earning classification (TaxabilityRule) ─────────────────────────────

def _rule_body(**over):
    return {"earningType": "bonus", "taxComponent": "ch_ahv", "isTaxable": True, "treatment": "SUBJECT",
            "effectiveFrom": "2026-01-01", **over}


def test_ch_rule_governs_only_once_approved_by_a_second_super_admin(db):
    from app.modules.payroll.service import get_taxability_classification

    src = _artifact(db, "CH-AHV-WAGE-TEST")
    with _http(db, SA_A) as c:
        no_src = c.post(f"{SA}/taxability-rules", json=_rule_body(earningType="tips"), headers=_h()).json()
        rule = c.post(f"{SA}/taxability-rules", json=_rule_body(sourceDocumentId=src.id), headers=_h()).json()
        assert rule["status"] == "Draft"
        assert get_taxability_classification(db, "CH", "ch_ahv", as_of=date(2026, 6, 1)) == {}
        res = c.post(f"{SA}/taxability-rules/{rule['id']}/approve", headers=_h())
        assert res.status_code == 400 and "other than its author" in res.text
    with _http(db, SA_B) as c:
        res = c.post(f"{SA}/taxability-rules/{no_src['id']}/approve", headers=_h())
        assert res.status_code == 400 and "source document" in res.text
        assert c.post(f"{SA}/taxability-rules/{rule['id']}/approve", headers=_h()).json()["status"] == "Approved"
    assert get_taxability_classification(db, "CH", "ch_ahv", as_of=date(2026, 6, 1)) == {"bonus": True}


def test_replacement_closes_the_previous_rule_and_history_still_replays(db):
    from app.modules.payroll.models import TaxabilityRule
    from app.modules.payroll.service import get_taxability_classification

    src = _artifact(db, "CH-AHV-WAGE-TEST")

    def approved(**over):
        with _http(db, SA_A) as c:
            rid = c.post(f"{SA}/taxability-rules", json=_rule_body(sourceDocumentId=src.id, **over),
                         headers=_h()).json()["id"]
        with _http(db, SA_B) as c:
            return c.post(f"{SA}/taxability-rules/{rid}/approve", headers=_h())

    first = approved().json()
    second = approved(isTaxable=False, effectiveFrom="2026-07-01").json()
    assert db.get(TaxabilityRule, first["id"]).effective_to == date(2026, 6, 30)
    assert get_taxability_classification(db, "CH", "ch_ahv", as_of=date(2026, 3, 1)) == {"bonus": True}
    assert get_taxability_classification(db, "CH", "ch_ahv", as_of=date(2026, 8, 1)) == {"bonus": False}
    backdated = approved(effectiveFrom="2026-05-01")
    assert backdated.status_code == 400 and f"approved rule {second['id']}" in backdated.text


def test_other_countries_legacy_rows_are_unaffected_and_legacy_crud_cannot_write_ch(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxabilityRule

    service.upsert_taxability_rule(db, "IN", "code_wages", "basic", True)
    assert db.query(TaxabilityRule).filter(TaxabilityRule.jurisdiction_country == "IN").one().status is None
    assert service.get_taxability_classification(db, "IN", "code_wages") == {"basic": True}
    with pytest.raises(BadRequestException, match="governed"):
        service.upsert_taxability_rule(db, "CH", "ch_ahv", "bonus", True)
    db.add(TaxabilityRule(jurisdiction_country="CH", earning_type="x", tax_component="ch_ahv", is_taxable=True))
    db.commit()                                                 # a stray ungoverned CH row ...
    assert service.get_taxability_classification(db, "CH", "ch_ahv") == {}     # ... never governs
    with pytest.raises(BadRequestException, match="governed"):
        service.delete_taxability_rule(db, db.query(TaxabilityRule).filter(
            TaxabilityRule.jurisdiction_country == "CH").one().id)


def test_unknown_ch_component_and_bad_canton_are_refused(db):
    with _http(db, SA_A) as c:
        res = c.post(f"{SA}/taxability-rules", json=_rule_body(taxComponent="federal_income_tax"), headers=_h())
        assert res.status_code == 400 and "ch_qst" in res.text
        assert c.post(f"{SA}/taxability-rules", json=_rule_body(jurisdictionState="ZH"),
                      headers=_h()).status_code == 422


# ── wage floors ─────────────────────────────────────────────────────────

def _floor(**over):
    return {"agreementType": "CH_CANTON_MINIMUM", "agreementCode": "CH-GE-MIN", "name": "Test canton minimum",
            "jurisdictionState": "CH-GE", "effectiveFrom": "2026-01-01",
            "wageFloor": {"basis": "HOURLY", "amount": "20.00"}, **over}


def test_wage_floor_shape_and_lifecycle(db):
    from app.modules.payroll.models import CollectiveAgreement

    src = _artifact(db, "CH-GE-MIN-WAGE-TEST")
    with _http(db, SA_A) as c:
        assert c.post(f"{SA}/wage-floors", json=_floor(jurisdictionState=None), headers=_h()).status_code == 422
        assert c.post(f"{SA}/wage-floors", json=_floor(agreementType="SECTOR"), headers=_h()).status_code == 422
        assert c.post(f"{SA}/wage-floors", json=_floor(wageFloor={"basis": "HOURLY"}), headers=_h()).status_code == 422
        v1 = c.post(f"{SA}/wage-floors", json=_floor(sourceDocumentId=src.id), headers=_h()).json()
        gav = c.post(f"{SA}/wage-floors", json=_floor(
            agreementType="CH_GAV", agreementCode="CH-GAV-TEST", jurisdictionState=None,
            wageFloor={"basis": "MONTHLY", "scales": [{"occupation": "cook", "grade": "I", "amount": "4000"}]}),
            headers=_h())
        assert gav.status_code == 200 and gav.json()["wageFloor"]["scales"][0]["amount"] == "4000"
        assert c.post(f"{SA}/wage-floors/{v1['id']}/approve", headers=_h()).status_code == 400
    row = db.get(CollectiveAgreement, v1["id"])
    assert row.jurisdiction_country == "CH" and row.jurisdiction_state == "CH-GE" and row.organization_id is None
    assert row.modules == {"wage_floor": {"basis": "HOURLY", "amount": "20.00", "scales": []}}
    with _http(db, SA_B) as c:
        assert c.post(f"{SA}/wage-floors/{v1['id']}/approve", headers=_h()).json()["status"] == "Approved"
        assert c.post(f"{SA}/wage-floors/{v1['id']}/activate", headers=_h()).status_code == 400
    with _http(db, SA_A) as c:
        assert c.post(f"{SA}/wage-floors/{v1['id']}/activate", headers=_h()).json()["status"] == "Active"
        v2 = c.post(f"{SA}/wage-floors", json=_floor(version="2.0", sourceDocumentId=src.id), headers=_h()).json()
    assert v2["previousVersionId"] == v1["id"]
    with _http(db, SA_B) as c:
        c.post(f"{SA}/wage-floors/{v2['id']}/approve", headers=_h())
    with _http(db, SA_A) as c:
        assert c.post(f"{SA}/wage-floors/{v2['id']}/activate", headers=_h()).status_code == 200
        assert [f["id"] for f in c.get(f"{SA}/wage-floors", params={"canton": "CH-GE", "status": "Active"}).json()] \
            == [v2["id"]]
    assert db.get(CollectiveAgreement, v1["id"]).status == "Superseded"


def test_generic_cba_routes_cannot_write_ch(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    data = SimpleNamespace(jurisdictionCountry="CH", agreementType="SECTOR", modules=[], effectiveFrom=None,
                           effectiveTo=None, id=None)
    with pytest.raises(BadRequestException, match="governed"):
        service.upsert_collective_agreement(db, data, actor_id=SA_A.id)
    with _http(db, SA_A) as c:
        fid = c.post(f"{SA}/wage-floors", json=_floor(), headers=_h()).json()["id"]
    with pytest.raises(BadRequestException, match="governed"):
        service.set_collective_agreement_status(db, fid, "In Review", actor_id=SA_A.id)


# ── Idempotency-Key / X-Correlation-ID helper ───────────────────────────

def test_idempotency_key_is_required_and_nothing_is_written_without_it(db, orgs):
    from app.modules.payroll.models import ChSchemeProfile

    with _http(db, orgs.admin) as c:
        res = c.post(f"{ORG}/schemes", json=_scheme_body())
    assert res.status_code == 400 and "Idempotency-Key" in res.text
    assert db.query(ChSchemeProfile).count() == 0


def test_same_key_same_body_replays_without_writing_twice(db, orgs):
    from app.modules.payroll.models import ChSchemeProfile

    with _http(db, orgs.admin) as c:
        first = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h("k-1", "corr-1"))
        again = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h("k-1", "corr-2"))
        other = c.post(f"{ORG}/schemes", json=_scheme_body(code="FAK-OTHER"), headers=_h("k-1"))
    assert first.headers["Idempotent-Replayed"] == "false" and first.headers["X-Correlation-ID"] == "corr-1"
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    assert other.status_code == 409 and "different request" in other.text
    assert db.query(ChSchemeProfile).count() == 1


def test_key_cannot_be_replayed_against_another_target(db, orgs):
    with _http(db, orgs.admin) as c:
        a = c.post(f"{ORG}/schemes", json=_scheme_body(code="A"), headers=_h()).json()["id"]
        b = c.post(f"{ORG}/schemes", json=_scheme_body(code="B"), headers=_h()).json()["id"]
    with _http(db, orgs.payroll) as c:
        assert c.post(f"{ORG}/schemes/{a}/approve", headers=_h("approve-1")).status_code == 200
        assert c.post(f"{ORG}/schemes/{b}/approve", headers=_h("approve-1")).status_code == 409


def test_keys_are_scoped_per_organization_and_failed_writes_do_not_consume_them(db, orgs):
    from app.modules.payroll.models import ChSchemeProfile

    with _http(db, orgs.admin) as c:
        bad = c.post(f"{ORG}/schemes", json=_scheme_body(rules={"employer_pct": "500"}), headers=_h("shared"))
        assert bad.status_code == 400
        assert c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h("shared")).status_code == 200
    with _http(db, orgs.other_admin) as c:
        res = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h("shared"))
        assert res.status_code == 200 and res.headers["Idempotent-Replayed"] == "false"
    assert db.query(ChSchemeProfile).count() == 2


def test_correlation_id_reaches_the_audit_trail_and_is_generated_when_absent(db, orgs):
    from app.modules.payroll.models import TaxConfigurationAudit

    with _http(db, orgs.admin) as c:
        res = c.post(f"{ORG}/schemes", json=_scheme_body(), headers=_h(cid="trace-abc"))
        gen = c.post(f"{ORG}/schemes", json=_scheme_body(code="FAK-2"), headers=_h())
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "ch_scheme_profile",
                                                   TaxConfigurationAudit.entity_id == res.json()["id"]).one()
    assert audit.new_value["correlationId"] == "trace-abc" and audit.actor_id == orgs.admin.id
    assert len(gen.headers["X-Correlation-ID"]) == 32


# ── migration 376bb8637603 ──────────────────────────────────────────────

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load(filename):
    spec = importlib.util.spec_from_file_location(f"mig_{filename[:12]}", _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrate(steps):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.test_switzerland_schema_contract import ALTERED_TABLES

    base = _load("3baddbaa011a_add_switzerland_jurisdiction_support.py")
    step5 = _load("376bb8637603_ch_versioned_entity_profile_and_idempotency.py")
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.begin()
        for statement in ALTERED_TABLES:
            conn.execute(sa.text(statement))
        ops = Operations(MigrationContext.configure(conn))
        for module, step in [(base, "upgrade")] + [(step5, s) for s in steps]:
            saved, module.op = module.op, ops
            try:
                getattr(module, step)()
            finally:
                module.op = saved
        insp = sa.inspect(conn)
        uniques = {tuple(i["column_names"]) for i in insp.get_indexes("payroll_ch_entity_profiles") if i["unique"]}
        tables = set(insp.get_table_names())
        idem_cols = ({c["name"] for c in insp.get_columns("payroll_ch_idempotency_records")}
                     if "payroll_ch_idempotency_records" in tables else set())
    return uniques, tables, idem_cols


def test_migration_makes_entity_profile_versioned_and_adds_idempotency_table():
    from app.modules.payroll.models import ChIdempotencyRecord

    uniques, tables, idem_cols = _migrate(["upgrade"])
    assert uniques == {("organization_id", "effective_from")}
    assert idem_cols == set(ChIdempotencyRecord.__table__.columns.keys())
    assert _migrate(["upgrade", "upgrade"])[0] == uniques                     # idempotent
    down_uniques, down_tables, _ = _migrate(["upgrade", "downgrade"])
    assert down_uniques == {("organization_id",)} and "payroll_ch_idempotency_records" not in down_tables


def test_migration_is_the_single_head_on_top_of_switzerland_support():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(_VERSIONS.parent.parent / "alembic.ini")))
    assert script.get_revision("376bb8637603").down_revision == "3baddbaa011a"
    # Single head, with 376bb8637603 on its chain (later migrations, e.g. the
    # c5981cbcbe13 attendance gate, may sit on top of it).
    heads = list(script.get_heads())
    assert len(heads) == 1
    assert "376bb8637603" in {rev.revision for rev in script.walk_revisions("base", heads[0])}
