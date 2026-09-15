"""
tests/test_germany_batch_payroll_partial_processing.py
--------------------------------------------------------
Phase 8BI (P0) — regression coverage for the batch payroll abort fix.

Before this phase, `generate_payslips_for_run`'s per-employee loop had no
exception handling: a single Germany employee hitting the statutorily
blocked wage-tax path (GermanyCalculationBlockedException — no PUBLISHED
PAP asset, no effective EmployeeStatutoryProfile, etc.) aborted the ENTIRE
batch before the one `db.commit()` at the end, so even employees who
calculated successfully (Minijob, or any other country) got no payslip at
all. That is now fixed at the employee level, NOT by catching bare
Exception: only the specific, well-defined GermanyCalculationBlockedException
is caught, and it is recorded as a real, persisted FAILED PayslipItem
(zero fabricated monetary figures, the full calculation trace preserved)
rather than silently converted into a fake successful result. Any OTHER,
genuinely unexpected exception still propagates and aborts the whole
batch, exactly as before this phase.

See docs/PHASE_8BI_GERMANY_JURISDICTION_ENGINEERING_COMPLETION_REPORT.md
for the full root-cause/fix narrative.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import GermanyCalculationBlockedException
from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayrollRun, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


# ── Test helpers (same pattern as test_germany_e2e_payroll_scenario.py /
# test_germany_pap_calculation.py — deliberately duplicated per this
# project's own established test-file convention rather than shared) ────

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
    source = SourceArtifact(agency="Test Fixture", title="Batch-processing test source", checksum_sha256=None)
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


def _make_full_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=False,
        de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="BATCH-FUND",
        de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
        de_employment_classification="REGULAR",
    )
    kwargs.update(overrides)
    return service.create_employee_statutory_profile_version(
        db, emp.id, org_id, EmployeeStatutoryProfileCreate(**kwargs), actor_id=None,
    )


def _publish_all_registries(db):
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "BATCH-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _publish_registries_except_rv_alv_ceiling(db):
    """Phase 8BR: REGULAR/MIDIJOB employees no longer block on PAP (see
    engine/germany_internal_tax.py) once the full registry resolves — a
    genuinely missing RV_ALV ceiling is used instead wherever this test
    file needs a REAL, still-existing block for a REGULAR employee.
    MINIJOB is entirely unaffected (its flat-rate calculation consults no
    ceiling/health-fund/PV registry at all)."""
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_health_fund(db, "BATCH-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _publish_registries_except_health_fund(db):
    """Same idea as above, but for MIDIJOB: its RV/ALV branches don't
    consult the ceiling at all (Phase 8J — never capped in practice), so a
    missing ceiling would NOT block it. A missing Health Fund DOES block
    (calculate_midijob_gkv), and blocks AFTER RV/ALV have already
    resolved — exactly the 'SI resolves, then blocks' shape these tests
    document."""
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_pv_configuration(db, "CHILDLESS", False)


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _add_attendance(db, org_id, emp_id):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(2026, 1, 15),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _run_data(employee_ids):
    return PayrollRunCreate(
        periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
        employeeIds=employee_ids, auto_generate_payslips=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. All-success batch
# ══════════════════════════════════════════════════════════════════════════

def test_all_success_batch_two_minijob_employees(db, organization, monkeypatch):
    """Baseline: a batch with zero blocked employees behaves exactly as
    before this phase — every employee gets a real, PENDING payslip, no
    FAILED rows exist, and aggregates count everyone."""
    _stub_business_code_generation(monkeypatch)
    emp_a = _make_employee(db, organization.id, code="DE-BATCH-A", gross=520)
    emp_b = _make_employee(db, organization.id, code="DE-BATCH-B", gross=450)
    _make_full_profile(db, emp_a, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, emp_b, organization.id, de_employment_classification="MINIJOB", de_pension_insurance_exempt=True)
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp_a.id)
    _add_attendance(db, organization.id, emp_b.id)

    run = service.create_payroll_run(db, created_by=1, data=_run_data([emp_a.id, emp_b.id]), organization_id=organization.id)

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == 2
    assert all(i.status == "Pending" for i in items)
    db.refresh(run)
    assert run.employee_count == 2
    assert run.total_net == Decimal("501.28") + Decimal("450.00")


# ══════════════════════════════════════════════════════════════════════════
# 2/3. Mixed batches — one classification succeeds, another is blocked
# ══════════════════════════════════════════════════════════════════════════

def test_minijob_succeeds_alongside_blocked_regular(db, organization, monkeypatch):
    """The exact scenario the audit flagged: a Minijob employee (who can
    fully complete today, no PAP needed) must get a real payslip even
    though another employee in the SAME batch is a Regular employee that
    is genuinely blocked (Phase 8BR: REGULAR itself no longer blocks on
    PAP once the registry is complete — see engine/germany_internal_tax.py
    — so this test now uses a genuinely missing RV_ALV ceiling, which
    MINIJOB never consults, to keep exercising the 'one blocked, one
    complete in the same batch' guarantee)."""
    _stub_business_code_generation(monkeypatch)
    minijob_emp = _make_employee(db, organization.id, code="DE-BATCH-MINI", gross=520)
    regular_emp = _make_employee(db, organization.id, code="DE-BATCH-REG", gross=5000)
    _make_full_profile(db, minijob_emp, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, regular_emp, organization.id, de_employment_classification="REGULAR")
    _publish_registries_except_rv_alv_ceiling(db)
    _add_attendance(db, organization.id, minijob_emp.id)
    _add_attendance(db, organization.id, regular_emp.id)

    # Must NOT raise — this is the headline fix.
    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([minijob_emp.id, regular_emp.id]), organization_id=organization.id,
    )
    assert run is not None

    minijob_item = db.query(PayslipItem).filter(PayslipItem.employee_id == minijob_emp.id).one()
    assert minijob_item.status == "Pending"
    assert minijob_item.net_pay == Decimal("501.28")

    regular_item = db.query(PayslipItem).filter(PayslipItem.employee_id == regular_emp.id).one()
    assert regular_item.status == "Failed"
    assert regular_item.net_pay == Decimal("0.00")
    assert regular_item.gross_pay == Decimal("0.00")
    trace = regular_item.germany_calculation_snapshot or {}
    assert trace.get("blockedReasonCode") == "GERMANY_CEILING_NOT_AVAILABLE"

    db.refresh(run)
    assert run.employee_count == 1  # only the real Minijob payslip counts
    assert run.total_net == Decimal("501.28")


def test_minijob_succeeds_alongside_blocked_midijob(db, organization, monkeypatch):
    """Same mixed-batch guarantee, with Midijob as the blocked classification.
    Phase 8BR: Midijob wage tax also completes via the internal functional
    calculator now, so this uses a genuinely missing Health Fund instead
    (SI/RV/ALV still compute first, then GKV blocks — same 'SI resolves,
    then blocks' shape these tests document)."""
    _stub_business_code_generation(monkeypatch)
    minijob_emp = _make_employee(db, organization.id, code="DE-BATCH-MINI2", gross=520)
    midijob_emp = _make_employee(db, organization.id, code="DE-BATCH-MIDI", gross=1500)
    _make_full_profile(db, minijob_emp, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, midijob_emp, organization.id, de_employment_classification="MIDIJOB")
    _publish_registries_except_health_fund(db)
    _add_attendance(db, organization.id, minijob_emp.id)
    _add_attendance(db, organization.id, midijob_emp.id)

    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([minijob_emp.id, midijob_emp.id]), organization_id=organization.id,
    )
    assert run is not None

    minijob_item = db.query(PayslipItem).filter(PayslipItem.employee_id == minijob_emp.id).one()
    assert minijob_item.status == "Pending"

    midijob_item = db.query(PayslipItem).filter(PayslipItem.employee_id == midijob_emp.id).one()
    assert midijob_item.status == "Failed"
    trace = midijob_item.germany_calculation_snapshot or {}
    assert trace.get("blockedReasonCode") == "GERMANY_HEALTH_FUND_NOT_AVAILABLE"
    # SI resolution happened before the block (proves no shortcut skipped it)
    assert "midijob_rv" in trace.get("resolved", {})

    db.refresh(run)
    assert run.employee_count == 1


# ══════════════════════════════════════════════════════════════════════════
# 4. Multiple blocked employees in one batch
# ══════════════════════════════════════════════════════════════════════════

def test_multiple_blocked_employees_all_recorded_as_failed(db, organization, monkeypatch):
    """Two independently-blocked employees in the same batch: both must
    be individually recorded as FAILED, neither should prevent the other
    from being recorded, and the run itself still succeeds."""
    _stub_business_code_generation(monkeypatch)
    regular_emp = _make_employee(db, organization.id, code="DE-BATCH-REG2", gross=4000)
    no_profile_emp = _make_employee(db, organization.id, code="DE-BATCH-NOPROFILE", gross=3000)
    _make_full_profile(db, regular_emp, organization.id, de_employment_classification="REGULAR")
    # no_profile_emp deliberately has NO EmployeeStatutoryProfile at all —
    # a different, earlier blocker (GERMANY_STATUTORY_PROFILE_MISSING).
    # regular_emp is blocked by a genuinely missing RV_ALV ceiling (Phase
    # 8BR: REGULAR no longer blocks on PAP alone — see
    # engine/germany_internal_tax.py) — a different blocker again, proving
    # two INDEPENDENT block reasons are each individually recorded.
    _publish_registries_except_rv_alv_ceiling(db)
    _add_attendance(db, organization.id, regular_emp.id)
    _add_attendance(db, organization.id, no_profile_emp.id)

    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([regular_emp.id, no_profile_emp.id]), organization_id=organization.id,
    )
    assert run is not None

    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert len(items) == 2
    assert items[regular_emp.id].status == "Failed"
    assert (items[regular_emp.id].germany_calculation_snapshot or {}).get("blockedReasonCode") == "GERMANY_CEILING_NOT_AVAILABLE"
    assert items[no_profile_emp.id].status == "Failed"
    assert (items[no_profile_emp.id].germany_calculation_snapshot or {}).get("blockedReasonCode") == "GERMANY_STATUTORY_PROFILE_MISSING"

    db.refresh(run)
    assert run.employee_count == 0
    assert run.total_net == Decimal("0.00")


# ══════════════════════════════════════════════════════════════════════════
# 5. An unexpected (non-statutory-block) failure must still abort the batch
# ══════════════════════════════════════════════════════════════════════════

def test_unexpected_calculation_failure_still_aborts_batch(db, organization, monkeypatch):
    """The fix must NOT become a blanket `except Exception: continue`. A
    genuinely unexpected error (not GermanyCalculationBlockedException)
    must still propagate and abort the whole call — silently swallowing
    an unknown failure mode would be worse than today's behavior, not
    better."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="DE-BATCH-BUG", gross=520)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    import app.modules.payroll.engine.resolver as resolver_module

    def _boom(ctx, calculation_mode):
        raise RuntimeError("simulated unexpected engine bug — not a statutory block")

    monkeypatch.setattr(resolver_module, "calculate_payroll", _boom)

    with pytest.raises(RuntimeError, match="simulated unexpected engine bug"):
        service.create_payroll_run(db, created_by=1, data=_run_data([emp.id]), organization_id=organization.id)

    # The run row itself may still exist (created before payslip
    # generation, an already-disclosed pre-existing property unrelated to
    # this fix), but NO payslip — real or FAILED — was fabricated for an
    # error type this code has no defined handling for.
    assert db.query(PayslipItem).count() == 0


# ══════════════════════════════════════════════════════════════════════════
# 6. Retry behavior — a previously-blocked employee must be re-attempted
# ══════════════════════════════════════════════════════════════════════════

def test_retry_reprocesses_previously_blocked_employee(db, organization, monkeypatch):
    """A FAILED item must not be treated as 'already generated' —
    otherwise fixing the underlying blocker (here: adding the missing
    EmployeeStatutoryProfile) would have no way to ever produce a real
    payslip for that employee within the same run."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="DE-BATCH-RETRY", gross=520)
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    # First attempt: no profile yet -> FAILED.
    run = service.create_payroll_run(db, created_by=1, data=_run_data([emp.id]), organization_id=organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    assert item.status == "Failed"

    # Fix the blocker.
    _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")

    # Retry: re-run generation for the same run/employee.
    run = service.generate_payslips_for_run(db, run, organization.id, employee_ids=[emp.id])

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == 1  # the stale FAILED row was replaced, not duplicated
    retried_item = items[0]
    assert retried_item.status == "Pending"
    assert retried_item.net_pay == Decimal("501.28")

    db.refresh(run)
    assert run.employee_count == 1
    assert run.total_net == Decimal("501.28")


# ══════════════════════════════════════════════════════════════════════════
# 7/8/9. Transaction behavior, persisted run status, no false successes
# ══════════════════════════════════════════════════════════════════════════

def test_transaction_behavior_partial_success_persists_durably(db, organization, monkeypatch):
    """Both the successful and the blocked employee's rows must survive
    a fresh re-query (i.e. actually committed, not just present in the
    in-memory session) — proves this isn't an uncommitted/rolled-back
    partial state."""
    _stub_business_code_generation(monkeypatch)
    minijob_emp = _make_employee(db, organization.id, code="DE-BATCH-TXN-MINI", gross=520)
    regular_emp = _make_employee(db, organization.id, code="DE-BATCH-TXN-REG", gross=5000)
    _make_full_profile(db, minijob_emp, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, regular_emp, organization.id, de_employment_classification="REGULAR")
    _publish_registries_except_rv_alv_ceiling(db)
    _add_attendance(db, organization.id, minijob_emp.id)
    _add_attendance(db, organization.id, regular_emp.id)

    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([minijob_emp.id, regular_emp.id]), organization_id=organization.id,
    )
    run_id = run.id
    minijob_emp_id = minijob_emp.id
    regular_emp_id = regular_emp.id
    db.expunge_all()  # force every subsequent query to hit the DB fresh

    reloaded_run = db.query(PayrollRun).filter(PayrollRun.id == run_id).one()
    assert reloaded_run.status == "Draft"  # persisted run status: unaffected by the block
    reloaded_items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run_id).all()
    assert len(reloaded_items) == 2
    statuses = {i.employee_id: i.status for i in reloaded_items}
    assert statuses[minijob_emp_id] == "Pending"
    assert statuses[regular_emp_id] == "Failed"


def test_no_false_successful_payroll_records_across_all_failed_items(db, organization, monkeypatch):
    """Blanket invariant check: every FAILED item, however it was
    produced, must carry exactly zero monetary values everywhere — a
    FAILED status must never coexist with a nonzero net/gross figure
    that would make it look like a real (if small) payroll result."""
    _stub_business_code_generation(monkeypatch)
    regular_emp = _make_employee(db, organization.id, code="DE-BATCH-NOFAKE", gross=9999)
    _make_full_profile(db, regular_emp, organization.id, de_employment_classification="REGULAR")
    _publish_registries_except_rv_alv_ceiling(db)
    _add_attendance(db, organization.id, regular_emp.id)

    service.create_payroll_run(db, created_by=1, data=_run_data([regular_emp.id]), organization_id=organization.id)

    failed_items = db.query(PayslipItem).filter(PayslipItem.status == "Failed").all()
    assert len(failed_items) >= 1
    for item in failed_items:
        assert item.gross_pay == Decimal("0.00")
        assert item.net_pay == Decimal("0.00")
        assert item.total_deductions == Decimal("0.00")
        assert item.pf == Decimal("0.00")
        assert item.esi == Decimal("0.00")
        assert item.tds == Decimal("0.00")
