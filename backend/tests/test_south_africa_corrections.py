"""South Africa corrections (ZP-ZA-ENG-001 §8; Phase 9): a committed payslip is
corrected by a LINKED delta payslip replayed from its frozen context; the
original is never edited; ETI is reversed and re-recorded when it changes.
"ZA" is South Africa."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import south_africa_lifecycle as lifecycle
from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.models import PayrollRun, PayrollStatus, PayrollZaEtiLedgerEntry, PayslipItem

from tests._za_run_helpers import APPROVER, PREPARER, employee, payslip, run


def _committed(db, organization, fixture="f1_monthly_salary_age_40", code="ZA-K1"):
    r = run(db, organization, status="Authorized")
    emp = employee(db, organization, code)
    item = payslip(db, organization, r, emp, fixture)
    svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)    # commit hook (no approval stored)
    r.status = "Paid"
    db.commit()
    return r, emp, item


def test_correction_books_a_linked_delta_and_leaves_the_original(db, organization):
    r, emp, item = _committed(db, organization)
    before = (item.gross_pay, item.net_pay, item.tds, dict(item.za_calculation_snapshot))
    out = lifecycle.create_za_correction(db, organization.id, item.id, "missed salary increase",
                                         {"gross": "52000", "basic": "52000"}, PREPARER)
    db.refresh(item)
    assert (item.gross_pay, item.net_pay, item.tds, item.za_calculation_snapshot) == before
    corr = db.get(PayslipItem, out["payslipId"])
    corr_run = db.get(PayrollRun, out["correctionRunId"])
    assert corr_run.notes.startswith(lifecycle.ZA_CORRECTION_MARKER) and lifecycle.is_za_correction_run(corr_run)
    assert str(getattr(corr_run.status, "value", corr_run.status)) == "Paid"
    link = corr.za_calculation_snapshot["correction"]
    assert (link["originalPayslipId"], link["originalRunId"], link["sequence"]) == (item.id, r.id, 1)
    assert corr.gross_pay == Decimal("2000")
    assert corr.tds == Decimal(out["deltas"]["za_paye"]) > 0
    assert corr.net_pay == corr.gross_pay - corr.total_deductions
    assert out["eti"] is None


def test_second_correction_restates_on_the_latest_basis(db, organization):
    _r, _emp, item = _committed(db, organization)
    lifecycle.create_za_correction(db, organization.id, item.id, "raise", {"gross": "52000", "basic": "52000"},
                                   PREPARER)
    out = lifecycle.create_za_correction(db, organization.id, item.id, "raise again",
                                         {"gross": "53000", "basic": "53000"}, PREPARER)
    assert out["sequence"] == 2 and out["grossDelta"] == "1000"


@pytest.mark.parametrize("changes, message", [
    ({}, "at least one"),
    ({"za_paye": "1"}, "not correctable"),
    ({"gross": "50000"}, "no change"),
])
def test_correction_refusals(db, organization, changes, message):
    _r, _emp, item = _committed(db, organization)
    with pytest.raises(BadRequestException, match=message):
        lifecycle.create_za_correction(db, organization.id, item.id, "x", changes, PREPARER)


def test_correction_needs_a_reason_and_a_committed_run(db, organization):
    _r, _emp, item = _committed(db, organization)
    with pytest.raises(BadRequestException, match="reason"):
        lifecycle.create_za_correction(db, organization.id, item.id, " ", {"gross": "1"}, PREPARER)
    open_run = run(db, organization, status="Review")
    open_item = payslip(db, organization, open_run, employee(db, organization, "ZA-OPEN"))
    db.commit()
    with pytest.raises(BadRequestException, match="committed"):
        lifecycle.create_za_correction(db, organization.id, open_item.id, "x", {"gross": "1"}, PREPARER)


def test_a_correction_delta_is_not_itself_corrected(db, organization):
    _r, _emp, item = _committed(db, organization)
    out = lifecycle.create_za_correction(db, organization.id, item.id, "raise", {"gross": "52000", "basic": "52000"},
                                         PREPARER)
    with pytest.raises(BadRequestException, match="original payslip"):
        lifecycle.create_za_correction(db, organization.id, out["payslipId"], "x", {"gross": "1"}, PREPARER)


def test_drifted_frozen_context_is_refused(db, organization):
    _r, _emp, item = _committed(db, organization)
    snap = dict(item.za_calculation_snapshot)
    snap["totalsAll"] = {**snap["totalsAll"], "za_paye": "1.00"}
    item.za_calculation_snapshot = snap
    db.commit()
    with pytest.raises(BadRequestException, match="does not reproduce"):
        lifecycle.create_za_correction(db, organization.id, item.id, "x", {"gross": "52000"}, PREPARER)


def test_eti_is_reversed_and_re_recorded_when_it_changes(db, organization):
    _r, emp, item = _committed(db, organization, "f3_eti_first_twelve_months_r5000_is_r1500", "ZA-ETI")
    original = db.query(PayrollZaEtiLedgerEntry).filter_by(employee_id=emp.id).one()
    assert original.eti_amount == Decimal("1500.00")
    out = lifecycle.create_za_correction(db, organization.id, item.id, "hours were 80 not 160",
                                         {"za_eti_paid_hours": "80"}, PREPARER)
    rows = db.query(PayrollZaEtiLedgerEntry).filter_by(employee_id=emp.id).order_by(PayrollZaEtiLedgerEntry.id).all()
    assert [r.status for r in rows] == ["REVERSED", "CALCULATED"]
    assert rows[1].reverses_id == original.id and rows[1].payslip_item_id == out["payslipId"]
    assert rows[1].eti_amount < original.eti_amount
    assert out["eti"] == {"reversedEntryId": original.id, "recordedEntryId": rows[1].id}
    # ETI never moves the employee's money (ZA-010)
    corr = db.get(PayslipItem, out["payslipId"])
    assert corr.net_pay == Decimal("0") and corr.gross_pay == Decimal("0")
