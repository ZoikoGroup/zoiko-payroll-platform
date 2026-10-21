"""Mexico Phase 9a — correction runs (plan B2, D10). SYNTHETIC world.

The original committed payslip, its CFDI and its ledgers are never edited;
the CORRECTION run recalculates the period and its commit posts deltas; a
correction never changes an already committed run (no approval drift); the
authority ledger, IMSS movements and CFDI substitution follow the deltas."""

from datetime import date
from decimal import Decimal as D

import pytest
from fastapi import HTTPException

from tests import _mx_authority_helpers as ah


def _S():
    from app.modules.payroll import mexico_correction_service as S

    return S


def _ledger_snapshot(db, run):
    from app.modules.payroll import mexico_run_service

    return {name: sorted((tuple(sorted((k, str(v)) for k, v in vars(r).items() if not k.startswith("_")))
                          for r in q.all()))
            for name, q in zip(("imss", "isn", "sbc", "acc", "accr"), mexico_run_service._ledger_queries(db, run))}


def _corrected(db, monkeypatch, daily="700"):
    """Committed Jun 1-15 run, then the salary is corrected from 1 June and a
    correction run opened for its payslip."""
    S = _S()
    w = ah.committed_world(db, monkeypatch, code="MXCOR")
    (orig,) = ah.rh.mx_items(db, w.run)
    before = (dict(orig.mx_calculation_snapshot), orig.net_pay, _ledger_snapshot(db, w.run))
    ah.raise_salary(db, w, daily, effective_from=date(2026, 6, 1))
    out = S.create_correction(db, w.org.id, w.run.id, [orig.id], "SYNTHETIC: daily salary was 700 from 1 June",
                              w.users[0].id)
    from app.modules.payroll.models import PayrollRun

    corr_run = db.get(PayrollRun, out["corrects"][0]["correctionRunId"])
    return S, w, orig, before, corr_run


def _approve(db, w, run):
    from app.modules.payroll import service

    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    return run


def test_open_correction_recalculates_the_original_period_and_never_touches_the_original(db, monkeypatch):
    S, w, orig, before, corr_run = _corrected(db, monkeypatch)
    assert corr_run.mx_run_type == "CORRECTION" and corr_run.status == "Draft"
    assert (corr_run.period_start, corr_run.period_end, corr_run.pay_date) == (w.run.period_start, w.run.period_end,
                                                                              w.run.pay_date)
    (new,) = ah.rh.mx_items(db, corr_run)
    view = S.run_view(db, w.org.id, corr_run.id)["corrects"][0]
    assert view["correctedItemId"] == new.id and view["status"] == "DRAFT"
    assert D(str(new.gross_pay)) > D(str(orig.gross_pay))                       # 700 > 600 a day
    db.refresh(orig)
    assert (orig.mx_calculation_snapshot, orig.net_pay, _ledger_snapshot(db, w.run)) == before


def test_preconditions(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    S, w, orig, _, corr_run = _corrected(db, monkeypatch)
    with pytest.raises(MXBlock) as exc:
        S.create_correction(db, w.org.id, w.run.id, [orig.id], "again", w.users[0].id)
    assert exc.value.key == "MX_CORRECTION_ALREADY_OPEN"
    with pytest.raises(Exception, match="committed"):
        S.create_correction(db, w.org.id, corr_run.id, [ah.rh.mx_items(db, corr_run)[0].id], "x", w.users[0].id)
    with pytest.raises(Exception, match="reason"):
        S.create_correction(db, w.org.id, w.run.id, [orig.id], "  ", w.users[0].id)
    draft = ah.new_run(db, w)
    with pytest.raises(Exception, match="committed"):
        S.create_correction(db, w.org.id, draft.id, [orig.id], "x", w.users[0].id)


def test_commit_posts_deltas_and_marks_the_correction_committed(db, monkeypatch):
    from app.modules.payroll.models import (
        PayrollMxBenefitAccrual, PayrollMxIsnLiability, PayrollMxSbcHistory, PayrollMxVariableAccumulator,
    )

    S, w, orig, before, corr_run = _corrected(db, monkeypatch)
    _approve(db, w, corr_run)
    (new,) = ah.rh.mx_items(db, corr_run)
    row = S.run_view(db, w.org.id, corr_run.id)["corrects"][0]
    o, c = orig.mx_calculation_snapshot["result"], new.mx_calculation_snapshot["result"]
    assert row["status"] == "COMMITTED"
    assert D(row["deltas"]["isr_withheld"]) == D(str(c["isr_withheld"])) - D(str(o["isr_withheld"]))
    assert D(row["deltas"]["gross"]) > 0
    (isn,) = db.query(PayrollMxIsnLiability).filter(PayrollMxIsnLiability.payslip_item_id == new.id).all()
    assert isn.amount == D(str(c["isn"]["amount"])) - D(str(o["isn"]["amount"])) == D(row["deltas"]["isn"])
    acc = db.query(PayrollMxVariableAccumulator).filter(PayrollMxVariableAccumulator.payroll_run_id == corr_run.id).one()
    assert acc.days == 0                                                         # same period: no extra days
    accr = db.query(PayrollMxBenefitAccrual).filter(PayrollMxBenefitAccrual.payroll_run_id == corr_run.id).all()
    assert accr and all(a.statutory_amount >= 0 for a in accr)
    sbc = db.query(PayrollMxSbcHistory).filter(PayrollMxSbcHistory.payroll_run_id == corr_run.id).all()
    assert sbc and {s.source for s in sbc} == {"CORRECTION"}
    db.refresh(orig)
    assert (orig.mx_calculation_snapshot, orig.net_pay, _ledger_snapshot(db, w.run)) == before


def test_a_correction_never_changes_an_already_committed_run_but_counts_for_later_ones(db, monkeypatch):
    """Directional month-to-date: Jun 16-30 committed BEFORE the correction keeps
    its approval; a run committed AFTER it sees original + delta (= corrected)."""
    from app.modules.payroll import mexico_run_service

    S, w, orig, _, corr_run = _corrected(db, monkeypatch)
    jun30 = ah.commit(db, w, ah.new_run(db, w))
    assert mexico_run_service.approval_drift(db, jun30) == []
    _approve(db, w, corr_run)
    assert mexico_run_service.approval_drift(db, jun30) == []                   # committed before: unchanged
    assert mexico_run_service.approval_drift(db, corr_run) == []
    late = ah.new_run(db, w, "Jun extra", date(2026, 6, 16), date(2026, 6, 30), date(2026, 6, 30))
    (new,) = ah.rh.mx_items(db, corr_run)
    (j30,) = ah.rh.mx_items(db, jun30)
    mtd = mexico_run_service._month_to_date(db, w.employee.id, late, late.pay_date)
    corrected = D(str(new.mx_calculation_snapshot["result"]["isr_taxable"]))
    assert mtd["taxable"] == corrected + D(str(j30.mx_calculation_snapshot["result"]["isr_taxable"]))
    # The correction's own month-to-date leaves out the payslip it replaces.
    own = mexico_run_service._month_to_date(db, w.employee.id, corr_run, corr_run.pay_date)
    assert own["taxable"] == 0


def test_reset_rules_and_void(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import PayrollMxIsnLiability, PayrollRun

    S, w, orig, _, corr_run = _corrected(db, monkeypatch)
    _approve(db, w, corr_run)
    with pytest.raises(HTTPException) as exc:                                     # original: a live correction
        mexico_run_service.reset_run(db, w.run, w.users[0].id, "SYNTHETIC")
    assert exc.value.status_code == 409 and "correction" in exc.value.detail
    db.rollback()
    with pytest.raises(Exception, match="uncommitted"):
        S.void(db, w.org.id, corr_run.id, "x", w.users[0].id)
    (new,) = ah.rh.mx_items(db, corr_run)
    out = mexico_run_service.reset_run(db, corr_run, w.users[0].id, "SYNTHETIC: wrong salary in the correction")
    assert out["removed"]["correctionsReopened"] == 1
    assert db.query(PayrollMxIsnLiability).filter(PayrollMxIsnLiability.payslip_item_id == new.id).count() == 0
    assert S.run_view(db, w.org.id, corr_run.id)["corrects"][0]["status"] == "DRAFT"
    with pytest.raises(HTTPException):
        from app.modules.payroll import service

        service.delete_payroll_run(db, corr_run.id, w.org.id)                    # only through void
    db.rollback()
    corr_id = corr_run.id
    S.void(db, w.org.id, corr_id, "SYNTHETIC: opened by mistake", w.users[0].id)
    assert db.get(PayrollRun, corr_id) is None
    (row,) = S.run_view(db, w.org.id, w.run.id)["corrections"]
    assert row["status"] == "VOIDED" and row["correctionRunId"] is None and row["voidReason"]
    assert mexico_run_service.run_downstream_actions(db, w.run) == []           # original resettable again


def test_a_chain_corrects_the_corrected_payslip(db, monkeypatch):
    S, w, orig, _, corr_run = _corrected(db, monkeypatch)
    _approve(db, w, corr_run)
    (new,) = ah.rh.mx_items(db, corr_run)
    ah.raise_salary(db, w, "650", effective_from=date(2026, 6, 2))
    out = S.create_correction(db, w.org.id, corr_run.id, [new.id], "SYNTHETIC: 650, not 700", w.users[0].id)
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import PayrollRun

    second = db.get(PayrollRun, out["corrects"][0]["correctionRunId"])
    assert S.replaced_chain(db, second) == {new.id, orig.id}
    assert mexico_run_service._month_to_date(db, w.employee.id, second, second.pay_date)["taxable"] == 0


def test_authority_ledger_takes_the_deltas_complementary_when_filed(db, monkeypatch):
    s = ah.svc()
    S, w, orig, _, corr_run = _corrected(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    first = isr.amount
    s.F.file_liability(db, w.org.id, isr.id, "SYN-DECL", w.users[0].id)
    _approve(db, w, corr_run)
    s.F.accrue(db, w.org.id, w.users[0].id)
    rows = ah.liabilities(db, w, "SAT_ISR")
    (new,) = ah.rh.mx_items(db, corr_run)
    delta = D(str(new.mx_calculation_snapshot["result"]["isr_withheld"])) - D(str(orig.mx_calculation_snapshot["result"]["isr_withheld"]))
    assert [(r.sequence, r.status) for r in rows] == [(0, "FILED"), (1, "ACCRUED")]
    assert rows[0].amount == first and rows[1].amount == delta > 0
    isn = ah.liabilities(db, w, "ISN")
    assert sum(r.amount for r in isn) == D(str(new.mx_calculation_snapshot["result"]["isn"]["amount"]))


def test_a_lower_correction_posts_a_negative_delta(db, monkeypatch):
    s = ah.svc()
    S, w, orig, _, corr_run = _corrected(db, monkeypatch, daily="500")
    _approve(db, w, corr_run)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (imss,) = ah.liabilities(db, w, "IMSS")
    (new,) = ah.rh.mx_items(db, corr_run)
    o, c = orig.mx_calculation_snapshot["result"], new.mx_calculation_snapshot["result"]
    expected = D(str(c["imss_employee"])) + D(str(c["imss_employer"]))
    assert imss.amount == expected < D(str(o["imss_employee"])) + D(str(o["imss_employer"]))


def test_imss_modification_movement_from_a_corrected_sbc(db, monkeypatch):
    s = ah.svc()
    S, w, orig, _, corr_run = _corrected(db, monkeypatch)
    _approve(db, w, corr_run)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    moves = ah.movements(db, w)
    assert [m.movement_type for m in moves] == ["ALTA", "MODIFICACION"]
    assert moves[1].payroll_run_id == corr_run.id and moves[1].sbc > moves[0].sbc


def test_every_phase9_run_type_is_built(db, monkeypatch):
    """9a corrections, 9b aguinaldo, 9c finiquito, 9d PTU: no run type is still
    refused with MX_RUN_TYPE_PHASE9."""
    from app.modules.payroll import mexico_run_service

    assert set(mexico_run_service.RUN_TYPES) == set(mexico_run_service.BUILT_RUN_TYPES)


def test_cfdi_of_a_correction_replaces_the_stamped_original(db, monkeypatch, tmp_path):
    from tests import _mx_cfdi_helpers as ch

    from app.modules.payroll import mexico_cfdi_service as C

    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path, code="MXCORCF")
    ch.mock(monkeypatch)
    C.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    assert doc.status == "STAMPED"
    (orig,) = ah.rh.mx_items(db, w.run)
    ah.raise_salary(db, w, "700", effective_from=date(2026, 6, 1))
    out = S.create_correction(db, w.org.id, w.run.id, [orig.id], "SYNTHETIC", w.users[0].id)
    from app.modules.payroll.models import PayrollRun

    corr_run = _approve(db, w, db.get(PayrollRun, out["corrects"][0]["correctionRunId"]))
    C.generate(db, corr_run, w.users[0].id)
    (repl,) = ch.docs(db, corr_run)
    assert repl.replaces_document_id == doc.id and repl.replaces_uuid == doc.uuid
    assert "REPLACEMENT_LINKED" in ch.events(db, doc)


def test_an_untransmitted_original_cfdi_is_voided_by_the_correction(db, monkeypatch, tmp_path):
    from tests import _mx_cfdi_helpers as ch

    from app.modules.payroll import mexico_cfdi_service as C

    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path, code="MXCORCV")
    ch.mock(monkeypatch)
    C.generate(db, w.run, w.users[0].id)                                       # SIGNED, never sent
    (doc,) = ch.docs(db, w.run)
    (orig,) = ah.rh.mx_items(db, w.run)
    out = S.create_correction(db, w.org.id, w.run.id, [orig.id], "SYNTHETIC", w.users[0].id)
    from app.modules.payroll.models import PayrollRun

    corr_run = _approve(db, w, db.get(PayrollRun, out["corrects"][0]["correctionRunId"]))
    C.generate(db, corr_run, w.users[0].id)
    db.refresh(doc)
    (new,) = ch.docs(db, corr_run)
    assert doc.status == "VOIDED" and new.replaces_document_id is None


def test_correction_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = ah.committed_world(db, monkeypatch, code="MXCORAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    (orig,) = ah.rh.mx_items(db, w.run)
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        view = c.get(f"{ORG_BASE}/runs/{w.run.id}/corrections").json()
        assert view["correctable"] is True and view["corrections"] == []
        bad = c.post(f"{ORG_BASE}/runs/{w.run.id}/corrections", json={"itemIds": [orig.id], "reason": ""})
        assert bad.status_code == 400
        made = c.post(f"{ORG_BASE}/runs/{w.run.id}/corrections", json={"itemIds": [orig.id], "reason": "SYNTHETIC"})
        assert made.status_code == 200, made.text
        run_id = made.json()["corrects"][0]["correctionRunId"]
        assert c.get(f"{ORG_BASE}/runs/{w.run.id}/corrections").json()["corrections"][0]["status"] == "DRAFT"
        voided = c.post(f"{ORG_BASE}/corrections/{run_id}/void", json={"reason": "SYNTHETIC: mistake"})
        assert voided.status_code == 200 and voided.json()["voided"]


def test_a_failed_recalculation_leaves_no_half_made_correction(db, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollMxRunCorrection, PayrollRun

    S = _S()
    w = ah.committed_world(db, monkeypatch, code="MXCORFAIL")
    (orig,) = ah.rh.mx_items(db, w.run)
    runs_before = db.query(PayrollRun).count()

    def boom(*a, **k):
        raise RuntimeError("SYNTHETIC calculation failure")

    monkeypatch.setattr(service, "generate_payslips_for_run", boom)
    with pytest.raises(RuntimeError):
        S.create_correction(db, w.org.id, w.run.id, [orig.id], "SYNTHETIC", w.users[0].id)
    assert db.query(PayrollRun).count() == runs_before
    assert db.query(PayrollMxRunCorrection).count() == 0
