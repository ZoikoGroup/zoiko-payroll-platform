"""Mexico Phase 9e — the annual ISR adjustment (plan 9e D1–D10). Every rule is
SYNTHETIC and monkeypatched into the value-free content seams; with them empty
nothing is computed. Inputs come only from committed runs; the difference is
applied as its own section of a later ordinary payslip and the year's
payslips are never edited (MX-010)."""

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

import pytest

from tests import _mx_authority_helpers as ah

FY = 2026
TODAY = date(2027, 3, 1)


class SynAnnualRule:
    """Eligible unless the year's taxable income is above a SYNTHETIC cap;
    annual ISR = taxable × rate; the difference is applied in full when the
    period's withholding allows it, otherwise the rest is carried forward."""
    source, source_ref = "S24", "SYNTHETIC"

    def __init__(self, rate="0.30", cap=None):
        self.rate, self.cap = D(rate), None if cap is None else D(cap)

    def eligibility(self, worker, fiscal_year):
        if self.cap is not None and worker["annual_taxable"] > self.cap:
            return False, "SYN_ABOVE_CAP"
        return True, None

    def annual_isr(self, annual_taxable, fiscal_year, facts):
        return (annual_taxable * self.rate).quantize(D("0.01"), ROUND_HALF_UP)

    def apply_in_run(self, period_withheld, difference, facts):
        total = period_withheld + difference
        if total >= 0:
            return {"withheld": total, "carry_forward": D("0")}
        return {"withheld": D("0"), "carry_forward": total}


class SynExclusion:
    source, source_ref, label = "S24", "SYNTHETIC", "Synthetic written notice"


def _rules(monkeypatch, *, rule=None, exclusions=True):
    from app.modules.payroll import mexico_annual_service
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(mexico_annual_service, "_today", lambda: TODAY)
    if rule is not False:
        monkeypatch.setattr(c, "MX_ANNUAL_ADJUSTMENT_RULE", rule or SynAnnualRule())
    if exclusions:
        monkeypatch.setattr(c, "MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS", {"SYN_OWN_RETURN": SynExclusion()})


def _S():
    from app.modules.payroll import mexico_annual_service as S

    return S


def _world(db, monkeypatch, code):
    """Jun 1-15 (world run) and Jun 16-30 2026 committed for one employee."""
    w = ah.committed_world(db, monkeypatch, code=code)
    ah.commit(db, w, ah.new_run(db, w))
    return w


def _key(w):
    return {"employer_profile_id": w.registration.employer_profile_id, "fiscal_year": FY}


def _extend_content_to(db, year=2027):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    for model in (JurisdictionPack, ContributionRate, TaxSlab):
        for row in db.query(model).filter(model.effective_to == date(2026, 12, 31)):
            row.effective_to = date(year, 12, 31)
    db.commit()


def _approved(db, w):
    _S().compute(db, w.org.id, _key(w), w.users[0].id)
    return _S().approve(db, w.org.id, _key(w), w.users[1].id)


def _jan_run(db, w):
    return ah.new_run(db, w, "Jan 1-15, 2027", date(2027, 1, 1), date(2027, 1, 15), date(2027, 1, 15))


def _snapshots(db, w):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    rows = (db.query(PayslipItem).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
            .filter(PayrollRun.organization_id == w.org.id, PayrollRun.pay_date <= date(2026, 12, 31))
            .order_by(PayslipItem.id).all())
    return [json.dumps(i.mx_calculation_snapshot, sort_keys=True, default=str) for i in rows]


# ── compute ─────────────────────────────────────────────────────────────────

def test_without_the_rule_nothing_is_computed_and_the_year_must_have_ended(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxAnnualIsrAdjustment

    _rules(monkeypatch, rule=False)
    w = _world(db, monkeypatch, "MXANN1")
    with pytest.raises(Exception, match="has ended"):
        _S().compute(db, w.org.id, {**_key(w), "fiscal_year": 2027}, w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        _S().compute(db, w.org.id, _key(w), w.users[0].id)
    assert exc.value.key == "MX_ANNUAL_ADJUSTMENT_RULE_MISSING"
    assert db.query(PayrollMxAnnualIsrAdjustment).count() == 0


def test_computed_from_committed_runs_only(db, monkeypatch):
    from app.modules.payroll import service

    _rules(monkeypatch)
    w = _world(db, monkeypatch, "MXANN2")
    draft = ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15))
    service.generate_payslips_for_run(db, draft, w.org.id, [w.employee.id])          # NOT committed
    out = _S().compute(db, w.org.id, _key(w), w.users[0].id)
    (row,) = out["rows"]
    items = ah.rh.mx_items(db, w.run) + ah.rh.mx_items(db, _june2(db, w))
    taxable = sum((D(str(i.mx_calculation_snapshot["result"]["isr_taxable"])) for i in items), D("0"))
    withheld = sum((D(str(i.mx_calculation_snapshot["result"]["isr_withheld"])) for i in items), D("0"))
    assert D(row["annualTaxable"]) == taxable and D(row["withheldTotal"]) == withheld
    assert set(row["incomeByRunType"]) == {"ORDINARY"} and D(row["incomeByRunType"]["ORDINARY"]) == taxable
    annual = (taxable * D("0.30")).quantize(D("0.01"), ROUND_HALF_UP)
    assert D(row["annualIsr"]) == annual and D(row["difference"]) == annual - withheld
    assert row["status"] == "COMPUTED" and row["eligible"] is True and row["ruleSource"] == "S24 SYNTHETIC"


def _june2(db, w):
    from app.modules.payroll.models import PayrollRun

    return db.query(PayrollRun).filter(PayrollRun.organization_id == w.org.id,
                                       PayrollRun.period_label == "Jun 16-30, 2026").one()


def test_a_higher_rate_owes_more_directional(db, monkeypatch):
    _rules(monkeypatch, rule=SynAnnualRule("0.10"))
    w1 = _world(db, monkeypatch, "MXANN3A")
    low = D(_S().compute(db, w1.org.id, _key(w1), w1.users[0].id)["rows"][0]["difference"])
    _rules(monkeypatch, rule=SynAnnualRule("0.30"))
    w2 = _world(db, monkeypatch, "MXANN3B")
    high = D(_S().compute(db, w2.org.id, _key(w2), w2.users[0].id)["rows"][0]["difference"])
    assert low < high


def test_the_rule_may_exclude_with_a_reason_waived_at_approval(db, monkeypatch):
    _rules(monkeypatch, rule=SynAnnualRule(cap="1"))
    w = _world(db, monkeypatch, "MXANN4")
    (row,) = _S().compute(db, w.org.id, _key(w), w.users[0].id)["rows"]
    assert (row["eligible"], row["exclusionReason"], row["difference"]) == (False, "SYN_ABOVE_CAP", None)
    (row,) = _S().approve(db, w.org.id, _key(w), w.users[1].id)["rows"]
    assert row["status"] == "WAIVED"


# ── exclusions, approval, staleness ─────────────────────────────────────────

def test_operator_exclusions_need_the_catalog_evidence_and_a_second_person(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _rules(monkeypatch, exclusions=False)
    w = _world(db, monkeypatch, "MXANN5")
    (row,) = _S().compute(db, w.org.id, _key(w), w.users[0].id)["rows"]
    with pytest.raises(MXBlock) as exc:
        _S().record_exclusion(db, w.org.id, row["id"], {"reason_code": "SYN_OWN_RETURN", "evidence_ref": "SYN"},
                              w.users[0].id)
    assert exc.value.key == "MX_ANNUAL_ADJUSTMENT_EXCLUSION_RULE_MISSING"
    _rules(monkeypatch)
    with pytest.raises(Exception, match="evidence"):
        _S().record_exclusion(db, w.org.id, row["id"], {"reason_code": "SYN_OWN_RETURN", "evidence_ref": " "},
                              w.users[0].id)
    _S().record_exclusion(db, w.org.id, row["id"], {"reason_code": "SYN_OWN_RETURN", "evidence_ref": "SYN-NOTICE"},
                          w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        _S().approve(db, w.org.id, _key(w), w.users[1].id)
    assert exc.value.key == "MX_ANNUAL_ADJUSTMENT_EXCLUSION_PENDING"
    with pytest.raises(MXBlock) as exc:
        _S().approve_exclusion(db, w.org.id, row["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    _S().approve_exclusion(db, w.org.id, row["id"], w.users[1].id)
    (again,) = _S().compute(db, w.org.id, _key(w), w.users[0].id)["rows"]           # survives a re-compute
    assert (again["eligible"], again["exclusionReason"], again["exclusionEvidenceRef"]) == \
        (False, "SYN_OWN_RETURN", "SYN-NOTICE")
    (done,) = _S().approve(db, w.org.id, _key(w), w.users[1].id)["rows"]
    assert done["status"] == "WAIVED"


def test_approval_is_four_eyes_and_refuses_stale_inputs(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _rules(monkeypatch)
    w = _world(db, monkeypatch, "MXANN6")
    _S().compute(db, w.org.id, _key(w), w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        _S().approve(db, w.org.id, _key(w), w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    ah.commit(db, w, ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15)))
    with pytest.raises(MXBlock) as exc:
        _S().approve(db, w.org.id, _key(w), w.users[1].id)
    assert exc.value.key == "MX_ANNUAL_ADJUSTMENT_STALE"
    _S().compute(db, w.org.id, _key(w), w.users[0].id)
    assert _S().approve(db, w.org.id, _key(w), w.users[1].id)["rows"][0]["status"] == "APPROVED"
    with pytest.raises(Exception, match="already approved"):
        _S().compute(db, w.org.id, _key(w), w.users[0].id)


# ── application in a later run ──────────────────────────────────────────────

def test_applied_in_a_later_run_as_its_own_section_never_editing_the_year(db, monkeypatch):
    from app.modules.payroll import mexico_run_service, service

    _rules(monkeypatch)
    w = _world(db, monkeypatch, "MXANN7")
    before = _snapshots(db, w)
    (row,) = _approved(db, w)["rows"]
    _extend_content_to(db)
    jan = _jan_run(db, w)
    with pytest.raises(Exception, match="already committed"):
        _S().apply_to_run(db, w.org.id, {**_key(w), "run_id": w.run.id}, w.users[0].id)
    open_2026 = ah.new_run(db, w, "Dec 1-15, 2026", date(2026, 12, 1), date(2026, 12, 15), date(2026, 12, 15))
    with pytest.raises(Exception, match="paid after that year"):
        _S().apply_to_run(db, w.org.id, {**_key(w), "run_id": open_2026.id}, w.users[0].id)
    assert _S().apply_to_run(db, w.org.id, {**_key(w), "run_id": jan.id}, w.users[0].id)["assigned"] == [w.employee.id]
    service.generate_payslips_for_run(db, jan, w.org.id, [w.employee.id])
    (item,) = ah.rh.mx_items(db, jan)
    res = item.mx_calculation_snapshot["result"]
    adj = res["annual_adjustment"]
    diff = D(row["difference"])
    assert D(adj["difference"]) == diff and D(adj["change"]) == diff and D(adj["carry_forward"]) == 0
    assert D(res["isr_withheld"]) == D(adj["period_withheld"]) + diff
    for _ in range(2):
        service.advance_payroll_run_status(db, jan.id, w.users[1].id, w.org.id)
    (applied,) = _S().employee_adjustments(db, w.org.id, w.employee.id)
    assert applied["status"] == "APPLIED" and applied["appliedItemId"] == item.id
    assert D(applied["appliedWithheldChange"]) == diff
    assert _snapshots(db, w) == before                                               # MX-010: the year untouched
    db.refresh(jan)
    out = mexico_run_service.reset_run(db, jan, w.users[0].id, "SYNTHETIC")
    assert out["removed"]["annualAdjustmentsReopened"] == 1
    assert _S().employee_adjustments(db, w.org.id, w.employee.id)[0]["status"] == "APPROVED"


def test_a_refund_larger_than_the_period_withholding_is_carried_forward(db, monkeypatch):
    from app.modules.payroll import service

    _rules(monkeypatch, rule=SynAnnualRule("0"))                       # annual ISR 0: everything withheld is refunded
    w = _world(db, monkeypatch, "MXANN8")
    (row,) = _approved(db, w)["rows"]
    _extend_content_to(db)
    jan = _jan_run(db, w)
    _S().apply_to_run(db, w.org.id, {**_key(w), "run_id": jan.id}, w.users[0].id)
    service.generate_payslips_for_run(db, jan, w.org.id, [w.employee.id])
    (item,) = ah.rh.mx_items(db, jan)
    res = item.mx_calculation_snapshot["result"]
    adj = res["annual_adjustment"]
    period = D(adj["period_withheld"])
    assert D(row["difference"]) < -period                                # more refund than this period withholds
    assert D(res["isr_withheld"]) == 0 and D(adj["carry_forward"]) == period + D(row["difference"])


def test_a_rule_breaking_the_invariant_is_refused(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.engine.jurisdictions.mexico import annual_adjustment

    class Leaky(SynAnnualRule):
        def apply_in_run(self, period_withheld, difference, facts):
            return {"withheld": period_withheld, "carry_forward": D("0")}             # silently drops the difference

    _rules(monkeypatch, rule=Leaky())
    with pytest.raises(MXBlock) as exc:
        annual_adjustment.apply_in_run(D("100"), D("25"), {})
    assert exc.value.key == "MX_ANNUAL_ADJUSTMENT_RULE_INVALID"


def test_annual_adjustment_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    _rules(monkeypatch)
    w = _world(db, monkeypatch, "MXANNAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    body = {"employerId": w.registration.employer_profile_id, "fiscalYear": FY}
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        made = c.post(f"{ORG_BASE}/annual-adjustments/compute", json=body)
        assert made.status_code == 200 and made.json()["rows"][0]["status"] == "COMPUTED", made.text
        own = c.post(f"{ORG_BASE}/annual-adjustments/approve", json=body)
        assert own.status_code == 400 and "MX_FOUR_EYES_REQUIRED" in own.text
        assert [r["code"] for r in c.get(f"{ORG_BASE}/annual-adjustments/exclusion-reasons").json()["reasons"]] == \
            ["SYN_OWN_RETURN"]
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        assert c.post(f"{ORG_BASE}/annual-adjustments/approve", json=body).json()["rows"][0]["status"] == "APPROVED"
        assert c.get(f"{ORG_BASE}/annual-adjustments").json()[0]["fiscalYear"] == FY
        assert c.get(f"{ORG_BASE}/employees/{w.employee.id}/annual-adjustments").json()[0]["status"] == "APPROVED"
