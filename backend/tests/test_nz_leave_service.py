"""New Zealand Holidays Act service (ZP-NZ-ENG-001 Phase 5; SQLite, no
external services): employments, vesting, leave events from the generic leave
flow, public-holiday decisions, alternative holidays and the gross-earnings
ledger. The pack is tests/_nz_engine_helpers.build_pack (spec values, signed
for the test) with TEST public-holiday rows."""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_service as lv
from app.modules.payroll import service
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import components as comp
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.new_zealand.pack import NzPack
from app.modules.payroll.models import (
    PayrollAttendanceRecord, PayrollEmployee, PayrollLeaveRequest, PayrollNzGrossEarningsLedger,
    PayrollNzLeaveEntitlement, PayrollNzLeaveEvent, PayrollRun, PayrollStatus, PayslipItem,
)
from tests._nz_engine_helpers import build_pack

D = Decimal
HOLIDAYS = [dict(rule_type=content.NZ_PUBLIC_HOLIDAY_RULE, effective_from=date(2026, 12, 25), effective_to=None,
                 rate_label="TEST Christmas", jurisdiction_state=None),
            dict(rule_type=content.NZ_PUBLIC_HOLIDAY_RULE, effective_from=date(2026, 1, 26), effective_to=None,
                 rate_label="TEST Auckland anniversary", jurisdiction_state="AUK"),
            dict(rule_type=content.NZ_PUBLIC_HOLIDAY_RULE, effective_from=date(2026, 1, 19), effective_to=None,
                 rate_label="TEST Wellington anniversary", jurisdiction_state="WGN")]


@pytest.fixture(autouse=True)
def _request_codes(monkeypatch):
    """Request codes use a PostgreSQL advisory lock; SQLite gets a counter."""
    from app.core import code_generation

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")


def _pack_fixture(monkeypatch, pending=False):
    rate_map, slabs = build_pack(pending=pending, extra_slabs=HOLIDAYS)
    pack = SimpleNamespace(tax_year="2026-27", effective_from=date(2026, 4, 1))
    monkeypatch.setattr(nzs, "_nz_pack_in_force", lambda db, on: (rate_map, slabs, pack))


@pytest.fixture()
def signed(monkeypatch):
    _pack_fixture(monkeypatch)


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="NZ-1", name="Aroha Ngata",
                          date_of_birth=date(1996, 5, 1), country_code="NZ", work_state="Auckland")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _employment(db, org_id, employee_id, start, **kw):
    row = lv.record_nz_employment(db, org_id, employee_id, dict(start_date=start, **kw), 1, "hired")
    lv.approve_nz_employment(db, org_id, row.id, 2)
    db.commit()
    return row


def _pattern(db, org_id, employee_id, start=date(2024, 1, 1)):
    row = nzs.record_nz_work_pattern(db, org_id, employee_id, {
        "effective_from": start, "pattern_type": "FIXED", "hours_source": "CONTRACT",
        "contracted_hours_per_week": 40, "contracted_days_per_week": 5,
        "weekly_schedule": {"MON": 8, "TUE": 8, "WED": 8, "THU": 8, "FRI": 8, "SAT": 0, "SUN": 0}}, 1, "contract")
    nzs.approve_nz_work_pattern(db, org_id, row.id, 2)
    db.commit()
    return row


def _request(db, org_id, employee_id, leave_type, start, end, reason=None):
    data = SimpleNamespace(employeeId=employee_id, leaveType=leave_type, startDate=start, endDate=end, reason=reason,
                           source="manual")
    return service.create_payroll_leave_request(db, data, org_id)


def _review(db, org_id, request_id, status="approved", reviewer=2):
    return service.review_payroll_leave_request(db, request_id, SimpleNamespace(status=status), org_id, reviewer)


def _ents(db, employee_id, leave_type=None):
    q = db.query(PayrollNzLeaveEntitlement).filter(PayrollNzLeaveEntitlement.employee_id == employee_id)
    if leave_type:
        q = q.filter(PayrollNzLeaveEntitlement.leave_type == leave_type)
    return q.order_by(PayrollNzLeaveEntitlement.entitlement_date).all()


# ── employments ─────────────────────────────────────────────────────────────
def test_employment_is_four_eyes_and_one_active(db, organization, employee):
    row = lv.record_nz_employment(db, organization.id, employee.id, {"start_date": date(2025, 5, 12)}, 1, "hired")
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        lv.approve_nz_employment(db, organization.id, row.id, 1)
    lv.approve_nz_employment(db, organization.id, row.id, 2)
    second = lv.record_nz_employment(db, organization.id, employee.id, {"start_date": date(2026, 1, 1)}, 1, "x")
    with pytest.raises(BadRequestException, match="already has an ACTIVE"):
        lv.approve_nz_employment(db, organization.id, second.id, 2)
    with pytest.raises(BadRequestException, match="agreement"):
        lv.record_nz_employment(db, organization.id, employee.id,
                                {"start_date": date(2026, 1, 1), "payg_eligible": True,
                                 "payg_basis": "IRREGULAR_INTERMITTENT"}, 1, "x")


def test_rehire_new_instance_resets_anchor(db, organization, employee):
    first = _employment(db, organization.id, employee.id, date(2024, 1, 8))
    lv.end_nz_employment(db, organization.id, first.id, date(2025, 6, 30), "RESIGNED", 1, "left")
    rehire = _employment(db, organization.id, employee.id, date(2025, 7, 1))
    assert lv.anchor_date(db, rehire) == date(2025, 7, 1)


def test_continuous_keeps_anchor(db, organization, employee):
    first = _employment(db, organization.id, employee.id, date(2024, 1, 8))
    lv.end_nz_employment(db, organization.id, first.id, date(2025, 6, 30), "TRANSFER", 1, "transfer")
    with pytest.raises(BadRequestException, match="evidence"):
        lv.record_nz_employment(db, organization.id, employee.id,
                                {"start_date": date(2025, 7, 1), "continuity_rule": "CONTINUOUS",
                                 "prior_employment_id": first.id}, 1, "x")
    cont = _employment(db, organization.id, employee.id, date(2025, 7, 1), continuity_rule="CONTINUOUS",
                       prior_employment_id=first.id, evidence_ref="transfer-letter.pdf")
    assert lv.anchor_date(db, cont) == date(2024, 1, 8)


# ── vesting ─────────────────────────────────────────────────────────────────
def test_vest_idempotent(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    result = lv.vest_entitlements(db, organization.id, date(2026, 7, 1), actor_id=1)
    db.commit()
    assert result["vested"] == 3
    assert sorted((e.leave_type, e.entitlement_date, e.unit, e.quantity) for e in _ents(db, employee.id)) == [
        ("ANNUAL", date(2026, 5, 12), "WEEKS", D("4")), ("FAMILY_VIOLENCE", date(2025, 11, 12), "DAYS", D("10")),
        ("SICK", date(2025, 11, 12), "DAYS", D("10"))]
    assert lv.vest_entitlements(db, organization.id, date(2026, 7, 1), actor_id=1)["vested"] == 0
    assert all(len(e.pack_hash) == 64 for e in _ents(db, employee.id))


def test_vest_carries_sick_and_supersedes_the_old_year(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    lv.vest_entitlements(db, organization.id, date(2026, 7, 1))
    old = _ents(db, employee.id, "SICK")[0]
    old.taken = D("4")
    db.commit()
    lv.vest_entitlements(db, organization.id, date(2026, 11, 12))
    sick = _ents(db, employee.id, "SICK")
    assert [(e.status, e.carried_in) for e in sick] == [("SUPERSEDED", D("0")), ("ACTIVE", D("6"))]


def test_vest_blocks_on_unsigned_pack(db, organization, employee, monkeypatch):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pack_fixture(monkeypatch, pending=True)
    with pytest.raises(HTTPException) as refused:
        lv.vest_entitlements(db, organization.id, date(2026, 7, 1))
    assert refused.value.status_code == 409 and "NZ_PACK_UNSIGNED" in refused.value.detail
    monkeypatch.setattr(nzs, "_nz_pack_in_force", lambda db, on: (None, None, None))
    with pytest.raises(HTTPException, match="no rule pack"):
        lv.vest_entitlements(db, organization.id, date(2026, 7, 1))


# ── leave requests -> events ────────────────────────────────────────────────
def test_approved_request_creates_event_and_consumes_fifo(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2024, 5, 12))
    _pattern(db, organization.id, employee.id)
    lv.vest_entitlements(db, organization.id, date(2026, 6, 1))
    annual = _ents(db, employee.id, "ANNUAL")
    assert [e.entitlement_date for e in annual] == [date(2025, 5, 12), date(2026, 5, 12)]
    req = _request(db, organization.id, employee.id, "annual", date(2026, 6, 1), date(2026, 6, 7))    # Mon..Sun
    _review(db, organization.id, req["id"])
    event = db.query(PayrollNzLeaveEvent).filter(PayrollNzLeaveEvent.source_request_id == req["id"]).one()
    assert (event.leave_type, event.unit, event.quantity, event.status) == ("ANNUAL", "WEEKS", D("1"), "APPROVED")
    db.refresh(annual[0])
    assert event.entitlement_id == annual[0].id and annual[0].taken == D("1")           # oldest first
    sick = _request(db, organization.id, employee.id, "sick", date(2026, 6, 8), date(2026, 6, 8))
    _review(db, organization.id, sick["id"])
    sick_event = db.query(PayrollNzLeaveEvent).filter(PayrollNzLeaveEvent.source_request_id == sick["id"]).one()
    assert (sick_event.unit, sick_event.quantity) == ("DAYS", D("1"))


def test_insufficient_entitlement_rolls_back_generic_approval(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2026, 1, 5))
    _pattern(db, organization.id, employee.id)
    req = _request(db, organization.id, employee.id, "annual", date(2026, 6, 1), date(2026, 6, 5))
    with pytest.raises(HTTPException) as refused:
        _review(db, organization.id, req["id"])
    assert refused.value.status_code == 409 and "insufficient annual" in refused.value.detail
    db.rollback()
    assert db.get(PayrollLeaveRequest, req["id"]).status == "pending"
    assert db.query(PayrollAttendanceRecord).filter(PayrollAttendanceRecord.employee_id == employee.id).count() == 0
    assert db.query(PayrollNzLeaveEvent).count() == 0


def test_nz_employee_needs_an_nz_leave_type(db, organization, employee):
    with pytest.raises(BadRequestException, match="New Zealand leave type"):
        _request(db, organization.id, employee.id, "compOff", date(2026, 6, 1), date(2026, 6, 1))
    unpaid = _request(db, organization.id, employee.id, "unpaid", date(2026, 6, 1), date(2026, 6, 1))
    _review(db, organization.id, unpaid["id"])                                          # passes through
    assert db.query(PayrollNzLeaveEvent).count() == 0


def test_bereavement_vests_per_event(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pattern(db, organization.id, employee.id)
    req = _request(db, organization.id, employee.id, "nz_bereavement_close", date(2026, 6, 1), date(2026, 6, 3))
    _review(db, organization.id, req["id"])
    ent = _ents(db, employee.id, "BEREAVEMENT_CLOSE")
    assert [(e.entitlement_date, e.quantity, e.taken, e.status) for e in ent] == \
        [(date(2026, 6, 1), D("3"), D("3"), "EXHAUSTED")]


def test_bereavement_before_qualifying_is_refused(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2026, 5, 1))
    _pattern(db, organization.id, employee.id)
    req = _request(db, organization.id, employee.id, "nz_bereavement_other", date(2026, 6, 1), date(2026, 6, 1))
    with pytest.raises(HTTPException, match="not yet available"):
        _review(db, organization.id, req["id"])


def test_cancel_restores_balance(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pattern(db, organization.id, employee.id)
    lv.vest_entitlements(db, organization.id, date(2026, 6, 1))
    req = _request(db, organization.id, employee.id, "sick", date(2026, 6, 1), date(2026, 6, 2))
    _review(db, organization.id, req["id"])
    event = db.query(PayrollNzLeaveEvent).one()
    sick = _ents(db, employee.id, "SICK")[0]
    assert sick.taken == D("2")
    with pytest.raises(BadRequestException, match="reason"):
        lv.cancel_leave_event(db, organization.id, event.id, 1, "")
    lv.cancel_leave_event(db, organization.id, event.id, 1, "entered in error")
    db.refresh(sick)
    assert (event.status, sick.taken) == ("CANCELLED", D("0"))


def test_rejecting_an_approved_request_releases_the_event(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pattern(db, organization.id, employee.id)
    lv.vest_entitlements(db, organization.id, date(2026, 6, 1))
    req = _request(db, organization.id, employee.id, "sick", date(2026, 6, 1), date(2026, 6, 1))
    _review(db, organization.id, req["id"])
    _review(db, organization.id, req["id"], status="rejected")
    assert db.query(PayrollNzLeaveEvent).one().status == "CANCELLED"
    assert _ents(db, employee.id, "SICK")[0].taken == D("0")


def test_non_nz_leave_is_untouched(db, organization):
    other = PayrollEmployee(organization_id=organization.id, employee_code="IN-1", name="Asha", country_code="IN")
    db.add(other)
    db.commit()
    req = _request(db, organization.id, other.id, "sick", date(2026, 6, 1), date(2026, 6, 1))
    _review(db, organization.id, req["id"])
    assert db.query(PayrollNzLeaveEvent).count() == 0
    with pytest.raises(BadRequestException, match="only for New Zealand"):
        _request(db, organization.id, other.id, "nz_alternative", date(2026, 6, 1), date(2026, 6, 1))


# ── public holidays ─────────────────────────────────────────────────────────
def test_propose_decisions_once_per_holiday(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pattern(db, organization.id, employee.id)
    rows = lv.propose_public_holiday_decisions(db, organization.id, 2026, actor_id=1)
    db.commit()
    assert sorted((r.holiday_date, r.region, r.otherwise_working_day, r.owd_basis) for r in rows) == [
        (date(2026, 1, 26), "AUK", "YES", "FIXED_PATTERN"), (date(2026, 12, 25), None, "YES", "FIXED_PATTERN")]
    assert lv.propose_public_holiday_decisions(db, organization.id, 2026, actor_id=1) == []


def test_public_holidays_block_until_g2(db, organization, employee, monkeypatch):
    rate_map, slabs = build_pack()
    monkeypatch.setattr(nzs, "_nz_pack_in_force", lambda db, on: (rate_map, slabs, SimpleNamespace()))
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    with pytest.raises(HTTPException, match="NZ_TABLE_EMPTY:public_holidays"):
        lv.propose_public_holiday_decisions(db, organization.id, 2026)


def test_undetermined_cannot_be_approved(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))                     # no work pattern
    row = lv.propose_public_holiday_decisions(db, organization.id, 2026, actor_id=1)[0]
    db.commit()
    assert (row.otherwise_working_day, row.owd_basis) == ("UNDETERMINED", "HISTORY")
    with pytest.raises(BadRequestException, match="UNDETERMINED"):
        lv.approve_public_holiday_decision(db, organization.id, row.id, 2)


def test_operator_decision_needs_evidence(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    row = lv.propose_public_holiday_decisions(db, organization.id, 2026, actor_id=1)[0]
    with pytest.raises(BadRequestException, match="evidence"):
        lv.update_public_holiday_decision(db, organization.id, row.id, {"otherwise_working_day": "YES"}, 1, "roster")
    lv.update_public_holiday_decision(db, organization.id, row.id,
                                      {"otherwise_working_day": "NO", "owd_evidence_ref": "roster.pdf"}, 1, "roster")
    db.commit()
    lv.approve_public_holiday_decision(db, organization.id, row.id, 2)
    assert (row.status, row.owd_basis, row.alternative_holiday_due) == ("APPROVED", "OPERATOR_DECISION", False)


def test_alternative_created_once(db, organization, employee, signed):
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pattern(db, organization.id, employee.id)
    rows = lv.propose_public_holiday_decisions(db, organization.id, 2026, actor_id=1)
    christmas = next(r for r in rows if r.holiday_date == date(2026, 12, 25))
    lv.update_public_holiday_decision(db, organization.id, christmas.id, {
        "worked": True, "shift_start": "2026-12-24T22:00:00", "shift_end": "2026-12-25T06:00:00"}, 1, "worked")
    assert (christmas.hours_on_holiday, christmas.alternative_holiday_due) == (D("6.00"), True)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        lv.approve_public_holiday_decision(db, organization.id, christmas.id, 1)
    lv.approve_public_holiday_decision(db, organization.id, christmas.id, 2)
    with pytest.raises(BadRequestException, match="DRAFT"):
        lv.approve_public_holiday_decision(db, organization.id, christmas.id, 3)
    alt = _ents(db, employee.id, "ALTERNATIVE")
    assert [(e.quantity, e.unit, e.source, e.source_decision_id) for e in alt] == \
        [(D("1"), "DAYS", "PUBLIC_HOLIDAY_WORKED", christmas.id)]
    req = _request(db, organization.id, employee.id, "nz_alternative", date(2027, 1, 4), date(2027, 1, 4))
    _review(db, organization.id, req["id"])
    db.refresh(alt[0])
    assert (alt[0].taken, alt[0].status) == (D("1"), "EXHAUSTED")


# ── gross-earnings ledger ───────────────────────────────────────────────────
def _paid_run(db, organization, employee):
    run = PayrollRun(organization_id=organization.id, period_label="Jun 2026", period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 14), pay_date=date(2026, 6, 15), status="Review")
    db.add(run)
    db.flush()
    snapshot = {"netPay": "1000.00", "exceptions": [], "accumulatorDeltas": {},
                "hashes": {"resultHash": "r", "packHash": "p" * 64},
                "baseLines": {"HOLIDAY_GROSS": [
                    {"component": "SALARY", "amount": "3000.00", "treatment": "INCLUDED", "counted": "3000.00"},
                    {"component": "ALLOWANCE", "amount": "120.00", "treatment": "REVIEW", "counted": "0.00"}]}}
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ", nz_calculation_snapshot=snapshot)
    db.add(item)
    db.commit()
    return run, item


def test_paid_run_writes_gross_ledger_once(db, organization, employee, signed):
    from tests._nz_p6_fixtures import employer_profile

    employer_profile(db, organization)
    _employment(db, organization.id, employee.id, date(2025, 5, 12))
    _pattern(db, organization.id, employee.id)
    run, item = _paid_run(db, organization, employee)
    run.nz_approval_fingerprint = nzs.nz_approval_fingerprint(db, run)
    nzs.before_run_transition(db, run, PayrollStatus.PAID, 1)
    nzs.before_run_transition(db, run, PayrollStatus.PAID, 1)                       # a retry writes nothing
    rows = db.query(PayrollNzGrossEarningsLedger).order_by(PayrollNzGrossEarningsLedger.component).all()
    assert [(r.component, r.amount, r.included, r.treatment, r.reason) for r in rows] == [
        ("ALLOWANCE", D("120.00"), False, "REVIEW", "HOLIDAY_GROSS:ALLOWANCE REVIEW"),
        ("SALARY", D("3000.00"), True, "INCLUDED", "HOLIDAY_GROSS:SALARY INCLUDED")]
    assert {r.days_worked for r in rows} == {D("10")}                                 # two FIXED Mon-Fri weeks
    assert {r.pack_hash for r in rows} == {"p" * 64} and rows[0].employment_id is not None


def test_holiday_gross_review_recorded_not_blocking_pay():
    rate_map, slabs = build_pack()
    pack = NzPack(rate_map, slabs, 1, date(2026, 6, 15))
    classes = comp.earning_classes(pack)
    parts = [("SALARY", D("3000")), ("ALLOWANCE", D("120"))]
    holiday = comp.obligation_base("HOLIDAY_GROSS", parts, classes, pack)
    assert holiday["base"] == D("3000")
    assert [(l["component"], l["treatment"], l["counted"]) for l in holiday["lines"]] == [
        ("SALARY", "INCLUDED", D("3000")), ("ALLOWANCE", "REVIEW", D("0"))]
    with pytest.raises(NZCalculationBlockedError, match="REVIEW"):
        comp.obligation_base("PAYE", parts, classes, pack)                            # pay bases still block
    assert "HOLIDAY_GROSS" in comp.BASES
