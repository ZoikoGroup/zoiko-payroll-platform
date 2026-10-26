"""Mexico Phase 3 — employer readiness (panel H) and its mapping onto G1–G8.
Every mapped item cites the spec §22 gate definition; items without a clear
gate are "unmapped"; LIVE eligibility is unreachable in Phase 3; `on` is
always explicit. SYNTHETIC data."""

from datetime import date

import pytest

from tests._mx_employer_helpers import GCP_REF, active_pack, make_org, new_employer, new_registration, self_signed_cert


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


def _items(r, key):
    return [i for i in r["items"] if i["key"] == key]


def test_on_is_required():
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="explicit date"):
        _svc().organisation_readiness(None, 1, None)


def test_every_mapped_item_cites_the_section_22_definition_verbatim(db):
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    new_registration(db, t.org.id, emp["id"])
    r = _svc().organisation_readiness(db, t.org.id, date(2026, 3, 1))["employers"][0]
    for item in r["items"]:
        if item["gates"]:
            assert item["gateMapping"] == "mapped"
            assert item["gateBasis"] == {g: _svc().GATE_DEFINITIONS[g] for g in item["gates"]}
        else:
            assert item["gateMapping"] == "unmapped" and item["gateBasis"] == {}
    assert set(_svc().GATE_DEFINITIONS) == {f"G{i}" for i in range(1, 9)}
    assert "time_record" in r["unmapped"]


def test_live_is_unreachable_in_phase_3_even_with_everything_configured(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(c, "MX_RISK_PREMIUM_PERIOD", c.RiskPremiumPeriodRule(3, 1, "S29", "SYNTHETIC"))
    t = make_org(db, admins=2)
    emp = new_employer(db, t.org.id, pacProvider="SYNTHETIC PAC", pacEnvironment="SANDBOX")
    reg = new_registration(db, t.org.id, emp["id"], infonavit_operating_model="SUA")
    active_pack(db)
    svc = _svc()
    csd = svc.create_credential(db, t.org.id, emp["id"], {"kind": "CSD", "secret_ref": GCP_REF}, 701)
    der, _c, _k = self_signed_cert()
    svc.attach_certificate(db, t.org.id, csd["id"], der, 701)
    r = svc.organisation_readiness(db, t.org.id, date(2026, 3, 1))["employers"][0]
    assert r["liveEligible"] is False
    for key, phase in (("stamp_test", "Phase 7"), ("sua_reconciliation", "Phase 8"), ("bank_workflow", "Phase 10"),
                       ("parallel_payroll", "Phase 10")):
        item = _items(r, key)[0]
        assert item["status"] == "BLOCKED" and phase in item["detail"]
    assert _items(r, "csd_credential")[0]["status"] == "PASS"
    assert _items(r, "infonavit_model")[0]["status"] == "PASS"
    assert "platform gates G1–G8 not all SIGNED" in r["liveBlockedBy"]
    assert reg["id"]


def test_empty_content_dependencies_show_as_blocked(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    for table in ("MX_MIN_WAGES", "MX_ZLFN_MUNICIPALITIES"):      # empty content (Batch 2 transcribed S9)
        monkeypatch.setattr(c, table, ())
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    new_registration(db, t.org.id, emp["id"])
    _svc().create_establishment(db, t.org.id, emp["id"], {"name": "Planta", "state_code": "JAL",
                                                          "municipality": "Guadalajara", "postal_code": "44100"}, 701)
    r = _svc().organisation_readiness(db, t.org.id, date(2026, 3, 1))["employers"][0]
    assert "S10/S14/S29" in _items(r, "risk_premium")[0]["detail"]
    assert _items(r, "min_wage_zone")[0]["status"] == "BLOCKED"
    assert "MX-045" in _items(r, "isn_state")[0]["detail"]
    assert "Phase 7" in _items(r, "fiscal_regime_catalog")[0]["detail"]
    assert _items(r, "labor_policy")[0]["status"] == "NOT_STARTED"


def test_waiting_for_a_second_org_admin(db):
    from app.modules.payroll import mexico_employer_service as svc

    t = make_org(db, admins=1)
    emp = new_employer(db, t.org.id)
    reg = new_registration(db, t.org.id, emp["id"])
    svc.create_risk_premium(db, t.org.id, reg["id"], {"premium_rate_pct": "1.5", "period_from": date(2026, 3, 1),
                                                      "period_to": date(2027, 2, 28), "determination_year": 2025}, 701)
    r = svc.organisation_readiness(db, t.org.id, date(2026, 3, 1))["employers"][0]
    item = _items(r, "premium_second_admin")[0]
    assert item["status"] == "BLOCKED" and "waiting for a second org admin" in item["detail"]
    assert item["gateMapping"] == "unmapped"


def test_expiring_and_expired_certificates(db):
    from datetime import datetime, timezone

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    csd = _svc().create_credential(db, t.org.id, emp["id"], {"kind": "CSD", "secret_ref": GCP_REF}, 701)
    der, _c, _k = self_signed_cert(days=40, not_before=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _svc().attach_certificate(db, t.org.id, csd["id"], der, 701)
    on_warn = _svc().organisation_readiness(db, t.org.id, date(2026, 1, 20))["employers"][0]
    assert _items(on_warn, "csd_credential")[0]["status"] == "WARNING"
    on_expired = _svc().organisation_readiness(db, t.org.id, date(2026, 3, 1))["employers"][0]
    assert _items(on_expired, "csd_credential")[0]["status"] == "BLOCKED"


def test_expiry_window_is_the_setting(db, monkeypatch):
    from datetime import datetime, timezone

    from app.config import settings

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    csd = _svc().create_credential(db, t.org.id, emp["id"], {"kind": "CSD", "secret_ref": GCP_REF}, 701)
    der, _c, _k = self_signed_cert(days=40, not_before=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _svc().attach_certificate(db, t.org.id, csd["id"], der, 701)
    assert settings.MX_CREDENTIAL_EXPIRY_WARNING_DAYS == 30
    r = _svc().organisation_readiness(db, t.org.id, date(2026, 1, 1))["employers"][0]
    assert _items(r, "csd_credential")[0]["status"] == "PASS"            # 40 days left > 30
    monkeypatch.setattr(settings, "MX_CREDENTIAL_EXPIRY_WARNING_DAYS", 45)
    r = _svc().organisation_readiness(db, t.org.id, date(2026, 1, 1))["employers"][0]
    assert _items(r, "csd_credential")[0]["status"] == "WARNING"


def test_gate_states_are_unchanged_by_employer_readiness(db):
    from app.modules.payroll import mexico_service

    before = mexico_service.gate_states(db)
    t = make_org(db)
    new_employer(db, t.org.id)
    out = _svc().organisation_readiness(db, t.org.id, date(2026, 3, 1))
    assert out["gates"] == before and all(g["state"] == "OPEN" for g in before)


def test_super_admin_summary_counts_per_gate(db):
    t = make_org(db)
    new_employer(db, t.org.id)
    s = _svc().readiness_summary(db, date(2026, 3, 1))
    assert s["employers"][0]["liveEligible"] is False and s["employers"][0]["firstBlockingItem"]
    assert s["perGate"]["G1"]["employers"] == 1 and s["perGate"]["G1"]["allPassing"] == 0
