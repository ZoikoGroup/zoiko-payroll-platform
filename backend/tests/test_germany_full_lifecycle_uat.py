"""
tests/test_germany_full_lifecycle_uat.py
-----------------------------------------
UAT gap-closure: drives a Germany payroll run through the FULL real
lifecycle state machine end to end.

Prior coverage (532 Germany-specific tests, a 15-employee business-
acceptance scenario, test_germany_e2e_payroll_scenario.py) proves each
individual calculation path (Minijob/Midijob/Regular) produces a real,
non-fabricated payslip, and test_payroll_safety_guards.py proves a run
carrying any FAILED/PARTIAL payslip item cannot advance past AUTHORIZED.
Neither ever calls the actual state-advancement chain
(`service.advance_payroll_run_status`) on a Germany run, nor walks a run
all the way to its terminal status. This file closes that gap.

── The REAL state machine (read from models.py, not assumed) ──────────
`PayrollStatus` is a genuine 6-state machine, in this exact order
(`PAYROLL_STATUS_ORDER`):

    DRAFT -> REVIEW -> APPROVED -> AUTHORIZED -> PAID -> CLOSED

`service.advance_payroll_run_status(db, run_id, approver_id,
organization_id)` moves a run exactly one step forward per call (there is
no "jump straight to Approved" or "skip a state" path) and is the single
function backing every lifecycle transition — there is no separate
per-state function (no dedicated "review_run"/"approve_run"/"authorize_
run" function; it is the same function called four times). It only
inspects payslip-item status when the NEXT status is PAID: any
PayslipItem whose status isn't PENDING (i.e. FAILED or PARTIAL) makes it
raise HTTPException(409) and leaves `run.status` unchanged. Reaching PAID
also stamps every PayslipItem PAID. CLOSED is a real further status
beyond PAID (calling advance again from PAID reaches it); advancing from
CLOSED raises HTTPException(409) ("already reached its final status"),
proving CLOSED — not PAID — is the actual terminal state, though PAID is
the money-movement finality the phase brief cared about.

This maps onto the phase brief's illustrative "Draft -> Calculate ->
Review -> Approve -> Payslip -> Paid" wording as follows: "Calculate"/
"Payslip" is not a persisted PayrollStatus at all — it is
`generate_payslips_for_run` (invoked automatically by `create_payroll_run`
when `auto_generate_payslips=True`), which populates PayslipItem rows
while the run itself is still sitting in DRAFT. "Review" and "Approve"
ARE both genuine, separately-persisted statuses (REVIEW and APPROVED),
exactly as the brief assumed — plus two more the brief didn't name
(AUTHORIZED as a distinct step before PAID, and CLOSED after it).

A second real lock, discovered while building this test and worth
documenting precisely: `service.regenerate_employee_payslip` (the
"fix a blocked employee's payslip in place" entry point) only works
while `run.status in (DRAFT, REVIEW)` — once a run reaches APPROVED it is
"locked" and regeneration raises HTTPException(400). So the realistic
"blocked -> fixed -> unblocked -> finalized" workflow is: catch a FAILED
payslip while the run is still editable (DRAFT/REVIEW), fix and
regenerate THERE, and only then advance the run onward — not fix-in-place
after the run has already been walked past REVIEW. Both orderings are
exercised below.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollAttendanceRecord, PayrollEmployee, PayrollRun, PayrollStatus,
    PayslipItem, PayslipStatus, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


# ── Test helpers (mirroring test_germany_e2e_payroll_scenario.py) ────────

def _make_employee(db, org_id, code, gross):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=gross * 12, basic=gross, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Full-lifecycle UAT test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_ceiling(db, branch, monthly, annual, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_contribution_ceiling_approver(db, row.id, actor_id=checker)
    return service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_health_fund(db, health_fund_id, rate=Decimal("1.7000"), maker=1, checker=2):
    source = _make_source(db)
    row = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id=health_fund_id, fund_name="Test Fund (fixture)",
            supplementary_rate_pct=rate, effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_health_fund_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_health_fund_approver(db, row.id, actor_id=checker)
    return service.set_health_fund_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_pv_configuration(db, child_category="CHILDLESS", is_saxony=False, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category=child_category, is_saxony=is_saxony,
            total_rate_pct=Decimal("4.2000"), standard_employee_rate_pct=Decimal("2.4000"),
            employer_rate_pct=Decimal("1.8000"), saxony_employee_rate_pct=Decimal("2.9000"),
            saxony_employer_rate_pct=Decimal("1.3000"),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_all_registries(db):
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "UAT-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _make_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=False,
        de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="UAT-FUND",
        de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
        de_employment_classification="REGULAR",
    )
    kwargs.update(overrides)
    return service.create_employee_statutory_profile_version(
        db, emp.id, org_id, EmployeeStatutoryProfileCreate(**kwargs), actor_id=None,
    )


def _add_attendance(db, org_id, emp_id, day=15):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(2026, 1, day),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"UAT{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _advance(db, run, organization_id, approver_id=42):
    """Thin wrapper so every call site refreshes `run` from the returned
    object (advance_payroll_run_status already commits+refreshes it)."""
    return service.advance_payroll_run_status(
        db, run.id, approver_id=approver_id, organization_id=organization_id,
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. HAPPY PATH — full Draft -> Review -> Approved -> Authorized -> Paid
#    (-> Closed) walk for a real, mixed-classification Germany run.
# ══════════════════════════════════════════════════════════════════════════

def test_germany_run_walks_full_lifecycle_to_paid_with_reconciled_totals(db, organization, monkeypatch):
    """Two real Germany employees (REGULAR Tax-Class-I and MINIJOB) are
    calculated, then the run is walked one real state-machine step at a
    time — via the actual `advance_payroll_run_status` function, never a
    shortcut — through every real persisted PayrollStatus, ending at PAID
    with the run-level total_net aggregate reconciling against the sum of
    the individual (real, non-fabricated) payslip net_pay figures."""
    _stub_business_code_generation(monkeypatch)
    _publish_all_registries(db)

    regular_emp = _make_employee(db, organization.id, code="DE-UAT-REG-001", gross=5000)
    _make_profile(db, regular_emp, organization.id, de_employment_classification="REGULAR")
    _add_attendance(db, organization.id, regular_emp.id)

    minijob_emp = _make_employee(db, organization.id, code="DE-UAT-MINI-001", gross=520)
    _make_profile(db, minijob_emp, organization.id, de_employment_classification="MINIJOB")
    _add_attendance(db, organization.id, minijob_emp.id)

    run_data = PayrollRunCreate(
        periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
        employeeIds=[regular_emp.id, minijob_emp.id], auto_generate_payslips=True,
    )
    run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)

    # ── 2. Payslip generation (the brief's illustrative "Calculate" step)
    # happens synchronously inside create_payroll_run above — there is no
    # separate persisted status for it; the run is still DRAFT afterwards.
    assert run.status == PayrollStatus.DRAFT.value

    items = {
        item.employee_id: item
        for item in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    }
    assert set(items.keys()) == {regular_emp.id, minijob_emp.id}
    for item in items.values():
        assert item.status == PayslipStatus.PENDING.value
        assert item.net_pay > Decimal("0.00")
        assert item.net_pay < item.gross_pay
    assert items[minijob_emp.id].net_pay == Decimal("501.28")  # documented Minijob figure

    # ── 3/4/5. Walk the REAL intermediate states one real transition at a
    # time: DRAFT -> REVIEW -> APPROVED -> AUTHORIZED -> PAID -> CLOSED.
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.REVIEW.value

    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.APPROVED.value
    assert run.approved_by == 42
    assert run.approved_at is not None

    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.AUTHORIZED.value
    assert run.authorized_by == 42
    assert run.authorized_at is not None

    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.PAID.value
    assert run.paid_by == 42
    assert run.processed_at is not None

    # Every payslip item is stamped PAID as part of the Paid transition.
    db.refresh(items[regular_emp.id])
    db.refresh(items[minijob_emp.id])
    for item in items.values():
        assert item.status == PayslipStatus.PAID.value
        assert item.paid_at is not None

    # Persisted run-level aggregate reconciles against the real per-payslip
    # net_pay figures — not just "both non-zero", an actual sum match.
    expected_total_net = items[regular_emp.id].net_pay + items[minijob_emp.id].net_pay
    assert run.total_net == expected_total_net
    assert run.employee_count == 2

    # CLOSED is real and further than PAID; PAID is not actually terminal.
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.CLOSED.value

    # CLOSED genuinely is the terminal state — one more attempt is refused.
    with pytest.raises(HTTPException) as exc_info:
        _advance(db, run, organization.id)
    assert exc_info.value.status_code == 409
    db.refresh(run)
    assert run.status == PayrollStatus.CLOSED.value


# ══════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE CASE — a run with one FAILED payslip item (no statutory
#    profile) can be walked to Authorized, but is REJECTED at Paid.
# ══════════════════════════════════════════════════════════════════════════

def test_germany_run_with_failed_payslip_blocked_at_paid_but_not_earlier(db, organization, monkeypatch):
    """A run with one healthy Germany employee and one employee who has NO
    EmployeeStatutoryProfile at all: batch isolation holds (the healthy
    employee still gets a real payslip), the FAILED item does NOT block
    Review/Approved/Authorized (only the Paid transition inspects payslip
    status), but advancing to Paid is rejected per the existing fail-closed
    guard (test_payroll_safety_guards.py) and the run's status is left
    unchanged. Also proves regenerate_employee_payslip's own "locked past
    Review" guard now applies to this run."""
    _stub_business_code_generation(monkeypatch)
    _publish_all_registries(db)

    healthy_emp = _make_employee(db, organization.id, code="DE-UAT-OK-001", gross=4000)
    _make_profile(db, healthy_emp, organization.id, de_employment_classification="REGULAR")
    _add_attendance(db, organization.id, healthy_emp.id)

    broken_emp = _make_employee(db, organization.id, code="DE-UAT-BROKEN-001", gross=4500)
    # Deliberately NO statutory profile created for this employee.
    _add_attendance(db, organization.id, broken_emp.id)

    run_data = PayrollRunCreate(
        periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
        employeeIds=[healthy_emp.id, broken_emp.id], auto_generate_payslips=True,
    )
    run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)
    assert run.status == PayrollStatus.DRAFT.value

    healthy_item = db.query(PayslipItem).filter(PayslipItem.employee_id == healthy_emp.id).one()
    broken_item = db.query(PayslipItem).filter(PayslipItem.employee_id == broken_emp.id).one()

    # Batch isolation (already proven elsewhere) re-confirmed in this
    # specific full-walk context: the healthy employee is unaffected.
    assert healthy_item.status == PayslipStatus.PENDING.value
    assert healthy_item.net_pay > Decimal("0.00")

    assert broken_item.status == PayslipStatus.FAILED.value
    assert broken_item.net_pay in (None, Decimal("0.00"))
    assert "GERMANY_STATUTORY_PROFILE_MISSING" in (broken_item.notes or "")

    # Review/Approved/Authorized transitions do NOT inspect payslip status
    # — only the Paid transition does — so all three succeed normally.
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.REVIEW.value
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.APPROVED.value
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.AUTHORIZED.value

    # The Paid transition is rejected while the FAILED item is unresolved.
    with pytest.raises(HTTPException) as exc_info:
        _advance(db, run, organization.id)
    assert exc_info.value.status_code == 409
    assert "unresolved statuses" in exc_info.value.detail

    db.refresh(run)
    assert run.status == PayrollStatus.AUTHORIZED.value  # unchanged

    # The items are untouched by the rejected attempt too.
    db.refresh(healthy_item)
    db.refresh(broken_item)
    assert healthy_item.status == PayslipStatus.PENDING.value
    assert broken_item.status == PayslipStatus.FAILED.value

    # A run locked past Review also can't be fixed in place anymore —
    # regenerate_employee_payslip refuses once the run has moved on.
    with pytest.raises(HTTPException) as exc_info:
        service.regenerate_employee_payslip(
            db, run.id, broken_emp.id, organization.id, actor_id=1,
        )
    assert exc_info.value.status_code == 400
    assert "locked" in exc_info.value.detail.lower()


# ══════════════════════════════════════════════════════════════════════════
# 3. THIRD CASE — blocked, fixed WHILE still editable, then legitimately
#    walked all the way to Paid.
# ══════════════════════════════════════════════════════════════════════════

def test_germany_run_blocked_then_fixed_then_reaches_paid(db, organization, monkeypatch):
    """Same starting point as the negative case (one healthy employee, one
    employee with no statutory profile => FAILED payslip), but this time
    the statutory profile is added and the payslip regenerated WHILE the
    run is still Draft (the only window regenerate_employee_payslip
    allows) — proving the full 'blocked -> fixed -> unblocked ->
    finalized' lifecycle, not just the negative case in isolation."""
    _stub_business_code_generation(monkeypatch)
    _publish_all_registries(db)

    healthy_emp = _make_employee(db, organization.id, code="DE-UAT-OK-002", gross=4000)
    _make_profile(db, healthy_emp, organization.id, de_employment_classification="REGULAR")
    _add_attendance(db, organization.id, healthy_emp.id)

    fixable_emp = _make_employee(db, organization.id, code="DE-UAT-FIXME-001", gross=3200)
    # No statutory profile yet — this employee's payslip will FAIL.
    _add_attendance(db, organization.id, fixable_emp.id)

    run_data = PayrollRunCreate(
        periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
        employeeIds=[healthy_emp.id, fixable_emp.id], auto_generate_payslips=True,
    )
    run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)
    assert run.status == PayrollStatus.DRAFT.value

    fixable_item = db.query(PayslipItem).filter(PayslipItem.employee_id == fixable_emp.id).one()
    assert fixable_item.status == PayslipStatus.FAILED.value

    # Attempting Paid right now (still Draft, several steps early) would
    # also be refused for the same unresolved-status reason once reached —
    # but we fix it now, before advancing at all, which is the realistic
    # operator workflow (catch it during Draft/Review, not after Approve).
    _make_profile(db, fixable_emp, organization.id, de_employment_classification="REGULAR")
    run = service.regenerate_employee_payslip(
        db, run.id, fixable_emp.id, organization.id, actor_id=1,
    )
    assert run.status == PayrollStatus.DRAFT.value  # regenerate doesn't move the run's status

    db.refresh(fixable_item)
    assert fixable_item.status == PayslipStatus.PENDING.value
    assert fixable_item.net_pay > Decimal("0.00")
    assert fixable_item.net_pay < fixable_item.gross_pay

    healthy_item = db.query(PayslipItem).filter(PayslipItem.employee_id == healthy_emp.id).one()
    assert healthy_item.status == PayslipStatus.PENDING.value

    # Now the run can legitimately walk all the way to Paid.
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.REVIEW.value
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.APPROVED.value
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.AUTHORIZED.value
    run = _advance(db, run, organization.id)
    assert run.status == PayrollStatus.PAID.value

    db.refresh(fixable_item)
    db.refresh(healthy_item)
    assert fixable_item.status == PayslipStatus.PAID.value
    assert healthy_item.status == PayslipStatus.PAID.value

    expected_total_net = fixable_item.net_pay + healthy_item.net_pay
    assert run.total_net == expected_total_net
    assert run.employee_count == 2
