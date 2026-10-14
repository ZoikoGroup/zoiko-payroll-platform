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
    from app.modules.payroll.hong_kong_service import identity_token, identity_token_version

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
    from app.modules.payroll import retention_service, service

    bare = _employee(db, hk.org.id, "HKBARE")                            # no statutory record at all
    hold = retention_service.place_legal_hold(db, "HK", hk.org.id, bare.id, "IRD enquiry", "IRD/2026/1", MAKER.id)
    with pytest.raises(HTTPException, match="legal hold") as exc:
        service.delete_employee(db, bare.id, hk.org.id)
    assert exc.value.status_code == 409
    with pytest.raises(BadRequestException, match="four-eyes"):
        retention_service.release_legal_hold(db, "HK", hk.org.id, hold.id, "closed", MAKER.id)
    from app.modules.payroll.models import TaxConfigurationAudit
    assert (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "legal_hold",
                                                   TaxConfigurationAudit.entity_id == hold.id,
                                                   TaxConfigurationAudit.action == "refused",
                                                   TaxConfigurationAudit.actor_id == MAKER.id).count() == 1)
    retention_service.release_legal_hold(db, "HK", hk.org.id, hold.id, "enquiry closed", CHECKER.id)
    with pytest.raises(HTTPException, match="legal-hold history"):        # released, but retained as evidence
        service.delete_employee(db, bare.id, hk.org.id)
    clean = _employee(db, hk.org.id, "HKCLEAN")                          # no hold, no retained record → allowed
    service.delete_employee(db, clean.id, hk.org.id)


def test_an_organisation_wide_hold_covers_every_hk_employee(db, hk):
    from app.modules.payroll import hong_kong_service
    from fastapi import HTTPException

    from app.modules.payroll import retention_service, service

    bare = _employee(db, hk.org.id, "HKBARE2")
    retention_service.place_legal_hold(db, "HK", hk.org.id, None, "litigation", None, MAKER.id)
    with pytest.raises(HTTPException, match="legal hold"):
        service.delete_employee(db, bare.id, hk.org.id)
    assert hong_kong_service.hk_employer_readiness(db, hk.org.id)["legalHolds"]["active"] == 1


def test_retained_hk_statutory_records_block_a_hard_delete(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import service

    with pytest.raises(HTTPException, match="statutory profile versions"):
        service.delete_employee(db, hk.emp.id, hk.org.id)               # has a profile version


def test_legal_hold_is_tenant_and_jurisdiction_scoped(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import retention_service

    other = _other_org(db, "HKPRIVOTHER")
    with pytest.raises(NotFoundException):
        retention_service.place_legal_hold(db, "HK", other.id, hk.emp.id, "x", None, MAKER.id)
    sg = _employee(db, hk.org.id, "SGX", country_code="SG")
    with pytest.raises(BadRequestException, match="not a Hong Kong employee"):
        retention_service.place_legal_hold(db, "HK", hk.org.id, sg.id, "x", None, MAKER.id)
    retention_service.place_legal_hold(db, "HK", hk.org.id, hk.emp.id, "x", None, MAKER.id)
    assert retention_service.list_legal_holds(db, "HK", other.id) == []


def test_non_hk_employee_deletion_is_unchanged(db, organization):
    from app.modules.payroll import service

    us = _employee(db, organization.id, "US1", country_code="US", compliance_fields={})
    service.delete_employee(db, us.id, organization.id)                  # no HK guard involved


# ── access log ──────────────────────────────────────────────────────────

def test_access_log_records_hk_reports_only_and_is_tenant_scoped(db, hk):
    from app.modules.payroll import retention_service
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
    retention_service.log_report_download(db, hk.org.id, MAKER.id, hk_report.id, "DOWNLOAD_CERTIFICATE", request=request)
    retention_service.log_report_download(db, hk.org.id, MAKER.id, uk_report.id, "DOWNLOAD_CERTIFICATE", request=request)
    events = retention_service.list_access_events(db, "HK", hk.org.id)
    assert len(events) == 1 and events[0]["reportType"] == "HK_IR56B" and events[0]["employeeId"] == hk.emp.id
    assert events[0]["clientAddress"] == "203.0.113.7" and events[0]["actorId"] == MAKER.id
    assert retention_service.list_access_events(db, "HK", _other_org(db, "HKLOGOTHER").id) == []
    with pytest.raises(ValueError):
        retention_service.record_access(db, "HK", hk.org.id, MAKER.id, "DELETE_EVERYTHING", "x")


def test_statutory_profile_view_and_certificate_download_are_logged_over_http(db, hk):
    from app.modules.payroll import hong_kong_service
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription
    from app.modules.payroll import retention_service, service
    from tests.test_hong_kong_reports import _seeded

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    hk_service_module = __import__("app.modules.payroll.hong_kong_service", fromlist=["x"])
    hk_service_module.generate_annual_return(db, hk.org.id, "2025/26", None)
    tmpl = _seeded(db, "HK-IR56B")
    report = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, tmpl.id, hk.emp.id, "2025/26")
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
    actions = [e["action"] for e in retention_service.list_access_events(db, "HK", hk.org.id, hk.emp.id)]
    assert set(actions) == {"VIEW_STATUTORY_PROFILE", "DOWNLOAD_CERTIFICATE", "VIEW_REPORT"}


def test_access_event_records_an_assisted_access_session(db, hk):
    from app.modules.payroll import retention_service

    import app.core.security as security

    request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.1"),
                              headers={"user-agent": "x", "authorization": "Bearer aa-token"})
    original = security.decode_assisted_access_token
    security.decode_assisted_access_token = lambda token: {"assisted_access_session_id": 42} if token == "aa-token" else None
    try:
        event = retention_service.record_access(db, "HK", hk.org.id, MAKER.id, "VIEW_STATUTORY_PROFILE", "employee_statutory_profile",
                                         employee_id=hk.emp.id, request=request)
    finally:
        security.decode_assisted_access_token = original
    assert event.assisted_access_session_id == 42


def test_legacy_identity_tokens_are_rederived_only_on_write(db, hk):
    from app.modules.payroll.models import EmployeeStatutoryProfile
    from scripts.rehash_hk_identity_tokens import rehash

    profile = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.employee_id == hk.emp.id).one()
    profile.hk_identity_token = hashlib.sha256(b"A123456(3)").hexdigest()          # a legacy v1 token
    db.commit()
    dry = rehash(db)
    db.refresh(profile)
    assert dry["legacy"] == 1 and dry["rederived"] == 1 and len(profile.hk_identity_token) == 64   # nothing written
    done = rehash(db, write=True)
    db.refresh(profile)
    assert done["rederived"] == 1 and profile.hk_identity_token.startswith("v2:")
    assert rehash(db)["legacy"] == 0                                                   # idempotent
    profile.hk_identity_token = hashlib.sha256(b"SOMEONE-ELSE").hexdigest()
    db.commit()
    assert rehash(db, write=True)["notReproducible"] == 1
    db.refresh(profile)
    assert len(profile.hk_identity_token) == 64                                       # left untouched


# ── MPF member account: masked by default, audited permission-gated reveal (G5 F-1) ──

def _users(db, org_id):
    from app.modules.auth.models import User, UserRole

    def mk(email, role):
        u = User(email=email, hashed_password="x", role=role, organization_id=org_id, first_name="T", last_name=email[:4],
                 is_active=True)
        db.add(u)
        db.commit()
        return u
    return (mk("admin-a@zoikotest.example.com", UserRole.ORG_ADMIN), mk("admin-b@zoikotest.example.com", UserRole.ORG_ADMIN),
            mk("filer@zoikotest.example.com", UserRole.PAYROLL_ADMIN), mk("clerk@zoikotest.example.com", UserRole.PAYROLL_ADMIN))


def _events(db, action="REVEAL_MPF_MEMBER_ACCOUNT"):
    from app.modules.payroll.models import PersonalDataAccessEvent

    return db.query(PersonalDataAccessEvent).filter(PersonalDataAccessEvent.action == action).order_by(
        PersonalDataAccessEvent.id).all()


def test_mpf_member_account_is_masked_by_default_in_employee_and_payslip_responses(db, hk):
    from app.modules.payroll.schemas import EmployeeResponse
    from tests.test_hong_kong_governance import _http

    stored = hk.emp.compliance_fields["mpf_member_account"]
    shown = EmployeeResponse.model_validate(hk.emp).complianceFields["mpf_member_account"]
    assert stored == "MB-HK1" and shown == "**-HK1" and stored not in shown
    item = _item(db, _month(db, hk.org, 4), hk.emp)
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, operator) as c:
        body = c.get(f"/api/payroll/payslips/{item.id}").json()
        emp = c.get(f"/api/payroll/employees/{hk.emp.id}").json()
    assert body["complianceFields"]["mpf_member_account"] == "**-HK1" and "MB-HK1" not in str(body)
    assert emp["complianceFields"]["mpf_member_account"] == "**-HK1" and "MB-HK1" not in str(emp)
    db.refresh(hk.emp)
    assert hk.emp.compliance_fields["mpf_member_account"] == "MB-HK1"          # storage untouched


def test_mpf_account_reveal_needs_the_permission_and_every_read_and_refusal_is_logged(db, hk):
    from app.core.exceptions import BadRequestException, ForbiddenException
    from app.modules.payroll import hong_kong_service as hks
    from app.modules.payroll.models import TaxConfigurationAudit

    admin_a, admin_b, filer, clerk = _users(db, hk.org.id)
    with pytest.raises(ForbiddenException, match="HK_MPF_ACCOUNT_REVEAL"):
        hks.reveal_mpf_member_account(db, hk.org.id, filer.id, hk.emp.id, "eMPF filing 2026-04")
    assert [(e.actor_id, e.result) for e in _events(db)] == [(filer.id, "REFUSED")]
    with pytest.raises(ForbiddenException, match="organisation admin"):
        hks.grant_mpf_account_reveal(db, hk.org.id, clerk.id, filer.id, "trying")             # payroll admin cannot grant
    with pytest.raises(BadRequestException, match="yourself"):
        hks.grant_mpf_account_reveal(db, hk.org.id, admin_a.id, admin_a.id, "self")
    with pytest.raises(BadRequestException, match="reason"):
        hks.grant_mpf_account_reveal(db, hk.org.id, admin_a.id, filer.id, " ")
    grant = hks.grant_mpf_account_reveal(db, hk.org.id, admin_a.id, filer.id, "eMPF filing duty (TEST)")
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "user_permission",
                                                   TaxConfigurationAudit.entity_id == grant.id).one()
    assert audit.actor_id == admin_a.id and audit.new_value["userId"] == filer.id
    with pytest.raises(ForbiddenException, match="purpose"):
        hks.reveal_mpf_member_account(db, hk.org.id, filer.id, hk.emp.id, "  ")
    out = hks.reveal_mpf_member_account(db, hk.org.id, filer.id, hk.emp.id, "eMPF filing 2026-04")
    assert out["mpfMemberAccount"] == "MB-HK1"
    with pytest.raises(ForbiddenException):
        hks.reveal_mpf_member_account(db, hk.org.id, clerk.id, hk.emp.id, "curious")           # no permission
    ev = _events(db)
    assert [(e.actor_id, e.result) for e in ev] == [(filer.id, "REFUSED"), (filer.id, "REFUSED"),
                                                    (filer.id, "SUCCESS"), (clerk.id, "REFUSED")]
    assert ev[2].employee_id == hk.emp.id and ev[2].purpose == "eMPF filing 2026-04"
    hks.revoke_mpf_account_reveal(db, hk.org.id, admin_b.id, filer.id, "duty ended (TEST)")
    with pytest.raises(ForbiddenException):
        hks.reveal_mpf_member_account(db, hk.org.id, filer.id, hk.emp.id, "after revoke")


def test_empf_filing_view_carries_the_full_account_while_the_stored_batch_stays_masked(db, hk):
    from app.core.exceptions import ForbiddenException
    from app.modules.payroll import hong_kong_service as hks

    admin_a, _b, filer, clerk = _users(db, hk.org.id)
    _month(db, hk.org, 4)
    sub = hks.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    assert "MB-HK1" not in str(sub.rows) and sub.rows[0]["memberAccount"] == "**-HK1"
    with pytest.raises(ForbiddenException):
        hks.empf_filing_view(db, hk.org.id, clerk.id, sub.id, "filing")
    hks.grant_mpf_account_reveal(db, hk.org.id, admin_a.id, filer.id, "eMPF filing duty (TEST)")
    view = hks.empf_filing_view(db, hk.org.id, filer.id, sub.id, "eMPF filing 2026-04")
    assert view["rows"][0]["memberAccount"] == "MB-HK1" and view["rows"][0]["employerMandatory"] == sub.rows[0]["employerMandatory"]
    db.refresh(sub)
    assert "MB-HK1" not in str(sub.rows)                                      # filing view never rewrites the batch
    assert [(e.resource_type, e.result) for e in _events(db)][-1] == ("empf_submission", "SUCCESS")


def test_mpf_reveal_over_http_is_masked_for_a_plain_operator(db, hk):
    from tests.test_hong_kong_governance import _http

    _a, _b, _filer, clerk = _users(db, hk.org.id)
    principal = SimpleNamespace(id=clerk.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    with _http(db, principal) as c:
        r = c.post(f"/api/payroll/hong-kong/employees/{hk.emp.id}/mpf-member-account", json={"purpose": "look"})
    assert r.status_code == 403 and "MB-HK1" not in r.text


# ── eMPF submission guard (contract): the full MPF account reaches a filing payload only via the audited filing view ──

_MPF_ACCOUNT_READERS = {
    # file -> functions allowed to read compliance_fields["mpf_member_account"], and why
    "app/modules/payroll/employee_validation.py": {"<module>"},                      # field spec + SENSITIVE_FIELDS
    "app/modules/payroll/service.py": {"_payslip_identity_rows"},                   # payslip: masked (last 4)
    "app/modules/payroll/hong_kong_service.py": {
        "_hk_mpf_enrolled",              # presence check only (enrolment evidence)
        "prepare_empf_submission",       # stored batch: masked (last 4)
        "reveal_mpf_member_account",     # audited, permission-gated single reveal
        "empf_filing_view",              # audited, permission-gated filing payload (the ONLY full-number filing path)
    },
}


def test_no_new_code_reads_the_mpf_member_account_outside_the_audited_paths():
    """Tripwire for any future eMPF file / API submission builder: it must obtain the full account through
    hong_kong_service.empf_filing_view (permission + purpose + access log), never by reading the field
    itself or the masked stored batch. A new reader fails this test until it is reviewed and listed."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    found = {}
    for f in (root / "app").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8-sig"))

        def walk(node, fn=None):
            for ch in ast.iter_child_nodes(node):
                name = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if isinstance(ch, ast.Constant) and ch.value == "mpf_member_account":
                    found.setdefault(f.relative_to(root).as_posix(), set()).add(fn or "<module>")
                walk(ch, name)
        walk(tree)
    assert found == _MPF_ACCOUNT_READERS, found
    src = (root / "app/modules/payroll/hong_kong_service.py").read_text(encoding="utf-8")
    assert 'mask_account_last4(cf.get("mpf_member_account"))' in src          # the stored batch is built masked


def test_empf_filing_payload_contract_full_number_only_via_the_filing_view(db, hk):
    """Contract for the future eMPF builder: input = empf_filing_view(...) rows; each row carries the FULL member
    account and the same contribution figures as the stored batch; the stored batch never holds the full number;
    the read is permission-gated and logged."""
    from app.core.exceptions import ForbiddenException
    from app.modules.payroll import hong_kong_service as hks

    admin_a, _b, filer, clerk = _users(db, hk.org.id)
    _month(db, hk.org, 4)
    sub = hks.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    with pytest.raises(ForbiddenException):
        hks.empf_filing_view(db, hk.org.id, clerk.id, sub.id, "eMPF upload")
    hks.grant_mpf_account_reveal(db, hk.org.id, admin_a.id, filer.id, "eMPF filing duty (TEST)")
    payload = hks.empf_filing_view(db, hk.org.id, filer.id, sub.id, "eMPF upload 2026-04")
    assert [r["memberAccount"] for r in payload["rows"]] == ["MB-HK1"]
    for stored, filed in zip(sub.rows, payload["rows"]):
        assert {k: v for k, v in filed.items() if k != "memberAccount"} == {k: v for k, v in stored.items() if k != "memberAccount"}
        assert stored["memberAccount"] == "**-HK1"
    assert _events(db)[-1].resource_type == "empf_submission" and _events(db)[-1].result == "SUCCESS"
