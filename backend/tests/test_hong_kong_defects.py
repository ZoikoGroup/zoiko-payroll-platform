"""Regression tests for the wrong-result defects found by the 2026-10-14 HK gap audit
(docs/hk-evidence/HK_IMPLEMENTATION_GAP_MATRIX.md, D-A … D-H). TEST data only; app modules
are imported inside the tests (collection-order hazard)."""
from datetime import date
from decimal import Decimal as D

from tests.test_hong_kong_e2e import (  # noqa: F401  (hk is a fixture)
    CHECKER, MAKER, _employee, _hours, _item, _month, _profile, _spaced_codes, hk,
)


# ── D-A: contractual overtime is paid and flows into every statutory base ─────────────────────
# Wireframe §4 "Contractual overtime: do not invent a statutory universal overtime premium; apply
# contract/collective terms while including hours/earnings correctly for minimum-wage and wage
# calculations"; §10 "Contract overtime"; Labour Department Concise Guide ch.3 (wages include
# overtime pay; archived sources/ld_cg_03, sha256 dd61788183c75fca…).

def _overtime_hours(db, org_id, emp_id, days=10, total="10", overtime="2"):
    from app.modules.payroll import hong_kong_service

    hong_kong_service.record_work_hours(db, org_id, emp_id, [
        {"date": date(2026, 4, d).isoformat(), "hours": total, "overtimeHours": overtime} for d in range(1, days + 1)],
        MAKER.id)


def test_d_a_contractual_overtime_is_paid_and_counted_in_every_base(db, hk, monkeypatch):
    _spaced_codes(monkeypatch)
    emp = _employee(db, hk.org.id, "DA1", ctc=D("240000"))                     # HK$20,000 a month
    _profile(db, emp, hk.org.id, "2026-01-16", hkgContractualOvertimeHourlyRate="150")
    _overtime_hours(db, hk.org.id, emp.id)                                      # 10 days x 2 h = 20 h
    run = _month(db, hk.org, 4)
    item = _item(db, run, emp)
    assert D(str(item.overtime)) == D("3000.00")                                # 20 h x HK$150 (contract rate)
    trace = item.hk_calculation_trace
    ot = trace["workerFacts"]["overtime"]
    assert ot["status"] == "PAID" and D(ot["hours"]) == D("20") and D(ot["hourlyRate"]) == D("150")
    for obligation in ("EO_WAGES", "MPF_RI", "SMW_WAGES"):                   # per-obligation classification
        line = next(l for l in trace["classification"][obligation]["lines"] if l["component"] == "overtime")
        assert line["treatment"] == "INCLUDED" and D(line["amount"]) == D("3000.00")
    assert D(trace["classification"]["EO_WAGES"]["included"]) == D("23000.00")
    current = trace["mpf"]["currentPeriod"]
    assert D(current["relevantIncome"]) == D("23000.00") and current["branch"] == "WITHIN_LEVELS"
    assert D(trace["mpf"]["employee"]) == D("1150.00") and D(trace["mpf"]["employer"]) == D("1150.00")
    assert D(trace["ird"]["reportable"]["SALARY_WAGES"]) == D("11000.00")    # basic 8,000 + overtime 3,000
    assert D(trace["result"]["gross"]) == D("23000.00")


def test_d_a_overtime_hours_without_a_contract_rate_pay_nothing_and_block(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service

    _spaced_codes(monkeypatch)
    emp = _employee(db, hk.org.id, "DA2", ctc=D("240000"))
    _profile(db, emp, hk.org.id, "2026-01-16")                                  # no overtime rate recorded
    _overtime_hours(db, hk.org.id, emp.id, days=3)
    from app.modules.payroll.models import PayrollStatus

    run = _month(db, hk.org, 4, status=PayrollStatus.DRAFT)
    item = _item(db, run, emp)
    assert D(str(item.overtime)) == D("0")
    assert item.hk_calculation_trace["workerFacts"]["overtime"]["status"] == "RATE_NOT_RECORDED"
    checks = hong_kong_service.hk_payroll_preflight(db, hk.org.id, run.id)["checks"]
    block = [c for c in checks if c["code"] == "HK_OVERTIME_RATE_NOT_RECORDED" and c["employeeId"] == emp.id]
    assert block and block[0]["severity"] == "BLOCK" and "contractual overtime hourly rate" in block[0]["action"]


# ── D-B: a leaver's final run is approvable once its real preconditions are met ────────────────
# Labour Department Concise Guide ch.9 "Time of Making Termination Payments": all termination
# payments except severance "as soon as practicable and in any case not later than seven days after
# the date of termination" (archived sources/ld_cg_09, sha256 3ee3b5333bbe1eb0…). The old check
# said "due IMMEDIATELY" and blocked every leaver with no way to clear it.

def _final_run(db, hk, leaving):
    from app.modules.payroll.models import PayrollStatus

    _hours(db, hk.org, hk.emp, date(2026, 1, 16), date(2026, 2, 28))
    run = _month(db, hk.org, 2, status=PayrollStatus.REVIEW)       # pay date 28 Feb 2026
    hk.emp.date_of_leaving = leaving
    db.commit()
    return run


def test_d_b_leaver_paid_within_seven_days_of_termination_can_be_approved(db, hk):
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import PayrollStatus

    run = _final_run(db, hk, date(2026, 2, 24))                    # latest payment 3 Mar; pays 28 Feb
    checks = hong_kong_service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 2, 28))["checks"]
    timing = [c for c in checks if c["code"].startswith("EO_TERMINATION")]
    assert [c["code"] for c in timing] == ["EO_TERMINATION_PAYMENT_TIMING"] and timing[0]["severity"] == "INFO"
    assert "2026-03-03" in timing[0]["message"]
    assert service.advance_payroll_run_status(db, run.id, MAKER.id, hk.org.id).status == PayrollStatus.APPROVED


def test_d_b_late_final_payment_blocks_and_names_the_latest_date(db, hk):
    from app.modules.payroll import hong_kong_service

    run = _final_run(db, hk, date(2026, 2, 10))                    # latest payment 17 Feb; pays 28 Feb
    checks = hong_kong_service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 2, 28))["checks"]
    late = [c for c in checks if c["code"] == "EO_TERMINATION_PAYMENT_LATE"]
    assert late and late[0]["severity"] == "BLOCK"
    assert "2026-02-17" in late[0]["message"] and "2026-02-17" in late[0]["action"]


def test_d_b_a_later_leaving_date_does_not_block_an_earlier_period(db, hk):
    from app.modules.payroll import hong_kong_service

    run = _final_run(db, hk, date(2026, 6, 30))                    # leaves in June; February is ordinary
    codes = {c["code"] for c in hong_kong_service.hk_payroll_preflight(db, hk.org.id, run.id,
                                                                      today=date(2026, 2, 28))["checks"]}
    assert "EO_WAGE_PAYMENT_TIMING" in codes and not {c for c in codes if c.startswith("EO_TERMINATION")}


# ── D-C: the frozen pre-1-May-2025 wage cannot be bypassed (HK-017) ─────────────────────────────
# Wireframe HK-017: "Store a frozen pre-transition wage snapshot for employees employed before
# 1 May 2025 ... do not recalculate it from later wages"; Labour Department MPF-offsetting page
# (archived sources/ld_aoa, sha256 4c40afaa941fd852…). Before the fix, a profile without the frozen
# wage let calculate_termination use whatever wage the request typed.

_TERMINATION = {"terminationDate": "2027-03-31", "reason": "REDUNDANCY", "postTransitionWage": "30000"}


def _pre_2025_hire(db, hk, code):
    emp = _employee(db, hk.org.id, code, date_of_joining=date(2015, 5, 1))
    _profile(db, emp, hk.org.id, "2015-05-01", hkgContractualWeeklyHours="44")      # no frozen wage recorded
    return emp


def test_d_c_a_typed_pre_transition_wage_is_refused_without_a_frozen_or_approved_value(db, hk):
    import pytest

    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service

    emp = _pre_2025_hire(db, hk, "DC1")
    with pytest.raises(BadRequestException, match="HK-017"):
        hong_kong_service.calculate_termination(db, hk.org.id, emp.id, {**_TERMINATION, "preTransitionWage": "40000"},
                                                MAKER.id)


def test_d_c_an_override_needs_reason_evidence_and_a_second_person_and_is_audited(db, hk):
    import pytest

    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import TaxConfigurationAudit

    emp = _pre_2025_hire(db, hk, "DC2")
    with pytest.raises(BadRequestException, match="reason and evidence"):
        hong_kong_service.request_pre_transition_wage_override(
            db, hk.org.id, emp.id, {"monthlyWage": "26000", "basis": "LAST_FULL_MONTH"}, MAKER.id)
    ov = hong_kong_service.request_pre_transition_wage_override(
        db, hk.org.id, emp.id, {"monthlyWage": "26000", "basis": "LAST_FULL_MONTH", "reason": "TEST April 2025 payslip",
                                "evidenceRef": "PAYSLIP-2025-04"}, MAKER.id)
    with pytest.raises(BadRequestException, match="HK-017"):                     # not usable until approved
        hong_kong_service.calculate_termination(db, hk.org.id, emp.id, dict(_TERMINATION), MAKER.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        hong_kong_service.approve_pre_transition_wage_override(db, hk.org.id, ov.id, MAKER.id)
    assert hong_kong_service.approve_pre_transition_wage_override(db, hk.org.id, ov.id, CHECKER.id).status == "APPROVED"
    row = hong_kong_service.calculate_termination(db, hk.org.id, emp.id, dict(_TERMINATION), MAKER.id)
    assert row.result["portions"]["preTransition"]["wage"] == "26000.00"
    assert row.result["preTransitionWageSource"] == {"source": "APPROVED_OVERRIDE", "overrideId": ov.id,
                                                     "evidenceRef": "PAYSLIP-2025-04", "basis": "LAST_FULL_MONTH"}
    with pytest.raises(BadRequestException, match="HK-017"):                     # still never typed at termination
        hong_kong_service.calculate_termination(db, hk.org.id, emp.id, {**_TERMINATION, "preTransitionWage": "40000"},
                                                MAKER.id)
    actions = {(a.entity_type, a.action) for a in db.query(TaxConfigurationAudit).filter(
        TaxConfigurationAudit.entity_type == "hk_pre_transition_wage_override")}
    assert ("hk_pre_transition_wage_override", "create") in actions
    assert ("hk_pre_transition_wage_override", "status_change") in actions


# ── D-D: recording an IR56G as filed is four-eyes, like every other IRD filing ──────────────────
# Wireframe §15 "RBAC and four-eyes: separate prepare/approve/submit/release roles for ... IRD";
# §7 IR56G "file IR56G, activate statutory hold". Before the fix record_ir56g_filed set the case
# FILED directly — no four-eyes, no submission record (IRD employer obligations, archived
# sources/ird_employers sha256 f3c47471346d…; PAM 46(e) ird_pam46e).

def test_d_d_ir56g_filing_needs_a_second_person_and_a_submission_record(db, hk):
    import pytest

    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase, TaxConfigurationAudit
    from tests.test_hong_kong_e2e import INTERNAL_FILING

    hold = hong_kong_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 8, 31), actor_id=MAKER.id)
    case = db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.id == hold.ird_case_id).one()
    with pytest.raises(BadRequestException, match="four-eyes"):
        hong_kong_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 7, 20), "IR56G-REF", MAKER.id,
                                             submission=INTERNAL_FILING)
    refusals = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "hk_ird_reporting_case",
                                                      TaxConfigurationAudit.entity_id == case.id,
                                                      TaxConfigurationAudit.action == "refused").count()
    assert refusals >= 1
    with pytest.raises(BadRequestException, match="submission mode"):
        hong_kong_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 7, 20), "IR56G-REF", CHECKER.id)
    db.refresh(case)
    assert case.status != "FILED" and hold.state != "IR56G_FILED_HOLD_ACTIVE"
    hold = hong_kong_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 7, 20), "IR56G-REF", CHECKER.id,
                                                submission=INTERNAL_FILING)
    db.refresh(case)
    assert hold.state == "IR56G_FILED_HOLD_ACTIVE"
    assert (case.status, case.filing_reference, case.approved_by_id, case.submission_mode) == (
        "FILED", "IR56G-REF", CHECKER.id, "INTERNAL_PREPARATION_ONLY")


# ── D-F: the BIR56A reconciliation explains suppressed and excluded amounts ─────────────────────
# HK-011 / wireframe §7 "Annual reconciliation: reported remuneration must reconcile exactly to
# committed payroll plus certified non-payroll reportable adjustments". Before the fix the BIR56A
# compared the reported total (suppressed IR56B and IRD-excluded amounts removed) with EVERY
# employee's full gross, so a legitimate IR56F suppression showed a "Variance".

def test_d_f_bir56a_reconciles_when_an_ir56b_is_suppressed_by_a_filed_ir56f(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase
    from tests.test_hong_kong_reports import _seeded

    _spaced_codes(monkeypatch)
    leaver = _employee(db, hk.org.id, "DF2")
    _profile(db, leaver, hk.org.id, "2026-01-16")
    for m in (1, 2, 3):
        _month(db, hk.org, m)
    db.add(HongKongIrdReportingCase(organization_id=hk.org.id, employee_id=leaver.id, form_type="IR56F",
                                    year_of_assessment="2025/26", event_date=date(2026, 3, 31), status="FILED",
                                    income_period_start=date(2025, 4, 1), income_period_end=date(2026, 3, 31)))
    db.commit()
    report = hong_kong_service.generate_hong_kong_bir56a(db, hk.org.id, _seeded(db, "HK-BIR56A").id, "2025/26")
    rec = report.reconciliation
    assert rec["status"] == "Reconciled", rec
    assert D(rec["lessReportedOnIr56fIr56g"]) == D("49999.95")      # the leaver's Jan-Mar committed pay
    assert D(rec["expectedReportable"]) == D(rec["reportedTotal"]) == D("49999.95")   # the other employee only
    assert D(rec["committedPayrollGross"]) == D("99999.90") and D(rec["variance"]) == D("0")
