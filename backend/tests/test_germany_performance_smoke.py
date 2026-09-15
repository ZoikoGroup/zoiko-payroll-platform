"""
tests/test_germany_performance_smoke.py
------------------------------------------
Phase 8BS — a performance SMOKE test, not a benchmark suite: measures
wall-clock time for a Germany payroll run across 1/10/50/100 Regular
employees to catch an obvious O(n^2) regression (e.g. an accidental
per-employee registry re-publish or a query-per-employee loop), without
asserting a specific absolute latency (this test's own execution
environment — a shared CI/dev machine — is not a controlled benchmark
rig). Marked slow; safe to skip in a fast pre-commit loop.
"""

import time
from datetime import date
from decimal import Decimal

from app.modules.organizations.models import Organization
from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


def _make_employee(db, org_id, code, gross=4500):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=gross * 12, basic=gross, hra=0, status="Active",
        date_of_joining=date(2020, 1, 1),
    )
    db.add(emp)
    return emp


def _make_source(db):
    source = SourceArtifact(agency="Perf Fixture", title="Performance smoke source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_all_registries(db):
    source = _make_source(db)
    for branch, monthly, annual in (("GKV_PV", Decimal("5812.50"), Decimal("69750.00")), ("RV_ALV", Decimal("8450.00"), Decimal("101400.00"))):
        row = service.create_contribution_ceiling_record(
            db, GermanyContributionCeilingCreate(
                branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
                effective_from=date(2020, 1, 1), authority_source_id=source.id,
            ), actor_id=1,
        )
        row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=1)
        row = service.set_contribution_ceiling_approver(db, row.id, actor_id=2)
        service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=2)
    fund = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id="PERF-FUND", fund_name="Perf Fund",
            supplementary_rate_pct=Decimal("1.7000"), effective_from=date(2020, 1, 1), authority_source_id=source.id,
        ), actor_id=1,
    )
    fund = service.set_health_fund_status(db, fund.id, "VERIFIED", actor_id=1)
    fund = service.set_health_fund_approver(db, fund.id, actor_id=2)
    service.set_health_fund_status(db, fund.id, "PUBLISHED", actor_id=2)
    pv = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category="CHILDLESS", is_saxony=False,
            total_rate_pct=Decimal("4.2000"), standard_employee_rate_pct=Decimal("2.4000"),
            employer_rate_pct=Decimal("1.8000"), saxony_employee_rate_pct=Decimal("2.9000"),
            saxony_employer_rate_pct=Decimal("1.3000"),
            effective_from=date(2020, 1, 1), authority_source_id=source.id,
        ), actor_id=1,
    )
    pv = service.set_pv_configuration_status(db, pv.id, "VERIFIED", actor_id=1)
    pv = service.set_pv_configuration_approver(db, pv.id, actor_id=2)
    service.set_pv_configuration_status(db, pv.id, "PUBLISHED", actor_id=2)


def _stub_business_code_generation(monkeypatch):
    """`generate_payslips_for_run` (service.py) calls the REAL
    `generate_business_code` exactly ONCE per batch (not once per
    employee — see its own comment: "Pre-generate... to avoid duplicate
    key violations... within the same uncommitted transaction"), takes
    the last 5 characters of the returned code, parses them as an int,
    and increments that integer LOCALLY once per employee in the batch —
    never calling this function again for the rest of that batch. So a
    naive per-call counter (the pattern most other Germany test files'
    stub uses safely, because THEY only ever run a single batch) is NOT
    safe here: this test runs 4 sequential batches sized up to 100 in one
    test function, and a plain +1-per-call counter's base code for a
    LATER batch can fall inside the numeric RANGE an EARLIER, larger
    batch already locally incremented through, producing a real
    `payslip_number` collision (observed and root-caused this phase, not
    guessed). Stepping by 1000 per call guarantees every batch's whole
    locally-incremented range (max batch size in this test: 100) is
    disjoint from every other's."""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1000
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _run_batch_and_time(db, organization_id, monkeypatch, count):
    # NOTE: the business-code stub must be installed ONCE for the whole
    # test (see test_performance_smoke_1_10_50_100_employees), not per
    # batch — its counter starting over at 1 for each batch size would
    # collide with payslip_number rows already committed by an earlier,
    # smaller batch. Each batch also gets its OWN organization (see the
    # caller) — sharing one organization/period across batch sizes was
    # tried first and a real create_payroll_run behavior (documented
    # nowhere obvious) pulled a PRIOR batch's already-attended employee
    # into a LATER batch's run for the same period; a dedicated org per
    # batch size sidesteps that entirely rather than this test asserting
    # anything about that specific, tangential-to-performance behavior.
    employee_ids = []
    for i in range(count):
        emp = _make_employee(db, organization_id, code=f"DE-PERF-{count}-{i}")
        db.commit()
        db.refresh(emp)
        service.create_employee_statutory_profile_version(
            db, emp.id, organization_id, EmployeeStatutoryProfileCreate(
                effective_from=date(2020, 1, 1), de_tax_class="I", de_church_tax_liable=False,
                de_child_count=0, de_childless=True, de_saxony=False,
                de_health_insurance_status="PUBLIC", de_health_fund_code="PERF-FUND",
                de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
                de_employment_classification="REGULAR",
            ), actor_id=None,
        )
        db.add(PayrollAttendanceRecord(
            organization_id=organization_id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00",
        ))
        employee_ids.append(emp.id)
    db.commit()

    start = time.perf_counter()
    run = service.create_payroll_run(
        db, created_by=1,
        data=PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=employee_ids, auto_generate_payslips=True,
        ),
        organization_id=organization_id,
    )
    elapsed = time.perf_counter() - start

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == count
    assert all(i.status == "Pending" for i in items)
    assert all(i.net_pay > Decimal("0.00") for i in items)
    return elapsed


def test_performance_smoke_1_10_50_100_500_employees(db, organization, monkeypatch):
    """Not a benchmark — an O(n) sanity check. Prints per-employee timing
    for each batch size so a human reviewer can eyeball whether it's
    growing linearly (expected) or super-linearly (a real bottleneck
    worth investigating in a dedicated performance phase). Each batch
    size gets its own organization (registries are org-scoped and cheap
    to republish; this also avoids any cross-batch interaction in a
    shared org/period, keeping the test purely about per-employee cost).
    Phase 8BT: extended to 500 employees per the phase brief's explicit
    request ("500 employees if practical") — practical here, since the
    whole batch (including per-employee statutory-profile creation)
    completes in well under the suite's own timeout."""
    _stub_business_code_generation(monkeypatch)
    # Germany's contribution-ceiling/health-fund/PV registries are GLOBAL
    # (super-admin managed, shared across every organization — see
    # test_germany_contribution_rate_effective_dating.py's own tenant-
    # isolation test for this same fact) — published exactly ONCE here,
    # never per-org/per-batch, or the second publish attempt would hit
    # the same overlapping-effective-period validation error a shared
    # per-org republish would.
    _publish_all_registries(db)
    timings = {}
    for count in (1, 10, 50, 100, 500):
        org = Organization(organization_name=f"Perf Org {count}", organization_code=f"PERF{count}")
        db.add(org)
        db.commit()
        db.refresh(org)

        elapsed = _run_batch_and_time(db, org.id, monkeypatch, count)
        timings[count] = elapsed
        print(f"\n[perf] {count} Germany employees: {elapsed:.3f}s total, {elapsed / count * 1000:.1f}ms/employee")

    # Sanity bound only — catches a genuine pathological regression (e.g.
    # an accidental O(n^2) loop) without asserting a specific absolute
    # latency this shared test environment can't guarantee. 500 employees
    # taking more than 120s total would indicate a real problem regardless
    # of machine speed.
    assert timings[100] < 60.0, f"100-employee Germany payroll run took {timings[100]:.1f}s — investigate for an O(n^2) regression"
    assert timings[500] < 120.0, f"500-employee Germany payroll run took {timings[500]:.1f}s — investigate for an O(n^2) regression"

    # Per-employee cost should not grow dramatically as the batch grows —
    # a genuine O(n^2) issue would show per-employee cost roughly
    # doubling/tripling as the batch size grows 10x. Generous multiplier
    # (5x) to avoid flaking on a loaded CI box while still catching a
    # real quadratic blowup.
    per_employee_at_10 = timings[10] / 10
    per_employee_at_100 = timings[100] / 100
    per_employee_at_500 = timings[500] / 500
    assert per_employee_at_100 < per_employee_at_10 * 5, (
        f"per-employee cost grew from {per_employee_at_10*1000:.1f}ms (10 employees) to "
        f"{per_employee_at_100*1000:.1f}ms (100 employees) — possible O(n^2) bottleneck"
    )
    assert per_employee_at_500 < per_employee_at_10 * 5, (
        f"per-employee cost grew from {per_employee_at_10*1000:.1f}ms (10 employees) to "
        f"{per_employee_at_500*1000:.1f}ms (500 employees) — possible O(n^2) bottleneck"
    )
