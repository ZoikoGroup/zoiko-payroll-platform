"""Mexico Phase 9b — the aguinaldo run and vacation records / premium
(plan B4 / B5, D2–D4). Every rule is SYNTHETIC and monkeypatched into the
value-free content seams; with the seams empty every special payment BLOCKS
(never the ordinary tariff, MX-009)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

import pytest

from tests import _mx_authority_helpers as ah


class SynAguinaldoRule:
    source, source_ref = "S26", "SYNTHETIC"

    def fraction(self, year, employed_from, employed_to):
        start = max(date(year, 1, 1), employed_from or date(year, 1, 1))
        end = min(date(year, 12, 31), employed_to or date(year, 12, 31))
        days_in_year = (date(year, 12, 31) - date(year, 1, 1)).days + 1
        return D(max((end - start).days + 1, 0)) / D(days_in_year)

    def payable_by(self, year):
        return date(year, 12, 20)


class SynSpecialPayRule:
    source, source_ref = "S24", "SYNTHETIC"
    combine_with_ordinary = True

    def __init__(self, exempt_cap="100"):
        self.cap = D(exempt_cap)

    def exempt(self, concept, amount, facts):
        return min(amount, self.cap)

    def standalone_isr(self, taxable, facts):
        return (taxable * D("0.10")).quantize(D("0.01"), ROUND_HALF_UP)


def _rules(monkeypatch, *, aguinaldo=True, special=True, isn=True):
    from app.modules.payroll.engine.countries import mexico_content as c

    if aguinaldo:
        monkeypatch.setattr(c, "MX_AGUINALDO_RULE", SynAguinaldoRule())
    if not special:                                      # W1-3a transcribed the real rules
        monkeypatch.setattr(c, "MX_SPECIAL_PAY_RULES", {})
    if special:
        monkeypatch.setattr(c, "MX_SPECIAL_PAY_RULES", {"AGUINALDO": SynSpecialPayRule(),
                                                        "VACATION_PREMIUM": SynSpecialPayRule("50")})
    if not isn:                                          # W1-2 transcribed the real CDMX inclusions
        monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", {})
    if isn:
        monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", {("CDMX", "AGUINALDO"): (True, "S22", "SYNTHETIC"),
                                                                ("CDMX", "VACATION_PREMIUM"): (True, "S22", "SYNTHETIC")})


def _B():
    from app.modules.payroll import mexico_benefits_service as B

    return B


def _codes(db, run):
    from app.modules.payroll import mexico_run_service

    return {e["code"] for e in mexico_run_service.run_preflight(db, run)["exceptions"]}


def _aguinaldo(db, w, pay=date(2026, 12, 15)):
    from app.modules.payroll.models import PayrollRun

    out = _B().create_aguinaldo_run(db, w.org.id, 2026, pay, None, w.users[0].id)
    return db.get(PayrollRun, out["runId"])


# ── aguinaldo ───────────────────────────────────────────────────────────────

def test_aguinaldo_blocks_without_its_rules(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(c, "MX_AGUINALDO_RULE", None)                # W1-3a: the real rule is transcribed
    w = ah.committed_world(db, monkeypatch, code="MXAG0")
    run = _aguinaldo(db, w)
    assert run.mx_run_type == "AGUINALDO" and (run.period_start, run.period_end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert "MX_AGUINALDO_RULE_MISSING" in _codes(db, run)
    _rules(monkeypatch, special=False)
    run2 = _aguinaldo_regenerate(db, w, run)
    assert "MX_SPECIAL_PAY_RULE_MISSING" in _codes(db, run2)


def _aguinaldo_regenerate(db, w, run):
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, run, w.org.id, [w.employee.id])
    db.refresh(run)
    return run


def test_aguinaldo_is_days_times_salary_times_the_transcribed_fraction(db, monkeypatch):
    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXAG1")
    run = _aguinaldo(db, w)
    (item,) = ah.rh.mx_items(db, run)
    res = item.mx_calculation_snapshot["result"]
    days, daily = D("15"), D("600")                          # labour policy 15 days; SYNTHETIC daily salary
    joined = w.employee.date_of_joining                       # 2026-01-01 → the whole year
    assert joined == date(2026, 1, 1)
    assert D(res["gross"]) == (days * daily).quantize(D("0.01")) == D(str(item.gross_pay))
    assert D(res["isr_taxable"]) == D(res["gross"]) - 100 and D(res["isr_withheld"]) == (D(res["isr_taxable"]) * D("0.10")).quantize(D("0.01"))
    assert res["imss"] == [] and D(res["imss_employer"]) == 0 and D(res["infonavit_employer"]) == 0
    assert D(res["isn"]["amount"]) > 0 and res["special"]["concept"] == "AGUINALDO"
    assert res["special"]["detail"]["payableBy"] == "2026-12-20" and res["special"]["rule_source"] == "S24 SYNTHETIC"
    assert _codes(db, run) == set()


def test_part_of_the_year_pays_less_directional(db, monkeypatch):
    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXAG2")
    full = D(str(ah.rh.mx_items(db, _aguinaldo(db, w))[0].gross_pay))
    w2 = ah.committed_world(db, monkeypatch, code="MXAG3")
    w2.employee.date_of_joining = date(2026, 7, 1)
    db.commit()
    part = D(str(ah.rh.mx_items(db, _aguinaldo(db, w2))[0].gross_pay))
    assert 0 < part < full


def test_aguinaldo_commit_and_authority_accrual(db, monkeypatch):
    _rules(monkeypatch)
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch, code="MXAG4")
    run = _aguinaldo(db, w)
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollMxIsnLiability, PayrollMxSbcHistory

    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    assert run.status == "Approved" and run.mx_approval_fingerprint["committedAt"]
    (item,) = ah.rh.mx_items(db, run)
    assert db.query(PayrollMxSbcHistory).filter(PayrollMxSbcHistory.payroll_run_id == run.id).count() == 0
    assert db.query(PayrollMxIsnLiability).filter(PayrollMxIsnLiability.payslip_item_id == item.id).count() == 1
    s.F.accrue(db, w.org.id, w.users[0].id)
    dec = [l for l in ah.liabilities(db, w, "SAT_ISR") if l.period_key == "2026-12"]
    assert len(dec) == 1 and dec[0].amount == D(str(item.mx_calculation_snapshot["result"]["isr_withheld"]))
    assert not [l for l in ah.liabilities(db, w, "IMSS") if l.period_key == "2026-12"]


def test_aguinaldo_needs_the_state_inclusion_and_one_run_per_year(db, monkeypatch):
    _rules(monkeypatch, isn=False)
    w = ah.committed_world(db, monkeypatch, code="MXAG5")
    run = _aguinaldo(db, w)
    assert "MX_ISN_SPECIAL_PAY_RULE_MISSING" in _codes(db, run)
    with pytest.raises(Exception, match="already exists"):
        _aguinaldo(db, w)


def test_aguinaldo_below_the_statutory_floor_blocks(db, monkeypatch):
    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXAG6")
    w.policy.aguinaldo_days = D("5")                          # SYNTHETIC statutory minimum is 10
    db.commit()
    assert "MX_LABOR_POLICY_BELOW_FLOOR" in _codes(db, _aguinaldo(db, w))


# ── vacation records ────────────────────────────────────────────────────────

def _taken(db, w, days="3", start=date(2026, 6, 10), actor=0):
    return _B().record_vacation(db, w.org.id, w.employee.id,
                                {"kind": "TAKEN", "days": days, "start_date": start, "end_date": start,
                                 "service_year": None}, w.users[actor].id)


def test_vacation_records_need_a_second_person_and_a_balance(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    B = _B()
    w = ah.committed_world(db, monkeypatch, code="MXVAC1")
    rec = _taken(db, w)
    assert rec["serviceYear"] == 3 and rec["status"] == "DRAFT"           # seniority 2024-03-01 → year 3 in June 2026
    with pytest.raises(MXBlock) as exc:
        B.approve_vacation(db, w.org.id, rec["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    assert B.approve_vacation(db, w.org.id, rec["id"], w.users[1].id)["status"] == "APPROVED"
    big = _taken(db, w, days="14")                                        # policy year 3+ = 16 days; 3 used
    with pytest.raises(MXBlock) as exc:
        B.approve_vacation(db, w.org.id, big["id"], w.users[1].id)
    assert exc.value.key == "MX_VACATION_BALANCE_EXCEEDED"
    ledger = B.ledger(db, w.org.id, w.employee.id, date(2026, 6, 30))
    (year3,) = [y for y in ledger["years"] if y["serviceYear"] == 3]
    assert (D(year3["policyDays"]), D(year3["taken"]), D(year3["balance"])) == (D("16"), D("3"), D("13"))
    with pytest.raises(Exception, match="termination"):
        B.record_vacation(db, w.org.id, w.employee.id, {"kind": "PAID_OUT", "days": "1"}, w.users[0].id)
    with pytest.raises(Exception, match="note"):
        B.record_vacation(db, w.org.id, w.employee.id, {"kind": "OPENING", "days": "2"}, w.users[0].id)


def test_vacation_premium_blocks_the_ordinary_payslip_without_its_rule(db, monkeypatch):
    B = _B()
    w = ah.committed_world(db, monkeypatch, code="MXVAC2")
    rec = _taken(db, w, start=date(2026, 6, 20))
    B.approve_vacation(db, w.org.id, rec["id"], w.users[1].id)
    run = ah.new_run(db, w)                                               # Jun 16-30 reaches 20 June
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(c, "MX_SPECIAL_PAY_RULES", {})                  # W1-3a: the real rules are transcribed
    service.generate_payslips_for_run(db, run, w.org.id, [w.employee.id])
    assert "MX_SPECIAL_PAY_RULE_MISSING" in _codes(db, run)


def test_vacation_premium_is_paid_once_and_never_changes_a_committed_run(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    _rules(monkeypatch)
    B = _B()
    w = ah.committed_world(db, monkeypatch, code="MXVAC3")
    rec = _taken(db, w, days="2", start=date(2026, 6, 20))
    B.approve_vacation(db, w.org.id, rec["id"], w.users[1].id)
    run = ah.commit(db, w, ah.new_run(db, w))
    (item,) = ah.rh.mx_items(db, run)
    prem = [c for c in item.mx_calculation_snapshot["result"]["concepts"] if c["kind"] == "VACATION_PREMIUM"]
    expected = D("2") * D("600") * D("25") / 100                          # days × daily × policy premium %
    assert len(prem) == 1 and D(prem[0]["gross"]) == expected
    assert D(prem[0]["isr_exempt"]) == 50 and D(prem[0]["isr_taxable"]) == expected - 50
    row = B.ledger(db, w.org.id, w.employee.id)["records"][0]
    assert row["status"] == "PAID" and row["premiumRunId"] == run.id
    late = _taken(db, w, days="1", start=date(2026, 6, 25))               # approved AFTER the commit
    B.approve_vacation(db, w.org.id, late["id"], w.users[1].id)
    assert mexico_run_service.approval_drift(db, run) == []
    nxt = ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15))
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, nxt, w.org.id, [w.employee.id])
    (n_item,) = ah.rh.mx_items(db, nxt)
    codes = [c["code"] for c in n_item.mx_calculation_snapshot["result"]["concepts"] if c["kind"] == "VACATION_PREMIUM"]
    assert codes == [f"MX_VACATION_PREMIUM:{late['id']}"]                 # only the unpaid one
    out = mexico_run_service.reset_run(db, run, w.users[0].id, "SYNTHETIC")
    assert out["removed"]["vacationPremiumsReopened"] == 1
    assert {r["status"] for r in B.ledger(db, w.org.id, w.employee.id)["records"]} == {"APPROVED"}


def test_benefit_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXVACAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        made = c.post(f"{ORG_BASE}/employees/{w.employee.id}/vacation",
                      json={"kind": "TAKEN", "days": "1", "startDate": "2026-06-10", "endDate": "2026-06-10"})
        assert made.status_code == 200, made.text
        assert c.get(f"{ORG_BASE}/employees/{w.employee.id}/vacation").json()["records"][0]["status"] == "DRAFT"
        agu = c.post(f"{ORG_BASE}/aguinaldo-runs", json={"year": 2026, "payDate": "2026-12-15"})
        assert agu.status_code == 200 and agu.json()["employees"] == [w.employee.id], agu.text
        bad = c.post(f"{ORG_BASE}/aguinaldo-runs", json={"year": 2026, "payDate": "2027-01-05"})
        assert bad.status_code == 400
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        rid = made.json()["id"]
        assert c.post(f"{ORG_BASE}/vacation/{rid}/approve").json()["status"] == "APPROVED"


def test_with_the_transcribed_rules_an_aguinaldo_run_waits_for_the_g1_decisions(db, monkeypatch):
    """W1-3a: the real LFT Art. 87 rule computes the amount; its LISR Art. 93 exempt
    part waits for the unit decision (DECISIONS_PENDING D-07) — never a guess."""
    from app.modules.payroll.engine.countries import mexico_content, mexico_rules

    assert isinstance(mexico_content.MX_AGUINALDO_RULE, mexico_rules.Lft87AguinaldoRule)
    monkeypatch.setattr(mexico_content, "MX_SPECIAL_PAY_ISN_INCLUSION",
                        {("CDMX", "AGUINALDO"): (True, "S22", "SYNTHETIC")})
    w = ah.committed_world(db, monkeypatch, code="MXAGR")
    run = _aguinaldo(db, w)
    codes = _codes(db, run)
    assert "MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED" in codes
    assert "MX_AGUINALDO_RULE_MISSING" not in codes and "MX_SPECIAL_PAY_RULE_MISSING" not in codes


def test_year_to_date_exempt_counts_committed_payslips_of_the_calendar_year_only(db, monkeypatch):
    """W1-3a: LISR Art. 93 XIV caps each special concept per calendar year, so a
    later payslip receives the exempt amounts committed earlier that year — and
    nothing from the run itself, an uncommitted run, or another year."""
    from app.modules.payroll import mexico_run_service as rs

    _rules(monkeypatch)
    B = _B()
    w = ah.committed_world(db, monkeypatch, code="MXYTD")
    rec = _taken(db, w, days="2", start=date(2026, 6, 20))
    B.approve_vacation(db, w.org.id, rec["id"], w.users[1].id)
    run = ah.commit(db, w, ah.new_run(db, w))
    assert rs._year_to_date_exempt(db, w.employee.id, run, run.pay_date)["VACATION_PREMIUM"] == 0   # itself
    later = ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15))
    ytd = rs._year_to_date_exempt(db, w.employee.id, later, date(2026, 7, 15))
    assert ytd["VACATION_PREMIUM"] == D("50") and ytd["AGUINALDO"] == 0     # the synthetic rule exempted 50
    assert rs._year_to_date_exempt(db, w.employee.id, later, date(2027, 1, 15))["VACATION_PREMIUM"] == 0
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, later, w.org.id, [w.employee.id])
    (item,) = ah.rh.mx_items(db, later)
    assert "yearToDateExempt" in item.mx_calculation_snapshot["components"]   # bound into the input hash
