"""Mexico Phase 9c — termination and finiquito (plan B6, D5 / D6). Every rule is
SYNTHETIC and monkeypatched into the value-free content seams; with the seams
empty no termination is recorded and no finiquito calculated (MX-057 / MX-009)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

import pytest

from tests import _mx_authority_helpers as ah

TERM_DATE = date(2026, 6, 20)


class SynReason:
    source, source_ref = "S26", "SYNTHETIC"

    def __init__(self, label, days_of_salary=None):
        self.label, self.days = label, days_of_salary

    def separation_components(self, facts):
        if self.days is None:
            return []
        return [{"code": "INDEMNITY", "label": "Synthetic indemnity", "amount": facts["daily_salary"] * self.days}]


class SynFiniquitoRule:
    """Owed: the current (incomplete) service year's policy days in proportion
    to the days elapsed, less what was taken or paid out."""
    source, source_ref = "S26/S24", "SYNTHETIC"

    def vacation_days_owed(self, years, termination_date):
        cur = years[-1]
        elapsed = D((cur["end"] - cur["start"]).days + 1) / D(365)
        owed = (cur["policy_days"] * elapsed).quantize(D("0.01"), ROUND_HALF_UP) + cur["opening"] - cur["taken"] \
            - cur["paid_out"]
        return {cur["service_year"]: max(owed, D("0"))}

    def isr(self, taxable_by_concept, facts):
        return (sum(taxable_by_concept.values(), D("0")) * D("0.10")).quantize(D("0.01"), ROUND_HALF_UP)


class SynAguinaldoRule:
    source, source_ref = "S26", "SYNTHETIC"

    def fraction(self, year, employed_from, employed_to):
        start = max(date(year, 1, 1), employed_from or date(year, 1, 1))
        end = min(date(year, 12, 31), employed_to or date(year, 12, 31))
        return D(max((end - start).days + 1, 0)) / D((date(year, 12, 31) - date(year, 1, 1)).days + 1)

    def payable_by(self, year):
        return date(year, 12, 20)


class SynSpecialPayRule:
    source, source_ref = "S24", "SYNTHETIC"
    combine_with_ordinary = True

    def exempt(self, concept, amount, facts):
        return min(amount, D("100"))

    def standalone_isr(self, taxable, facts):
        return (taxable * D("0.10")).quantize(D("0.01"), ROUND_HALF_UP)


CONCEPTS = ("AGUINALDO", "VACATION_PAYOUT", "VACATION_PREMIUM", "SEPARATION")


def _catalog(monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(c, "MX_TERMINATION_REASONS", {"SYN_DISMISSAL": SynReason("Synthetic dismissal", 90),
                                                      "SYN_RESIGNATION": SynReason("Synthetic resignation")})


def _rules(monkeypatch, *, finiquito=True):
    from app.modules.payroll.engine.countries import mexico_content as c

    _catalog(monkeypatch)
    if finiquito:
        monkeypatch.setattr(c, "MX_FINIQUITO_RULE", SynFiniquitoRule())
    monkeypatch.setattr(c, "MX_AGUINALDO_RULE", SynAguinaldoRule())
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_RULES", {k: SynSpecialPayRule() for k in CONCEPTS})
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", {("CDMX", k): (True, "S22", "SYNTHETIC") for k in CONCEPTS})


def _T():
    from app.modules.payroll import mexico_termination_service as T

    return T


def _codes(db, run):
    from app.modules.payroll import mexico_run_service

    return {e["code"] for e in mexico_run_service.run_preflight(db, run)["exceptions"]}


def _record(db, w, reason="SYN_DISMISSAL", when=TERM_DATE, evidence="SYN-LETTER-1", actor=0):
    return _T().record_termination(db, w.org.id, w.employee.id,
                                   {"termination_date": when, "reason_code": reason, "evidence_ref": evidence},
                                   w.users[actor].id)


def _approved(db, w, **kw):
    rec = _record(db, w, **kw)
    return _T().approve_termination(db, w.org.id, rec["id"], w.users[1].id)


def _finiquito(db, w, term_id, pay=date(2026, 6, 25)):
    from app.modules.payroll.models import PayrollRun

    out = _T().create_finiquito_run(db, w.org.id, term_id, pay, w.users[0].id)
    return db.get(PayrollRun, out["runId"])


# ── the record ──────────────────────────────────────────────────────────────

def test_without_the_reason_catalog_no_termination_is_recorded(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxTermination

    w = ah.committed_world(db, monkeypatch, code="MXTRM0")
    with pytest.raises(MXBlock) as exc:
        _record(db, w)
    assert exc.value.key == "MX_TERMINATION_RULE_MISSING"
    assert db.query(PayrollMxTermination).count() == 0
    assert _T().reasons(db, w.org.id)["block"]["code"] == "MX_TERMINATION_RULE_MISSING"


def test_record_needs_a_catalog_reason_evidence_and_one_live_termination(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _catalog(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXTRM1")
    with pytest.raises(MXBlock) as exc:
        _record(db, w, reason="ANYTHING_ELSE")
    assert exc.value.key == "MX_TERMINATION_REASON_UNKNOWN"
    with pytest.raises(Exception, match="evidence"):
        _record(db, w, evidence="  ")
    rec = _record(db, w)
    assert rec["status"] == "DRAFT" and rec["reasonSource"] == "S26 SYNTHETIC"
    with pytest.raises(Exception, match="already has a DRAFT termination"):
        _record(db, w)
    assert [r["code"] for r in _T().reasons(db, w.org.id)["reasons"]] == ["SYN_DISMISSAL", "SYN_RESIGNATION"]


def test_approval_is_four_eyes_sets_the_leaving_date_and_generates_the_baja_once(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _catalog(monkeypatch)
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch, code="MXTRM2")
    s.I.generate_movements(db, w.org.id, w.users[0].id)                  # the ALTA
    rec = _record(db, w)
    with pytest.raises(MXBlock) as exc:
        _T().approve_termination(db, w.org.id, rec["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    out = _T().approve_termination(db, w.org.id, rec["id"], w.users[1].id)
    db.refresh(w.employee)
    assert out["status"] == "APPROVED" and w.employee.date_of_leaving == TERM_DATE
    (baja,) = [m for m in ah.movements(db, w) if m.movement_type == "BAJA"]
    assert out["bajaMovementIds"] == [baja.id] and baja.event_date == TERM_DATE and baja.source_kind == "TERMINATION"
    assert s.I.generate_movements(db, w.org.id, w.users[0].id)["created"] == []


def test_cancel_withdraws_an_unsent_baja_and_restores_the_leaving_date(db, monkeypatch):
    _catalog(monkeypatch)
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch, code="MXTRM3")
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    out = _approved(db, w)
    with pytest.raises(Exception, match="reason"):
        _T().cancel_termination(db, w.org.id, out["id"], " ", w.users[0].id)
    done = _T().cancel_termination(db, w.org.id, out["id"], "SYNTHETIC: recorded in error", w.users[0].id)
    db.refresh(w.employee)
    assert done["status"] == "CANCELLED" and w.employee.date_of_leaving is None
    assert [m.status for m in ah.movements(db, w) if m.movement_type == "BAJA"] == ["WITHDRAWN"]
    again = _approved(db, w)                                             # a new termination is possible again
    assert again["status"] == "APPROVED"


def test_cancel_refused_once_the_baja_left_zoiko(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _catalog(monkeypatch)
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch, code="MXTRM4")
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    out = _approved(db, w)
    alta = [m for m in ah.movements(db, w) if m.movement_type == "ALTA"][0]
    s.I.export_worklist(db, w.org.id, w.users[0].id, out["bajaMovementIds"] + [alta.id])
    with pytest.raises(MXBlock) as exc:
        _T().cancel_termination(db, w.org.id, out["id"], "SYNTHETIC", w.users[0].id)
    assert exc.value.key == "MX_BAJA_ALREADY_EXPORTED"
    db.refresh(w.employee)
    assert _T().list_terminations(db, w.org.id, w.employee.id)[0]["status"] == "APPROVED"
    assert w.employee.date_of_leaving == TERM_DATE


# ── the ordinary run ────────────────────────────────────────────────────────

def test_the_final_period_pays_to_the_termination_date_and_later_periods_exclude(db, monkeypatch):
    """Directional: the same Jun 16–30 period pays less when the employment ends on 20 June."""
    from app.modules.payroll import service

    _catalog(monkeypatch)
    full_w = ah.committed_world(db, monkeypatch, code="MXTRM5F")
    full = ah.commit(db, full_w, ah.new_run(db, full_w))
    (full_item,) = ah.rh.mx_items(db, full)
    w = ah.committed_world(db, monkeypatch, code="MXTRM5")
    _approved(db, w)
    final = ah.commit(db, w, ah.new_run(db, w))
    (item,) = ah.rh.mx_items(db, final)
    period = item.mx_calculation_snapshot["inputs"]["mx_period"] if "inputs" in item.mx_calculation_snapshot else None
    res = item.mx_calculation_snapshot["result"]
    assert D(res["days_paid"]) == 5 and D(full_item.mx_calculation_snapshot["result"]["days_paid"]) == 15
    assert D(str(item.gross_pay)) < D(str(full_item.gross_pay))
    assert D(res["contribution_days"]) < D(full_item.mx_calculation_snapshot["result"]["contribution_days"])
    assert period is None or period.get("final_period")
    later = ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15))
    service.generate_payslips_for_run(db, later, w.org.id, None)
    assert ah.rh.mx_items(db, later) == []


def test_a_fixed_days_convention_blocks_the_final_period(db, monkeypatch):
    from app.modules.payroll import service

    _catalog(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXTRM6", convention="FIXED")
    _approved(db, w)
    run = ah.new_run(db, w)
    service.generate_payslips_for_run(db, run, w.org.id, [w.employee.id])
    assert "MX_SALARY_DAYS_PARTIAL_PERIOD" in _codes(db, run)


# ── the finiquito ───────────────────────────────────────────────────────────

def test_the_finiquito_blocks_without_its_rule_and_is_atomic_and_single(db, monkeypatch):
    _rules(monkeypatch, finiquito=False)
    w = ah.committed_world(db, monkeypatch, code="MXTRM7")
    out = _approved(db, w)
    with pytest.raises(Exception, match="on or after the termination date"):
        _finiquito(db, w, out["id"], pay=date(2026, 6, 19))
    run = _finiquito(db, w, out["id"])
    assert run.mx_run_type == "FINIQUITO" and (run.period_start, run.period_end) == (TERM_DATE, TERM_DATE)
    assert "MX_FINIQUITO_RULE_MISSING" in _codes(db, run)
    with pytest.raises(Exception, match="already has finiquito run"):
        _finiquito(db, w, out["id"])
    with pytest.raises(Exception, match="delete it first"):
        _T().cancel_termination(db, w.org.id, out["id"], "SYNTHETIC", w.users[0].id)


def test_the_finiquito_pays_the_reason_components_never_the_ordinary_tariff(db, monkeypatch):
    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXTRM8")
    run = _finiquito(db, w, _approved(db, w)["id"])
    assert _codes(db, run) == set()
    (item,) = ah.rh.mx_items(db, run)
    res = item.mx_calculation_snapshot["result"]
    by_kind = {c["kind"]: D(c["gross"]) for c in res["concepts"]}
    assert set(by_kind) == set(CONCEPTS)
    daily = D("600")
    assert by_kind["SEPARATION"] == daily * 90                              # the reason's component
    year = D((TERM_DATE - date(2026, 1, 1)).days + 1) / D(365)
    assert by_kind["AGUINALDO"] == (D("15") * daily * year).quantize(D("0.01"), ROUND_HALF_UP)
    detail = res["special"]["detail"]
    owed = D(detail["vacation"]["days"])                                    # year 3 from 2026-03-01: 16 × 112/365
    assert owed == (D("16") * D(112) / D(365)).quantize(D("0.01"), ROUND_HALF_UP)
    assert by_kind["VACATION_PAYOUT"] == (owed * daily).quantize(D("0.01"))
    assert by_kind["VACATION_PREMIUM"] == (owed * daily * D("25") / 100).quantize(D("0.01"), ROUND_HALF_UP)
    assert res["imss"] == [] and D(res["imss_employer"]) == 0 and res["subsidy"]["applied"] in (0, "0", "0.00")
    taxable = sum((D(c["isr_taxable"]) for c in res["concepts"]), D("0"))
    assert D(res["isr_withheld"]) == (taxable * D("0.10")).quantize(D("0.01"), ROUND_HALF_UP)
    assert res["special"]["concept"] == "FINIQUITO" and res["special"]["rule_source"] == "S26/S24 SYNTHETIC"


def test_a_reason_without_components_pays_no_separation(db, monkeypatch):
    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXTRM9")
    run = _finiquito(db, w, _approved(db, w, reason="SYN_RESIGNATION")["id"])
    (item,) = ah.rh.mx_items(db, run)
    kinds = {c["kind"] for c in item.mx_calculation_snapshot["result"]["concepts"]}
    assert "SEPARATION" not in kinds and "AGUINALDO" in kinds


def test_a_later_termination_owes_more_vacation_directional(db, monkeypatch):
    _rules(monkeypatch)
    early = ah.committed_world(db, monkeypatch, code="MXTRM10A")
    late = ah.committed_world(db, monkeypatch, code="MXTRM10B")

    def owed(w, when):
        run = _finiquito(db, w, _approved(db, w, when=when)["id"], pay=when)
        (item,) = ah.rh.mx_items(db, run)
        return D(item.mx_calculation_snapshot["result"]["special"]["detail"]["vacation"]["days"])

    assert 0 < owed(early, date(2026, 6, 20)) < owed(late, date(2026, 9, 20))


def test_commit_writes_paid_out_vacation_and_reset_reverses_it(db, monkeypatch):
    from app.modules.payroll import mexico_benefits_service as B
    from app.modules.payroll import mexico_run_service, service

    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXTRM11")
    term = _approved(db, w)
    run = _finiquito(db, w, term["id"])
    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    assert run.status == "Approved" and run.mx_approval_fingerprint["committedAt"]
    view = _T().list_terminations(db, w.org.id, w.employee.id)[0]
    assert view["status"] == "COMMITTED" and view["finiquitoRun"]["committed"] is True
    ledger = B.ledger(db, w.org.id, w.employee.id, TERM_DATE)
    (paid,) = [r for r in ledger["records"] if r["kind"] == "PAID_OUT"]
    assert paid["status"] == "PAID" and paid["serviceYear"] == 3 and paid["premiumRunId"] == run.id
    (y3,) = [y for y in ledger["years"] if y["serviceYear"] == 3]
    assert D(y3["paidOut"]) == D(paid["days"]) > 0
    with pytest.raises(Exception, match="finiquito is committed"):
        _T().cancel_termination(db, w.org.id, term["id"], "SYNTHETIC", w.users[0].id)
    out = mexico_run_service.reset_run(db, run, w.users[0].id, "SYNTHETIC")
    assert out["removed"]["vacationPaidOutRemoved"] == 1
    assert [r for r in B.ledger(db, w.org.id, w.employee.id, TERM_DATE)["records"] if r["kind"] == "PAID_OUT"] == []
    assert _T().list_terminations(db, w.org.id, w.employee.id)[0]["status"] == "APPROVED"


def test_termination_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    _rules(monkeypatch)
    w = ah.committed_world(db, monkeypatch, code="MXTRMAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        assert [r["code"] for r in c.get(f"{ORG_BASE}/termination-reasons").json()["reasons"]] == \
            ["SYN_DISMISSAL", "SYN_RESIGNATION"]
        made = c.post(f"{ORG_BASE}/employees/{w.employee.id}/terminations",
                      json={"terminationDate": "2026-06-20", "reasonCode": "SYN_DISMISSAL", "evidenceRef": "SYN-1"})
        assert made.status_code == 200, made.text
        own = c.post(f"{ORG_BASE}/terminations/{made.json()['id']}/approve")                     # four-eyes
        assert own.status_code == 400 and "MX_FOUR_EYES_REQUIRED" in own.text
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        tid = made.json()["id"]
        assert c.post(f"{ORG_BASE}/terminations/{tid}/approve").json()["status"] == "APPROVED"
        fin = c.post(f"{ORG_BASE}/terminations/{tid}/finiquito-run", json={"payDate": "2026-06-25"})
        assert fin.status_code == 200, fin.text
        listed = c.get(f"{ORG_BASE}/employees/{w.employee.id}/terminations").json()
        assert listed[0]["finiquitoRun"]["id"] == fin.json()["runId"]
