"""Mexico Phase 10g — the "no new Mexican organisations" switch. Four-eyes
(Super Admins), audited; while paused no organisation can BECOME Mexican and no
pilot grant can be approved, while organisations already Mexican keep running;
general availability needs it not paused. SYNTHETIC."""

import pytest

from tests import test_mexico_pilot as tp

SA_A, SA_B = tp.SA_A, tp.SA_B


def _P():
    from app.modules.payroll import mexico_pilot_service as P

    return P


def _paused(db):
    p = _P().propose_onboarding_change(db, {"action": "PAUSE", "reason": "SYNTHETIC: a go-live check failed"}, SA_A.id)
    return _P().approve_onboarding_change(db, p["id"], SA_B.id)


def test_pausing_is_four_eyes_audited_and_resumable(db):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import TaxConfigurationAudit as A

    P = _P()
    with pytest.raises(Exception, match="reason"):
        P.propose_onboarding_change(db, {"action": "PAUSE", "reason": " "}, SA_A.id)
    with pytest.raises(Exception, match="already not paused"):
        P.propose_onboarding_change(db, {"action": "RESUME", "reason": "x"}, SA_A.id)
    p = P.propose_onboarding_change(db, {"action": "PAUSE", "reason": "SYNTHETIC"}, SA_A.id)
    with pytest.raises(MXBlock) as exc:
        P.approve_onboarding_change(db, p["id"], SA_A.id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    assert P.onboarding_pause_state(db)["paused"] is False                # a proposal changes nothing
    P.approve_onboarding_change(db, p["id"], SA_B.id)
    assert P.onboarding_pause_state(db)["paused"] is True
    r = P.propose_onboarding_change(db, {"action": "RESUME", "reason": "SYNTHETIC: fixed"}, SA_B.id)
    P.approve_onboarding_change(db, r["id"], SA_A.id)
    assert P.onboarding_pause_state(db)["paused"] is False
    w = P.propose_onboarding_change(db, {"action": "PAUSE", "reason": "x"}, SA_A.id)
    assert P.withdraw_onboarding_change(db, w["id"], SA_A.id)["status"] == "WITHDRAWN"
    actions = {a.action for a in db.query(A).filter(A.entity_type == "mx_onboarding_pause")}
    assert {"propose_mx_onboarding_change", "approve_mx_onboarding_change", "withdraw_mx_onboarding_change"} <= actions


def test_while_paused_no_new_org_becomes_mexican_but_existing_ones_keep_running(db, monkeypatch):
    from app.modules.payroll import mexico_dormancy as D
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason
    from tests._mx_employer_helpers import make_org

    tp._real_registry(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", True)
    tp._registry(db, "AVAILABLE")
    existing = make_org(db, code="MXOP1")                                 # already Mexican
    newcomer = make_org(db, code="MXOP2", country="IN")
    assert get_jurisdiction_change_block_reason(db, "India", "Mexico", newcomer.org.id) is None
    _paused(db)
    assert get_jurisdiction_change_block_reason(db, "India", "Mexico", newcomer.org.id) == D.PAUSED_MESSAGE
    assert D.onboarding_enabled(db, existing.org.id) is True               # live employers keep running
    assert get_jurisdiction_change_block_reason(db, "India", "Germany", newcomer.org.id) is None   # not Mexico


def test_while_paused_no_pilot_grant_and_no_general_availability(db, monkeypatch):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.billing.models import JurisdictionServiceRegistry
    from tests._mx_employer_helpers import make_org

    tp._real_registry(monkeypatch)
    o = make_org(db, code="MXOP3")
    tp._evaluation(db, o.org)
    tp._pilot_ready(db, monkeypatch)
    g = _P().propose_grant(db, o.org.id, {"reason": "SYNTHETIC", "expiresOn": tp._expiry()}, SA_A.id)
    _paused(db)
    with pytest.raises(MXBlock) as exc:
        _P().approve_grant(db, g["id"], SA_B.id)
    assert exc.value.key == "MX_PILOT_PRECONDITIONS" and "not paused" in exc.value.reason
    db.add(JurisdictionServiceRegistry(country="MX", availability="PLANNED"))
    for i in (3, 6, 8):
        tp._evidence(db, f"MX-GATE-G{i}")
    db.commit()
    with pytest.raises(Exception, match="not paused"):
        jurisdiction_hooks.call("MX", "service_registry_transition", db, "AVAILABLE", "SYNTHETIC", actor_id=SA_B.id)


def test_onboarding_pause_routes(db):
    from tests._mx_employer_helpers import http

    base = "/api/super-admin/compliance/mexico"
    with http(db, SA_A) as c:
        r = c.post(f"{base}/onboarding-pause", json={"action": "PAUSE", "reason": "SYNTHETIC"})
        assert r.status_code == 200, r.text
        assert c.post(f"{base}/onboarding-pause/{r.json()['id']}/approve").status_code == 400   # four-eyes
    with http(db, SA_B) as c:
        assert c.post(f"{base}/onboarding-pause/{r.json()['id']}/approve").json()["status"] == "APPROVED"
        assert c.get(f"{base}/onboarding-pause").json()["paused"] is True
        assert c.get(f"{base}/readiness").json()["onboardingPaused"] is True
