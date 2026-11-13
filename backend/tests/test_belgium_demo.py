"""Belgium (ZP-BE-ENG-001) Block E4: the DEMO pack is non-production only.

BE-DEMO-2026 exists only with BE_DEMO_PACKS_ENABLED in a non-production
environment, is never activated or assigned through the governed paths, is never
used by a non-demo organisation, and its payslips / filings are watermarked and
can never be paid or transmitted. The real BE-PAYROLL-2026 stays Draft and
unsigned. Users come from the test fixture (the seed itself creates none)."""
import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException


def _demo():
    from app.modules.payroll import belgium_demo

    return belgium_demo


@pytest.fixture
def enabled(monkeypatch):
    from app.config import settings
    from app.core import code_generation

    counter = iter(range(1, 10_000))                   # SQLite seam: no PostgreSQL advisory lock (as in B3 tests)
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", "")
    return settings


@pytest.fixture
def demo_org(db, enabled, monkeypatch):
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="DEMO Belgium BV", code="BEDEMO", admins=2, country="BE")
    monkeypatch.setattr(enabled, "BE_DEMO_ORG_IDS", str(t.org.id))
    return t


# ── guards ─────────────────────────────────────────────────────────────────
def test_demo_packs_are_off_by_default_and_refused_in_production(monkeypatch):
    from app.config import settings

    d = _demo()
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert settings.BE_DEMO_PACKS_ENABLED is False and not d.be_demo_enabled()
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    assert d.be_demo_enabled()
    for name in ("production", "prod", "live"):
        monkeypatch.setenv("ENVIRONMENT", name)
        assert d.be_demo_is_production() and not d.be_demo_enabled()
    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert d.be_demo_enabled()
    monkeypatch.delenv("ENVIRONMENT")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(settings, "DEBUG", False)
    assert not d.be_demo_enabled()                                    # no environment name + DEBUG off = production


def test_the_seed_refuses_when_disabled_or_in_production(db, monkeypatch):
    from app.config import settings

    monkeypatch.setenv("ENVIRONMENT", "development")
    with pytest.raises(BadRequestException, match="disabled"):
        _demo().be_seed_demo_pack(db)
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(BadRequestException, match="disabled"):
        _demo().be_seed_demo_pack(db)


def test_the_demo_pack_is_labelled_signed_active_and_the_real_pack_is_untouched(db, enabled):
    from app.modules.payroll.engine.countries import belgium_content as c
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from scripts.seed_belgium_canonical_packs import seed_belgium

    real = seed_belgium(db)["pack"]
    db.commit()
    pack = _demo().be_seed_demo_pack(db)
    db.commit()
    assert (pack.pack_id, pack.status) == ("BE-DEMO-2026", "Active") and "DEMO" in pack.compliance_category
    rates = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id).all()
    slabs = db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id).all()
    assert len(rates) == len(c.KEYS)
    assert all(r.label.startswith(_demo().DEMO_LABEL) and c.PENDING_MARK not in r.label for r in rates)
    assert all(s.rate_label.startswith(_demo().DEMO_LABEL) for s in slabs)
    by_key = {r.component_key: r for r in rates}
    assert "AI draft" in by_key["be_onss_employee_rate"].label                       # drafted value used
    assert "DEMO PLACEHOLDER" in by_key["be_wht_applicability_rule"].label           # NOT FOUND -> fake placeholder
    assert _demo().be_seed_demo_pack(db).id == pack.id                               # idempotent
    real_rates = db.query(ContributionRate).filter_by(jurisdiction_pack_id=real.id).all()
    assert real.status == "Draft" and all(c.PENDING_MARK in r.label for r in real_rates)


def test_governed_activation_and_assignment_refuse_the_demo_pack(db, demo_org):
    from app.modules.payroll import belgium_service as be
    from tests._mx_employer_helpers import make_org

    pack = _demo().be_seed_demo_pack(db)
    db.commit()
    assert "activated only by the demo seed" in be.be_pack_activation_refusal(db, pack, actor_id=None)
    other = make_org(db, name="Real BV", code="BEREAL", admins=1, country="BE").org.id
    assert "only to demo" in be.be_pack_assignment_refusal(pack, [other])
    assert be.be_pack_assignment_refusal(pack, [demo_org.org.id]) is None


def test_a_non_demo_organisation_never_calculates_with_the_demo_pack(db, demo_org):
    from datetime import date
    from types import SimpleNamespace

    from app.modules.payroll import belgium_service as be
    from tests._mx_employer_helpers import make_org

    _demo().be_seed_demo_pack(db)
    db.commit()
    other = make_org(db, name="Real BV", code="BEREAL2", admins=1, country="BE").org.id
    employee = SimpleNamespace(organization_id=other, id=1, legal_entity_id=None)
    with pytest.raises(BadRequestException, match="only a demo organisation"):
        be.calc_inputs(db, None, employee, None, as_of=date(2026, 9, 30))
    assert be._be_pack_for(db, other, date(2026, 9, 30)) is None                     # preflight: no pack
    assert be._be_pack_for(db, demo_org.org.id, date(2026, 9, 30)) is not None


def test_the_demo_month_runs_end_to_end_and_is_never_paid_or_transmitted(db, demo_org, monkeypatch):
    from app.modules.payroll import belgium_filing as bf
    from app.modules.payroll import belgium_payment_service as pay
    from app.modules.payroll.models import PayrollBeFiling, PayslipItem

    _demo().be_seed_demo_pack(db)
    db.commit()
    org, a, b = demo_org.org.id, demo_org.users[0].id, demo_org.users[1].id
    out = _demo().be_seed_demo_month(db, org, a, b)
    assert out["status"] == "Approved" and out["demo"] is True and len(out["payslips"]) == 2
    for item in db.query(PayslipItem).filter(PayslipItem.id.in_(out["payslips"])):
        snap = item.be_calculation_snapshot
        assert snap["demo"] is True and snap["demoLabel"] == "DEMO — NOT FOR PAYROLL"
    view = pay.batch_view(db, org, out["paymentBatchId"])
    assert view["demo"] is True and view["status"] == "DRAFT"
    pay.approve_payment_batch(db, org, out["paymentBatchId"], b)
    for action in (lambda: pay.submit_payment_batch(db, org, out["paymentBatchId"], a),
                   lambda: pay.batch_file(db, org, out["paymentBatchId"]),
                   lambda: pay.record_bank_result(db, org, out["paymentBatchId"], "ACCEPTED")):
        with pytest.raises(Exception, match="never"):
            action()
    filing = db.get(PayrollBeFiling, out["dmfaFilingId"])
    assert filing.status == "DRAFT" and filing.payload["demo"] is True
    assert filing.rendition.startswith("DEMO — NOT FOR PAYROLL") and bf.filing_view(filing)["demo"] is True
    with pytest.raises(HTTPException, match="BE_DEMO_FILING"):
        bf.record_be_filing_submission(db, org, filing.id, {"submissionRef": "X"}, a)
    dimona = db.query(PayrollBeFiling).filter_by(organization_id=org, form_code="DIMONA").all()
    assert dimona and all(f.payload.get("demo") and f.status == "DRAFT" for f in dimona)


def test_switching_demo_off_blocks_the_demo_organisation_too(db, demo_org, monkeypatch):
    from datetime import date

    from app.modules.payroll import belgium_service as be

    _demo().be_seed_demo_pack(db)
    db.commit()
    monkeypatch.setattr(demo_org.org, "id", demo_org.org.id)
    from app.config import settings

    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", False)
    assert be._be_pack_for(db, demo_org.org.id, date(2026, 9, 30)) is None


def test_the_seed_script_never_creates_accounts(db, enabled):
    from scripts.seed_belgium_demo import seed_demo
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Users BV", code="BEUSR", admins=2, country="BE")
    with pytest.raises(SystemExit, match="DIFFERENT"):
        seed_demo(db, t.users[0].id, t.users[0].id)
    with pytest.raises(SystemExit, match="never creates accounts"):
        seed_demo(db, t.users[0].id, 999999)
    from app.modules.auth.models import User

    before = db.query(User).count()
    out = seed_demo(db, t.users[0].id, t.users[1].id)
    assert out["status"] == "Approved" and out["demo"] is True and db.query(User).count() == before
