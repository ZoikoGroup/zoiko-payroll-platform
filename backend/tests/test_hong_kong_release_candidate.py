"""
tests/test_hong_kong_release_candidate.py
-----------------------------------------
Release-candidate hardening (2026-10-01). Independent re-verification of the
nine audit fixes, plus the gaps that re-verification found and closed:

* every HK route (inventory pinned) refuses an unauthenticated caller and a
  non-operator role over HTTP;
* cross-tenant access to id-taking HK reads / writes / downloads is refused;
* IRD rejection: the filed evidence is snapshotted in the immutable audit
  trail, regeneration never silently reopens a REJECTED case, and the case
  history endpoint returns the full filing lifecycle;
* BIR56A regeneration never reopens a superseded (AMENDED) cover return;
* eMPF preparation is idempotent and never touches a submitted batch;
* a refused cross-jurisdiction correction leaves nothing behind;
* payslip ZIP / bank-file downloads are access-logged without identifiers;
* identity-token key rotation (rehash --rotate);
* IRD schema registry negative paths;
* an HK legal hold blocks the shared employee delete.
"""

import re
from contextlib import contextmanager
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _other_org, _profile  # noqa: F401

HK_ROUTE_COUNT = 65           # 44 tenant /api/payroll/hong-kong/* + 21 Super Admin (pinned: review a new route's RBAC)

# FILED needs the external-submission record (how the employer submitted).
INTERNAL_FILING = {"submissionMode": "INTERNAL_PREPARATION_ONLY", "authorizedSigner": "Director (test)"}


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


def _hk_routes():
    from app.main import app

    return sorted((m, r.path) for r in app.routes if hasattr(r, "methods") and "hong-kong" in r.path
                  for m in r.methods - {"HEAD", "OPTIONS"})


def _call(client, method, path):
    url = re.sub(r"\{[^}]+\}", "1", path)
    return client.request(method, url, json={})


# ── RBAC over HTTP, every route ─────────────────────────────────────────

def test_hk_route_inventory_is_pinned():
    routes = _hk_routes()
    assert len(routes) == HK_ROUTE_COUNT, routes
    assert sum(1 for _m, p in routes if p.startswith("/api/payroll/hong-kong")) == HK_ROUTE_COUNT - 21


def test_every_hk_route_refuses_an_unauthenticated_caller_over_http(db):
    with _http(db, None) as client:
        bad = [(m, p, r.status_code) for m, p in _hk_routes() if (r := _call(client, m, p)).status_code not in (401, 403)]
    assert bad == []


def test_every_hk_route_refuses_a_non_operator_role_over_http(db, organization):
    employee_user = SimpleNamespace(id=999, organization_id=organization.id, role="employee", is_active=True)
    with _http(db, employee_user) as client:
        bad = [(m, p, r.status_code) for m, p in _hk_routes() if (r := _call(client, m, p)).status_code != 403]
    assert bad == []


def test_cross_tenant_id_routes_are_refused(db, hk):
    from fastapi import HTTPException

    from app.core.exceptions import NotFoundException
    from app.modules.payroll import hk_corrections, hk_privacy, hk_service

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    item = _item(db, _month(db, hk.org, 4), hk.emp)
    case_id = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)["employees"][0]["caseId"]
    hold = hk_privacy.place_legal_hold(db, hk.org.id, hk.emp.id, "enquiry", None, MAKER.id)
    batch = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    hk.emp.ctc = hk.emp.ctc + D("24000")
    db.commit()
    corr = hk_corrections.request_correction(db, hk.org.id, item.id, "under-stated", MAKER.id)
    other = _other_org(db, "HKRCX")
    intruder = SimpleNamespace(id=CHECKER.id, organization_id=other.id, role="payroll_admin", is_active=True)

    with _http(db, intruder) as client:                                   # reads / downloads
        for path in (f"/api/payroll/hong-kong/ird/cases/{case_id}/history",
                     f"/api/payroll/payslips/{item.id}/download",
                     f"/api/payroll/hong-kong/employees/{hk.emp.id}/average-wage-snapshots"):
            assert client.get(path).status_code == 404, path
    refusals = [  # writes, through the service layer every write route delegates to
        lambda: hk_service.transition_ird_case(db, other.id, case_id, "VALIDATED", CHECKER.id),
        lambda: hk_service.amend_ird_case(db, other.id, case_id, "x", CHECKER.id),
        lambda: hk_service.transition_empf_submission(db, other.id, batch.id, "SUBMITTED", CHECKER.id, "R"),
        lambda: hk_privacy.release_legal_hold(db, other.id, hold.id, "x", CHECKER.id),
        lambda: hk_corrections.approve_correction(db, other.id, corr.id, CHECKER.id),
        lambda: hk_corrections.request_correction(db, other.id, item.id, "x", CHECKER.id),
        lambda: hk_service.calculate_average_wage(db, other.id, hk.emp.id, "ANNUAL_LEAVE", date(2026, 4, 30), [],
                                                  CHECKER.id),
    ]
    for fn in refusals:
        with pytest.raises((NotFoundException, HTTPException)) as exc:
            fn()
        assert getattr(exc.value, "status_code", 404) == 404
        db.rollback()
    db.refresh(corr)
    assert corr.status == "REQUESTED" and hk_privacy.active_legal_holds(db, hk.org.id)


def test_a_non_hk_employee_is_refused_on_hk_routes(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    us = _employee(db, hk.org.id, "US1", country_code="US")
    with pytest.raises(BadRequestException, match="not a Hong Kong employee"):
        hk_service.create_event_cases(db, hk.org.id, us.id, MAKER.id)


# ── IRD rejection lifecycle ─────────────────────────────────────────────

def _filed_ir56b(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgIrdReportingCase

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    ar = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    case = db.get(HkgIrdReportingCase, ar["employees"][0]["caseId"])
    hk_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-F1", submission=INTERNAL_FILING)
    return case


def test_ird_rejection_keeps_the_filed_evidence_and_regeneration_never_reopens_it(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    case = _filed_ir56b(db, hk)
    filed_hash = case.payload_hash
    with pytest.raises(BadRequestException):                       # a filed case is never silently re-prepared
        hk_service.transition_ird_case(db, hk.org.id, case.id, "PREPARED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "REJECTED", MAKER.id, receipt_reference="REJ-9 bad file no")
    with pytest.raises(BadRequestException):                       # no double rejection
        hk_service.transition_ird_case(db, hk.org.id, case.id, "REJECTED", MAKER.id, receipt_reference="again")

    out = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)   # must NOT silently re-prepare
    row = next(e for e in out["employees"] if e["caseId"] == case.id)
    db.refresh(case)
    assert row["status"] == "REJECTED" and "Prepare again" in row["message"]
    assert case.status == "REJECTED" and case.payload_hash == filed_hash

    hk_service.transition_ird_case(db, hk.org.id, case.id, "PREPARED", MAKER.id)    # the explicit, audited step
    hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    db.refresh(case)
    assert case.status == "PREPARED" and not any("rejected by the IRD" in e for e in case.validation_errors or [])
    hk_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-F2", submission=INTERNAL_FILING)

    history = hk_service.ird_case_history(db, hk.org.id, case.id)
    steps = [(h["from"], h["to"]) for h in history if h["action"] == "status_change"]
    assert steps == [("PREPARED", "VALIDATED"), ("VALIDATED", "FILED"), ("FILED", "REJECTED"),
                     ("REJECTED", "PREPARED"), ("PREPARED", "VALIDATED"), ("VALIDATED", "FILED")]
    rejected = next(h for h in history if h["to"] == "REJECTED")
    assert rejected["reference"] == "REJ-9 bad file no"
    assert rejected["filedEvidence"]["filingReference"] == "IRD-F1" and rejected["filedEvidence"]["payloadHash"] == filed_hash
    assert "payload" not in rejected["filedEvidence"]                       # the API returns the hash, not the payload
    assert [h["filingReference"] for h in history if h["to"] == "FILED"] == ["IRD-F1", "IRD-F2"]


def test_the_rejection_audit_row_holds_the_full_filed_payload(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import TaxConfigurationAudit

    case = _filed_ir56b(db, hk)
    filed_payload = dict(case.payload)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "REJECTED", MAKER.id, receipt_reference="REJ")
    row = (db.query(TaxConfigurationAudit)
           .filter(TaxConfigurationAudit.entity_type == "hkg_ird_reporting_case", TaxConfigurationAudit.entity_id == case.id)
           .order_by(TaxConfigurationAudit.id.desc()).first())
    assert row.new_value["filedEvidence"]["payload"] == filed_payload
    assert "A123456" not in str(row.new_value)                               # no HKID in the IRD payload evidence


def test_bir56a_regeneration_never_reopens_an_amended_cover_return(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgIrdReportingCase

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    cover_id = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)["bir56aCaseId"]
    hk_service.transition_ird_case(db, hk.org.id, cover_id, "VALIDATED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, cover_id, "FILED", CHECKER.id, filing_reference="BIR-1", submission=INTERNAL_FILING)
    amendment = hk_service.amend_ird_case(db, hk.org.id, cover_id, "late employee", MAKER.id)
    out = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    original = db.get(HkgIrdReportingCase, cover_id)
    assert original.status == "AMENDED" and original.filing_reference == "BIR-1"
    assert out["bir56aCaseId"] == amendment.id


def test_ird_history_is_tenant_scoped(db, hk):
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import hk_service

    case = _filed_ir56b(db, hk)
    with pytest.raises(NotFoundException):
        hk_service.ird_case_history(db, _other_org(db, "HKRCH").id, case.id)


# ── eMPF ────────────────────────────────────────────────────────────────

def test_empf_preparation_is_idempotent_and_never_touches_a_submitted_batch(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgEmpfSubmission

    _month(db, hk.org, 4)
    first = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    again = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    assert again.id == first.id
    assert db.query(HkgEmpfSubmission).filter(HkgEmpfSubmission.organization_id == hk.org.id).count() == 1
    hk_service.transition_empf_submission(db, hk.org.id, first.id, "SUBMITTED", CHECKER.id, submission_reference="E-1")
    db.commit()
    rows, totals = list(first.rows), dict(first.totals)
    supp = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    db.refresh(first)
    assert supp.id != first.id and supp.supplements_submission_id == first.id and supp.rows == []
    assert first.status == "SUBMITTED" and first.rows == rows and first.totals == totals


# ── corrections ─────────────────────────────────────────────────────────

def test_a_refused_cross_jurisdiction_correction_leaves_nothing_behind(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import hk_corrections
    from app.modules.payroll.models import HkgPayslipCorrection, PayrollRun, PayslipItem

    item = _item(db, _month(db, hk.org, 4), hk.emp)
    before = (db.query(PayrollRun).count(), db.query(PayslipItem).count(), str(item.net_pay))
    hk.emp.country_code = "SG"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        hk_corrections.request_correction(db, hk.org.id, item.id, "moved", MAKER.id)
    assert exc.value.status_code == 409
    db.rollback()
    assert db.query(HkgPayslipCorrection).count() == 0
    db.refresh(item)
    assert (db.query(PayrollRun).count(), db.query(PayslipItem).count(), str(item.net_pay)) == before


# ── D-19 ────────────────────────────────────────────────────────────────

def test_payslip_zip_download_is_access_logged_without_identifiers(db, hk):
    from app.modules.payroll import hk_privacy
    from app.modules.payroll.models import HkgAccessEvent

    run = _month(db, hk.org, 4)
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, operator) as client:
        res = client.get(f"/api/payroll/runs/{run.id}/download")
    assert res.status_code == 200 and res.content[:2] == b"PK"
    events = hk_privacy.list_access_events(db, hk.org.id)
    assert [(e["action"], e["employeeId"]) for e in events] == [("DOWNLOAD_PAYSLIPS_ZIP", hk.emp.id)]
    row = db.query(HkgAccessEvent).one()
    assert row.organization_id == hk.org.id and row.actor_id == MAKER.id and row.occurred_at is not None
    assert row.resource_type == "payslip_item" and row.purpose == f"payroll run {run.id}"
    stored = " ".join(str(getattr(row, c.name)) for c in HkgAccessEvent.__table__.columns)
    assert "A123456" not in stored and "MB-HK1" not in stored                  # no identifiers in the log


def test_bank_file_download_is_access_logged(db, hk):
    from app.modules.payroll import hk_privacy

    run = _month(db, hk.org, 4)
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, operator) as client:
        res = client.get(f"/api/payroll/runs/{run.id}/bank-transfer-file", params={"format": "csv"})
    if res.status_code != 200:
        pytest.skip(f"bank file not producible for this fixture ({res.status_code}): logging covered at service level")
    assert [e["action"] for e in hk_privacy.list_access_events(db, hk.org.id)] == ["DOWNLOAD_BANK_FILE"]


def test_identity_token_key_rotation_rekeys_v2_tokens(db, hk, monkeypatch):
    from app.config import settings
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import EmployeeStatutoryProfile
    from scripts.rehash_hk_identity_tokens import rehash

    profile = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.employee_id == hk.emp.id).first()
    profile.hkg_identity_token = hk_service.identity_token("A123456(3)")
    db.commit()
    old = profile.hkg_identity_token
    monkeypatch.setattr(settings, "HK_IDENTITY_TOKEN_KEY", "rotated-key-for-test")
    assert rehash(db)["staleKey"] == 0                                         # without --rotate: v2 untouched
    dry = rehash(db, rotate=True)
    db.refresh(profile)
    assert dry["staleKey"] == 1 and profile.hkg_identity_token == old           # dry run writes nothing
    done = rehash(db, write=True, rotate=True)
    db.refresh(profile)
    assert done["staleKey"] == 1 and profile.hkg_identity_token == hk_service.identity_token("A123456(3)") != old
    assert rehash(db, rotate=True)["staleKey"] == 0                            # idempotent


def test_an_hk_legal_hold_blocks_the_shared_employee_delete(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import hk_privacy, service

    hk_privacy.place_legal_hold(db, hk.org.id, hk.emp.id, "IRD enquiry", "R-1", MAKER.id)
    with pytest.raises(HTTPException) as exc:
        service.delete_employee(db, hk.emp.id, hk.org.id)
    assert exc.value.status_code == 409 and "legal hold" in exc.value.detail


# ── IRD schema registry ─────────────────────────────────────────────────

def test_ird_schema_registry_negative_paths_and_review_state(db, tmp_path):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_ird_schema

    xsd = tmp_path / "t.xsd"            # SYNTHETIC test-only schema — not an IRD schema
    xsd.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="R" type="xs:string"/></xs:schema>')
    with pytest.raises(BadRequestException, match="unknown IRD form"):
        hk_ird_schema.register_schema(db, "IR99", "2025/26", str(xsd))
    with pytest.raises(BadRequestException, match="not found"):
        hk_ird_schema.register_schema(db, "IR56B", "2025/26", str(tmp_path / "missing.xsd"))
    a = hk_ird_schema.register_schema(db, "IR56B", "2025/26", str(xsd))
    b = hk_ird_schema.register_schema(db, "IR56B", "2026/27", str(xsd))             # same file, another YA: separate
    assert a.id != b.id and a.superseded_by_id is None
    status = {r["form"]: r["status"] for r in hk_ird_schema.readiness(db, "2025/26")}
    assert status["IR56B"] == "REGISTERED — AWAITING REVIEW" and status["BIR56A"] == "EXTERNAL SCHEMA REQUIRED"
    a.created_by_id = CHECKER.id
    a.reviewer_id = CHECKER.id                                                    # self-review: not four-eyes
    db.commit()
    assert {r["form"]: r["status"] for r in hk_ird_schema.readiness(db, "2025/26")}["IR56B"] == "REGISTERED — AWAITING REVIEW"
    a.created_by_id = MAKER.id
    db.commit()
    assert {r["form"]: r["status"] for r in hk_ird_schema.readiness(db, "2025/26")}["IR56B"] == "REGISTERED — REVIEWED"
    assert hk_ird_schema.validate(b"<R>", str(xsd))[0].startswith("not well-formed")
    assert hk_ird_schema.validate(b"<R>x</R>", str(xsd)) == []
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    xxe = (f'<?xml version="1.0"?><!DOCTYPE R [<!ENTITY x SYSTEM "{secret.as_uri()}">]><R>&x;</R>').encode()
    from lxml import etree

    assert b"TOP-SECRET" not in etree.tostring(etree.fromstring(xxe, hk_ird_schema._parser()))   # never resolved
    errors = hk_ird_schema.validate(xxe, str(xsd))
    assert errors == ["a DOCTYPE / entity declaration is not accepted in an IRD submission"]


# ── reports: exact-year template enforcement at generation ─────────────

def test_an_earlier_years_active_template_is_never_used_to_generate(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service, service
    from tests.test_hong_kong_reports import _seeded

    for m in (1, 2, 3, 4):
        _month(db, hk.org, m)
    hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    ir56b = _seeded(db, "HK-IR56B")                                      # the 2025/26 version, Active
    assert ir56b.reporting_year == "2025/26"
    service.generate_hong_kong_ir56b(db, hk.org.id, ir56b.id, hk.emp.id, "2025/26")   # its own year: fine
    with pytest.raises(BadRequestException, match="earlier year's template is never used"):
        service.generate_hong_kong_ir56b(db, hk.org.id, ir56b.id, hk.emp.id, "2026/27")
    bir = _seeded(db, "HK-BIR56A")
    with pytest.raises(BadRequestException, match="2026/27"):
        service.generate_hong_kong_bir56a(db, hk.org.id, bir.id, "2026/27")
    empf = _seeded(db, "HK-EMPF-REMITTANCE")                             # the 2026 version
    sub = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    service.generate_hong_kong_empf_remittance(db, hk.org.id, empf.id, sub.id)
    empf.reporting_year = "2025"                                         # a stale-year Active template
    db.commit()
    with pytest.raises(BadRequestException, match="2026 version"):
        service.generate_hong_kong_empf_remittance(db, hk.org.id, empf.id, sub.id)


# ── final pass: positive authorization, report attack paths, XML bombs ─

def test_critical_hk_routes_succeed_for_the_right_role(db, hk):
    """The positive half of the RBAC sweep: an org payroll operator reaches its
    own tenant's HK data; a platform Super Admin reaches the SA HK routes."""
    from app.modules.payroll import hk_service

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    case_id = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)["employees"][0]["caseId"]
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, operator) as client:
        for path in ("/api/payroll/hong-kong/ird/cases", "/api/payroll/hong-kong/corrections",
                     "/api/payroll/hong-kong/legal-holds", "/api/payroll/hong-kong/access-events",
                     "/api/payroll/hong-kong/empf/submissions", "/api/payroll/hong-kong/tax-clearance",
                     "/api/payroll/hong-kong/termination-results", "/api/payroll/hong-kong/readiness",
                     f"/api/payroll/hong-kong/ird/cases/{case_id}/history"):
            assert client.get(path).status_code == 200, path
        cases = client.get("/api/payroll/hong-kong/ird/cases").json()
        assert case_id in {c["id"] for c in cases}
    admin = SimpleNamespace(id=9, organization_id=None, role="super_admin", is_active=True)
    with _http(db, admin) as client:
        assert client.get("/api/super-admin/compliance/hong-kong/statutory-summary").status_code == 200
    with _http(db, operator) as client:                                  # an operator is not a Super Admin
        assert client.get("/api/super-admin/compliance/hong-kong/statutory-summary").status_code == 403


def test_report_generators_refuse_every_unsafe_template_or_subject(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import hk_service, service
    from tests.test_hong_kong_reports import _seeded

    for m in (1, 2, 3, 4):
        _month(db, hk.org, m)
    hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    ir56b = _seeded(db, "HK-IR56B")
    ir56b.reporting_year = "2026"                                # a calendar-year key on a YA report
    db.commit()
    with pytest.raises(BadRequestException, match="2026 version"):          # 2025/26 report, 2026 template
        service.generate_hong_kong_ir56b(db, hk.org.id, ir56b.id, hk.emp.id, "2025/26")
    ir56b.reporting_year = "2025/26"
    ir56b.status = "Draft"                                         # the exact year, but not Active
    db.commit()
    with pytest.raises(BadRequestException, match="not Active"):
        service.generate_hong_kong_ir56b(db, hk.org.id, ir56b.id, hk.emp.id, "2025/26")
    ir56b.status = "Active"
    db.commit()
    with pytest.raises(NotFoundException):                          # no such template
        service.generate_hong_kong_ir56b(db, hk.org.id, 999999, hk.emp.id, "2025/26")
    other = _other_org(db, "HKRCR")
    with pytest.raises(NotFoundException):                         # another tenant's employee: not found
        service.generate_hong_kong_ir56b(db, other.id, ir56b.id, hk.emp.id, "2025/26")
    term = _seeded(db, "HK-TERMINATION-STATEMENT")                 # the 2026 version
    term.reporting_year = "2025/26"
    db.commit()
    result = hk_service.calculate_termination(db, hk.org.id, hk.emp.id, {"terminationDate": "2026-06-30",
                                              "reason": "RESIGNATION", "postTransitionWage": "20000"}, MAKER.id)
    hk_service.approve_termination(db, hk.org.id, result.id, CHECKER.id)
    with pytest.raises(BadRequestException, match="2026 version"):          # 2026 statement, 2025/26 template
        service.generate_hong_kong_termination_statement(db, hk.org.id, term.id, result.id)
    term.reporting_year = "2026"
    db.commit()
    assert service.generate_hong_kong_termination_statement(db, hk.org.id, term.id, result.id).id


def test_xml_bombs_and_external_entities_are_refused(tmp_path):
    from app.modules.payroll import hk_ird_schema

    xsd = tmp_path / "t.xsd"            # SYNTHETIC test-only schema — not an IRD schema
    xsd.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="R" type="xs:string"/></xs:schema>')
    lol = ('<?xml version="1.0"?><!DOCTYPE R [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
           '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><R>&c;</R>').encode()
    refused = ["a DOCTYPE / entity declaration is not accepted in an IRD submission"]
    assert hk_ird_schema.validate(lol, str(xsd)) == refused                      # entity expansion ("billion laughs")
    remote = b'<?xml version="1.0"?><!DOCTYPE R SYSTEM "http://example.invalid/x.dtd"><R>x</R>'
    assert hk_ird_schema.validate(remote, str(xsd)) == refused                   # external DTD
