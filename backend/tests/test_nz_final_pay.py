"""New Zealand final pay and rehire (ZP-NZ-ENG-001 Phase 6; SQLite; NZ-021):
one case per employment, vesting before calculating, four-eyes, a FINAL run
that ends the employment without zeroing any entitlement, and rehire."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_pay_service as lps
from app.modules.payroll import nz_leave_service as lv
from app.modules.payroll import nz_lifecycle as life
from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollNzEmployment, PayrollNzLeaveEntitlement, PayrollNzLeavePayCalculation, PayrollRun, PayrollStatus,
    PayslipItem,
)
from tests._nz_p6_fixtures import _request_codes, add_ledger, employ, employer_profile, make_employee, signed  # noqa: F401

D = Decimal
END = date(2026, 10, 15)


@pytest.fixture()
def world(db, organization, signed, monkeypatch):
    employee = make_employee(db, organization)
    employment = employ(db, organization, employee)
    employer_profile(db, organization)
    add_ledger(db, organization, employee, employment, end=date(2026, 10, 9), weeks=52)
    monkeypatch.setattr(service, "generate_payslips_for_run", lambda db, run, org, employee_ids=None: run)
    return organization, employee, employment


def _case(db, organization, employee):
    case = life.open_final_pay_case(db, organization.id, employee.id, END, "RESIGNED", 1, "resigned")
    db.commit()
    return case


def test_open_case_once_per_employment(db, world):
    organization, employee, _employment = world
    _case(db, organization, employee)
    with pytest.raises(BadRequestException, match="already has a final pay case"):
        life.open_final_pay_case(db, organization.id, employee.id, END, "RESIGNED", 1, "again")
    with pytest.raises(BadRequestException, match="reason"):
        life.open_final_pay_case(db, organization.id, employee.id, END, "RESIGNED", 1, " ")


def test_calculate_vests_first_and_resolves_every_entitlement(db, world):
    organization, employee, _employment = world
    case = life.calculate_final_pay(db, organization.id, _case(db, organization, employee).id, 1)
    db.commit()
    by_purpose = {entry["purpose"]: entry for entry in case.outstanding}
    assert case.last_anniversary == date(2026, 5, 12) and case.status == "CALCULATED"
    assert D(by_purpose["FINAL_VESTED"]["units"]) == 4 and by_purpose["FINAL_VESTED"]["amount"] == "5200.00"
    assert "calculationId" in by_purpose["FINAL_UNVESTED"]
    for kind in ("SICK", "FAMILY_VIOLENCE"):
        assert by_purpose[kind]["amount"] == "0" and "calculationId" not in by_purpose[kind]
        assert by_purpose[kind]["reason"] == "not payable on termination"
    # recalculating voids the earlier lines
    life.calculate_final_pay(db, organization.id, case.id, 1)
    statuses = [c.status for c in db.query(PayrollNzLeavePayCalculation)
                .filter(PayrollNzLeavePayCalculation.final_pay_case_id == case.id)]
    assert statuses.count("CALCULATED") == 2 and statuses.count("VOID") == 2


def test_approve_four_eyes(db, world):
    organization, employee, _employment = world
    case = life.calculate_final_pay(db, organization.id, _case(db, organization, employee).id, 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        life.approve_final_pay(db, organization.id, case.id, 1)
    assert life.approve_final_pay(db, organization.id, case.id, 2).status == "APPROVED"


def _final_run(db, organization, employee, case):
    run = life.create_special_run(db, organization.id, {
        "kind": "FINAL", "payDate": END, "periodStart": date(2026, 10, 3), "periodEnd": END,
        "employeeIds": [employee.id], "options": {"finalPayCaseId": case.id}}, 1, "final pay")
    lines = life.final_pay_lines_for_run(db, run, employee)
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ",
                       nz_calculation_snapshot={"finalPay": lines, "exceptions": [], "hashes": {"resultHash": "x"},
                                                "accumulatorDeltas": {}})
    db.add(item)
    db.commit()
    return run, lines


def test_final_run_paid_ends_employment_without_zeroing(db, world):
    organization, employee, employment = world
    case = life.calculate_final_pay(db, organization.id, _case(db, organization, employee).id, 1)
    db.commit()
    life.approve_final_pay(db, organization.id, case.id, 2)
    run, lines = _final_run(db, organization, employee, case)
    assert run.nz_payment_kind == "FINAL" and case.run_id == run.id and len(lines) == 2
    inputs = nzs.resolve_nz_calc_inputs(db, organization.id, employee, run.pay_date, run=run)
    assert inputs["nz_final_pay_lines"] == lines and inputs["nz_run_options"] == {"finalPayCaseId": case.id}
    run.nz_approval_fingerprint = nzs.nz_approval_fingerprint(db, run)
    nzs.before_run_transition(db, run, PayrollStatus.PAID, 1)
    db.refresh(employment)
    assert (case.status, employment.status, employment.end_date) == ("PAID", "ENDED", END)
    ents = {e.leave_type: e for e in db.query(PayrollNzLeaveEntitlement)
            .filter(PayrollNzLeaveEntitlement.employment_id == employment.id)}
    assert (ents["ANNUAL"].status, ents["ANNUAL"].paid_out) == ("PAID_OUT", D("4"))
    sick = ents["SICK"]
    assert (sick.status, sick.expires_on) == ("ACTIVE", END) and lv._engine().balance(sick) == 10
    assert lv._engine().balance(ents["FAMILY_VIOLENCE"]) > 0 and ents["FAMILY_VIOLENCE"].expires_on == END


def test_preflight_blocks_final_run_without_case(db, world):
    organization, employee, _employment = world
    run = PayrollRun(organization_id=organization.id, period_label="Final", period_start=END, period_end=END,
                     pay_date=END, status="Review", nz_payment_kind="FINAL", nz_run_options={})
    db.add(run)
    db.flush()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ", nz_calculation_snapshot={"exceptions": []}))
    db.commit()
    assert "NZ_FINAL_PAY_OPEN" in {p["code"] for p in nzs.nz_run_preflight(db, run)}
    with pytest.raises(BadRequestException, match="APPROVED"):
        life.create_special_run(db, organization.id, {
            "kind": "FINAL", "payDate": END, "employeeIds": [employee.id],
            "options": {"finalPayCaseId": _case(db, organization, employee).id}}, 1, "too early")


def test_rehire_new_instance_new_anniversaries(db, world):
    organization, employee, employment = world
    with pytest.raises(BadRequestException, match="still has an ACTIVE"):
        life.rehire(db, organization.id, employee.id, {"start_date": date(2027, 1, 4)}, 1, "rehired")
    lv.end_nz_employment(db, organization.id, employment.id, END, "RESIGNED", 1, "left")
    rehire = life.rehire(db, organization.id, employee.id, {"start_date": date(2027, 1, 4)}, 1, "rehired")
    lv.approve_nz_employment(db, organization.id, rehire.id, 2)
    assert (rehire.continuity_rule, lv.anchor_date(db, rehire)) == ("NEW_INSTANCE", date(2027, 1, 4))
    assert db.query(PayrollNzEmployment).filter(PayrollNzEmployment.employee_id == employee.id).count() == 2


def test_special_run_kinds(db, world):
    organization, employee, _employment = world
    run = life.create_special_run(db, organization.id, {
        "kind": "LUMP_SUM", "payDate": date(2026, 12, 18), "employeeIds": [employee.id],
        "options": {"lumpSumComponent": "BONUS", "ignored": 1}}, 1, "Christmas bonus")
    assert (run.nz_payment_kind, run.nz_run_options, run.period_start) == \
        ("LUMP_SUM", {"lumpSumComponent": "BONUS"}, date(2026, 12, 18))
    with pytest.raises(BadRequestException, match="kind must be"):
        life.create_special_run(db, organization.id, {"kind": "CORRECTION", "payDate": END,
                                                      "employeeIds": [employee.id]}, 1, "x")


def test_list_final_pay_cases_and_cash_ups(db, world):
    """P7c list routes: an employee's final pay cases and cash-up requests."""
    organization, employee, _employment = world
    case = _case(db, organization, employee)
    assert [c.id for c in life.list_final_pay_cases(db, organization.id, employee.id)] == [case.id]
    assert lps.list_cash_ups(db, organization.id, employee.id) == []
