"""Mexico Phase 8 B8 — registration in run_downstream_actions (plan §6, the
Phase 6 reset rule): a reset is refused once a movement, liability, SUA
period or ISN return including the run has left Zoiko (or is UNKNOWN);
untransmitted drafts are withdrawn and recomputed. Plus the run's own
"Authorities" lane (MX-041)."""

import pytest
from fastapi import HTTPException

from tests import _mx_authority_helpers as ah


def _reset(db, w, run=None):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.reset_run(db, run or w.run, w.users[0].id, "SYNTHETIC reset")


def _refused(db, w, fragment):
    with pytest.raises(HTTPException) as exc:
        _reset(db, w)
    assert exc.value.status_code == 409 and "MX_RESET_DOWNSTREAM_ACTED" in exc.value.detail
    assert fragment in exc.value.detail
    db.rollback()


def test_reset_with_only_drafts_voids_and_withdraws_then_recommit_reaccrues(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    out = _reset(db, w)
    assert out["removed"]["movementsVoided"] == 1 and out["removed"]["liabilitySourcesRemoved"] > 0
    assert {l.status for l in ah.liabilities(db, w)} == {"WITHDRAWN"} and {l.amount for l in ah.liabilities(db, w)} == {0}
    assert [m.status for m in ah.movements(db, w)] == ["VOIDED"]
    from app.modules.payroll.models import PayrollMxIsnReturn

    assert [r.status for r in db.query(PayrollMxIsnReturn)] == ["WITHDRAWN"]
    from app.modules.payroll import service

    assert out["status"] == "Review"
    service.advance_payroll_run_status(db, w.run.id, w.users[1].id, w.org.id)    # re-approve (re-commit)
    db.refresh(w.run)
    assert w.run.status == "Approved"
    s.F.accrue(db, w.org.id, w.users[0].id)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    rows = ah.liabilities(db, w)
    assert {(l.sequence, l.status) for l in rows} == {(0, "ACCRUED")}           # the same liabilities, re-accrued
    assert [m.status for m in ah.movements(db, w)] == ["VOIDED", "PENDING"]      # regenerated after the void
    assert "REACCRUED" in ah.events(db, "LIABILITY", rows[0])


def test_reset_refused_once_a_movement_was_exported(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    s.I.export_worklist(db, w.org.id, w.users[0].id)
    _refused(db, w, "IMSS movement")


def test_reset_refused_once_a_liability_was_filed_or_is_unknown(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    s.L.mark_unknown(db, w.org.id, "LIABILITY", isr, w.users[0].id)
    db.commit()
    _refused(db, w, "SAT_ISR liability 2026-06 #0 is UNKNOWN")


def test_reset_refused_once_a_sua_period_was_reconciled(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    period = s.F.open_sua_period(db, w.org.id, w.registration.id, "2026-06", w.users[0].id)
    rows = [{"employeeId": int(k.split("|")[0]), "branch": k.split("|")[1].split(":")[0],
             "side": k.split(":")[-1], "amount": v} for k, v in period["zoikoTotals"].items()]
    s.F.enter_sua_figures(db, w.org.id, period["id"], rows, None, w.users[0].id)
    s.F.reconcile_sua(db, w.org.id, period["id"], w.users[1].id)
    _refused(db, w, "SUA period 2026-06")


def test_reset_refused_once_an_isn_return_was_filed(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    ret = s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    s.F.file_isn_return(db, w.org.id, ret["id"], "SYN-CDMX-1", w.users[0].id)
    _refused(db, w, "ISN return CDMX 2026-06 #0 is FILED")


def test_the_authorities_lane_is_its_own_lifecycle(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    lane = lambda: mexico_run_service.run_status(db, w.run)          # noqa: E731
    before = lane()
    assert before["authorities"]["status"] == "NOT_STARTED"
    s.F.accrue(db, w.org.id, w.users[0].id)
    after = lane()
    assert after["authorities"]["status"] == "ACCRUED"
    assert (after["payroll"], after["cfdi"], after["bank"]) == (before["payroll"], before["cfdi"], before["bank"])
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    s.F.file_liability(db, w.org.id, isr.id, "SYN-DECL", w.users[0].id)
    assert lane()["authorities"]["status"] == "IN_PROGRESS"
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    s.I.export_worklist(db, w.org.id, w.users[0].id)
    (alta,) = ah.movements(db, w)
    s.L.mark_unknown(db, w.org.id, "MOVEMENT", alta, w.users[0].id)
    db.commit()
    assert lane()["authorities"]["status"] == "UNKNOWN"
