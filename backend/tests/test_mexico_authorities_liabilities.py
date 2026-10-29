"""Mexico Phase 8 B3 / B6 — the authority liability ledger (SYNTHETIC world).

Fed only from committed rows, each linked once (no double counting), every
amount traceable to its payslip; rows committed after a period left Zoiko go
to a complementary liability; due dates only from an Active calendar row."""

from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_authority_helpers as ah


def test_accrue_links_every_committed_row_once_and_sums_exactly(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    out = s.F.accrue(db, w.org.id, w.users[0].id)
    assert out["sourcesAdded"] > 0 and out["skipped"] == []
    rows = ah.liabilities(db, w)
    assert {r.authority for r in rows} == {"SAT_ISR", "IMSS", "IMSS_RCV", "INFONAVIT", "ISN"}
    assert {r.period_key for r in rows} == {"2026-06"} and all(r.status == "ACCRUED" for r in rows)
    (item,) = ah.rh.mx_items(db, w.run)
    res = item.mx_calculation_snapshot["result"]
    by = {r.authority: r for r in rows}
    assert by["SAT_ISR"].amount == D(str(res["isr_withheld"])) and by["SAT_ISR"].scope_key == "ORG"
    assert by["ISN"].amount == D(str(res["isn"]["amount"])) and by["ISN"].scope_key == "ST:CDMX"
    imss_total = D(str(res["imss_employee"])) + D(str(res["imss_employer"]))
    # A18: retiro and CEAV (paid by bimester, LSS Transitorio XXVII) are their own liability
    rcv = sum((D(str(b["amount"])) for b in res["imss"] if b.get("branch") in ("RETIRO", "CEAV")), D("0"))
    assert rcv > 0 and by["IMSS_RCV"].amount == rcv and by["IMSS_RCV"].registration_id == w.registration.id
    assert by["IMSS"].amount + by["IMSS_RCV"].amount == imss_total and by["IMSS"].registration_id == w.registration.id
    assert by["IMSS_RCV"].scope_key == by["IMSS"].scope_key == f"REG:{w.registration.id}"
    assert by["INFONAVIT"].amount == D(str(res["infonavit_employer"])) + D(str(res["infonavit_credit"] or 0))
    for liab in rows:                                           # each liability = the sum of its sources
        view = s.F.liability_view(db, liab, with_sources=True)
        assert sum(D(x["amount"]) for x in view["sources"]) == liab.amount
        assert {x["runId"] for x in view["sources"]} == {w.run.id}
    assert s.F.accrue(db, w.org.id, w.users[0].id)["sourcesAdded"] == 0          # idempotent


def test_a_draft_run_is_never_accrued(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    draft = ah.new_run(db, w)
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, draft, w.org.id, [w.employee.id])     # calculated, not committed
    s.F.accrue(db, w.org.id, w.users[0].id)
    from app.modules.payroll.models import PayrollMxAuthorityLiabilitySource as S

    assert {r for (r,) in db.query(S.payroll_run_id)} == {w.run.id}


def test_a_source_row_cannot_be_linked_twice(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll.models import PayrollMxAuthorityLiabilitySource as S

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    src = db.query(S).first()
    db.add(S(liability_id=src.liability_id, organization_id=src.organization_id, payroll_run_id=src.payroll_run_id,
             payslip_item_id=src.payslip_item_id, employee_id=src.employee_id, source_table=src.source_table,
             source_row_id=src.source_row_id, branch_code=src.branch_code, amount=src.amount))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_rows_committed_after_filing_go_to_a_complementary_liability(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    first_amount = isr.amount
    s.F.file_liability(db, w.org.id, isr.id, "SYN-ACUSE-1", w.users[0].id)
    run2 = ah.commit(db, w, ah.new_run(db, w))                              # same pay-date month (2026-06)
    s.F.accrue(db, w.org.id, w.users[0].id)
    rows = ah.liabilities(db, w, "SAT_ISR")
    assert [(r.sequence, r.status) for r in rows] == [(0, "FILED"), (1, "ACCRUED")]
    assert rows[0].amount == first_amount                                    # a filed liability never changes
    view = s.F.liability_view(db, rows[1], with_sources=True)
    assert view["complementary"] and {x["runId"] for x in view["sources"]} == {run2.id}


def test_due_dates_only_from_an_active_calendar_row(db, monkeypatch):
    from app.modules.payroll import mexico_due_dates as due
    from app.modules.payroll.models import StatutoryFilingCalendar as C

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    assert isr.due_date is None and isr.due_rule_ref == due.UNSOURCED
    assert s.F.liability_view(db, isr)["dueState"] == due.UNSOURCED
    row = C(jurisdiction_country="MX", report_type="MX_ISR_WITHHOLDING", reporting_year="2026", period_key="2026-06",
            period_label="SYNTHETIC", due_date=date(2026, 7, 17), status="Draft")
    db.add(row)
    db.commit()
    s.F.accrue(db, w.org.id, w.users[0].id)
    db.refresh(isr)
    assert isr.due_date is None                                              # a Draft row is not content
    row.status = "Active"
    db.commit()
    s.F.accrue(db, w.org.id, w.users[0].id)
    db.refresh(isr)
    assert isr.due_date == date(2026, 7, 17) and isr.due_rule_ref == f"calendar:{row.id}"
    assert due.due_state(isr.due_date, False, today=date(2026, 7, 18)) == "OVERDUE"
    assert due.due_state(isr.due_date, False, today=date(2026, 7, 14)) == "DUE_SOON"


def test_isr_remittance_record_file_pay_reconcile_with_four_eyes(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    with pytest.raises(Exception):
        s.F.file_liability(db, w.org.id, isr.id, "  ", w.users[0].id)            # a reference is required
    s.F.file_liability(db, w.org.id, isr.id, "SYN-DECL-1", w.users[0].id)
    s.F.pay_liability(db, w.org.id, isr.id, "SYN-PAY-1", w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        s.F.reconcile_liability(db, w.org.id, isr.id, w.users[0].id)             # the payer cannot reconcile
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    out = s.F.reconcile_liability(db, w.org.id, isr.id, w.users[1].id)
    assert out["status"] == "RECONCILED" and out["declarationReference"] == "SYN-DECL-1"
    assert ah.events(db, "LIABILITY", isr) == ["ACCRUED", "FILED", "PAYMENT_RECORDED", "RECONCILED"]


def test_isn_is_filed_only_through_its_return_and_imss_reconciles_only_against_sua(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isn,) = ah.liabilities(db, w, "ISN")
    with pytest.raises(Exception, match="state return"):
        s.F.file_liability(db, w.org.id, isn.id, "SYN", w.users[0].id)
    (imss,) = ah.liabilities(db, w, "IMSS")
    s.F.file_liability(db, w.org.id, imss.id, "SYN-SUA", w.users[0].id)
    s.F.pay_liability(db, w.org.id, imss.id, "SYN-PAY", w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        s.F.reconcile_liability(db, w.org.id, imss.id, w.users[1].id)
    assert exc.value.key == "MX_SUA_NOT_RECONCILED"


def test_other_organisations_cannot_see_or_touch_a_liability(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    other = ah.committed_world(db, monkeypatch, code="MXAUTH2")                # another Mexican organisation
    with pytest.raises(Exception, match="not found"):
        s.F.file_liability(db, other.org.id, isr.id, "SYN", other.users[0].id)
    db.refresh(isr)
    assert isr.status == "ACCRUED"
