"""Mexico Phase 10f — option B: the tenant-run master-data handshake (pilot →
live organisation of the same employer). SYNTHETIC organisations and data.

The four safeguards: same employer RFC on both organisations; a one-time
release expiring after 7 days, revocable before use; two pilot-org admins
release and two live-org admins import after reviewing the diff; audited on
both sides with identifiers masked. The retired Super Admin routes stay
retired (tests/test_mexico_pilot.py)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests import _mx_authority_helpers as ah
from tests import test_mexico_pilot as tp


def _T():
    from app.modules.payroll import mexico_transfer_service as T

    return T


def _world(db, monkeypatch, code):
    """A pilot organisation (its grant approved) with a committed run, general
    availability open on the REAL registry, and a live organisation of the
    same employer (its own open employer profile, same RFC, two admins)."""
    from app.modules.payroll.models import PayrollMxEmployerProfile
    from tests._mx_employer_helpers import make_org, new_employer

    w = tp._pilot_world(db, monkeypatch, code)
    ah.commit(db, w, w.run)
    tp._real_registry(monkeypatch)
    tp._registry(db, "AVAILABLE")
    live = make_org(db, code=f"{code}L", admins=2)
    live.org.workspace_type = "PRODUCTION"
    db.commit()
    rfc = db.query(PayrollMxEmployerProfile).filter(PayrollMxEmployerProfile.organization_id == w.org.id).one().rfc
    new_employer(db, live.org.id, actor=live.users[0].id, rfc=rfc)
    return w, live


def _released(db, w, live):
    T = _T()
    r = T.propose_release(db, w.org.id, {"targetOrganizationId": live.org.id, "reason": "SYNTHETIC go-live"},
                          w.users[0].id)
    return T.approve_release(db, w.org.id, r["id"], w.users[1].id)


def _imported(db, w, live, rel):
    T = _T()
    preview = T.preview_import(db, live.org.id, rel["id"])
    c = T.propose_import(db, live.org.id, rel["id"], {"previewSha256": preview["previewSha256"], "reason": "SYNTHETIC"},
                         live.users[0].id)
    return preview, T.approve_import(db, live.org.id, c["id"], live.users[1].id)


# ── 1. same employer (RFC) ──────────────────────────────────────────────────

def test_the_live_org_must_have_recorded_the_same_employer(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxEmployerProfile
    from tests._mx_employer_helpers import make_org, new_employer

    w = tp._pilot_world(db, monkeypatch, "MXT1")
    tp._real_registry(monkeypatch)
    tp._registry(db, "AVAILABLE")
    live = make_org(db, code="MXT1L", admins=2)
    live.org.workspace_type = "PRODUCTION"
    db.commit()
    T = _T()
    with pytest.raises(MXBlock) as exc:                                   # no employer recorded yet
        T.propose_release(db, w.org.id, {"targetOrganizationId": live.org.id, "reason": "x"}, w.users[0].id)
    assert exc.value.key == "MX_TRANSFER_RFC_MISMATCH"
    new_employer(db, live.org.id, actor=live.users[0].id, rfc="XYZ010101AB1")   # a different employer
    with pytest.raises(MXBlock) as exc:
        T.propose_release(db, w.org.id, {"targetOrganizationId": live.org.id, "reason": "x"}, w.users[0].id)
    assert exc.value.key == "MX_TRANSFER_RFC_MISMATCH" and "XYZ010101AB1" not in exc.value.reason   # masked
    pilot_rfc = db.query(PayrollMxEmployerProfile).filter(PayrollMxEmployerProfile.organization_id == w.org.id).one().rfc
    assert pilot_rfc not in exc.value.reason


# ── 2. the one-time release ────────────────────────────────────────────────

def test_the_release_is_four_eyes_expires_in_7_days_and_is_revocable_before_use(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxMasterRelease

    w, live = _world(db, monkeypatch, "MXT2")
    T = _T()
    r = T.propose_release(db, w.org.id, {"targetOrganizationId": live.org.id, "reason": "SYNTHETIC"}, w.users[0].id)
    assert r["state"] == "PROPOSED" and r["plan"]["employerProfiles"].startswith("matched by RFC")
    with pytest.raises(MXBlock) as exc:
        T.approve_release(db, w.org.id, r["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    rel = T.approve_release(db, w.org.id, r["id"], w.users[1].id)
    left = datetime.fromisoformat(rel["expiresAt"]) - datetime.now(timezone.utc)
    assert rel["state"] == "AVAILABLE" and timedelta(days=6, hours=23) < left <= timedelta(days=7)
    with pytest.raises(Exception, match="reason"):
        T.revoke_release(db, w.org.id, rel["id"], " ", w.users[0].id)
    assert T.revoke_release(db, w.org.id, rel["id"], "SYNTHETIC: wrong target", w.users[0].id)["state"] == "REVOKED"
    with pytest.raises(MXBlock) as exc:
        T.preview_import(db, live.org.id, rel["id"])
    assert exc.value.key == "MX_TRANSFER_RELEASE_UNAVAILABLE"
    again = _released(db, w, live)                                        # a new release after a revocation
    row = db.get(PayrollMxMasterRelease, again["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    with pytest.raises(MXBlock) as exc:                                   # expired: unusable
        T.preview_import(db, live.org.id, again["id"])
    assert exc.value.key == "MX_TRANSFER_RELEASE_UNAVAILABLE"


# ── 3. the import: reviewed diff, four eyes, one use ───────────────────────

def test_the_import_needs_the_reviewed_diff_and_a_second_admin_and_uses_the_release_once(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import (
        EmployeeStatutoryProfile, PayrollEmployee, PayrollMxEmployerProfile, PayrollMxImssRegistration, PayrollRun,
    )

    w, live = _world(db, monkeypatch, "MXT3")
    rel = _released(db, w, live)
    T = _T()
    preview = T.preview_import(db, live.org.id, rel["id"])
    fields = w.employee.compliance_fields or {}
    body = json.dumps(preview, default=str)
    for secret in (fields.get("rfc"), fields.get("curp"), fields.get("nss"), fields.get("clabe")):
        if secret:
            assert secret not in body, secret                             # identifiers masked in the diff
    assert preview["willCreate"]["employees"] == 1 and "employerProfiles" not in preview["willCreate"]
    with pytest.raises(MXBlock) as exc:
        T.propose_import(db, live.org.id, rel["id"], {"previewSha256": "not-the-reviewed-one", "reason": "x"},
                         live.users[0].id)
    assert exc.value.key == "MX_TRANSFER_DIFF_NOT_REVIEWED"
    c = T.propose_import(db, live.org.id, rel["id"], {"previewSha256": preview["previewSha256"], "reason": "SYNTHETIC"},
                         live.users[0].id)
    with pytest.raises(MXBlock) as exc:
        T.approve_import(db, live.org.id, c["id"], live.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    done = T.approve_import(db, live.org.id, c["id"], live.users[1].id)
    assert done["status"] == "EXECUTED" and done["report"]["differences"] == []
    assert done["report"]["employerProfilesMatchedByRfc"] == 1 and done["report"]["copied"]["employerProfiles"] == 0
    live_profile = db.query(PayrollMxEmployerProfile).filter(PayrollMxEmployerProfile.organization_id == live.org.id).one()
    reg = db.query(PayrollMxImssRegistration).filter(PayrollMxImssRegistration.organization_id == live.org.id).one()
    assert reg.employer_profile_id == live_profile.id                     # under the live org's own employer
    emp = db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == live.org.id).one()
    prof = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.organization_id == live.org.id).one()
    assert prof.employee_id == emp.id and prof.mx_imss_registration_id == reg.id
    assert db.query(PayrollRun).filter(PayrollRun.organization_id == live.org.id).count() == 0   # never results
    assert T.transfer_status(db, w.org.id)["outgoing"][0]["state"] == "USED"
    with pytest.raises(MXBlock) as exc:                                   # one use only
        T.preview_import(db, live.org.id, rel["id"])
    assert exc.value.key == "MX_TRANSFER_RELEASE_UNAVAILABLE"
    with pytest.raises(Exception, match="used release cannot be revoked"):
        T.revoke_release(db, w.org.id, rel["id"], "late", w.users[0].id)


def test_a_change_to_the_pilot_after_the_release_refuses_the_import(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    w, live = _world(db, monkeypatch, "MXT4")
    rel = _released(db, w, live)
    T = _T()
    preview = T.preview_import(db, live.org.id, rel["id"])
    c = T.propose_import(db, live.org.id, rel["id"], {"previewSha256": preview["previewSha256"], "reason": "x"},
                         live.users[0].id)
    w.employee.name = "SYNTHETIC renamed after the release"
    db.commit()
    with pytest.raises(MXBlock) as exc:
        T.approve_import(db, live.org.id, c["id"], live.users[1].id)
    assert exc.value.key == "MX_COPY_SOURCE_CHANGED"


# ── 4. audited on both sides, identifiers masked ───────────────────────────

def test_every_step_is_audited_for_both_organisations_with_identifiers_masked(db, monkeypatch):
    from app.modules.payroll.models import TaxConfigurationAudit as A

    w, live = _world(db, monkeypatch, "MXT5")
    rel = _released(db, w, live)
    _imported(db, w, live, rel)
    rows = db.query(A).filter(A.entity_type.in_(("mx_master_release", "mx_master_import"))).all()
    by_action = {}
    for r in rows:
        by_action.setdefault(r.action, set()).add((r.new_value or {}).get("organizationId"))
    for action in ("propose_mx_master_release", "release_mx_master_data", "propose_mx_master_import",
                   "execute_mx_master_import"):
        assert by_action.get(action) == {w.org.id, live.org.id}, action   # one row per side
    fields = w.employee.compliance_fields or {}
    dump = json.dumps([[r.new_value, r.reason] for r in rows], default=str)
    for secret in (fields.get("rfc"), fields.get("curp"), fields.get("nss"), fields.get("clabe"), w.employee.name):
        if secret:
            assert secret not in dump, secret
    from app.modules.payroll.models import PayrollMxEmployerProfile

    rfc = db.query(PayrollMxEmployerProfile).filter(PayrollMxEmployerProfile.organization_id == w.org.id).first().rfc
    assert rfc not in dump and "*" in json.dumps(by_action and [r.new_value.get("employerRfcs") for r in rows
                                                               if r.new_value.get("employerRfcs")])


# ── guards and tenant scope ─────────────────────────────────────────────────

def test_only_a_pilot_releases_only_a_live_org_imports_and_ga_is_required(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    w, live = _world(db, monkeypatch, "MXT6")
    T = _T()
    with pytest.raises(MXBlock) as exc:
        T.propose_release(db, live.org.id, {"targetOrganizationId": w.org.id, "reason": "x"}, live.users[0].id)
    assert exc.value.key == "MX_TRANSFER_NOT_PILOT"
    rel = _released(db, w, live)
    with pytest.raises(MXBlock) as exc:
        T.preview_import(db, w.org.id, rel["id"])
    assert exc.value.key == "MX_TRANSFER_NOT_LIVE"
    tp._registry(db, "PLANNED")
    with pytest.raises(MXBlock) as exc:
        T.propose_release(db, w.org.id, {"targetOrganizationId": live.org.id, "reason": "x"}, w.users[0].id)
    assert exc.value.key == "MX_TRANSFER_REQUIRES_GA"


def test_the_import_reads_the_pilot_only_through_its_own_tenant_scope(db, monkeypatch):
    """Under the live organisation's REAL tenant context (as a request runs),
    worker reads are filtered to the live organisation — the copy still finds
    the pilot's rows, because it reads them inside tenant_session(pilot)."""
    from app.core.authz import tenant_context as tc

    w, live = _world(db, monkeypatch, "MXT7")
    rel = _released(db, w, live)
    tc.set_context(db, tc.TenantContext(tc.KIND_TENANT, live.org.id))
    try:
        preview, done = _imported(db, w, live, rel)
    finally:
        tc.set_context(db, None)
    assert preview["willCreate"]["employees"] == 1 and done["report"]["copied"]["employees"] == 1


# ── routes ──────────────────────────────────────────────────────────────────

def test_transfer_routes_for_both_organisations(db, monkeypatch):
    from tests._mx_employer_helpers import http, principal

    w, live = _world(db, monkeypatch, "MXTAPI")
    base = "/api/payroll/mexico-transfer"
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        r = c.post(f"{base}/releases", json={"targetOrganizationId": live.org.id, "reason": "SYNTHETIC"})
        assert r.status_code == 200, r.text
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        ok = c.post(f"{base}/releases/{r.json()['id']}/release")
        assert ok.status_code == 200 and ok.json()["state"] == "AVAILABLE", ok.text
    with http(db, principal(live.org.id, live.users[0].id)) as c:
        st = c.get(f"{base}/status")
        assert st.status_code == 200 and st.json()["incoming"][0]["state"] == "AVAILABLE", st.text
        pv = c.get(f"{base}/releases/{r.json()['id']}/preview")
        assert pv.status_code == 200, pv.text
        prop = c.post(f"{base}/releases/{r.json()['id']}/import",
                      json={"previewSha256": pv.json()["previewSha256"], "reason": "SYNTHETIC"})
        assert prop.status_code == 200, prop.text
    with http(db, principal(live.org.id, live.users[1].id)) as c:
        done = c.post(f"{base}/imports/{prop.json()['id']}/approve")
        assert done.status_code == 200 and done.json()["status"] == "EXECUTED", done.text


# ── PILOT on the run screen and the payslip view ───────────────────────────

def test_a_pilot_run_and_its_payslips_say_pilot(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = tp._pilot_world(db, monkeypatch, "MXT8")
    ah.commit(db, w, w.run)
    assert mexico_run_service.run_status(db, w.run)["payroll"]["pilot"] is True
    (item,) = ah.rh.mx_items(db, w.run)
    assert item.mx_calculation_snapshot["pilot"] is True
    live = ah.committed_world(db, monkeypatch, code="MXT8L")
    (litem,) = ah.rh.mx_items(db, live.run)
    assert mexico_run_service.run_status(db, live.run)["payroll"]["pilot"] is False
    assert litem.mx_calculation_snapshot["pilot"] is False
