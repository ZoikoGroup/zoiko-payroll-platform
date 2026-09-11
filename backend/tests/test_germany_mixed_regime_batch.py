"""
tests/test_germany_mixed_regime_batch.py
----------------------------------------
Phase 8BN — one batch run containing every Germany employment regime at
once (the "mixed 5-regime" scenario the implementation program requires):

  A  MINIJOB  gross  520.00  -> CALCULATED (no PAP needed)
  B  MIDIJOB  gross 1500.00  -> BLOCKED  GERMANY_PAP_NOT_AVAILABLE
                                  (social insurance fully computed first —
                                   proven via the preserved trace)
  C  REGULAR  gross 5000.00  -> BLOCKED  GERMANY_PAP_NOT_AVAILABLE
  D  no profile gross 3000.00 -> BLOCKED  GERMANY_STATUTORY_PROFILE_MISSING
  E  MINIJOB-classified but gross 5000.00
                               -> BLOCKED  GERMANY_MINIJOB_THRESHOLD_VIOLATION
                                  (classification vs. earnings inconsistency;
                                   never silently reclassified)

Pins:
1. Exactly one employee computes; every blocked employee is recorded as a
   real, persisted FAILED PayslipItem with its structured block reason and
   full calculation trace — zero fabricated monetary figures anywhere.
2. The run's aggregates count ONLY the real payslip (employee_count == 1,
   total_gross == 520.00, total_net == 501.28).
3. Retry (generate_payslips_for_run on the same run/employees) is
   idempotent: still exactly 5 rows — stale rows replaced, never
   duplicated — with byte-identical statuses and aggregates.
4. The Germany payroll summary report's aggregates exclude all four
   blocked employees (grossPay 520.00, byStatus {CALCULATED: 1,
   BLOCKED: 4}), and Soli reports as an honest CALCULATED 0.00
   (Phase 8BN's new PayslipItem.soli surface).
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


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
    source = SourceArtifact(agency="Test Fixture", title="Mixed-regime batch test source", checksum_sha256=None)
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


def _publish_health_fund(db, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id="BATCH-FUND", fund_name="Test Fund (fixture)",
            supplementary_rate_pct=Decimal("1.7000"), effective_from=date(2026, 1, 1),
            authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_health_fund_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_health_fund_approver(db, row.id, actor_id=checker)
    return service.set_health_fund_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_pv_configuration(db, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category="CHILDLESS", is_saxony=False,
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
    _publish_health_fund(db)
    _publish_pv_configuration(db)


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


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _add_attendance(db, org_id, emp_id, day=15):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(2026, 1, day),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _run_data(employee_ids):
    return PayrollRunCreate(
        periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
        employeeIds=employee_ids, auto_generate_payslips=True,
    )


_BLOCKED_REASONS = {
    "DE-MIX-D": "GERMANY_STATUTORY_PROFILE_MISSING",
    "DE-MIX-E": "GERMANY_MINIJOB_THRESHOLD_VIOLATION",
}


def _assert_regime_row(item, emp_code, expected_status, expected_reason=None):
    assert item.status == expected_status
    if expected_status == "Failed":
        assert expected_reason is not None
        trace = item.germany_calculation_snapshot or {}
        assert trace.get("blockedReasonCode") == expected_reason
        # A blocked payslip never fabricates monetary figures.
        assert item.gross_pay == Decimal("0.00")
        assert item.net_pay == Decimal("0.00")
    return item


def test_mixed_five_regime_batch_exact_run_aggregates_and_idempotent_retry(
    db, organization, monkeypatch,
):
    """Phase 8BR: B (MIDIJOB) and C (REGULAR) now COMPLETE via the internal
    functional wage-tax calculator instead of blocking on PAP — 3 of the 5
    regimes now produce a real payslip, only D (missing profile) and E
    (Minijob/earnings inconsistency) remain genuinely blocked. B/C's exact
    wage-tax figures are NOT hand-computed here (that's
    test_germany_internal_wage_tax_calculator.py's job) — this test
    asserts the non-fabrication/aggregation INVARIANTS: net < gross,
    COMPLETE status, and run/summary aggregates matching the sum of the
    persisted items exactly."""
    _stub_business_code_generation(monkeypatch)

    a = _make_employee(db, organization.id, code="DE-MIX-A", gross=520)     # MINIJOB -> CALCULATED
    b = _make_employee(db, organization.id, code="DE-MIX-B", gross=1500)    # MIDIJOB -> CALCULATED (Phase 8BR)
    c = _make_employee(db, organization.id, code="DE-MIX-C", gross=5000)    # REGULAR -> CALCULATED (Phase 8BR)
    d = _make_employee(db, organization.id, code="DE-MIX-D", gross=3000)    # no profile -> BLOCKED
    e = _make_employee(db, organization.id, code="DE-MIX-E", gross=5000)    # MINIJOB-classified w/ gross 5000
    _make_full_profile(db, a, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, b, organization.id, de_employment_classification="MIDIJOB")
    _make_full_profile(db, c, organization.id, de_employment_classification="REGULAR")
    _make_full_profile(db, e, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    for emp in (a, b, c, d, e):
        _add_attendance(db, organization.id, emp.id)

    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([a.id, b.id, c.id, d.id, e.id]),
        organization_id=organization.id,
    )
    assert run is not None

    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert len(items) == 5

    # A: exact figures pinned (unaffected by this phase — Minijob never
    # touches wage tax at all).
    item_a = items[a.id]
    _assert_regime_row(item_a, "DE-MIX-A", "Pending")
    assert item_a.gross_pay == Decimal("520.00")
    assert item_a.tds == Decimal("0.00")
    assert item_a.church_tax == Decimal("0.00")
    assert item_a.soli == Decimal("0.00")          # Minijob flat tax carries no employee Soli
    assert item_a.pf == Decimal("18.72")           # employee pension top-up
    assert item_a.net_pay == Decimal("501.28")

    # B/C: real, non-fabricated, INTERNAL_FUNCTIONAL_REFERENCE calculations.
    for item, expected_gross in ((items[b.id], Decimal("1500.00")), (items[c.id], Decimal("5000.00"))):
        assert item.status == "Pending"
        assert item.gross_pay == expected_gross
        assert item.net_pay > Decimal("0.00")
        assert item.net_pay < item.gross_pay
        assert item.tds > Decimal("0.00")
        snap = item.germany_calculation_snapshot or {}
        assert snap.get("calculationStatus") == "COMPLETE"
        assert snap.get("papVersion") == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"

    # Midijob's social insurance was genuinely computed, not shortcut.
    midi_trace = items[b.id].germany_calculation_snapshot or {}
    assert "midijob_rv" in midi_trace.get("resolved", {})
    assert "employee" in midi_trace.get("resolved", {})["midijob_rv"]

    # D/E remain genuinely blocked, with zero fabricated figures.
    assert (items[d.id].germany_calculation_snapshot or {}).get("blockedReasonCode") == _BLOCKED_REASONS["DE-MIX-D"]
    _assert_regime_row(items[e.id], "DE-MIX-E", "Failed", _BLOCKED_REASONS["DE-MIX-E"])

    # Run aggregates count exactly the 3 real payslips (A, B, C) — no
    # blocked money leaks, and the totals equal the sum of the persisted
    # per-employee figures exactly (never hand-recomputed/approximated).
    db.refresh(run)
    expected_gross_total = item_a.gross_pay + items[b.id].gross_pay + items[c.id].gross_pay
    expected_net_total = item_a.net_pay + items[b.id].net_pay + items[c.id].net_pay
    assert run.employee_count == 3
    assert run.total_gross == expected_gross_total
    assert run.total_net == expected_net_total

    # ── Retry: idempotent, stale FAILED rows replaced, no duplication ──
    run = service.generate_payslips_for_run(
        db, run, organization.id, employee_ids=[a.id, b.id, c.id, d.id, e.id],
    )
    retried = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert len(retried) == 5  # replaced, never duplicated
    _assert_regime_row(retried[a.id], "DE-MIX-A", "Pending")
    assert retried[a.id].net_pay == Decimal("501.28")
    assert retried[b.id].status == "Pending"
    assert retried[b.id].net_pay == items[b.id].net_pay  # deterministic, byte-identical retry
    assert retried[c.id].status == "Pending"
    assert retried[c.id].net_pay == items[c.id].net_pay
    for emp_code in ("DE-MIX-D", "DE-MIX-E"):
        emp = db.query(PayrollEmployee).filter(PayrollEmployee.employee_code == emp_code).one()
        _assert_regime_row(retried[emp.id], emp_code, "Failed", _BLOCKED_REASONS[emp_code])

    db.refresh(run)
    assert run.employee_count == 3
    assert run.total_net == expected_net_total

    # ── Summary report: blocked employees excluded from every aggregate ──
    summary = service.get_germany_payroll_summary_report(
        db, organization.id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    assert summary["employeeCounts"]["total"] == 5
    # Phase 8BU: byStatus gained a third PARTIAL bucket (real components
    # calculated, at least one other genuinely unavailable) — 0 here since
    # none of this scenario's employees hit that path.
    assert summary["employeeCounts"]["byStatus"] == {"CALCULATED": 3, "BLOCKED": 2, "PARTIAL": 0}
    assert summary["employeeCounts"]["byClassification"]["MINIJOB"] == 2
    assert summary["grossPay"]["status"] == "CALCULATED"
    assert Decimal(summary["grossPay"]["amount"]) == expected_gross_total
    assert summary["netPay"]["status"] == "CALCULATED"
    assert Decimal(summary["netPay"]["amount"]) == expected_net_total
    assert summary["wageTaxStatus"]["calculated"] == 3
    assert summary["wageTaxStatus"]["blocked"] == 2
    assert summary["wageTaxStatus"]["blockedReasonCounts"] == {
        "GERMANY_STATUTORY_PROFILE_MISSING": 1,
        "GERMANY_MINIJOB_THRESHOLD_VIOLATION": 1,
    }


def test_partial_employee_end_to_end_run_aggregates_and_summary(db, organization, monkeypatch):
    """Phase 8BU (Part 21 — "remove unnecessary internal blocking") — a
    full service-layer run with one REGULAR employee whose church-tax Land
    is unresolved (church-tax-liable, no Land) alongside one ordinary
    REGULAR employee. The partial employee must:
      - persist as a real PayslipItem with status Partial (never Failed —
        RV/ALV/GKV/PV and wage tax/Soli all genuinely calculated),
      - carry a real, nonzero gross/RV/ESI but a forced-zero net_pay/
        church_tax, both explicitly flagged, never presented as a
        plausible real figure,
      - be EXCLUDED from the run's total_net (a real placeholder-zero must
        never be silently summed as if it were a genuine net pay) while
        still counting toward employee_count/total_gross,
      - render a PDF without crashing (the dedicated PARTIAL renderer),
      - surface correctly in the Germany summary report's PARTIAL bucket.
    """
    _stub_business_code_generation(monkeypatch)
    ok_emp = _make_employee(db, organization.id, code="DE-PART-OK", gross=5000)
    partial_emp = _make_employee(db, organization.id, code="DE-PART-CT", gross=4000)
    _make_full_profile(db, ok_emp, organization.id)
    _make_full_profile(db, partial_emp, organization.id, de_church_tax_liable=True, de_church_tax_land=None)
    _publish_all_registries(db)
    _add_attendance(db, organization.id, ok_emp.id)
    _add_attendance(db, organization.id, partial_emp.id)

    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([ok_emp.id, partial_emp.id]), organization_id=organization.id,
    )
    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}

    ok_item = items[ok_emp.id]
    partial_item = items[partial_emp.id]

    assert ok_item.status == "Pending"
    assert partial_item.status == "Partial"
    assert (partial_item.notes or "").startswith("[PARTIALLY_CALCULATED]")
    assert "church_tax" in partial_item.notes

    # Real, calculated figures — never discarded.
    assert partial_item.gross_pay > Decimal("0.00")
    assert partial_item.pf > Decimal("0.00")
    assert partial_item.esi > Decimal("0.00")
    # Forced-zero, explicitly flagged — never fabricated.
    assert partial_item.church_tax == Decimal("0.00")
    assert partial_item.net_pay == Decimal("0.00")
    snap = partial_item.germany_calculation_snapshot or {}
    assert snap.get("calculationStatus") == "PARTIALLY_CALCULATED"
    assert snap.get("unavailableComponents") == ["church_tax"]

    db.refresh(run)
    assert run.employee_count == 2
    assert run.total_gross == ok_item.gross_pay + partial_item.gross_pay
    # total_net excludes the PARTIAL employee's forced-zero placeholder —
    # it is NOT ok_item.net_pay + Decimal("0.00") by coincidence, it is
    # ok_item.net_pay because the placeholder was never summed at all.
    assert run.total_net == ok_item.net_pay

    # PDF rendering must not crash and must route to the dedicated
    # PARTIAL renderer (never the normal payslip layout, which would show
    # a fabricated €0.00 net pay with no explanation).
    pdf_bytes = service.generate_payslip_pdf_bytes(db, partial_item.id, organization.id)
    assert pdf_bytes[:4] == b"%PDF"

    summary = service.get_germany_payroll_summary_report(
        db, organization.id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    assert summary["employeeCounts"]["byStatus"] == {"CALCULATED": 1, "BLOCKED": 0, "PARTIAL": 1}
    assert summary["netPay"]["status"] == "PARTIAL"
    assert summary["netPay"]["excludedPartialCount"] == 1
    assert Decimal(summary["netPay"]["amount"]) == ok_item.net_pay
    assert summary["statutoryContributions"]["churchTax"]["status"] == "PARTIAL"
    assert summary["statutoryContributions"]["churchTax"]["excludedPartialCount"] == 1
    assert len(summary["partialEmployees"]) == 1
    assert summary["partialEmployees"][0]["employeeId"] == partial_emp.id
    assert summary["partialEmployees"][0]["unavailableComponents"] == ["church_tax"]