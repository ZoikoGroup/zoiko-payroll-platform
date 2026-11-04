"""New Zealand leave-pay service (ZP-NZ-ENG-001 Phase 6; SQLite): calculation
rows keep both candidates (NZ-017), lines feed the run covering them, PAID
exactly once, cash-ups on a written request with a second person, and
family-violence calculations stay restricted (NZ-023)."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_pay_service as lps
from app.modules.payroll import nz_leave_service as lv
from app.modules.payroll.models import (
    PayrollNzCashUpRequest, PayrollNzLeaveEntitlement, PayrollNzLeaveEvent, PayrollNzLeavePayCalculation,
    PayrollRun, PayslipItem,
)
from tests._nz_p6_fixtures import _request_codes, add_ledger, employ, make_employee, request, signed  # noqa: F401

D = Decimal


@pytest.fixture()
def world(db, organization, signed):
    employee = make_employee(db, organization)
    employment = employ(db, organization, employee)
    add_ledger(db, organization, employee, employment)
    lv.vest_entitlements(db, organization.id, date(2026, 6, 1))
    db.commit()
    return organization, employee, employment


def _annual_event(db, organization, employee):
    req = request(db, organization, employee, "annual", date(2026, 6, 1), date(2026, 6, 5))
    return db.query(PayrollNzLeaveEvent).filter(PayrollNzLeaveEvent.source_request_id == req["id"]).one()


def _run(db, organization, start=date(2026, 6, 1), end=date(2026, 6, 14)):
    run = PayrollRun(organization_id=organization.id, period_label="Jun", period_start=start, period_end=end,
                     pay_date=end + (date(2026, 6, 15) - date(2026, 6, 14)), status="Review")
    db.add(run)
    db.commit()
    return run


def test_calculation_row_keeps_both_candidates(db, world):
    organization, employee, _employment = world
    event = _annual_event(db, organization, employee)
    row = lps.calculate_for_event(db, organization.id, event.id, 1)
    db.commit()
    assert (row.candidate_a_name, row.candidate_a_amount, row.candidate_b_name, row.candidate_b_amount) == \
        ("OWP", D("1200"), "AWE", D("1300"))
    assert (row.chosen, row.amount, row.displaced_amount, row.unit, row.units) == \
        ("AWE", D("1300.00"), D("1200.00"), "WEEKS", D("1"))
    assert row.statutory_reason.startswith("greater of OWP and AWE") and len(row.inputs["ledgerRowIds"]) == 52
    assert event.leave_pay_calculation_id == row.id and len(row.pack_hash) == 64
    with pytest.raises(BadRequestException, match="already has"):
        lps.calculate_for_event(db, organization.id, event.id, 1)


def test_leave_lines_feed_regular_run(db, world):
    organization, employee, _employment = world
    event = _annual_event(db, organization, employee)
    calc = lps.calculate_for_event(db, organization.id, event.id, 1)
    run = _run(db, organization)
    lines = lps.leave_lines_for_run(db, run, employee)
    assert lines == [{"calculationId": calc.id, "purpose": "ANNUAL_LEAVE", "amount": "1300.00",
                      "displaced": "1200.00"}]
    inputs = nzs.resolve_nz_calc_inputs(db, organization.id, employee, run.pay_date, run=run)
    assert inputs["nz_leave_lines"] == lines and inputs["nz_prior_four_week_gross"] is None


def test_preflight_flags_uncalculated_leave(db, world):
    organization, employee, _employment = world
    event = _annual_event(db, organization, employee)
    run = _run(db, organization)
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ", nz_calculation_snapshot={"exceptions": []})
    db.add(item)
    db.commit()
    assert "NZ_LEAVE_PAY_UNCALCULATED" in {p["code"] for p in nzs.nz_run_preflight(db, run)}
    lps.calculate_for_event(db, organization.id, event.id, 1)
    assert "NZ_LEAVE_PAY_UNCALCULATED" not in {p["code"] for p in nzs.nz_run_preflight(db, run)}


def _paid_item(db, organization, employee, run, lines):
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ",
                       nz_calculation_snapshot={"leavePay": lines, "exceptions": []})
    db.add(item)
    db.commit()
    return item


def test_leave_pay_marked_paid_once(db, world):
    organization, employee, _employment = world
    event = _annual_event(db, organization, employee)
    calc = lps.calculate_for_event(db, organization.id, event.id, 1)
    run = _run(db, organization)
    item = _paid_item(db, organization, employee, run, lps.leave_lines_for_run(db, run, employee))
    assert lps.mark_paid(db, run) == 1
    assert lps.mark_paid(db, run) == 0                                           # a retry pays nothing twice
    assert (calc.status, calc.run_id, calc.payslip_item_id, event.status) == ("PAID", run.id, item.id, "PAID")
    assert lps.leave_lines_for_run(db, _run(db, organization, date(2026, 6, 1), date(2026, 6, 2)), employee) == []


def _annual_entitlement(db, employee):
    return (db.query(PayrollNzLeaveEntitlement)
            .filter(PayrollNzLeaveEntitlement.employee_id == employee.id,
                    PayrollNzLeaveEntitlement.leave_type == "ANNUAL").one())


def test_cash_up_requires_written_request_and_second_person(db, world):
    organization, employee, _employment = world
    ent = _annual_entitlement(db, employee)
    with pytest.raises(BadRequestException, match="written request"):
        lps.request_cash_up(db, organization.id, employee.id, {"entitlement_id": ent.id, "weeks": 1}, 1, "asked")
    row = lps.request_cash_up(db, organization.id, employee.id,
                              {"entitlement_id": ent.id, "weeks": 1, "written_request_ref": "email-2026-06-01.pdf",
                               "requested_on": date(2026, 6, 1)}, 1, "employee asked in writing")
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        lps.approve_cash_up(db, organization.id, row.id, 1)
    lps.approve_cash_up(db, organization.id, row.id, 2)
    calc = db.get(PayrollNzLeavePayCalculation, row.leave_pay_calculation_id)
    assert (row.status, calc.purpose, calc.amount, calc.displaced_amount) == ("APPROVED", "CASH_UP", D("1300.00"), 0)


def test_cash_up_limit_blocks(db, world):
    organization, employee, _employment = world
    ent = _annual_entitlement(db, employee)
    row = lps.request_cash_up(db, organization.id, employee.id,
                              {"entitlement_id": ent.id, "weeks": "1.5", "written_request_ref": "letter.pdf",
                               "requested_on": date(2026, 6, 1)}, 1, "asked")
    db.commit()
    with pytest.raises(HTTPException, match="NZ_CASHUP_LIMIT"):
        lps.approve_cash_up(db, organization.id, row.id, 2)


def test_cash_up_reduces_entitlement_on_paid(db, world):
    organization, employee, _employment = world
    ent = _annual_entitlement(db, employee)
    row = lps.request_cash_up(db, organization.id, employee.id,
                              {"entitlement_id": ent.id, "weeks": 1, "written_request_ref": "letter.pdf",
                               "requested_on": date(2026, 6, 3)}, 1, "asked")
    db.commit()
    lps.approve_cash_up(db, organization.id, row.id, 2)
    run = _run(db, organization)
    _paid_item(db, organization, employee, run, lps.leave_lines_for_run(db, run, employee))
    lps.mark_paid(db, run)
    db.refresh(ent)
    assert (row.status, ent.paid_out, lv._engine().balance(ent)) == ("PAID", D("1"), D("3"))


def test_family_violence_calculations_restricted(db, world):
    organization, employee, _employment = world
    req = request(db, organization, employee, "nz_family_violence", date(2026, 6, 1), date(2026, 6, 1))
    event = db.query(PayrollNzLeaveEvent).filter(PayrollNzLeaveEvent.source_request_id == req["id"]).one()
    calc = lps.calculate_for_event(db, organization.id, event.id, 1)
    assert (calc.purpose, calc.restricted, calc.chosen) == ("FAMILY_VIOLENCE", True, "RDP")   # 1,200 / 5 days
    assert calc.amount == D("240.00")
    assert lps.list_calculations(db, organization.id, 3, employee.id) == []
    run = _run(db, organization)
    assert [l["purpose"] for l in lps.leave_lines_for_run(db, run, employee)] == ["RESTRICTED_LEAVE"]


def test_public_holiday_worked_pay(db, world):
    organization, employee, _employment = world
    decision = next(r for r in lv.propose_public_holiday_decisions(db, organization.id, 2026, actor_id=1)
                    if r.holiday_date == date(2026, 12, 25))
    lv.update_public_holiday_decision(db, organization.id, decision.id, {
        "worked": True, "shift_start": "2026-12-25T08:00:00", "shift_end": "2026-12-25T14:00:00"}, 1, "worked")
    lv.approve_public_holiday_decision(db, organization.id, decision.id, 2)
    calc = lps.calculate_for_public_holiday(db, organization.id, decision.id, 1)
    assert (calc.purpose, calc.units, calc.unit) == ("PUBLIC_HOLIDAY_WORKED", D("6.00"), "HOURS")
    assert (calc.amount, calc.displaced_amount) == (D("270.00"), D("180.00"))    # 6h x 30 x 1.5; salary covers 1.0
