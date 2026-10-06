"""
tests/test_hong_kong_corrections.py
-----------------------------------
D-14 — linked corrections of COMMITTED Hong Kong payroll (Option B, HK-only):
append-only delta payslips booked to the original wage period, recalculated on
the original's frozen pack, maker-checker approval, and every statutory
consequence (IR56B amendment / regeneration, eMPF supersede / supplementary
batch, IR56G hold, average wage, MPF history, payment treatment).

app.* is imported lazily (collection-order hazard, see conftest.py).
"""

from datetime import date
from decimal import Decimal as D

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _other_org, _profile  # noqa: F401

# FILED needs the external-submission record (how the employer submitted).
INTERNAL_FILING = {"submissionMode": "INTERNAL_PREPARATION_ONLY", "authorizedSigner": "Director (test)"}


def _runs(db, hk, months=(1, 2, 3, 4)):
    return {m: _month(db, hk.org, m) for m in months}


def _raise_pay(db, emp, ctc="264000"):
    emp.ctc = D(ctc)
    db.commit()


def _request(db, hk, item, reason="April allowance under-paid"):
    from app.modules.payroll import hong_kong_service

    return hong_kong_service.request_correction(db, hk.org.id, item.id, reason, MAKER.id)


def _approve(db, hk, correction, actor=CHECKER):
    from app.modules.payroll import hong_kong_service

    return hong_kong_service.approve_correction(db, hk.org.id, correction.id, actor.id)


def test_unchanged_payslip_reproduces_exactly_so_there_is_nothing_to_correct(db, hk):
    """The frozen recompute (original snapshot + pinned pack) reproduces the
    committed payslip to the cent — the precondition for any honest delta."""
    from app.core.exceptions import BadRequestException

    runs = _runs(db, hk)
    with pytest.raises(BadRequestException, match="no change"):
        _request(db, hk, _item(db, runs[4], hk.emp))


def test_correction_appends_a_linked_delta_and_never_touches_the_original(db, hk):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import canonical_hash
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    runs = _runs(db, hk)
    april = _item(db, runs[4], hk.emp)
    before = (canonical_hash(april.hk_calculation_trace), april.gross_pay, april.net_pay, april.employee_pension)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, april)
    db.refresh(april)
    assert (canonical_hash(april.hk_calculation_trace), april.gross_pay, april.net_pay, april.employee_pension) == before
    assert corr.status == "REQUESTED" and corr.sequence == 1 and corr.requested_by_id == MAKER.id
    delta = db.get(PayslipItem, corr.delta_payslip_id)
    run = db.get(PayrollRun, corr.correction_run_id)
    assert run.status == PayrollStatus.DRAFT and run.notes.startswith("[HK-CORRECTION]")
    assert (run.period_start, run.period_end, run.pay_date) == (runs[4].period_start, runs[4].period_end, runs[4].pay_date)
    assert (delta.gross_pay, delta.employee_pension, delta.employer_pension, delta.net_pay, delta.tds) == (
        D("2000.00"), D("100.00"), D("100.00"), D("1900.00"), D("0"))
    assert delta.tax_policy_pack_id == april.tax_policy_pack_id            # the original's pinned pack
    t = delta.hk_calculation_trace
    assert t["correction"]["originalPayslipId"] == april.id and t["period"] == april.hk_calculation_trace["period"]
    assert D(t["mpf"]["currentPeriod"]["relevantIncome"]) == D("2000.00") and t["mpf"]["catchUp"] == []
    assert t["salariesTax"]["withholding"] == "NONE"
    assert any(w["code"] == "CURRENT_FACTS_USED" for w in corr.warnings)


def test_the_requester_can_never_approve_and_the_generic_lifecycle_enforces_it(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    runs = _runs(db, hk)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, _item(db, runs[4], hk.emp))
    with pytest.raises(BadRequestException, match="four-eyes"):
        _approve(db, hk, corr, MAKER)
    service.advance_payroll_run_status(db, corr.correction_run_id, MAKER.id, hk.org.id)        # Draft → Review is fine
    with pytest.raises(BadRequestException, match="four-eyes"):
        service.advance_payroll_run_status(db, corr.correction_run_id, MAKER.id, hk.org.id)    # Review → Approved is not
    done = _approve(db, hk, corr)
    assert done.status == "APPROVED" and done.approved_by_id == CHECKER.id and done.consequences


def test_approved_delta_is_reported_in_the_original_period(db, hk):
    from app.modules.payroll import hong_kong_service

    runs = _runs(db, hk)
    _raise_pay(db, hk.emp)
    _approve(db, hk, _request(db, hk, _item(db, runs[4], hk.emp)))
    sub = hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    assert D(sub.totals["relevantIncome"]) == D("22000.00") and D(sub.totals["employerMandatory"]) == D("1100.00")
    ar = hong_kong_service.generate_annual_return(db, hk.org.id, "2026/27", MAKER.id)
    assert D(ar["reportedTotal"]) == D(ar["committedPayrollGross"]) == D("22000.00")


def test_correction_after_a_filed_ir56b_opens_a_linked_amendment(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase

    runs = _runs(db, hk)
    ar = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    case = db.get(HongKongIrdReportingCase, ar["employees"][0]["caseId"])
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-1", submission=INTERNAL_FILING)
    filed_payload = dict(case.payload)
    _raise_pay(db, hk.emp)
    corr = _approve(db, hk, _request(db, hk, _item(db, runs[3], hk.emp), "March allowance under-paid"))
    action = [c for c in corr.consequences["ird"] if c["form"] == "IR56B"][0]
    assert action["action"] == "AMENDMENT_CREATED"
    db.refresh(case)
    amendment = db.get(HongKongIrdReportingCase, action["amendmentCaseId"])
    assert case.status == "FILED" and case.payload == filed_payload              # in force until the replacement is filed
    assert amendment.amends_case_id == case.id and amendment.status == "PREPARED"
    again = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", CHECKER.id)
    row = [e for e in again["employees"] if e["employeeId"] == hk.emp.id][0]
    assert row["caseId"] == amendment.id and not row["validationErrors"]
    assert D(again["reportedTotal"]) == D(again["committedPayrollGross"])


def test_correction_before_filing_sends_a_validated_ir56b_back_for_regeneration(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase

    runs = _runs(db, hk)
    ar = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    case = db.get(HongKongIrdReportingCase, ar["employees"][0]["caseId"])
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    _raise_pay(db, hk.emp)
    corr = _approve(db, hk, _request(db, hk, _item(db, runs[3], hk.emp)))
    db.refresh(case)
    assert case.status == "PREPARED" and any("correction" in e for e in case.validation_errors)
    with pytest.raises(BadRequestException):
        hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)     # stale figures cannot proceed
    assert [c["action"] for c in corr.consequences["ird"] if c["form"] == "IR56B"] == ["REGENERATE_BEFORE_FILING"]
    hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    db.refresh(case)
    assert case.validation_errors == []


def test_submitted_empf_period_gets_a_supplementary_batch_and_unsubmitted_ones_are_superseded(db, hk):
    from app.modules.payroll import hong_kong_service

    runs = _runs(db, hk)
    first = hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    hong_kong_service.transition_empf_submission(db, hk.org.id, first.id, "SUBMITTED", CHECKER.id, submission_reference="EMPF-1")
    pending = hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)        # nothing new yet
    assert pending.totals["batchType"] == "SUPPLEMENTARY" and pending.rows == []
    _raise_pay(db, hk.emp)
    corr = _approve(db, hk, _request(db, hk, _item(db, runs[4], hk.emp)))
    db.refresh(pending)
    assert pending.status == "AMENDED"
    actions = {c["action"] for c in corr.consequences["empf"]}
    assert {"SUPERSEDED_UNSUBMITTED", "SUPPLEMENTARY_BATCH_REQUIRED"} <= actions
    supp = hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    assert supp.supplements_submission_id == first.id and supp.totals["batchType"] == "SUPPLEMENTARY"
    assert [r["payslipId"] for r in supp.rows] == [corr.delta_payslip_id]
    assert (D(supp.totals["relevantIncome"]), D(supp.totals["employerMandatory"])) == (D("2000.00"), D("100.00"))


def test_positive_delta_for_a_departing_employee_is_held_or_blocked_never_paid(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongTaxClearanceHoldLine, PayrollRun, PayslipItem

    runs = _runs(db, hk)
    hold = hong_kong_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 9, 30), MAKER.id, identified_on=date(2026, 5, 1))
    _raise_pay(db, hk.emp)
    corr = _approve(db, hk, _request(db, hk, _item(db, runs[4], hk.emp)))
    run, delta = db.get(PayrollRun, corr.correction_run_id), db.get(PayslipItem, corr.delta_payslip_id)
    assert hong_kong_service.payment_treatment(db, hk.org.id, run, [delta])[delta.id][0] == "FINAL_PAY_BLOCKED"
    hong_kong_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 6, 1), "IR56G-REF", MAKER.id)
    corr.approved_at = corr.approved_at.replace(year=2026, month=6, day=15)                 # released after filing
    db.commit()
    assert hong_kong_service.payment_treatment(db, hk.org.id, run, [delta])[delta.id][0] == "HELD"
    lines = db.query(HongKongTaxClearanceHoldLine).filter(HongKongTaxClearanceHoldLine.hold_id == hold.id).all()
    assert delta.id in {l.payslip_item_id for l in lines}


def test_negative_delta_is_flagged_and_never_paid(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import PayrollRun, PayslipItem

    runs = _runs(db, hk)
    _raise_pay(db, hk.emp, "216000")
    corr = _request(db, hk, _item(db, runs[4], hk.emp), "April over-paid")
    assert {w["code"] for w in corr.warnings} >= {"EMPLOYEE_OVERPAID", "MPF_OVER_CONTRIBUTED"}
    corr = _approve(db, hk, corr)
    run, delta = db.get(PayrollRun, corr.correction_run_id), db.get(PayslipItem, corr.delta_payslip_id)
    assert delta.net_pay < 0
    assert hong_kong_service.payment_treatment(db, hk.org.id, run, [delta])[delta.id][0] == "RECOVERY_NOT_PAID"
    assert corr.consequences["payment"][0]["action"] == "NOT_PAID_RECOVERY_IS_SEPARATE"


def test_duplicate_open_correction_is_refused_and_a_second_follows_the_first(db, hk):
    from fastapi import HTTPException

    runs = _runs(db, hk)
    april = _item(db, runs[4], hk.emp)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, april)
    with pytest.raises(HTTPException) as exc:
        _request(db, hk, april)
    assert exc.value.status_code == 409
    _approve(db, hk, corr)
    _raise_pay(db, hk.emp, "276000")
    second = _request(db, hk, april, "a further increase")
    assert second.sequence == 2 and D(second.delta["col:gross_pay"]) == D("1000.00")   # against original + first delta


def test_a_pending_60_day_period_is_not_corrected_automatically(db, hk):
    from fastapi import HTTPException

    runs = _runs(db, hk)
    _raise_pay(db, hk.emp)
    with pytest.raises(HTTPException, match="60-day") as exc:
        _request(db, hk, _item(db, runs[1], hk.emp))
    assert exc.value.status_code == 409


def test_cross_tenant_cross_jurisdiction_and_delta_corrections_are_refused(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import PayrollRun, PayslipItem

    runs = _runs(db, hk)
    april = _item(db, runs[4], hk.emp)
    other = _other_org(db, "HKCORR")
    with pytest.raises(NotFoundException):
        hong_kong_service.request_correction(db, other.id, april.id, "x", MAKER.id)
    sg_run = PayrollRun(organization_id=hk.org.id, period_label="sg", period_start=date(2026, 4, 1),
                        period_end=date(2026, 4, 30), pay_date=date(2026, 4, 30))
    db.add(sg_run)
    db.commit()
    sg_item = PayslipItem(payroll_run_id=sg_run.id, employee_id=hk.emp.id, organization_id=hk.org.id,
                          employee_name="x", country_code="SG", gross_pay=D("1"), net_pay=D("1"))
    db.add(sg_item)
    db.commit()
    with pytest.raises(BadRequestException, match="Hong Kong payslips only"):
        hong_kong_service.request_correction(db, hk.org.id, sg_item.id, "x", MAKER.id)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, april)
    with pytest.raises(BadRequestException, match="not a correction delta"):
        hong_kong_service.request_correction(db, hk.org.id, corr.delta_payslip_id, "x", MAKER.id)
    with pytest.raises(NotFoundException):
        hong_kong_service.approve_correction(db, other.id, corr.id, CHECKER.id)
    assert hong_kong_service.list_corrections(db, other.id) == []


def test_rejection_discards_the_uncommitted_delta_and_keeps_the_record(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import PayrollRun, PayslipItem

    runs = _runs(db, hk)
    april = _item(db, runs[4], hk.emp)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, april)
    run_id, delta_id = corr.correction_run_id, corr.delta_payslip_id
    done = hong_kong_service.reject_correction(db, hk.org.id, corr.id, "wrong figures", CHECKER.id)
    assert done.status == "REJECTED" and done.rejected_reason == "wrong figures" and done.delta
    assert db.get(PayrollRun, run_id) is None and db.get(PayslipItem, delta_id) is None
    assert done.consequences["discarded"] == {"correctionRunId": run_id, "deltaPayslipId": delta_id}
    assert _request(db, hk, april).sequence == 2


def test_a_correction_run_is_never_generated_regenerated_or_deleted_directly(db, hk):
    from fastapi import HTTPException

    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    runs = _runs(db, hk)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, _item(db, runs[4], hk.emp))
    run = db.get(PayrollRun, corr.correction_run_id)
    with pytest.raises(BadRequestException, match="correction run"):
        service.generate_payslips_for_run(db, run, hk.org.id)
    with pytest.raises(BadRequestException, match="correction delta"):
        service.regenerate_employee_payslip(db, run.id, hk.emp.id, hk.org.id, MAKER.id)
    with pytest.raises(HTTPException) as e1:
        service.delete_payroll_run(db, run.id, hk.org.id)
    with pytest.raises(HTTPException) as e2:
        service.delete_payslip(db, corr.delta_payslip_id, hk.org.id)
    assert e1.value.status_code == e2.value.status_code == 409


def test_committed_payroll_can_never_be_deleted(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import service

    runs = _runs(db, hk, months=(4,))
    with pytest.raises(HTTPException):
        service.delete_payroll_run(db, runs[4].id, hk.org.id)
    with pytest.raises(HTTPException):
        service.delete_payslip(db, _item(db, runs[4], hk.emp).id, hk.org.id)


def test_average_wage_and_mpf_history_attribute_the_delta_to_its_period(db, hk):
    from app.modules.payroll import hong_kong_service

    runs = _runs(db, hk)
    _raise_pay(db, hk.emp)
    corr = _approve(db, hk, _request(db, hk, _item(db, runs[4], hk.emp)))
    rows = hong_kong_service._average_wage_rows(db, hk.org.id, hk.emp.id, date(2026, 4, 1), date(2026, 4, 30))
    assert len(rows) == 1 and D(rows[0]["eoWages"]) == D("22000.00")
    may = _month(db, hk.org, 5)
    periods = hong_kong_service.prior_periods(db, hk.emp, may)
    assert corr.delta_payslip_id not in {p["payslipId"] for p in periods} and len(periods) == 4


def test_correction_preflight_is_scoped_to_the_correction(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll import service

    runs = _runs(db, hk)
    _employee(db, hk.org.id, "HKNOPROFILE")                    # would BLOCK an ordinary run's preflight
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, _item(db, runs[4], hk.emp))
    pre = hong_kong_service.hk_payroll_preflight(db, hk.org.id, corr.correction_run_id)
    assert pre["correction"] is True and pre["status"] != "BLOCKED"
    assert "HK_CORRECTION_AWAITING_APPROVAL" in {c["code"] for c in pre["checks"]}
    assert hong_kong_service.hk_employer_readiness(db, hk.org.id)["corrections"]["awaitingApproval"] == 1


def test_approval_refuses_when_the_original_changed_after_the_request(db, hk):
    import copy

    from fastapi import HTTPException

    runs = _runs(db, hk)
    april = _item(db, runs[4], hk.emp)
    _raise_pay(db, hk.emp)
    corr = _request(db, hk, april)
    tampered = copy.deepcopy(april.hk_calculation_trace)
    tampered["result"]["netPay"] = "1.00"
    april.hk_calculation_trace = tampered
    db.commit()
    with pytest.raises(HTTPException, match="changed after"):
        _approve(db, hk, corr)


def test_correction_routes_are_operator_gated_over_http(db, hk):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription
    from app.modules.payroll import router as payroll_router_module

    runs = _runs(db, hk)
    april = _item(db, runs[4], hk.emp)
    _raise_pay(db, hk.emp)
    maker = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    checker = SimpleNamespace(id=CHECKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    employee_user = SimpleNamespace(id=9, organization_id=hk.org.id, role="employee", is_active=True)
    saved = dict(app.dependency_overrides)

    def as_user(user):
        app.dependency_overrides.update({get_current_user: lambda: user, get_current_org_scoped_principal: lambda: user})

    app.dependency_overrides.update({get_db: lambda: db, require_active_subscription: lambda: None,
                                     payroll_router_module._HK_WRITE[1].dependency: lambda: None})
    try:
        client = TestClient(app)
        as_user(employee_user)
        assert client.post(f"/api/payroll/hong-kong/payslips/{april.id}/corrections", json={"reason": "x"}).status_code == 403
        as_user(maker)
        assert client.post(f"/api/payroll/hong-kong/payslips/{april.id}/corrections", json={"reason": ""}).status_code == 422
        made = client.post(f"/api/payroll/hong-kong/payslips/{april.id}/corrections", json={"reason": "allowance"})
        assert made.status_code == 200 and made.json()["status"] == "REQUESTED"
        assert client.post(f"/api/payroll/hong-kong/corrections/{made.json()['id']}/approve").status_code == 400
        as_user(checker)
        ok = client.post(f"/api/payroll/hong-kong/corrections/{made.json()['id']}/approve")
        assert ok.status_code == 200 and ok.json()["status"] == "APPROVED" and ok.json()["netPayDelta"] == "1900.00"
        assert len(client.get("/api/payroll/hong-kong/corrections").json()) == 1
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
