"""Mexico Phase 8 B4 / B5 — SUA reconciliation (MX-033 / MX-042: zero
tolerance, every difference BLOCKING until explained and approved by a
second person) and state ISN returns (MX-046: employee detail -> return ->
ledger; amendments are new rows). SYNTHETIC world and SUA figures."""

from decimal import Decimal as D

import pytest

from tests import _mx_authority_helpers as ah


def _accrued(db, monkeypatch, code="MXSUA"):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch, code=code)
    s.F.accrue(db, w.org.id, w.users[0].id)
    return s, w


def _rows(totals, change=None):
    out = []
    for key, amount in totals.items():
        emp, branch_side = key.split("|", 1)
        branch, side = branch_side.split(":", 1)
        value = D(amount) + (D(change[1]) if change and change[0] == key else 0)
        out.append({"employeeId": int(emp), "branch": branch, "side": side, "amount": str(value)})
    return out


def test_matching_sua_figures_reconcile_only_by_a_second_person(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w = _accrued(db, monkeypatch)
    period = s.F.open_sua_period(db, w.org.id, w.registration.id, "2026-06", w.users[0].id)
    assert period["status"] == "DRAFT" and period["zoikoTotals"]
    assert any("INFONAVIT" in k for k in period["zoikoTotals"]) and any("CEAV" in k for k in period["zoikoTotals"])
    with pytest.raises(MXBlock) as exc:
        s.F.reconcile_sua(db, w.org.id, period["id"], w.users[1].id)
    assert exc.value.key == "MX_SUA_FIGURES_MISSING"
    out = s.F.enter_sua_figures(db, w.org.id, period["id"], _rows(period["zoikoTotals"]), "3.7.1-SYN", w.users[0].id)
    assert out["differences"] == 0 and D(out["differenceTotal"]) == 0
    with pytest.raises(MXBlock) as exc:
        s.F.reconcile_sua(db, w.org.id, period["id"], w.users[0].id)          # who entered the figures
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    assert s.F.reconcile_sua(db, w.org.id, period["id"], w.users[1].id)["status"] == "RECONCILED"
    paid = s.F.record_sua_payment(db, w.org.id, period["id"], "SYN-SIPARE-1", "SYN-LINE", w.users[0].id)
    assert paid["status"] == "PAID" and paid["captureLine"] == "SYN-LINE"
    (imss,) = ah.liabilities(db, w, "IMSS")                                   # IMSS now reconciles against it
    s.F.file_liability(db, w.org.id, imss.id, "SYN-SUA", w.users[0].id)
    s.F.pay_liability(db, w.org.id, imss.id, "SYN-SIPARE-1", w.users[0].id)
    assert s.F.reconcile_liability(db, w.org.id, imss.id, w.users[1].id)["status"] == "RECONCILED"


def test_any_difference_blocks_until_explained_and_approved_by_someone_else(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w = _accrued(db, monkeypatch)
    period = s.F.open_sua_period(db, w.org.id, w.registration.id, "2026-06", w.users[0].id)
    key = next(iter(period["zoikoTotals"]))
    out = s.F.enter_sua_figures(db, w.org.id, period["id"], _rows(period["zoikoTotals"], (key, "0.01")), None,
                                w.users[0].id)
    (diff,) = out["differenceRows"]                                           # one cent: zero tolerance
    assert diff["status"] == "OPEN" and D(diff["difference"]) == D("-0.01")
    with pytest.raises(MXBlock) as exc:
        s.F.reconcile_sua(db, w.org.id, period["id"], w.users[1].id)
    assert exc.value.key == "MX_SUA_DIFFERENCES_OPEN"
    with pytest.raises(Exception, match="Explanation code"):
        s.F.explain_difference(db, w.org.id, diff["id"], "ROUNDING_IS_FINE", "x", w.users[0].id)
    s.F.explain_difference(db, w.org.id, diff["id"], "SUA_VERSION", "SYNTHETIC: SUA rounds per worker", w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        s.F.approve_difference(db, w.org.id, diff["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    s.F.approve_difference(db, w.org.id, diff["id"], w.users[1].id)
    assert s.F.reconcile_sua(db, w.org.id, period["id"], w.users[1].id)["status"] == "RECONCILED"


def test_figures_go_stale_when_committed_amounts_change(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w = _accrued(db, monkeypatch)
    period = s.F.open_sua_period(db, w.org.id, w.registration.id, "2026-06", w.users[0].id)
    s.F.enter_sua_figures(db, w.org.id, period["id"], _rows(period["zoikoTotals"]), None, w.users[0].id)
    ah.commit(db, w, ah.new_run(db, w))                                       # same month, more contributions
    s.F.accrue(db, w.org.id, w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        s.F.reconcile_sua(db, w.org.id, period["id"], w.users[1].id)
    assert exc.value.key == "MX_SUA_STALE"


def test_isn_return_equals_detail_and_ledger_and_files_its_liability(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w = _accrued(db, monkeypatch)
    (isn_liab,) = ah.liabilities(db, w, "ISN")
    ret = s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    assert D(ret["amount"]) == isn_liab.amount and ret["reconciliation"]["matches"]
    assert ret["reconciliation"]["byEmployee"] == {str(w.employee.id): str(isn_liab.amount)}
    filed = s.F.file_isn_return(db, w.org.id, ret["id"], "SYN-CDMX-1", w.users[0].id)
    assert filed["status"] == "FILED"
    db.refresh(isn_liab)
    assert isn_liab.status == "FILED" and isn_liab.declaration_reference == "SYN-CDMX-1"
    with pytest.raises(MXBlock) as exc:
        s.F.record_isn_outcome(db, w.org.id, ret["id"], "ACCEPTED", w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    s.F.record_isn_outcome(db, w.org.id, ret["id"], "ACCEPTED", w.users[1].id)
    s.F.pay_liability(db, w.org.id, isn_liab.id, "SYN-CDMX-PAY", w.users[0].id)
    assert s.F.reconcile_liability(db, w.org.id, isn_liab.id, w.users[1].id)["status"] == "RECONCILED"


def test_a_later_committed_run_needs_an_amendment_never_an_edit(db, monkeypatch):
    s, w = _accrued(db, monkeypatch)
    first = s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    s.F.file_isn_return(db, w.org.id, first["id"], "SYN-CDMX-1", w.users[0].id)
    with pytest.raises(Exception, match="record its outcome"):
        s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    s.F.record_isn_outcome(db, w.org.id, first["id"], "ACCEPTED", w.users[1].id)
    ah.commit(db, w, ah.new_run(db, w))
    s.F.accrue(db, w.org.id, w.users[0].id)
    rows = ah.liabilities(db, w, "ISN")
    assert [(r.sequence, r.status) for r in rows] == [(0, "FILED"), (1, "ACCRUED")]
    amended = s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    assert amended["sequence"] == 1 and amended["amendmentOfId"] == first["id"]
    assert D(amended["amount"]) == rows[0].amount + rows[1].amount and amended["reconciliation"]["matches"]
    assert s.F.isn_view(db, s.F._return(db, w.org.id, first["id"]))["amount"] == first["amount"]   # untouched


def test_isn_return_needs_an_open_state_registration(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w = _accrued(db, monkeypatch)
    w.isn_registration.status = "CLOSED"
    db.commit()
    with pytest.raises(MXBlock) as exc:
        s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    assert exc.value.key == "MX_ISN_REGISTRATION_MISSING"


def test_isn_return_with_an_unknown_outcome(db, monkeypatch):
    s, w = _accrued(db, monkeypatch)
    ret = s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    obj = s.F._return(db, w.org.id, ret["id"])
    s.L.mark_unknown(db, w.org.id, "ISN_RETURN", obj, w.users[0].id, "portal timed out")
    s.L.record_status_check(db, w.org.id, "ISN_RETURN", obj, True, "SYN-CDMX-FOUND", w.users[0].id)
    db.commit()
    assert obj.status == "FILED" and obj.filing_reference == "SYN-CDMX-FOUND"
    (liab,) = ah.liabilities(db, w, "ISN")                                    # found = filed: its liability too
    assert liab.status == "FILED" and liab.declaration_reference == "SYN-CDMX-FOUND"
