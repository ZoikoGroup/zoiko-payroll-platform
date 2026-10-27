"""Mexico Phase 3 — registration-scoped work-risk premiums (MX-024/MX-026).
Approval is refused while the period rule (S10/S14/S29) or the legal range
(S10) is missing; with SYNTHETIC content it enforces the period shape (incl.
a leap year), the determination year, the range, evidence and four-eyes."""

from datetime import date

import pytest

from tests._mx_employer_helpers import active_pack, evidence_doc, make_org, new_employer, new_registration


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


def _premium(db, org_id, reg_id, *, actor=701, rate="1.5", frm="2026-03-01", to="2027-02-28", year=2025, doc=None):
    return _svc().create_risk_premium(db, org_id, reg_id, {
        "premium_rate_pct": rate, "period_from": date.fromisoformat(frm), "period_to": date.fromisoformat(to),
        "determination_year": year, "evidence_document_id": doc}, actor)


@pytest.fixture()
def rule(monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(c, "MX_RISK_PREMIUM_PERIOD", c.RiskPremiumPeriodRule(3, 1, "S29", "SYNTHETIC"))


def _setup(db, admins=2):
    t = make_org(db, admins=admins)
    emp = new_employer(db, t.org.id)
    reg = new_registration(db, t.org.id, emp["id"])
    return t, emp, reg


def test_draft_is_recorded_but_approval_is_refused_until_the_period_rule_is_transcribed(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.models import TaxConfigurationAudit

    monkeypatch.setattr(c, "MX_RISK_PREMIUM_PERIOD", None)          # W1-5 transcribed the real one (RACERF)

    t, _emp, reg = _setup(db)
    doc = evidence_doc(db, t.org.id)
    p = _premium(db, t.org.id, reg["id"], doc=doc.id)
    assert p["status"] == "DRAFT"
    with pytest.raises(BadRequestException, match="awaiting transcription from S10 / S14 / S29"):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 702, "org_admin")
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.action == "refused").count() == 1


def test_approval_is_refused_while_the_legal_range_is_not_in_an_active_pack(db, rule):
    from app.core.exceptions import BadRequestException

    t, _emp, reg = _setup(db)
    p = _premium(db, t.org.id, reg["id"], doc=evidence_doc(db, t.org.id).id)
    with pytest.raises(BadRequestException, match="legal premium range"):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 702, "org_admin")


def test_four_eyes_no_exception_and_the_single_admin_message(db, rule):
    from app.core.exceptions import BadRequestException

    t, _emp, reg = _setup(db, admins=1)
    p = _premium(db, t.org.id, reg["id"])
    with pytest.raises(BadRequestException, match="waiting for a second org admin"):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 701, "org_admin")
    with pytest.raises(BadRequestException, match="approved by an org admin"):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 702, "payroll_admin")


def test_full_approval_with_synthetic_content_and_supersede(db, rule):
    t, _emp, reg = _setup(db)
    active_pack(db, start=date(2026, 1, 1), end=date(2026, 12, 31))
    doc = evidence_doc(db, t.org.id)
    first = _premium(db, t.org.id, reg["id"], doc=doc.id)
    ok = _svc().approve_risk_premium(db, t.org.id, first["id"], 702, "org_admin")
    assert (ok["status"], ok["approvedById"]) == ("ACTIVE", 702)
    corrected = _premium(db, t.org.id, reg["id"], rate="2.0", doc=doc.id)
    _svc().approve_risk_premium(db, t.org.id, corrected["id"], 702, "org_admin")
    statuses = [p["status"] for p in _svc().list_risk_premiums(db, reg["id"])]
    assert statuses == ["SUPERSEDED", "ACTIVE"]


@pytest.mark.parametrize("frm,to,year,rate,msg", [
    ("2026-01-01", "2026-12-31", 2025, "1.5", "must run 2026-03-01 to 2027-02-28"),
    ("2026-03-01", "2027-02-28", 2026, "1.5", "determined in 2025"),
    ("2026-03-01", "2027-02-28", 2025, "20", "outside the legal range"),
])
def test_period_shape_year_and_range(db, rule, frm, to, year, rate, msg):
    from app.core.exceptions import BadRequestException

    t, _emp, reg = _setup(db)
    active_pack(db)
    p = _premium(db, t.org.id, reg["id"], frm=frm, to=to, year=year, rate=rate, doc=evidence_doc(db, t.org.id).id)
    with pytest.raises(BadRequestException, match=msg):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 702, "org_admin")


def test_leap_year_period_ends_on_29_february(db, rule):
    assert _svc().premium_period_for(date(2027, 3, 1)) == (date(2027, 3, 1), date(2028, 2, 29))
    assert _svc().premium_period_for(date(2026, 3, 1)) == (date(2026, 3, 1), date(2027, 2, 28))


def test_evidence_is_required_to_approve(db, rule):
    from app.core.exceptions import BadRequestException

    t, _emp, reg = _setup(db)
    active_pack(db)
    p = _premium(db, t.org.id, reg["id"])
    with pytest.raises(BadRequestException, match="determination document"):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 702, "org_admin")


def test_premiums_are_registration_scoped(db, rule):
    t, emp, reg_a = _setup(db)
    reg_b = new_registration(db, t.org.id, emp["id"], rp="Z7654321109")
    active_pack(db)
    doc = evidence_doc(db, t.org.id)
    pa = _premium(db, t.org.id, reg_a["id"], rate="1.5", doc=doc.id)
    pb = _premium(db, t.org.id, reg_b["id"], rate="3.0", doc=doc.id)
    for p in (pa, pb):
        _svc().approve_risk_premium(db, t.org.id, p["id"], 702, "org_admin")
    assert [x["premiumRatePct"] for x in _svc().list_risk_premiums(db, reg_a["id"])] == ["1.50000"]
    assert [x["premiumRatePct"] for x in _svc().list_risk_premiums(db, reg_b["id"])] == ["3.00000"]


def test_another_tenant_cannot_approve(db, rule):
    from app.core.exceptions import NotFoundException

    t, _emp, reg = _setup(db)
    other = make_org(db, name="Other", code="OTHER")
    p = _premium(db, t.org.id, reg["id"])
    with pytest.raises(NotFoundException):
        _svc().approve_risk_premium(db, other.org.id, p["id"], 702, "org_admin")
