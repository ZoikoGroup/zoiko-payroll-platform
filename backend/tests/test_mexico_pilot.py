"""Mexico Phase 10e — two-level activation (docs/mexico/MEXICO_PHASE_10E_PLAN.md,
approved 2026-10-22). SYNTHETIC organisations, evidence and data.

  * the flag is a kill switch only: never sufficient on its own;
  * general availability = the registry AVAILABLE (G1–G8 + Q9 + the key);
  * a pilot = one named EVALUATION organisation, four-eyes, revocable,
    expiring; needs G1 G2 G4 G5 G7 + Q9 + hosting + the key (D2); its output
    is non-binding (sandbox PAC, no payments, no filings, watermark, banner);
  * the governed master-data copy into a new live organisation (D5).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests import _mx_authority_helpers as ah
from tests import _mx_run_helpers as rh

SA_A = SimpleNamespace(id=991, organization_id=None, role="super_admin", is_active=True)
SA_B = SimpleNamespace(id=992, organization_id=None, role="super_admin", is_active=True)


def _P():
    from app.modules.payroll import mexico_pilot_service as P

    return P


def _D():
    from app.modules.payroll import mexico_dormancy as D

    return D


def _evidence(db, tag, created_by=801, reviewer=802):
    from app.modules.payroll.models import SourceArtifact

    db.add(SourceArtifact(agency="Zoiko (SYNTHETIC)", title=f"{tag} evidence", form_number=tag,
                          created_by_id=created_by, reviewer_id=reviewer, file_path="evidence/mx.pdf"))
    db.flush()


def _pilot_ready(db, monkeypatch):
    """Everything D2 requires for a pilot grant, all SYNTHETIC."""
    from app.config import settings

    for g in ("G1", "G2", "G4", "G5", "G7"):
        _evidence(db, f"MX-GATE-{g}")
    _evidence(db, "MX-DECISION-Q9")
    _evidence(db, "MX-DECISION-HOSTING")
    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "MX_IDENTITY_TOKEN_KEY", "SYNTHETIC-test-key")
    db.commit()


def _registry(db, availability):
    from app.modules.billing.models import JurisdictionServiceRegistry as R

    row = db.query(R).filter(R.country == "MX").first()
    if row is None:
        db.add(R(country="MX", availability=availability))
    else:
        row.availability = availability
    db.commit()


def _real_registry(monkeypatch):
    """Undo the domain-test helper's general-availability stub."""
    import importlib

    from app.modules.payroll import mexico_dormancy

    real = importlib.reload(mexico_dormancy).registry_available
    monkeypatch.setattr(mexico_dormancy, "registry_available", real)


def _expiry(days=60):
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _granted(db, monkeypatch, org_id):
    _pilot_ready(db, monkeypatch)
    g = _P().propose_grant(db, org_id, {"reason": "SYNTHETIC: G8 parallel run", "expiresOn": _expiry()}, SA_A.id)
    return _P().approve_grant(db, g["id"], SA_B.id)


def _evaluation(db, org):
    org.workspace_type = "EVALUATION"
    db.commit()


# ── the kill switch and the two levels ──────────────────────────────────────

def test_the_flag_alone_never_opens_mexico(db, monkeypatch):
    from app.config import settings
    from tests._mx_employer_helpers import make_org

    o = make_org(db, code="MXP1")
    D = _D()
    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", True)
    assert D.onboarding_enabled(db, o.org.id) is False                    # no registry row
    _registry(db, "PLANNED")
    assert D.onboarding_enabled(db, o.org.id) is False and D.onboarding_enabled(db) is False
    _registry(db, "AVAILABLE")
    assert D.onboarding_enabled(db, o.org.id) is True                     # general availability
    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", False)
    assert D.onboarding_enabled(db, o.org.id) is False                    # the kill switch wins
    assert D.onboarding_enabled(None, o.org.id) is False                  # no session: closed
    assert D.entering_mexico_refusal("India", "Mexico") == D.DORMANT_MESSAGE


# ── pilot grants ────────────────────────────────────────────────────────────

def test_a_grant_is_for_an_evaluation_org_with_a_bounded_expiry(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from tests._mx_employer_helpers import make_org

    o = make_org(db, code="MXP2")
    with pytest.raises(MXBlock) as exc:
        _P().propose_grant(db, o.org.id, {"reason": "x", "expiresOn": _expiry()}, SA_A.id)
    assert exc.value.key == "MX_PILOT_EVALUATION_ONLY"
    _evaluation(db, o.org)
    with pytest.raises(Exception, match="at most 120 days"):
        _P().propose_grant(db, o.org.id, {"reason": "x", "expiresOn": _expiry(121)}, SA_A.id)
    with pytest.raises(Exception, match="future"):
        _P().propose_grant(db, o.org.id, {"reason": "x", "expiresOn": _expiry(-1)}, SA_A.id)
    with pytest.raises(Exception, match="reason"):
        _P().propose_grant(db, o.org.id, {"reason": " ", "expiresOn": _expiry()}, SA_A.id)
    assert _P().propose_grant(db, o.org.id, {"reason": "SYNTHETIC", "expiresOn": _expiry(120)}, SA_A.id)["status"] == "PROPOSED"


def test_approval_is_four_eyes_and_needs_every_d2_precondition(db, monkeypatch):
    from app.config import settings
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from tests._mx_employer_helpers import make_org

    _real_registry(monkeypatch)
    o = make_org(db, code="MXP3")
    _evaluation(db, o.org)
    g = _P().propose_grant(db, o.org.id, {"reason": "SYNTHETIC", "expiresOn": _expiry()}, SA_A.id)
    with pytest.raises(MXBlock) as exc:
        _P().approve_grant(db, g["id"], SA_A.id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    with pytest.raises(MXBlock) as exc:
        _P().approve_grant(db, g["id"], SA_B.id)
    assert exc.value.key == "MX_PILOT_PRECONDITIONS"
    for needed in ("kill switch", "Gate G1", "Gate G2", "Gate G4", "Gate G5", "Gate G7", "Q9", "Hosting",
                   "MX_IDENTITY_TOKEN_KEY"):
        assert needed in exc.value.reason, needed
    assert "Gate G3" not in exc.value.reason and "Gate G6" not in exc.value.reason   # produced during the pilot
    _pilot_ready(db, monkeypatch)
    monkeypatch.setattr(settings, "MX_IDENTITY_TOKEN_KEY", "")
    with pytest.raises(MXBlock, match="MX_IDENTITY_TOKEN_KEY"):
        _P().approve_grant(db, g["id"], SA_B.id)
    monkeypatch.setattr(settings, "MX_IDENTITY_TOKEN_KEY", "SYNTHETIC-test-key")
    assert _P().approve_grant(db, g["id"], SA_B.id)["state"] == "ACTIVE"


def test_a_grant_opens_only_its_organisation_and_revoke_or_expiry_closes_it(db, monkeypatch):
    from app.modules.payroll.models import PayrollMxPilotGrant
    from tests._mx_employer_helpers import make_org

    _real_registry(monkeypatch)
    D = _D()
    pilot, other = make_org(db, code="MXP4"), make_org(db, code="MXP4B")
    _evaluation(db, pilot.org)
    _registry(db, "PLANNED")
    g = _granted(db, monkeypatch, pilot.org.id)
    assert D.onboarding_enabled(db, pilot.org.id) is True and D.pilot_active(db, pilot.org.id)
    assert D.onboarding_enabled(db, other.org.id) is False
    assert D.entering_mexico_refusal("India", "Mexico", db, other.org.id) == D.DORMANT_MESSAGE
    assert D.entering_mexico_refusal("India", "Mexico", db, pilot.org.id) is None
    row = db.get(PayrollMxPilotGrant, g["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert D.onboarding_enabled(db, pilot.org.id) is False                # expired
    row.expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    db.commit()
    with pytest.raises(Exception, match="reason"):
        _P().revoke_grant(db, g["id"], " ", SA_A.id)
    _P().revoke_grant(db, g["id"], "SYNTHETIC: stop", SA_A.id)
    assert D.onboarding_enabled(db, pilot.org.id) is False
    _registry(db, "AVAILABLE")                                            # a pilot org never becomes live (D5)
    assert D.onboarding_enabled(db, pilot.org.id) is False and D.onboarding_enabled(db, other.org.id) is True


# ── non-binding output ──────────────────────────────────────────────────────

def _pilot_world(db, monkeypatch, code):
    w = rh.world(db, monkeypatch, code=code)
    _evaluation(db, w.org)
    _granted(db, monkeypatch, w.org.id)
    return w


def test_pilot_runs_are_recorded_watermarked_and_never_paid_or_filed(db, monkeypatch):
    from app.modules.payroll import (
        mexico_filing_service, mexico_imss_service, mexico_journal_service, mexico_payment_service, service,
    )
    from app.modules.payroll.engine.countries.mexico import MXBlock

    w = _pilot_world(db, monkeypatch, "MXP5")
    ah.commit(db, w, w.run)
    assert w.run.mx_approval_fingerprint["pilot"] is True
    (item,) = ah.rh.mx_items(db, w.run)
    drawn = []
    real = service._draw_evaluation_watermark
    monkeypatch.setattr(service, "_draw_evaluation_watermark",
                        lambda c, wd, h, f="Helvetica-Bold", text="PREVIEW — EVALUATION ONLY": drawn.append(text)
                        or real(c, wd, h, f, text=text))
    pdf = service.generate_payslip_pdf_bytes(db, item.id, w.org.id)
    assert pdf.startswith(b"%PDF") and _P().PILOT_WATERMARK in drawn
    for call in (lambda: mexico_payment_service.create_batch(db, w.org.id, w.run.id, w.users[0].id),):
        with pytest.raises(MXBlock) as exc:
            call()
        assert exc.value.key == "MX_PILOT_NO_PAYMENTS"
    mexico_filing_service.accrue(db, w.org.id, w.users[0].id)
    liab = mexico_filing_service.list_liabilities(db, w.org.id)[0]
    for call in (lambda: mexico_imss_service.export_worklist(db, w.org.id, w.users[0].id),
                 lambda: mexico_filing_service.file_liability(db, w.org.id, liab["id"], "SYN-REF", w.users[0].id),
                 lambda: mexico_filing_service.pay_liability(db, w.org.id, liab["id"], "SYN-REF", w.users[0].id)):
        with pytest.raises(MXBlock) as exc:
            call()
        assert exc.value.key == "MX_PILOT_NO_FILINGS"
    accounts = {code: f"SYN-{n}" for n, (code, _, _) in enumerate(mexico_journal_service.LINE_TYPES, start=100)}
    m = mexico_journal_service.create_mapping(db, w.org.id, {"accounts": accounts}, w.users[0].id)
    mexico_journal_service.approve_mapping(db, w.org.id, m["id"], w.users[1].id)
    out = mexico_journal_service.export_journal(db, w.org.id, w.run.id, w.users[0].id)
    assert out["content"].startswith(_P().PILOT_JOURNAL_BANNER)


def test_a_pilot_stamps_only_through_a_sandbox_pac(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from tests._mx_employer_helpers import make_org

    w = _pilot_world(db, monkeypatch, "MXP6")
    with pytest.raises(MXBlock) as exc:
        _P().refuse_non_sandbox_pac(db, w.org.id, "PRODUCTION")
    assert exc.value.key == "MX_PILOT_SANDBOX_ONLY"
    _P().refuse_non_sandbox_pac(db, w.org.id, "SANDBOX")                  # allowed
    live = make_org(db, code="MXP6L")
    _P().refuse_non_sandbox_pac(db, live.org.id, "PRODUCTION")            # not a pilot: unchanged


def test_a_live_org_is_unaffected_by_pilot_rules(db, monkeypatch):
    from app.modules.payroll import mexico_payment_service

    w = ah.committed_world(db, monkeypatch, code="MXP7")
    fields = dict(w.employee.compliance_fields or {})
    fields["clabe"] = "002180700012345678"                                # SYNTHETIC
    w.employee.compliance_fields = fields
    db.commit()
    assert w.run.mx_approval_fingerprint.get("pilot") is False
    assert mexico_payment_service.create_batch(db, w.org.id, w.run.id, w.users[0].id)["status"] == "DRAFT"


# ── the governed master-data copy (D5) ──────────────────────────────────────

def _live_target(db, code):
    from tests._mx_employer_helpers import make_org

    t = make_org(db, code=code)
    t.org.workspace_type = "PRODUCTION"
    db.commit()
    return t


def test_the_master_copy_is_four_eyes_unchanged_source_and_reported(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import (
        EmployeeStatutoryProfile, PayrollEmployee, PayrollMxEmployerProfile, PayrollMxImssRegistration, PayrollRun,
    )

    w = _pilot_world(db, monkeypatch, "MXP8")
    ah.commit(db, w, w.run)
    target = _live_target(db, "MXP8L")
    _registry(db, "AVAILABLE")
    c = _P().propose_copy(db, w.org.id, target.org.id, "SYNTHETIC: go-live", SA_A.id)
    assert c["plan"]["counts"]["employerProfiles"] == 1 and c["plan"]["counts"]["employees"] == 1
    assert c["plan"]["notCopied"]["payrollRuns"] >= 1
    with pytest.raises(MXBlock) as exc:
        _P().approve_copy(db, c["id"], SA_A.id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    w.employee.name = "SYNTHETIC renamed after the proposal"
    db.commit()
    with pytest.raises(MXBlock) as exc:
        _P().approve_copy(db, c["id"], SA_B.id)
    assert exc.value.key == "MX_COPY_SOURCE_CHANGED"
    _P().cancel_copy(db, c["id"], "SYNTHETIC", SA_A.id)
    c = _P().propose_copy(db, w.org.id, target.org.id, "SYNTHETIC: go-live", SA_A.id)
    done = _P().approve_copy(db, c["id"], SA_B.id)
    assert done["status"] == "EXECUTED" and done["report"]["differences"] == []
    assert done["report"]["copied"]["employees"] == 1 and done["report"]["copied"]["statutoryProfiles"] == 1
    t_reg = db.query(PayrollMxImssRegistration).filter(PayrollMxImssRegistration.organization_id == target.org.id).one()
    t_emp = db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == target.org.id).one()
    t_prof = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.organization_id == target.org.id).one()
    assert t_emp.employee_code == w.employee.employee_code and t_prof.employee_id == t_emp.id
    assert t_prof.mx_imss_registration_id == t_reg.id != w.registration.id          # remapped, not shared
    assert t_reg.registro_patronal == w.registration.registro_patronal
    assert db.query(PayrollMxEmployerProfile).filter(PayrollMxEmployerProfile.organization_id == target.org.id).one() \
        .stamp_test_status == "NOT_TESTED"                                           # environment-bound: reset
    assert db.query(PayrollRun).filter(PayrollRun.organization_id == target.org.id).count() == 0   # never results
    with pytest.raises(MXBlock, match="already has Mexican employer data"):
        _P().propose_copy(db, w.org.id, target.org.id, "again", SA_A.id)


def test_the_copy_refuses_without_ga_into_an_evaluation_or_from_a_non_pilot(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    w = _pilot_world(db, monkeypatch, "MXP9")
    _real_registry(monkeypatch)                         # after the world: its helper stubs general availability
    target = _live_target(db, "MXP9L")
    _registry(db, "PLANNED")
    with pytest.raises(MXBlock, match="general availability"):
        _P().propose_copy(db, w.org.id, target.org.id, "x", SA_A.id)
    _registry(db, "AVAILABLE")
    target.org.workspace_type = "EVALUATION"
    db.commit()
    with pytest.raises(MXBlock, match="live"):
        _P().propose_copy(db, w.org.id, target.org.id, "x", SA_A.id)
    with pytest.raises(MXBlock, match="not a pilot organisation"):
        _P().propose_copy(db, target.org.id, w.org.id, "x", SA_A.id)


# ── routes ──────────────────────────────────────────────────────────────────

def test_pilot_routes(db, monkeypatch):
    from tests._mx_employer_helpers import http, make_org, principal

    o = make_org(db, code="MXPAPI")
    _evaluation(db, o.org)
    _pilot_ready(db, monkeypatch)
    base = "/api/super-admin/compliance/mexico"
    with http(db, SA_A) as c:
        r = c.post(f"{base}/pilot-grants", json={"organizationId": o.org.id, "reason": "SYNTHETIC", "expiresOn": _expiry()})
        assert r.status_code == 200, r.text
        own = c.post(f"{base}/pilot-grants/{r.json()['id']}/approve")
        assert own.status_code == 400 and "MX_FOUR_EYES_REQUIRED" in own.text
    with http(db, SA_B) as c:
        ok = c.post(f"{base}/pilot-grants/{r.json()['id']}/approve")
        assert ok.status_code == 200 and ok.json()["state"] == "ACTIVE", ok.text
        listed = c.get(f"{base}/pilot-grants").json()
        assert listed["grants"][0]["state"] == "ACTIVE" and all(p["met"] for p in listed["preconditions"])
        assert c.get(f"{base}/readiness").json()["level"] == "PILOT (1 organisation)"
    with http(db, principal(o.org.id, o.users[0].id)) as c:
        s = c.get("/api/payroll/mexico/pilot-status")
        assert s.status_code == 200 and s.json()["active"] is True, s.text
    with http(db, SA_A) as c:
        assert c.post(f"{base}/pilot-grants/{r.json()['id']}/revoke", json={"reason": "SYNTHETIC"}).json()["status"] == "REVOKED"
    with http(db, principal(o.org.id, o.users[0].id)) as c:
        assert c.get("/api/payroll/mexico/pilot-status").status_code == 403        # closed at once


def test_master_copy_routes_stay_retired_and_the_copy_returns_no_worker_values(db, monkeypatch):
    """ZP-PRIV: a Super Admin never handles worker data, and statutory actions
    are tenant-run (decision 3). The copy is built and tested here at the
    service level; its two worker-touching routes stay RETIRED until the
    ZP-PRIV owner decides how a cross-tenant copy is authorised."""
    import json

    from tests._mx_employer_helpers import http

    w = _pilot_world(db, monkeypatch, "MXPCAPI")
    target = _live_target(db, "MXPCAPIL")
    _registry(db, "AVAILABLE")
    base = "/api/super-admin/compliance/mexico"
    with http(db, SA_A) as c:
        r = c.post(f"{base}/master-copies", json={"sourceOrganizationId": w.org.id,
                                                  "targetOrganizationId": target.org.id, "reason": "SYNTHETIC"})
        assert r.status_code == 403, r.text                                  # retired (ACCESS_DENIED)
        assert c.post(f"{base}/master-copies/1/approve").status_code == 403
        assert c.get(f"{base}/master-copies").status_code == 200           # counts and ids only
    proposed = _P().propose_copy(db, w.org.id, target.org.id, "SYNTHETIC", SA_A.id)
    done = _P().approve_copy(db, proposed["id"], SA_B.id)
    body = json.dumps([proposed, done, _P().list_copies(db)], default=str)
    fields = w.employee.compliance_fields or {}
    for secret in (w.employee.name, w.employee.email, fields.get("rfc"), fields.get("curp"), fields.get("nss")):
        if secret:
            assert secret not in body, secret                                # ids, counts and column names only
