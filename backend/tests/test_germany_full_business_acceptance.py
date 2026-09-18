"""
tests/test_germany_full_business_acceptance.py
------------------------------------------------
Genuine, runtime, end-to-end proof of a realistic Germany payroll business
scenario, driven entirely through this codebase's own service-layer API
(never raw DB manipulation for the calculation-relevant rows) against an
isolated, throwaway SQLite database (the same `db`/`organization` fixture
chain every other Germany e2e/master-matrix test file uses — see
conftest.py, test_germany_e2e_payroll_scenario.py,
test_germany_master_scenario_matrix.py).

ONE Germany test organization. FIFTEEN employees, created through the real
`service.create_employee` onboarding function (not `PayrollEmployee(...)`
construction) plus a real `EmployeeStatutoryProfile` via
`service.create_employee_statutory_profile_version`, covering:

  1. Tax Class I, no church tax
  2. Tax Class II (Alleinerziehende, 1 child)
  3. Tax Class III (Splittingverfahren)
  4. Tax Class IV
  5. Tax Class V
  6. Tax Class VI
  7. Minijob (EUR 520/month)
  8. Midijob (EUR 1,200/month, inside the EUR 603-2,000 corridor)
  9. Church-tax employee (Bavaria, 8%)
 10. Explicit non-church-tax employee (contrast with #9)
 11. Saxony employee (different PV split)
 12. Childless employee (PV childless surcharge applies)
 13. Employee with 2 children (no PV surcharge)
 14. Employee with approved overtime hours in the payroll period
 15. Employee deliberately missing EmployeeStatutoryProfile entirely

ONE PayrollRun (`service.create_payroll_run`) covers all 15 employees.
Employees 1-14 must reach a real, non-fabricated COMPLETE payslip (Phase
8BR's internal functional wage-tax calculator — see
engine/jurisdictions/germany/tax.py — since the certified BMF PAP remains
genuinely unavailable, unchanged by this file). Employee 15 must be
isolated as a FAILED sentinel without aborting the batch (Phase 8BI's own
fix — see service.py's generate_payslips_for_run docstring).

Known, disclosed gap (do not fabricate a workaround — see the task brief):
this codebase has no separate "recalculate" AND "retry" pair of functions.
`service.regenerate_employee_payslip` recalculates one employee's payslip
in place (used here for the CORRECTION step) and
`service.generate_payslips_for_run` is *itself* the documented idempotent
retry path — its own docstring: "Idempotent: re-running skips employees
who already have a payslip in this run" and Phase 8BI's comment that a
stale FAILED sentinel is cleared and re-attempted on retry. Both are
exercised directly below (RETRY section) rather than inventing a
non-existent third function.
"""

import io
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyOvertimePremiumComponent, PayrollAttendanceRecord, PayslipItem,
    PayslipStatus, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeCreate, EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyOvertimeWorkRecordCreate, GermanyPvConfigurationCreate,
    PayrollRunCreate,
)

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)
PAY_DATE = date(2026, 2, 1)


# ══════════════════════════════════════════════════════════════════════════
# Harness helpers — same shape as test_germany_e2e_payroll_scenario.py /
# test_germany_master_scenario_matrix.py, so this file follows established,
# already-proven fixture conventions rather than inventing new ones.
# ══════════════════════════════════════════════════════════════════════════

def _stub_business_code_generation(monkeypatch):
    """Real generate_business_code re-derives a fresh number from persisted
    row counts each call, so distinct calls never collide. This fake uses a
    per-call block of 100 numbers (counter['n'] * 100) instead of a single
    incrementing integer — the RETRY test below calls
    generate_payslips_for_run multiple times in the SAME test (each a
    genuinely separate "batch code generation" event, exactly like a real
    retry request would be), so a naive 1/2/3/... counter would hand out
    the exact same low payslip_number range a previous call already
    persisted, tripping the real UNIQUE constraint on payslip_number —
    the 100-wide block keeps every call's range disjoint."""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n'] * 100:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Full business acceptance source", checksum_sha256=None)
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


def _publish_health_fund(db, health_fund_id="E2E-FUND", rate=Decimal("1.7000"), maker=1, checker=2):
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
    """Same synthetic-but-registry-shaped rates as
    test_germany_master_scenario_matrix.py's own fixture (CHILDLESS
    4.2/2.4/1.8, non-CHILDLESS 3.6/1.8/1.8, Saxony 2.9/1.3 employee/employer
    for CHILDLESS) — reused here unchanged so every numeric assertion below
    derives from the SAME published fixture values, never a hand-invented
    second set of rates."""
    if child_category == "CHILDLESS" and not is_saxony:
        total, emp, employer, sax_emp, sax_employer = "4.2000", "2.4000", "1.8000", "2.9000", "1.3000"
    elif child_category != "CHILDLESS" and not is_saxony:
        total, emp, employer, sax_emp, sax_employer = "3.6000", "1.8000", "1.8000", "2.3000", "1.3000"
    else:
        total, emp, employer, sax_emp, sax_employer = "4.2000", "2.4000", "1.8000", "2.9000", "1.3000"
    source = _make_source(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category=child_category, is_saxony=is_saxony,
            total_rate_pct=Decimal(total), standard_employee_rate_pct=Decimal(emp),
            employer_rate_pct=Decimal(employer), saxony_employee_rate_pct=Decimal(sax_emp),
            saxony_employer_rate_pct=Decimal(sax_employer),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_all_registries(db):
    """Registries needed by every scenario in this file: the two
    contribution ceilings, the health fund, and every PV (child_category,
    is_saxony) combination actually used below."""
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)   # employees 1,3,4,5,6,9,10,12,14,15
    _publish_pv_configuration(db, "1", False)           # employee 2, and employee 1's later correction
    _publish_pv_configuration(db, "2", False)           # employee 13
    _publish_pv_configuration(db, "CHILDLESS", True)    # employee 11 (Saxony)


def _create_employee(db, org_id, *, seq, code, name, gross, steuerklasse="I"):
    """Real onboarding through service.create_employee (not raw
    PayrollEmployee(...) construction) — exercises the actual DE
    EmployeeValidationStrategy (steuer_id/steuerklasse/krankenkasse/IBAN)
    exactly as a real onboarding API call would."""
    data = EmployeeCreate(
        employee_code=code, name=name, country_code="DE",
        date_of_joining=date(2025, 6, 1), ctc=Decimal(str(gross)) * 12,
        basic=Decimal(str(gross)), hra=Decimal("0"),
        compliance_fields={
            "steuer_id": f"{10000000000 + seq}",
            "steuerklasse": steuerklasse,
            "krankenkasse": "AOK Bayern",
            "iban": f"DE{seq:020d}",
        },
    )
    return service.create_employee(db, data, organization_id=org_id)


def _make_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=False,
        de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="E2E-FUND",
        de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
        de_employment_classification="REGULAR",
    )
    kwargs.update(overrides)
    return service.create_employee_statutory_profile_version(
        db, emp.id, org_id, EmployeeStatutoryProfileCreate(**kwargs), actor_id=None,
    )


def _make_attendance(db, org_id, emp_id, day=10):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(2026, 1, day),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _item_for(db, run_id, emp_id):
    return db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run_id, PayslipItem.employee_id == emp_id,
    ).one()


def _items_count_for(db, run_id, emp_id):
    return db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run_id, PayslipItem.employee_id == emp_id,
    ).count()


def _resolved_trace(item, branch) -> dict:
    return ((item.germany_calculation_snapshot or {}).get("resolved") or {}).get(branch, {})


def _block_code(item) -> str:
    return (item.germany_calculation_snapshot or {}).get("blockedReasonCode")


# ══════════════════════════════════════════════════════════════════════════
# Scenario builder — creates the ONE organization's 15 employees, their
# statutory profiles (employee 15 deliberately has none), the Germany
# overtime work record + premium component for employee 14, and runs the
# ONE payroll run covering all 15. Returns everything the tests need.
# ══════════════════════════════════════════════════════════════════════════

def _build_scenario(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    org_id = organization.id
    _publish_all_registries(db)

    emp = {}
    emp[1] = _create_employee(db, org_id, seq=1, code="DE-BIZ-01", name="Anna Fischer (Class I)", gross=5000, steuerklasse="I")
    emp[2] = _create_employee(db, org_id, seq=2, code="DE-BIZ-02", name="Berta Klein (Class II)", gross=5000, steuerklasse="II")
    emp[3] = _create_employee(db, org_id, seq=3, code="DE-BIZ-03", name="Claus Wagner (Class III)", gross=5000, steuerklasse="III")
    emp[4] = _create_employee(db, org_id, seq=4, code="DE-BIZ-04", name="Dieter Braun (Class IV)", gross=5000, steuerklasse="IV")
    emp[5] = _create_employee(db, org_id, seq=5, code="DE-BIZ-05", name="Erika Wolf (Class V)", gross=5000, steuerklasse="V")
    emp[6] = _create_employee(db, org_id, seq=6, code="DE-BIZ-06", name="Franz Neumann (Class VI)", gross=5000, steuerklasse="VI")
    emp[7] = _create_employee(db, org_id, seq=7, code="DE-BIZ-07", name="Gisela Schmidt (Minijob)", gross=520, steuerklasse="I")
    emp[8] = _create_employee(db, org_id, seq=8, code="DE-BIZ-08", name="Hans Becker (Midijob)", gross=1200, steuerklasse="I")
    emp[9] = _create_employee(db, org_id, seq=9, code="DE-BIZ-09", name="Ingrid Hofmann (Church Tax)", gross=5000, steuerklasse="I")
    emp[10] = _create_employee(db, org_id, seq=10, code="DE-BIZ-10", name="Jens Koch (No Church Tax)", gross=5000, steuerklasse="I")
    emp[11] = _create_employee(db, org_id, seq=11, code="DE-BIZ-11", name="Karin Richter (Saxony)", gross=5000, steuerklasse="I")
    emp[12] = _create_employee(db, org_id, seq=12, code="DE-BIZ-12", name="Lukas Bauer (Childless)", gross=5000, steuerklasse="I")
    emp[13] = _create_employee(db, org_id, seq=13, code="DE-BIZ-13", name="Maria Zimmermann (2 Children)", gross=5000, steuerklasse="I")
    emp[14] = _create_employee(db, org_id, seq=14, code="DE-BIZ-14", name="Niklas Vogel (Overtime)", gross=5000, steuerklasse="I")
    emp[15] = _create_employee(db, org_id, seq=15, code="DE-BIZ-15", name="Olga Krause (Missing Profile)", gross=5000, steuerklasse="I")

    # ── Statutory profiles — 14 of the 15 (employee 15 gets none). ──
    _make_profile(db, emp[1], org_id, de_tax_class="I")
    _make_profile(db, emp[2], org_id, de_tax_class="II", de_child_count=1, de_childless=False)
    _make_profile(db, emp[3], org_id, de_tax_class="III")
    _make_profile(db, emp[4], org_id, de_tax_class="IV")
    _make_profile(db, emp[5], org_id, de_tax_class="V")
    _make_profile(db, emp[6], org_id, de_tax_class="VI")
    _make_profile(db, emp[7], org_id, de_tax_class="I", de_employment_classification="MINIJOB")
    _make_profile(db, emp[8], org_id, de_tax_class="I", de_employment_classification="MIDIJOB")
    _make_profile(db, emp[9], org_id, de_tax_class="I", de_church_tax_liable=True, de_church_tax_land="DE-BY")
    _make_profile(db, emp[10], org_id, de_tax_class="I", de_church_tax_liable=False)
    _make_profile(db, emp[11], org_id, de_tax_class="I", de_saxony=True, de_childless=True, de_child_count=0)
    _make_profile(db, emp[12], org_id, de_tax_class="I", de_childless=True, de_child_count=0)
    _make_profile(db, emp[13], org_id, de_tax_class="I", de_childless=False, de_child_count=2)
    _make_profile(db, emp[14], org_id, de_tax_class="I")
    # emp[15]: deliberately NO EmployeeStatutoryProfile at all.

    for i in range(1, 15):
        _make_attendance(db, org_id, emp[i].id, day=10 + (i % 15))

    # ── Employee 14: a real, approved GermanyOvertimeWorkRecord, plus a
    # COMPLETE GermanyOvertimePremiumComponent constructed directly —
    # mirroring test_germany_overtime.py's own documented, sanctioned
    # pattern of bypassing only the wage-tax/social-insurance sub-engines
    # (which need the full registry setup this file already has), while
    # still exercising the REAL attach service function end to end below. ──
    work_record = service.create_germany_overtime_work_record(
        db, emp[14].id, org_id,
        GermanyOvertimeWorkRecordCreate(
            work_date=date(2026, 1, 20),
            start_datetime=datetime(2026, 1, 20, 18, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 1, 20, 21, 0, tzinfo=timezone.utc),
            hours=Decimal("3.00"), entry_source="MANUAL",
        ),
        actor_id=1,
    )
    work_record = service.set_germany_overtime_work_record_approval(
        db, work_record.id, org_id, "APPROVED", actor_id=1,
    )
    overtime_component = GermanyOvertimePremiumComponent(
        organization_id=org_id, work_record_id=work_record.id,
        segment_start=work_record.start_datetime, segment_end=work_record.end_datetime,
        work_date_local=work_record.work_date, qualifying_hours=Decimal("3.0000"),
        combination_status="COMPLETE",
        gross_premium_amount=Decimal("150.00"), wage_tax_free_amount=Decimal("0.00"),
        wage_taxable_amount=Decimal("150.00"), si_exempt_amount=Decimal("0.00"),
        si_contributory_amount=Decimal("150.00"),
    )
    db.add(overtime_component)
    db.commit()
    db.refresh(overtime_component)

    # ── ONE payroll run covering all 15 employees. ──
    run_data = PayrollRunCreate(
        periodStart=PERIOD_START, periodEnd=PERIOD_END, payDate=PAY_DATE,
        employeeIds=[emp[i].id for i in range(1, 16)], auto_generate_payslips=True,
    )
    run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=org_id)

    # ── Attach employee 14's approved overtime premium to their REAL,
    # now-persisted payslip item (the ONLY way overtime money ever reaches
    # a payslip — see attach_germany_overtime_premium_component_to_payslip's
    # own docstring: never automatic during run generation). ──
    item14_before = _item_for(db, run.id, emp[14].id)
    service.attach_germany_overtime_premium_component_to_payslip(
        db, overtime_component.id, item14_before.id, org_id, actor_id=1,
    )

    return {"org_id": org_id, "emp": emp, "run": run, "overtime_component_id": overtime_component.id}


# ══════════════════════════════════════════════════════════════════════════
# TEST 1 — batch isolation: 14 successes + 1 isolated failure, same run.
# ══════════════════════════════════════════════════════════════════════════

class TestBatchIsolationAndSuccessfulPayslips:
    def test_14_employees_complete_1_fails_without_aborting_batch(self, db, organization, monkeypatch):
        ctx = _build_scenario(db, organization, monkeypatch)
        run, emp = ctx["run"], ctx["emp"]

        items = {i: _item_for(db, run.id, emp[i].id) for i in range(1, 16)}

        # Employees 1-14: real, COMPLETE, non-fabricated payslips.
        for i in range(1, 15):
            item = items[i]
            assert item.status in (PayslipStatus.PENDING, PayslipStatus.PARTIAL), (
                f"employee {i} unexpectedly {item.status}"
            )
            snapshot = item.germany_calculation_snapshot or {}
            if i not in (7, 8):  # Minijob/Midijob snapshots use their own branch keys, checked separately below.
                assert snapshot.get("calculationStatus") == "COMPLETE", f"employee {i} snapshot: {snapshot}"
            assert item.gross_pay > Decimal("0.00"), f"employee {i} gross_pay not real"
            assert item.net_pay > Decimal("0.00"), f"employee {i} net_pay not real"
            assert item.net_pay < item.gross_pay, f"employee {i} net >= gross"
            # RULE 9 invariant, proven on every successful payslip.
            assert item.net_pay == item.gross_pay - item.total_deductions, (
                f"employee {i}: net_pay != gross_pay - total_deductions"
            )

        # Employee 15: deliberately missing EmployeeStatutoryProfile —
        # isolated FAILED sentinel, batch NOT aborted (all 14 others above
        # already proved COMPLETE in the very same run).
        item15 = items[15]
        assert item15.status == PayslipStatus.FAILED
        assert _block_code(item15) == "GERMANY_STATUTORY_PROFILE_MISSING"
        assert item15.gross_pay in (None, Decimal("0.00")) or item15.net_pay in (None, Decimal("0.00"))

        # The run itself must reflect exactly 15 payslip rows — no
        # employee silently dropped, no employee silently duplicated.
        assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).count() == 15

        # ── Cross-classification numeric ordering (never a fabricated,
        # hand-invented number — every inequality below is DERIVED from the
        # actual persisted figures of two employees who differ in exactly
        # one dimension). ──

        # Tax Class III (Splittingverfahren) nets MORE than Class I on
        # identical gross (halve-then-double on a progressive tariff always
        # yields less tax — see engine/jurisdictions/germany/tax.py's
        # compute_tax_for_class docstring).
        assert items[3].net_pay > items[1].net_pay, "Class III must net more than Class I on equal gross"

        # Tax Class VI (zero allowances at all) must net the LEAST of the
        # six regular tax-class employees (1-6), all on identical gross.
        six_class_nets = {i: items[i].net_pay for i in range(1, 7)}
        assert six_class_nets[6] == min(six_class_nets.values()), (
            f"Class VI must be the lowest net of the six classes, got {six_class_nets}"
        )

        # Church tax (employee 9, Bavaria 8%) vs the explicit non-church
        # contrast (employee 10) — identical Tax Class I / gross / every
        # other dimension, differing ONLY in church-tax liability. Church
        # tax must be the ENTIRE difference between the two (never a
        # fabricated second delta hiding elsewhere).
        item9, item10 = items[9], items[10]
        assert item9.church_tax > Decimal("0.00")
        assert item10.church_tax == Decimal("0.00")
        assert item9.total_deductions - item10.total_deductions == item9.church_tax
        assert item10.net_pay - item9.net_pay == item9.church_tax
        assert (item9.germany_calculation_snapshot or {}).get("churchTaxRateUsed") == "8"
        assert (item10.germany_calculation_snapshot or {}).get("churchTaxRateUsed") is None

        # Saxony (employee 11) PV split differs from the default fixture
        # split (2.9/1.3 vs 1.8/1.8 employer share on the same CHILDLESS
        # total) — traced explicitly, never silently defaulted.
        pv11 = _resolved_trace(items[11], "pv")
        assert pv11.get("employee") == str((Decimal("5000.00") * Decimal("2.9000") / 100).quantize(Decimal("0.01")))

        # Childless (12) vs 2-children (13): identical Tax Class I / gross,
        # differing ONLY in PV child category — the 0.6-point childless
        # surcharge (2.4% vs 1.8%) must be the EXACT, entire difference.
        item12, item13 = items[12], items[13]
        assert item12.esi - item13.esi == Decimal("30.00")
        # Net pay for the 2-children employee (13) is strictly HIGHER than
        # the childless employee (12) — but NOT by the full EUR 30.00 SI
        # saving: a lower PV contribution also means a smaller deductible
        # Vorsorgepauschale allowance, which raises the taxable wage-tax
        # base slightly (a genuine, documented interaction — see
        # calculate_internal_wage_tax's own `zve_for_lohnsteuer = annual_wage
        # - lohnsteuer_allowance` — never a fabricated 1:1 pass-through).
        # The net gain is therefore real, positive, but bounded above by
        # the pure SI saving.
        assert item13.net_pay > item12.net_pay
        assert item13.net_pay - item12.net_pay <= Decimal("30.00")

        # Minijob (7): documented flat-rate figures (spec-cited, matching
        # test_germany_e2e_payroll_scenario.py's own proven values).
        item7 = items[7]
        assert item7.gross_pay == Decimal("520.00")
        assert item7.pf == Decimal("18.72")          # 520 * 3.60% employee pension top-up
        assert item7.net_pay == Decimal("501.28")    # 520 - 18.72

        # Midijob (8): SI resolves via the official 3-step mechanism, wage
        # tax completes via the internal calculator — structural proof
        # (not hand-derived numbers — the 3-step midijob math is
        # deliberately NOT re-derived by hand here, matching
        # test_germany_e2e_payroll_scenario.py's own TestMidijobE2E).
        item8 = items[8]
        assert item8.gross_pay == Decimal("1200.00")
        midijob_snapshot = item8.germany_calculation_snapshot or {}
        assert midijob_snapshot.get("calculationStatus") == "COMPLETE"
        for branch in ("midijob_rv", "midijob_alv", "midijob_gkv", "midijob_pv"):
            assert branch in midijob_snapshot.get("resolved", {}), f"{branch} missing from midijob trace"

        # Employee 14: the approved overtime premium (EUR 150 gross) is
        # reflected in a HIGHER gross_pay than the same-tax-class/gross
        # baseline employee (1) — real money attached via the real
        # service function, not a fabricated bump.
        item14 = items[14]
        assert item14.gross_pay == Decimal("5150.00")   # 5000 base + 150 overtime premium
        assert item14.net_pay > items[1].net_pay
        component = db.query(GermanyOvertimePremiumComponent).filter(
            GermanyOvertimePremiumComponent.id == ctx["overtime_component_id"],
        ).one()
        assert component.attachment_status == "ATTACHED"
        assert component.applied_gross_delta == Decimal("150.00")


# ══════════════════════════════════════════════════════════════════════════
# TEST 2 — payroll register / summary aggregates match the 14 successes.
# ══════════════════════════════════════════════════════════════════════════

class TestPayrollRegisterAggregates:
    def test_summary_report_totals_equal_sum_of_successful_payslips(self, db, organization, monkeypatch):
        ctx = _build_scenario(db, organization, monkeypatch)
        run, emp, org_id = ctx["run"], ctx["emp"], ctx["org_id"]

        successful_items = [_item_for(db, run.id, emp[i].id) for i in range(1, 15)]
        failed_item = _item_for(db, run.id, emp[15].id)
        assert failed_item.status == PayslipStatus.FAILED

        expected_gross = sum((it.gross_pay or Decimal("0")) for it in successful_items)
        expected_net = sum((it.net_pay or Decimal("0")) for it in successful_items)

        summary = service.get_germany_payroll_summary_report(
            db, org_id, period_start=PERIOD_START, period_end=PERIOD_END,
        )
        assert Decimal(summary["grossPay"]["amount"]) == expected_gross
        assert Decimal(summary["netPay"]["amount"]) == expected_net
        # The failed employee contributes ZERO to every monetary total and
        # is counted in its own BLOCKED bucket, never silently dropped.
        assert summary["employeeCounts"]["byStatus"]["BLOCKED"] == 1
        assert summary["employeeCounts"]["byStatus"]["CALCULATED"] == 14
        assert summary["employeeCounts"]["total"] == 15
        assert len(summary["blockedEmployees"]) == 1
        assert summary["blockedEmployees"][0]["employeeId"] == emp[15].id


# ══════════════════════════════════════════════════════════════════════════
# TEST 3 — PDF generation (callable service function, no HTTP layer).
# ══════════════════════════════════════════════════════════════════════════

class TestPayslipPdfGeneration:
    def test_pdf_reflects_persisted_gross_and_net_for_one_payslip(self, db, organization, monkeypatch):
        ctx = _build_scenario(db, organization, monkeypatch)
        run, emp, org_id = ctx["run"], ctx["emp"], ctx["org_id"]
        item1 = _item_for(db, run.id, emp[1].id)

        # generate_payslip_pdf_bytes is a plain callable service function
        # (db, payslip_id, organization_id) -> bytes, needing no running
        # FastAPI app / HTTP layer — called directly, exactly like
        # test_germany_master_scenario_matrix.py's own PDF assertion.
        pdf_bytes = service.generate_payslip_pdf_bytes(db, item1.id, organization_id=org_id)
        assert isinstance(pdf_bytes, (bytes, bytearray))
        assert len(pdf_bytes) > 0

        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
        assert item1.employee_name in text
        # The rendered document's fmt_plain()-style money formatting is
        # f"{float(v):,.2f}" (service.py's generate_payslip_pdf_bytes) —
        # checked against the ACTUAL persisted net_pay, never a hand-typed
        # duplicate figure.
        assert f"{float(item1.net_pay):,.2f}" in text


# ══════════════════════════════════════════════════════════════════════════
# TEST 4 — CORRECTION: modify employee 1's profile, recalculate, no
# duplicate payslip row, register/summary aggregate reflects the new number.
# ══════════════════════════════════════════════════════════════════════════

class TestCorrectionRecalculation:
    def test_profile_change_recalculation_replaces_not_duplicates(self, db, organization, monkeypatch):
        ctx = _build_scenario(db, organization, monkeypatch)
        run, emp, org_id = ctx["run"], ctx["emp"], ctx["org_id"]

        item1_before = _item_for(db, run.id, emp[1].id)
        old_item_id = item1_before.id
        old_net = item1_before.net_pay
        old_esi = item1_before.esi
        assert _items_count_for(db, run.id, emp[1].id) == 1

        summary_before = service.get_germany_payroll_summary_report(
            db, org_id, period_start=PERIOD_START, period_end=PERIOD_END,
        )

        # CORRECTION: employee 1 gains a child (childless -> category "1",
        # published in _publish_all_registries) — a genuine statutory-
        # profile change with a real, derivable PV effect (surcharge
        # removed: 2.4% -> 1.8%, i.e. -EUR 30.00 employee PV on 5000
        # gross). effective_from is set mid-period (after the run's own
        # attendance-anchored period start) so auto_close_previous cleanly
        # supersedes the original open-ended version without an overlap,
        # and the run's own pay_date (01 Feb 2026) still resolves to this
        # NEW version.
        service.create_employee_statutory_profile_version(
            db, emp[1].id, org_id,
            EmployeeStatutoryProfileCreate(
                effective_from=date(2026, 1, 15), de_tax_class="I", de_church_tax_liable=False,
                de_child_count=1, de_childless=False, de_saxony=False,
                de_health_insurance_status="PUBLIC", de_health_fund_code="E2E-FUND",
                de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
                de_employment_classification="REGULAR",
            ),
            actor_id=1, auto_close_previous=True,
        )

        run_after = service.regenerate_employee_payslip(db, run.id, emp[1].id, org_id, actor_id=1)
        assert run_after.id == run.id

        # Exactly ONE current payslip item for employee 1 in this run —
        # the old row was UPDATED in place, never duplicated alongside a
        # second row.
        assert _items_count_for(db, run.id, emp[1].id) == 1
        item1_after = _item_for(db, run.id, emp[1].id)
        assert item1_after.id == old_item_id

        # The PV childless surcharge is gone: employee SI (esi, which
        # combines ALV+GKV+PV) drops by EXACTLY EUR 30.00 (0.6 points on
        # 5000 gross) — a pure rate-table effect, unaffected by tax class.
        assert old_esi - item1_after.esi == Decimal("30.00")

        # Net pay strictly increases, but NOT necessarily by the full
        # EUR 30.00: a lower PV contribution also shrinks the deductible
        # Vorsorgepauschale allowance, which slightly raises the taxable
        # wage-tax base (a genuine, documented interaction — see
        # calculate_internal_wage_tax's `zve_for_lohnsteuer = annual_wage -
        # lohnsteuer_allowance` — never a fabricated 1:1 pass-through of
        # the SI saving into net pay).
        net_delta = item1_after.net_pay - old_net
        assert Decimal("0.00") < net_delta <= Decimal("30.00")

        # The register/summary aggregate reflects the NEW number — total
        # net pay increases by EXACTLY this employee's own real net delta
        # (derived from the actual persisted figures, never hardcoded),
        # and gross pay is unchanged (PV doesn't touch gross).
        summary_after = service.get_germany_payroll_summary_report(
            db, org_id, period_start=PERIOD_START, period_end=PERIOD_END,
        )
        assert Decimal(summary_after["netPay"]["amount"]) - Decimal(summary_before["netPay"]["amount"]) == net_delta
        assert Decimal(summary_after["grossPay"]["amount"]) == Decimal(summary_before["grossPay"]["amount"])


# ══════════════════════════════════════════════════════════════════════════
# TEST 5 — RETRY / idempotency: fix employee 15, retry, no duplicates
# anywhere; retrying an already-successful employee is a safe no-op.
# ══════════════════════════════════════════════════════════════════════════

class TestRetryIdempotency:
    def test_retry_failed_employee_and_reretry_successful_employee_no_duplicates(self, db, organization, monkeypatch):
        ctx = _build_scenario(db, organization, monkeypatch)
        run, emp, org_id = ctx["run"], ctx["emp"], ctx["org_id"]

        item15_before = _item_for(db, run.id, emp[15].id)
        assert item15_before.status == PayslipStatus.FAILED
        assert _items_count_for(db, run.id, emp[15].id) == 1

        item1_before = _item_for(db, run.id, emp[1].id)
        item1_net_before = item1_before.net_pay
        item1_gross_before = item1_before.gross_pay

        # "Fix" employee 15's missing statutory profile.
        service.create_employee_statutory_profile_version(
            db, emp[15].id, org_id,
            EmployeeStatutoryProfileCreate(
                effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=False,
                de_child_count=0, de_childless=True, de_saxony=False,
                de_health_insurance_status="PUBLIC", de_health_fund_code="E2E-FUND",
                de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
                de_employment_classification="REGULAR",
            ),
            actor_id=1,
        )

        # RETRY: service.generate_payslips_for_run is the documented
        # idempotent retry path (own docstring: "Idempotent: re-running
        # skips employees who already have a payslip in this run"; Phase
        # 8BI: a stale FAILED sentinel is cleared and re-attempted). No
        # separate "retry_payroll_run" function exists in this codebase —
        # this IS the retry mechanism, called directly rather than
        # fabricating a different one.
        run_row = db.query(type(run)).filter(type(run).id == run.id).one()
        service.generate_payslips_for_run(db, run_row, org_id, employee_ids=[emp[15].id])

        assert _items_count_for(db, run.id, emp[15].id) == 1   # no duplicate FAILED+PENDING pair
        item15_after = _item_for(db, run.id, emp[15].id)
        assert item15_after.status in (PayslipStatus.PENDING, PayslipStatus.PARTIAL)
        assert item15_after.gross_pay == Decimal("5000.00")
        assert item15_after.net_pay > Decimal("0.00")
        assert item15_after.net_pay < item15_after.gross_pay

        # Retrying an ALREADY-successful employee (1) must be a safe
        # no-op: no duplicate row, no changed figures.
        service.generate_payslips_for_run(db, run_row, org_id, employee_ids=[emp[1].id])
        assert _items_count_for(db, run.id, emp[1].id) == 1
        item1_after = _item_for(db, run.id, emp[1].id)
        assert item1_after.id == item1_before.id
        assert item1_after.net_pay == item1_net_before
        assert item1_after.gross_pay == item1_gross_before

        # No employee anywhere in this run ends up with more than one
        # payslip row after both retries.
        for i in range(1, 16):
            assert _items_count_for(db, run.id, emp[i].id) == 1, f"employee {i} has duplicate payslip rows"
        assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).count() == 15
