"""New Zealand compensating corrections (ZP-NZ-ENG-001 Phase 6, NZ-006; SQLite):
refused while the correction policy is pending; the original PAID payslip is
never modified; the correction payslip carries only the deltas and posts its
year-to-date entries as CORRECTION."""
import copy
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_lifecycle as life
from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.models import PayrollEmployee, PayrollNzAccumulatorEntry, PayrollRun, PayslipItem
from tests._nz_engine_helpers import build_p6_pack, ctx
from tests._nz_p6_fixtures import _request_codes, use_pack  # noqa: F401

D = Decimal


@pytest.fixture()
def paid(db, organization, monkeypatch):
    use_pack(monkeypatch)
    employee = PayrollEmployee(organization_id=organization.id, employee_code="NZ-1", name="Aroha Ngata",
                               country_code="NZ")
    db.add(employee)
    db.flush()
    calc_ctx = ctx(pack=build_p6_pack(), nz_organization_id=organization.id, nz_employee_id=employee.id)
    result = {"nz_result": calculate_payroll(calc_ctx, "standard").nz_result}    # assigns the trace id
    frozen = nzs.nz_freeze_context(calc_ctx)
    run = PayrollRun(organization_id=organization.id, period_label="Apr", period_start=date(2026, 3, 26),
                     period_end=date(2026, 4, 8), pay_date=date(2026, 4, 8), status="Paid")
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ", gross_pay=D("3000"),
                       nz_calculation_snapshot=nzs.nz_payslip_snapshot(result, frozen))
    db.add(item)
    db.commit()
    return organization, item


def _create(db, organization, item, delta=None):
    row = life.create_correction(db, organization.id, item.id, delta or {"gross": "3200", "basic": "3200"}, 1,
                                 "late overtime approval")
    db.commit()
    return row


def test_correction_refused_while_policy_pending(db, paid, monkeypatch):
    organization, item = paid
    use_pack(monkeypatch, nz_correction_policy="PENDING_G1")
    with pytest.raises(HTTPException) as refused:
        _create(db, organization, item)
    assert refused.value.status_code == 409 and "NZ_CORRECTION_POLICY_PENDING" in refused.value.detail


def test_only_paid_payslips_and_known_inputs(db, paid):
    organization, item = paid
    with pytest.raises(BadRequestException, match="may change only"):
        _create(db, organization, item, {"tax_code": "S"})
    db.get(PayrollRun, item.payroll_run_id).status = "Review"
    db.commit()
    with pytest.raises(BadRequestException, match="PAID payslip"):
        _create(db, organization, item)


def test_original_never_modified_and_delta_payslip_only_differences(db, paid):
    organization, item = paid
    before = copy.deepcopy(item.nz_calculation_snapshot)
    row = _create(db, organization, item)
    assert row.result_delta["gross"] == "200" and D(row.result_delta["obligations"]["paye"]) > 0
    with pytest.raises(BadRequestException, match="four-eyes"):
        life.approve_correction(db, organization.id, row.id, 1)
    life.approve_correction(db, organization.id, row.id, 2)
    life.apply_correction(db, organization.id, row.id, date(2026, 4, 22), 1)
    db.commit()
    db.refresh(item)
    assert item.nz_calculation_snapshot == before and item.gross_pay == D("3000")
    fix = db.get(PayslipItem, row.correction_payslip_item_id)
    run = db.get(PayrollRun, row.correction_run_id)
    assert (row.status, fix.nz_correction_of_id, fix.gross_pay, run.nz_payment_kind) == \
        ("APPLIED", item.id, D("200"), "CORRECTION")
    assert fix.net_pay == D(row.result_delta["netPay"]) and fix.nz_calculation_snapshot["correctionOf"] == item.id


def test_correction_accumulator_entries_kind(db, paid):
    organization, item = paid
    row = _create(db, organization, item)
    life.approve_correction(db, organization.id, row.id, 2)
    life.apply_correction(db, organization.id, row.id, date(2026, 4, 22), 1)
    run = db.get(PayrollRun, row.correction_run_id)
    nzs.post_accumulators(db, run, 1)
    nzs.post_accumulators(db, run, 1)                                         # idempotent
    entries = db.query(PayrollNzAccumulatorEntry).filter(PayrollNzAccumulatorEntry.run_id == run.id).all()
    assert entries and {e.entry_kind for e in entries} == {"CORRECTION"}
    by_obligation = {e.obligation: e.amount for e in entries}
    assert by_obligation["PAYE_GROSS"] == D("200.00")
    assert len(entries) == len(row.result_delta["accumulatorDeltas"])


def test_replay_of_original_unchanged_after_correction(db, paid):
    organization, item = paid
    row = _create(db, organization, item)
    life.approve_correction(db, organization.id, row.id, 2)
    life.apply_correction(db, organization.id, row.id, date(2026, 4, 22), 1)
    replayed = nzs.nz_replay(item.nz_calculation_snapshot["frozenContext"])
    assert replayed.nz_result["hashes"]["resultHash"] == item.nz_calculation_snapshot["hashes"]["resultHash"]


def test_void_correction(db, paid):
    organization, item = paid
    row = _create(db, organization, item)
    life.void_correction(db, organization.id, row.id, 1, "entered in error")
    assert row.status == "VOID"
    with pytest.raises(BadRequestException, match="APPROVED"):
        life.apply_correction(db, organization.id, row.id, date(2026, 4, 22), 1)


def test_list_corrections(db, paid):
    """P7d list route: the organisation's corrections, newest first, or one employee's."""
    organization, item = paid
    row = _create(db, organization, item)
    assert [c.id for c in life.list_corrections(db, organization.id)] == [row.id]
    assert [c.id for c in life.list_corrections(db, organization.id, item.employee_id)] == [row.id]
