"""
tests/test_hong_kong_privacy.py
-------------------------------
D-19 technical controls (HK-only): keyed, versioned identity token; legal
holds that block deletion (four-eyes release); the deletion guard for retained
HK statutory records; the HK access log on statutory-profile views and report /
certificate downloads — and that no other country's behaviour changes.

No retention period is chosen or tested here: that is an owner / privacy-counsel
decision (docs/HONG_KONG_RELEASE_EVIDENCE/D19/).
"""

import hashlib
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _other_org, _profile  # noqa: F401


# ── keyed identity token ────────────────────────────────────────────────

def test_identity_token_is_keyed_versioned_and_never_the_raw_value(monkeypatch):
    from app.config import settings
    from app.modules.payroll.hk_service import identity_token, identity_token_version

    token = identity_token("A123456(3)")
    assert token.startswith("v2:") and len(token) == 67 and "A123456" not in token
    assert token != hashlib.sha256(b"A123456(3)").hexdigest()          # not the reversible legacy digest
    assert identity_token(" a123456(3) ") == token                      # normalised, deterministic
    assert identity_token("") is None and identity_token(None) is None
    monkeypatch.setattr(settings, "HK_IDENTITY_TOKEN_KEY", "a-dedicated-production-key")
    assert identity_token("A123456(3)") != token                        # depends on the key
    assert identity_token_version(token) == "v2"
    assert identity_token_version(hashlib.sha256(b"x").hexdigest()) == "v1"   # legacy rows stay readable


# ── legal holds and deletion ────────────────────────────────────────────

def test_legal_hold_blocks_deletion_and_needs_a_different_user_to_release(db, hk):
    from fastapi import HTTPException

    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_privacy, service

    bare = _employee(db, hk.org.id, "HKBARE")                            # no statutory record at all
    hold = hk_privacy.place_legal_hold(db, hk.org.id, bare.id, "IRD enquiry", "IRD/2026/1", MAKER.id)
    with pytest.raises(HTTPException, match="legal hold") as exc:
        service.delete_employee(db, bare.id, hk.org.id)
    assert exc.value.status_code == 409
    with pytest.raises(BadRequestException, match="four-eyes"):
        hk_privacy.release_legal_hold(db, hk.org.id, hold.id, "closed", MAKER.id)
    hk_privacy.release_legal_hold(db, hk.org.id, hold.id, "enquiry closed", CHECKER.id)
    with pytest.raises(HTTPException, match="legal-hold history"):        # released, but retained as evidence
        service.delete_employee(db, bare.id, hk.org.id)
    clean = _employee(db, hk.org.id, "HKCLEAN")                          # no hold, no retained record → allowed
    service.delete_employee(db, clean.id, hk.org.id)


def test_an_organisation_wide_hold_covers_every_hk_employee(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import hk_privacy, service

    bare = _employee(db, hk.org.id, "HKBARE2")
    hk_privacy.place_legal_hold(db, hk.org.id, None, "litigation", None, MAKER.id)
    with pytest.raises(HTTPException, match="legal hold"):
        service.delete_employee(db, bare.id, hk.org.id)
    assert service.hk_employer_readiness(db, hk.org.id)["legalHolds"]["active"] == 1


def test_retained_hk_statutory_records_block_a_hard_delete(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import service

    with pytest.raises(HTTPException, match="statutory profile versions"):
        service.delete_employee(db, hk.emp.id, hk.org.id)               # has a profile version


def test_legal_hold_is_tenant_and_jurisdiction_scoped(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import hk_privacy

    other = _other_org(db, "HKPRIVOTHER")
    with pytest.raises(NotFoundException):
        hk_privacy.place_legal_hold(db, other.id, hk.emp.id, "x", None, MAKER.id)
    sg = _employee(db, hk.org.id, "SGX", country_code="SG")
    with pytest.raises(BadRequestException, match="not a Hong Kong employee"):
        hk_privacy.place_legal_hold(db, hk.org.id, sg.id, "x", None, MAKER.id)
    hk_privacy.place_legal_hold(db, hk.org.id, hk.emp.id, "x", None, MAKER.id)
    assert hk_privacy.list_legal_holds(db, other.id) == []


def test_non_hk_employee_deletion_is_unchanged(db, organization):
    from app.modules.payroll import service

    us = _employee(db, organization.id, "US1", country_code="US", compliance_fields={})
    service.delete_employee(db, us.id, organization.id)                  # no HK guard involved


# ── access log ──────────────────────────────────────────────────────────

def test_access_log_records_hk_reports_only_and_is_tenant_scoped(db, hk):
    from app.modules.payroll import hk_privacy
    from app.modules.payroll.models import GeneratedReport, ReportTemplate

    tmpl = ReportTemplate(template_key="T", name="T", report_type="HK_IR56B", jurisdiction_country="HK",
                          reporting_year="2025/26", version="1.0", status="Active", document_scope="PER_EMPLOYEE")
    db.add(tmpl)
    db.commit()
    hk_report = GeneratedReport(organization_id=hk.org.id, report_template_id=tmpl.id, template_version="1.0",
                                report_type="HK_IR56B", employee_id=hk.emp.id, jurisdiction_country="HK",
                                reporting_year="2025/26", status="Generated", rendered_data={})
    uk_report = GeneratedReport(organization_id=hk.org.id, report_template_id=tmpl.id, template_version="1.0",
                                report_type="P60", jurisdiction_country="UK", reporting_year="2026-27",
                                status="Generated", rendered_data={})
    db.add_all([hk_report, uk_report])
    db.commit()
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"), headers={"user-agent": "pytest"})
    hk_privacy.log_report_download(db, hk.org.id, MAKER.id, hk_report.id, "DOWNLOAD_CERTIFICATE", request=request)
    hk_privacy.log_report_download(db, hk.org.id, MAKER.id, uk_report.id, "DOWNLOAD_CERTIFICATE", request=request)
    events = hk_privacy.list_access_events(db, hk.org.id)
    assert len(events) == 1 and events[0]["reportType"] == "HK_IR56B" and events[0]["employeeId"] == hk.emp.id
    assert events[0]["clientAddress"] == "203.0.113.7" and events[0]["actorId"] == MAKER.id
    assert hk_privacy.list_access_events(db, _other_org(db, "HKLOGOTHER").id) == []
    with pytest.raises(ValueError):
        hk_privacy.record_access(db, hk.org.id, MAKER.id, "DELETE_EVERYTHING", "x")


def test_statutory_profile_view_and_certificate_download_are_logged_over_http(db, hk):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription
    from app.modules.payroll import hk_privacy, service
    from tests.test_hong_kong_reports import _seeded

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    hk_service_module = __import__("app.modules.payroll.hk_service", fromlist=["x"])
    hk_service_module.generate_annual_return(db, hk.org.id, "2025/26", None)
    tmpl = _seeded(db, "HK-IR56B")
    report = service.generate_hong_kong_ir56b(db, hk.org.id, tmpl.id, hk.emp.id, "2025/26")
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.update({get_db: lambda: db, get_current_user: lambda: operator,
                                     get_current_org_scoped_principal: lambda: operator,
                                     require_active_subscription: lambda: None})
    try:
        client = TestClient(app)
        assert client.get(f"/api/payroll/employees/{hk.emp.id}/statutory-profile").status_code == 200
        pdf = client.get(f"/api/payroll/generated-reports/{report.id}/certificate/{hk.emp.id}")
        assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
        assert client.get(f"/api/payroll/generated-reports/{report.id}").status_code == 200
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
    actions = [e["action"] for e in hk_privacy.list_access_events(db, hk.org.id, hk.emp.id)]
    assert set(actions) == {"VIEW_STATUTORY_PROFILE", "DOWNLOAD_CERTIFICATE", "VIEW_REPORT"}


def test_access_event_records_an_assisted_access_session(db, hk):
    from app.modules.payroll import hk_privacy

    import app.core.security as security

    request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.1"),
                              headers={"user-agent": "x", "authorization": "Bearer aa-token"})
    original = security.decode_assisted_access_token
    security.decode_assisted_access_token = lambda token: {"assisted_access_session_id": 42} if token == "aa-token" else None
    try:
        event = hk_privacy.record_access(db, hk.org.id, MAKER.id, "VIEW_STATUTORY_PROFILE", "employee_statutory_profile",
                                         employee_id=hk.emp.id, request=request)
    finally:
        security.decode_assisted_access_token = original
    assert event.assisted_access_session_id == 42


def test_legacy_identity_tokens_are_rederived_only_on_write(db, hk):
    from app.modules.payroll.models import EmployeeStatutoryProfile
    from scripts.rehash_hk_identity_tokens import rehash

    profile = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.employee_id == hk.emp.id).one()
    profile.hkg_identity_token = hashlib.sha256(b"A123456(3)").hexdigest()          # a legacy v1 token
    db.commit()
    dry = rehash(db)
    db.refresh(profile)
    assert dry["legacy"] == 1 and dry["rederived"] == 1 and len(profile.hkg_identity_token) == 64   # nothing written
    done = rehash(db, write=True)
    db.refresh(profile)
    assert done["rederived"] == 1 and profile.hkg_identity_token.startswith("v2:")
    assert rehash(db)["legacy"] == 0                                                   # idempotent
    profile.hkg_identity_token = hashlib.sha256(b"SOMEONE-ELSE").hexdigest()
    db.commit()
    assert rehash(db, write=True)["notReproducible"] == 1
    db.refresh(profile)
    assert len(profile.hkg_identity_token) == 64                                       # left untouched
