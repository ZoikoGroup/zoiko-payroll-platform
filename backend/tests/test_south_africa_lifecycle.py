"""South Africa run lifecycle (ZP-ZA-ENG-001 §5, §8; ZA-013, ZA-016, ZA-017;
Phase 9): calculation inputs, four-eyes exceptions, the approval fingerprint,
the commit (ETI ledger / directive applied / overrides APPLIED, once), overrides
and the public-holiday calendar. "ZA" is South Africa."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from app.modules.payroll import south_africa_lifecycle as lifecycle
from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.models import (
    CourtOrderedDeduction, PayrollAttendanceRecord, PayrollHoliday, PayrollStatus, PayrollZaEtiLedgerEntry,
    PayrollZaPayrollOverride, PayrollZaTaxDirective,
)

from tests._za_run_helpers import APPROVER, PREPARER, THIRD, employee, payslip, run


def _codes(found):
    return sorted((e["code"], e["employeeId"]) for e in found)


def _approve_all(db, organization, r, approver=APPROVER):
    for e in lifecycle.za_run_exceptions(db, r):
        if not e["approved"]:
            lifecycle.approve_za_run_exception(db, organization.id, r.id, key=e["key"], approver_id=approver)


@pytest.fixture()
def september(db, organization):
    r = run(db, organization)
    e1 = employee(db, organization, "ZA-F1")
    item = payslip(db, organization, r, e1)
    return r, e1, item


# ── public holidays (Public Holidays Act 36 of 1994) ────────────────────────
def test_easter_and_the_sunday_rule():
    assert [lifecycle.easter_sunday(y) for y in (2026, 2027, 2028)] == \
        [date(2026, 4, 5), date(2027, 3, 28), date(2028, 4, 16)]
    days = {h["date"]: h["name"] for h in lifecycle.za_public_holidays(2026)}
    assert days["2026-04-03"] == "Good Friday" and days["2026-04-06"] == "Family Day"
    assert days["2026-08-10"] == "National Women's Day (observed)"            # 9 Aug 2026 is a Sunday
    assert len(days) == 13
    assert "2027-12-27" in {h["date"] for h in lifecycle.za_public_holidays(2027)}   # Day of Goodwill on Sunday


def test_pack_holidays_hook_returns_the_schedule(db):
    assert svc._za_pack_holidays(db, 2026) == lifecycle.za_public_holidays(2026)


# ── calculation inputs ──────────────────────────────────────────────────────
def test_hours_from_attendance_split_sunday_and_public_holiday(db, organization):
    emp = employee(db, organization, "ZA-H")
    db.add(PayrollHoliday(organization_id=organization.id, date=date(2026, 9, 24), name="Heritage Day",
                          country="ZA"))
    for day, hours, status in ((date(2026, 9, 1), "8", "present"), (date(2026, 9, 2), "8.5", "present"),
                               (date(2026, 9, 6), "4", "present"),          # Sunday
                               (date(2026, 9, 24), "6", "present"),         # public holiday
                               (date(2026, 9, 3), "8", "absent")):
        db.add(PayrollAttendanceRecord(organization_id=organization.id, employee_id=emp.id, date=day,
                                       hours=hours, status=status))
    db.flush()
    assert lifecycle.za_hours(db, emp, date(2026, 9, 1), date(2026, 9, 30)) == \
        {"ordinary": "16.5", "sunday": "4", "public_holiday": "6"}
    assert lifecycle.za_hours(db, emp, date(2026, 10, 1), date(2026, 10, 31)) is None


def test_deduction_orders_in_force_are_passed_with_authority_and_evidence(db, organization):
    emp = employee(db, organization, "ZA-D")
    row = lifecycle.record_za_deduction_order(db, organization.id, emp.id, {
        "orderType": "garnishee", "authorityType": "court_order", "evidenceRef": "EAO 12/2026",
        "amount": "500", "startDate": "2026-09-01"}, actor_id=PREPARER)
    db.add(CourtOrderedDeduction(organization_id=organization.id, employee_id=emp.id, jurisdiction="ENGLAND_WALES",
                                 order_type="AEO_PRIORITY", start_date=date(2026, 1, 1), fixed_deduction_amount=9))
    db.flush()
    assert lifecycle.za_deduction_orders(db, emp, date(2026, 9, 30)) == [
        {"id": row.id, "order_type": "GARNISHEE", "authority_type": "COURT_ORDER", "amount": "500.00",
         "evidence_ref": "EAO 12/2026"}]
    assert lifecycle.za_deduction_orders(db, emp, date(2026, 8, 31)) is None


@pytest.mark.parametrize("data, message", [
    ({"authorityType": "MANAGER"}, "authorityType"),
    ({"evidenceRef": ""}, "evidence"),
    ({"amount": "0"}, "positive"),
])
def test_deduction_order_needs_authority_evidence_and_amount(db, organization, data, message):
    emp = employee(db, organization, "ZA-D2")
    base = {"orderType": "LOAN", "authorityType": "CONSENT", "evidenceRef": "signed consent", "amount": "100",
            "startDate": "2026-09-01"}
    with pytest.raises(BadRequestException, match=message):
        lifecycle.record_za_deduction_order(db, organization.id, emp.id, {**base, **data})


def test_calc_inputs_carry_hours_orders_and_approved_overrides(db, organization, september):
    r, e1, item = september
    row = PayrollZaPayrollOverride(organization_id=organization.id, employee_id=e1.id, payroll_run_id=r.id,
                                   payslip_item_id=item.id, field="za_paye", before_value=Decimal("11075.58"),
                                   after_value=Decimal("11000"), reason_code="SARS", reason="letter",
                                   status="APPROVED", expires_on=date(2026, 12, 31))
    expired = PayrollZaPayrollOverride(organization_id=organization.id, employee_id=e1.id, payroll_run_id=r.id,
                                       field="za_sdl", before_value=Decimal("500"), after_value=Decimal("0"),
                                       reason_code="X", reason="x", status="APPROVED", expires_on=date(2026, 9, 1))
    db.add_all([row, expired])
    db.flush()
    inputs = svc.calc_inputs(db, r, e1)
    assert inputs["za_overrides"] == [{"id": row.id, "field": "za_paye", "before": "11075.58", "after": "11000.00",
                                       "reason_code": "SARS"}]
    assert inputs["za_hours"] is None and inputs["za_deduction_orders"] is None
    assert svc.calc_inputs(db, None, e1, as_of=date(2026, 9, 30))["za_overrides"] is None   # preview: none


def test_frozen_context_carries_the_phase_9_inputs():
    from tests._za_run_helpers import calc_frozen
    _r, frozen = calc_frozen("f1_monthly_salary_age_40", za_hours={"ordinary": "173"})
    assert frozen["ctx"]["za_hours"] == {"ordinary": "173"}
    assert frozen["ctx"]["date_of_birth"]                    # a replay needs it for the age rebates


# ── four-eyes exceptions (ZA-016) ───────────────────────────────────────────
def test_first_payroll_and_bank_history_are_exceptions(db, organization, september):
    r, e1, _item = september
    # nothing committed yet in the tax year, so EMP501 is READY (no imbalance)
    assert _codes(lifecycle.za_run_exceptions(db, r)) == [
        ("BANK_CHANGE_HISTORY_UNAVAILABLE", None), ("FIRST_OR_LAST_PAYROLL", e1.id)]


def test_committed_payroll_without_an_emp201_is_a_reconciliation_imbalance(db, organization, september):
    r, e1, _item = september
    old = run(db, organization, date(2026, 8, 31), status="Paid")
    payslip(db, organization, old, e1)
    found = _codes(lifecycle.za_run_exceptions(db, r))
    assert ("RECONCILIATION_IMBALANCE", None) in found
    assert ("FIRST_OR_LAST_PAYROLL", e1.id) not in found


def test_business_exceptions_are_detected(db, organization):
    r = run(db, organization)
    e1 = employee(db, organization, "ZA-X1")
    item = payslip(db, organization, r, e1, "directive_fixed_amount_8000")
    # The engine itself BLOCKS a bonus today (BONUS is REVIEW for UIF and the 7B
    # timing rule is PENDING_G1), so the variable pay and a retro earned period
    # are planted in the stored context to prove the exception checks.
    snap = dict(item.za_calculation_snapshot)
    frozen = {**snap["frozenContext"], "ctx": {**snap["frozenContext"]["ctx"], "za_components": {"BONUS": "5000"},
                                               "za_variable_items": [{"component": "BONUS", "amount": "5000",
                                                                      "earned_from": "2025-12-01",
                                                                      "earned_to": "2026-02-28"}]}}
    item.za_calculation_snapshot = {**snap, "frozenContext": frozen}
    item.net_pay = Decimal("-1")
    db.flush()
    codes = {c for c, _e in _codes(lifecycle.za_run_exceptions(db, r))}
    assert {"NEGATIVE_NET", "MANUAL_DIRECTIVE", "RETRO_ACROSS_TAX_YEARS", "LARGE_VARIABLE_PAY"} <= codes


def test_last_payroll_and_override_present(db, organization):
    old = run(db, organization, date(2026, 8, 31), status="Paid")
    emp = employee(db, organization, "ZA-L", date_of_leaving=date(2026, 9, 15))
    payslip(db, organization, old, emp)
    r = run(db, organization)
    item = payslip(db, organization, r, emp)
    item.za_calculation_snapshot = {**item.za_calculation_snapshot, "za_overrides_applied": 1}
    db.flush()
    found = {c: e for c, e in _codes(lifecycle.za_run_exceptions(db, r))}
    assert found["FIRST_OR_LAST_PAYROLL"] == emp.id and found["OVERRIDE_PRESENT"] == emp.id


def test_approval_refused_until_every_exception_is_approved(db, organization, september):
    r, _e1, _item = september
    with pytest.raises(HTTPException) as exc:
        svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    assert exc.value.status_code == 409 and "2 exception(s)" in exc.value.detail
    _approve_all(db, organization, r)
    svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    stored = r.za_approval_fingerprint
    assert stored["fingerprint"] == lifecycle.za_approval_fingerprint(db, r)["fingerprint"]
    assert stored["approvedBy"] == APPROVER and len(stored["exceptions"]) == 2


def test_the_preparer_cannot_approve_an_exception(db, organization, september):
    r, _e1, _item = september
    key = lifecycle.za_run_exceptions(db, r)[0]["key"]
    with pytest.raises(BadRequestException, match="second person"):
        lifecycle.approve_za_run_exception(db, organization.id, r.id, key=key, approver_id=PREPARER)


def test_unknown_exception_key_is_404(db, organization, september):
    from app.core.exceptions import NotFoundException
    r, _e1, _item = september
    with pytest.raises(NotFoundException):
        lifecycle.approve_za_run_exception(db, organization.id, r.id, key="NEGATIVE_NET:999", approver_id=APPROVER)


def test_a_payload_changed_after_approval_needs_a_fresh_second_approval(db, organization, september):
    r, _e1, item = september
    _approve_all(db, organization, r)
    svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    r.status = "Review"                                         # sent back and recalculated
    item.net_pay = item.net_pay - 1
    db.flush()
    drift = [e for e in lifecycle.za_run_exceptions(db, r) if e["code"] == "PAYLOAD_CHANGED_AFTER_APPROVAL"]
    assert len(drift) == 1 and not drift[0]["approved"]
    with pytest.raises(HTTPException, match="PAYLOAD_CHANGED_AFTER_APPROVAL"):
        svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    lifecycle.approve_za_run_exception(db, organization.id, r.id, key=drift[0]["key"], approver_id=THIRD)
    svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    # a further change produces a NEW key, so the old approval never covers it
    r.status = "Review"
    item.net_pay = item.net_pay - 1
    db.flush()
    again = [e for e in lifecycle.za_run_exceptions(db, r) if e["code"] == "PAYLOAD_CHANGED_AFTER_APPROVAL"]
    assert again[0]["key"] != drift[0]["key"] and not again[0]["approved"]


# ── commit (PAID) ───────────────────────────────────────────────────────────
def _approved_run(db, organization, fixture, **overrides):
    r = run(db, organization)
    emp = employee(db, organization, f"ZA-C-{fixture[:6]}")
    item = payslip(db, organization, r, emp, fixture, **overrides)
    _approve_all(db, organization, r)
    svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    r.status = "Authorized"
    return r, emp, item


def test_commit_writes_the_eti_ledger_once(db, organization):
    r, emp, item = _approved_run(db, organization, "f3_eti_first_twelve_months_r5000_is_r1500")
    svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)
    svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)              # retried commit
    rows = db.query(PayrollZaEtiLedgerEntry).filter_by(employee_id=emp.id).all()
    assert len(rows) == 1
    assert (rows[0].payslip_item_id, rows[0].eti_amount, rows[0].claim_month) == \
        (item.id, Decimal("1500.00"), date(2026, 9, 1))
    assert r.za_approval_fingerprint["committedAt"]


def test_commit_without_eligible_eti_writes_no_ledger_row(db, organization):
    r, emp, _item = _approved_run(db, organization, "f1_monthly_salary_age_40")
    svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)
    assert db.query(PayrollZaEtiLedgerEntry).filter_by(employee_id=emp.id).count() == 0


def test_commit_refuses_payslips_changed_after_approval(db, organization):
    r, _emp, item = _approved_run(db, organization, "f1_monthly_salary_age_40")
    item.net_pay = item.net_pay + 1
    db.flush()
    with pytest.raises(HTTPException, match="changed after approval"):
        svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)


def test_commit_marks_the_applied_directive(db, organization):
    r = run(db, organization)
    emp = employee(db, organization, "ZA-DIR")
    directive = PayrollZaTaxDirective(organization_id=organization.id, employee_id=emp.id,
                                      directive_number="D-2026-002", directive_type="FIXED_AMOUNT",
                                      amount=Decimal("8000"), tax_year="2027", issue_date=date(2026, 8, 15),
                                      effective_from=date(2026, 3, 1), status="APPROVED")
    db.add(directive)
    db.flush()
    item = payslip(db, organization, r, emp, "directive_fixed_amount_8000",
                   za_directives=[{"id": directive.id, "directive_number": "D-2026-002",
                                   "directive_type": "FIXED_AMOUNT", "rate_pct": None, "amount": "8000",
                                   "status": "APPROVED", "employee_id": 7, "tax_year": "2027",
                                   "issue_date": "2026-08-15", "effective_from": "2026-03-01",
                                   "effective_to": "2027-02-28"}])
    _approve_all(db, organization, r)
    svc._za_before_run_transition(db, r, PayrollStatus.APPROVED, APPROVER)
    assert directive.applied_payslip_item_id is None
    svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)
    assert directive.applied_payslip_item_id == item.id


def test_commit_marks_approved_overrides_applied(db, organization):
    r, emp, item = _approved_run(db, organization, "f1_monthly_salary_age_40")
    row = PayrollZaPayrollOverride(organization_id=organization.id, employee_id=emp.id, payroll_run_id=r.id,
                                   field="za_sdl", before_value=Decimal("500"), after_value=Decimal("0"),
                                   reason_code="EXEMPT", reason="x", status="APPROVED",
                                   expires_on=date(2026, 12, 31))
    db.add(row)
    db.flush()
    svc._za_before_run_transition(db, r, PayrollStatus.PAID, APPROVER)
    db.refresh(row)
    assert row.status == "APPLIED"


# ── overrides (ZA-017) ──────────────────────────────────────────────────────
def _propose(db, organization, r, emp, **kw):
    data = {"employeeId": emp.id, "field": "za_paye", "after": "11000", "reasonCode": "SARS_LETTER",
            "reason": "SARS correspondence", "evidenceRef": "doc-1",
            "expiresOn": (date.today() + timedelta(days=30)).isoformat(), **kw}
    return lifecycle.propose_za_override(db, organization.id, r.id, data, PREPARER)


def test_override_records_before_from_the_snapshot_and_needs_a_second_person(db, organization, september):
    r, e1, item = september
    row = _propose(db, organization, r, e1)
    assert (row.before_value, row.after_value, row.status, row.payslip_item_id) == \
        (Decimal("11075.58"), Decimal("11000.00"), "PROPOSED", item.id)
    with pytest.raises(BadRequestException, match="someone other"):
        lifecycle.approve_za_override(db, organization.id, row.id, PREPARER)
    lifecycle.approve_za_override(db, organization.id, row.id, APPROVER)
    assert row.status == "APPROVED" and row.approved_by_id == APPROVER
    with pytest.raises(BadRequestException, match="already APPROVED"):
        _propose(db, organization, r, e1)
    lifecycle.withdraw_za_override(db, organization.id, row.id)
    assert row.status == "WITHDRAWN"


@pytest.mark.parametrize("kw, message", [
    ({"field": "za_eti"}, "field must be"),
    ({"after": "11075.58"}, "does not change"),
    ({"reasonCode": ""}, "reason code"),
    ({"expiresOn": None}, "expiry date"),
    ({"after": "-1"}, "non-negative"),
])
def test_override_validation(db, organization, september, kw, message):
    r, e1, _item = september
    with pytest.raises(BadRequestException, match=message):
        _propose(db, organization, r, e1, **kw)


def test_override_only_on_an_open_run(db, organization, september):
    r, e1, _item = september
    r.status = "Approved"
    with pytest.raises(BadRequestException, match="not yet approved"):
        _propose(db, organization, r, e1)


def test_approved_override_changes_the_recalculated_result(db, organization, september):
    from tests._za_run_helpers import calc_frozen
    r, e1, _item = september
    row = _propose(db, organization, r, e1)
    lifecycle.approve_za_override(db, organization.id, row.id, APPROVER)
    overrides = lifecycle.za_overrides_for(db, e1, r, date(2026, 9, 30))
    result, _frozen = calc_frozen("f1_monthly_salary_age_40", za_overrides=overrides)
    assert result.tds == Decimal("11000.00")
    assert result.za_result["trace"]["overrides"][0]["before"] == "11075.58"
