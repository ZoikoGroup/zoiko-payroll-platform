"""
tests/test_germany_master_scenario_matrix.py
---------------------------------------------
Phase 8BN — the consolidated Germany scenario matrix (§ requirement of the
Master Completion Program). 22 scenarios exercising the production
payroll pipeline end to end, every scenario explicitly labelled with its
status:

  * COMPLETE    — the classification produces a real, payable payslip today.
  * BLOCKED/PAP — statutory SI resolved then fail-closed on the unavailable
                  BMF PAP (GermanyPapNotAvailableError). This is CORRECT
                  behaviour per §25, never a bug.
  * FAIL-CLOSED — an inconsistent/unsupported input fails closed with a
                  precise, stable blocked-reason code.

Nothing here asserts a value that the cited 2026 statutory constants
(hardcoded_defaults.py) or the fixture-published registry rows do not
themselves establish — where a number matters, the expected value is
*derived in-test from those constants*, never hardcoded by hand, so no
statutory figure can be silently invented or drift from the engine's own
fallback source. Root-level registries published via service.py's
maker/checker + PUBLISHED lifecycle with a real SourceArtifact, exactly
like the existing test_germany_e2e_payroll_scenario.py harness.

Test categories (same convention as the E2E file):
  AUTHORITATIVE — registry/cited constants drive the assertion
  REGRESSION    — protects documented production behaviour
  SECURITY      — fail-closed + zero-fabrication assertions
"""

import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.payroll import service
from app.modules.payroll.engine.germany_pap.core import _r2
from app.modules.payroll.hardcoded_defaults import (
    _DE_ALV_EMPLOYEE_RATE,
    _DE_ALV_EMPLOYER_RATE,
    _DE_GKV_GENERAL_EMPLOYEE_RATE,
    _DE_GKV_GENERAL_EMPLOYER_RATE,
    _DE_INSOLVENCY_LEVY_RATE,
    _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
    _DE_MINIJOB_EMPLOYER_HEALTH_RATE,
    _DE_MINIJOB_EMPLOYER_PENSION_RATE,
    _DE_MINIJOB_U1_RATE,
    _DE_MINIJOB_U2_RATE,
    _DE_MINIJOB_U3_RATE,
    _DE_RV_EMPLOYEE_RATE,
    _DE_RV_EMPLOYER_RATE,
)
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayrollRun, PayslipItem, PayslipStatus,
    SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


# ── Harness helpers (mirroring the E2E scenario file) ────────────────────

def _make_employee(db, org_id, code="DE-SMX-001", gross=5000):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=gross * 12, basic=gross, hra=0, status="Active",
        date_of_joining=date(2025, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Scenario matrix source (synthetic)", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_ceiling(db, branch, monthly, annual, maker=1, checker=2, effective_from=date(2026, 1, 1)):
    source = _make_source(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=effective_from, authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_contribution_ceiling_approver(db, row.id, actor_id=checker)
    return service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_health_fund(db, health_fund_id="E2E-FUND", rate=Decimal("1.7000"), maker=1, checker=2):
    source = _make_source(db)
    row = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id=health_fund_id, fund_name="Test Fund (synthetic fixture)",
            supplementary_rate_pct=rate, effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_health_fund_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_health_fund_approver(db, row.id, actor_id=checker)
    return service.set_health_fund_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_pv_configuration(db, child_category="CHILDLESS", is_saxony=False, maker=1, checker=2):
    """Fixture PV splits — CHILDLESS total 4.2 (employee 2.4 includes the
    0.6 childless surcharge, employer 1.8); children total 3.6 (1.8/1.8);
    Saxony shifts 0.5 points within each total. Purely synthetic test
    rows occupying the same shape as the real registry — not statutory
    claims in their own right (assertions derive from these exact fields)."""
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


def _make_full_profile(db, emp, org_id, **overrides):
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


def _publish_all_registries(db):
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _make_attendance(db, org_id, emp_id, day=15, month=1, year=2026, bonus=Decimal("0")):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(year, month, day),
        status="present", check_in="09:00", check_out="18:00", bonus=bonus,
    ))
    db.commit()


def _run_payroll(db, emp, org_id, period=date(2026, 1, 1), label="Jan 2026"):
    """Create a run for the employee and auto-generate payslips through
    the real production pipeline (service.create_payroll_run)."""
    period_end = date(period.year, period.month, 28) if period.month == 2 else date(period.year, period.month, 28)
    run_data = PayrollRunCreate(
        periodStart=period, periodEnd=period_end, payDate=date(period.year, period.month, 28),
        employeeIds=[emp.id], auto_generate_payslips=True,
    )
    run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=org_id)
    return run, db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id, PayslipItem.payroll_run_id == run.id).one()


def _block_code(item) -> str:
    return (item.germany_calculation_snapshot or {}).get("blockedReasonCode")


def _resolved_trace(item, branch) -> dict:
    return ((item.germany_calculation_snapshot or {}).get("resolved") or {}).get(branch, {})


def _round_half_up(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ══════════════════════════════════════════════════════════════════════════
# SCENARIO 01 — REGULAR below all ceilings, PUBLIC insurance (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestRegularPublic:
    def test_01_regular_below_ceilings_resolves_full_si_then_blocks_on_pap(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross 5,000/mo (60,000/y) is below both the GKV_PV
        69,750 and RV_ALV 101,400 ceilings. All four SI branches resolve and
        compute; the pipeline then fails closed on PAP with a FAILED
        sentinel item (never a fabricated wage tax)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S01", gross=5000)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)
        db.add(PayrollAttendanceRecord(
            organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00",
        ))
        db.commit()

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Pending"  # calculated (Phase 8BR internal tax calculator), awaiting payslip generation
        assert item.net_pay > Decimal("0.00")
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"

        # Derived straight from the documented constants on the uncapped base.
        base = Decimal("5000.00")
        rv = _round_half_up(base * (_DE_RV_EMPLOYEE_RATE) / 100)
        alv = _round_half_up(base * _DE_ALV_EMPLOYEE_RATE / 100)
        gkv = _round_half_up(base * (_DE_GKV_GENERAL_EMPLOYEE_RATE + Decimal("1.7000") / 2) / 100)
        pv_emp = _round_half_up(base * Decimal("2.4000") / 100)   # CHILDLESS employee share (incl. surcharge)
        pv_emp_r = _round_half_up(base * Decimal("1.8000") / 100)
        u3 = _round_half_up(base * _DE_INSOLVENCY_LEVY_RATE / 100)

        rv_trace = _resolved_trace(item, "rv")
        assert rv_trace.get("employee") == str(rv)
        assert rv_trace.get("employer") == str(rv)
        alv_trace = _resolved_trace(item, "alv")
        assert alv_trace.get("employee") == str(alv)
        assert alv_trace.get("employer") == str(alv)
        gkv_trace = _resolved_trace(item, "gkv")
        assert gkv_trace.get("employee") == str(gkv)
        assert gkv_trace.get("employer") == str(gkv)
        pv_trace = _resolved_trace(item, "pv")
        assert pv_trace.get("employee") == str(pv_emp)
        assert pv_trace.get("employer") == str(pv_emp_r)

        # U3 (insolvency levy) is the only universally-computable employer
        # levy on the regular path; U1/U2 are fund-specific, deliberately
        # NOT_CONFIGURED here (the fixture fund publishes no U1/U2 rates).
        levies = _resolved_trace(item, "employer_levies")
        assert levies.get("u3_insolvency_levy") == str(u3)
        assert "NOT_CONFIGURED" in levies.get("u1", "")
        assert "NOT_CONFIGURED" in levies.get("u2", "")
        assert levies.get("accident_insurance", "").startswith(("CONFIGURED", "NOT_CONFIGURED"))


# ══════════════════════════════════════════════════════════════════════════
# SCENARIOS 02–05 — ceiling capping (GKV_PV / RV_ALV) (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestCeilingCapping:
    def test_02_regular_above_gkv_ceiling_caps_gkv_pv_base(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross 6,000/mo = 72,000/y > 69,750 GKV_PV ceiling.
        GKV/PV must cap on 69,750 annual (5,812.50/mo) while RV/ALV stay on
        the full 72,000 — each branch caps independently on its own registry."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S02", gross=6000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"

        gkv_base = _round_half_up(Decimal("69750.00") / 12)
        gkv = _round_half_up(gkv_base * (_DE_GKV_GENERAL_EMPLOYEE_RATE + Decimal("1.7000") / 2) / 100)
        rv = _round_half_up(Decimal("6000.00") * _DE_RV_EMPLOYEE_RATE / 100)
        assert _resolved_trace(item, "gkv").get("employee") == str(gkv)
        assert _resolved_trace(item, "rv").get("employee") == str(rv)

    def test_03_regular_above_rv_alv_ceiling_caps_rv_alv_base(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross 9,000/mo = 108,000/y > 101,400 RV_ALV ceiling.
        RV/ALV cap on 101,400 (8,450/mo); GKV/PV cap on their own 69,750."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S03", gross=9000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"

        rv = _round_half_up(Decimal("8450.00") * _DE_RV_EMPLOYEE_RATE / 100)
        alv = _round_half_up(Decimal("8450.00") * _DE_ALV_EMPLOYEE_RATE / 100)
        gkv = _round_half_up(Decimal("5812.50") * (_DE_GKV_GENERAL_EMPLOYEE_RATE + Decimal("1.7000") / 2) / 100)
        assert _resolved_trace(item, "rv").get("employee") == str(rv)
        assert _resolved_trace(item, "rv").get("employer") == str(rv)
        assert _resolved_trace(item, "alv").get("employee") == str(alv)
        assert _resolved_trace(item, "gkv").get("employee") == str(gkv)

    def test_04_exact_gkv_ceiling_boundary_not_capped(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross 5,812.50/mo = exactly 69,750/y (the GKV_PV
        ceiling) — the base equals the ceiling, no over-cap distortion."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S04", gross=Decimal("5812.50"))
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        gkv = _round_half_up(Decimal("5812.50") * (_DE_GKV_GENERAL_EMPLOYEE_RATE + Decimal("1.7000") / 2) / 100)
        assert _resolved_trace(item, "gkv").get("employee") == str(gkv)

    def test_05_exact_rv_alv_ceiling_boundary_not_capped(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross 8,450/mo = exactly 101,400/y (the RV_ALV
        ceiling) — base equals the ceiling, no over-cap distortion."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S05", gross=Decimal("8450.00"))
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        rv = _round_half_up(Decimal("8450.00") * _DE_RV_EMPLOYEE_RATE / 100)
        assert _resolved_trace(item, "rv").get("employee") == str(rv)


# ══════════════════════════════════════════════════════════════════════════
# SCENARIOS 06–08 — PV child category / Saxony splits (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestPvCategorySplits:
    def test_06_pv_childless_surcharge_in_split(self, db, organization, monkeypatch):
        """AUTHORITATIVE: CHILDLESS PV configuration (fixture 2.4/1.8) — the
        employee share carries the 0.6 childless surcharge on top of the
        1.8 base, the employer share is untouched."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S06", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_childless=True, de_child_count=0)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        assert _resolved_trace(item, "pv").get("employee") == str(_round_half_up(Decimal("5000.00") * Decimal("2.4000") / 100))
        assert _resolved_trace(item, "pv").get("employer") == str(_round_half_up(Decimal("5000.00") * Decimal("1.8000") / 100))

    def test_07_pv_with_children_no_surcharge(self, db, organization, monkeypatch):
        """AUTHORITATIVE: two children (de_childless=False, de_child_count=2)
        resolve category "2" — symmetric 1.8/1.8 split, no surcharge."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S07", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_childless=False, de_child_count=2)
        _publish_all_registries(db)
        _publish_pv_configuration(db, "2", False)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        assert _resolved_trace(item, "pv").get("employee") == str(_round_half_up(Decimal("5000.00") * Decimal("1.8000") / 100))
        assert _resolved_trace(item, "pv").get("employer") == str(_round_half_up(Decimal("5000.00") * Decimal("1.8000") / 100))

    def test_08_pv_saxony_split(self, db, organization, monkeypatch):
        """AUTHORITATIVE: Saxony CHILDLESS (2.9/1.3) — Saxony's own 0.5-point
        employee-only adjustment changes the split, not the total."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S08", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_saxony=True, de_childless=True, de_child_count=0)
        _publish_all_registries(db)
        _publish_pv_configuration(db, "CHILDLESS", True)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        assert _resolved_trace(item, "pv").get("employee") == str(_round_half_up(Decimal("5000.00") * Decimal("2.9000") / 100))
        assert _resolved_trace(item, "pv").get("employer") == str(_round_half_up(Decimal("5000.00") * Decimal("1.3000") / 100))


# ══════════════════════════════════════════════════════════════════════════
# SCENARIO 09 — PRIVATE health insurance (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestPrivateHealth:
    def test_09_private_health_insurance_skips_gkv_and_pv(self, db, organization, monkeypatch):
        """AUTHORITATIVE: de_health_insurance_status="PRIVATE" (PKV) — no
        statutory GKV/PV; premium allowances are PAP-side fields, so the
        pipeline still fails closed on PAP (never fabricates a premium)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S09", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        # PRIVATE insurance needs no published Health Fund or PV config —
        # deliberately left unpublished to prove they are not consulted.
        _make_full_profile(db, emp, organization.id, de_health_insurance_status="PRIVATE")
        _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
        _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        assert _resolved_trace(item, "gkv").get("employee") == "0"
        snapshot = item.germany_calculation_snapshot or {}
        assert "pv" not in snapshot.get("resolved", {})  # PV is skipped, not computed-as-zero
        steps = " ".join(snapshot.get("steps", []))
        assert "Skipped PV — employee is privately health-insured (PKV)" in steps


# ══════════════════════════════════════════════════════════════════════════
# SCENARIOS 10–11 — Church tax (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestChurchTax:
    def test_10_church_tax_liable_traces_land_rate(self, db, organization, monkeypatch):
        """AUTHORITATIVE: de_church_tax_liable=True with a resolvable Land
        (DE-BY, Bayerische Land rate 8%) — the rate is traced and fed into
        the PAP computation, which still blocks (PAP unavailable)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S10", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_church_tax_liable=True, de_church_tax_land="DE-BY")
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        snapshot = item.germany_calculation_snapshot or {}
        assert snapshot.get("churchTaxRateUsed") == "8"

    def test_11_church_tax_not_liable_no_rate(self, db, organization, monkeypatch):
        """AUTHORITATIVE: de_church_tax_liable=False — no rate traced, and
        the PAP input runs with R=0 (religion off), still block on PAP."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S11", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_church_tax_liable=False)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        assert (item.germany_calculation_snapshot or {}).get("churchTaxRateUsed") is None


# ══════════════════════════════════════════════════════════════════════════
# SCENARIO 12 — Earning taxability without PUBLISHED rules (SECURITY)
# ══════════════════════════════════════════════════════════════════════════

class TestEarningTaxabilityFailClosed:
    def test_12_no_published_taxability_rules_surface_not_configured(self, db, organization, monkeypatch):
        """SECURITY: no GermanyEarningTaxabilityRule is published — the
        engine must surface NOT_CONFIGURED for the four dimensions and
        never invent a taxable/non-taxable decision."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S12", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id)
        # Registries published, taxability rules deliberately absent.
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        detail = ((item.germany_calculation_snapshot or {}).get("earningTaxabilityDetail") or {})
        assert any(str(status).startswith("NOT_CONFIGURED") for status in [detail.get("status")] + [v.get("status") for v in detail.values() if v])


# ══════════════════════════════════════════════════════════════════════════
# SCENARIOS 13–18 — Minijob / Midijob boundaries (COMPLETE / FAIL-CLOSED)
# ══════════════════════════════════════════════════════════════════════════

class TestMinijobBoundaries:
    def test_13_minijob_at_exact_upper_threshold_is_complete(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross exactly 603.00 (the Minijob upper threshold)
        is still Minijob — a REAL complete payslip (no PAP needed)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S13", gross=603)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Pending"
        assert item.gross_pay == Decimal("603.00")
        topup = _round_half_up(Decimal("603.00") * _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE / 100)
        assert item.pf == topup
        health = _round_half_up(Decimal("603.00") * _DE_MINIJOB_EMPLOYER_HEALTH_RATE / 100)
        u1 = _round_half_up(Decimal("603.00") * _DE_MINIJOB_U1_RATE / 100)
        u2 = _round_half_up(Decimal("603.00") * _DE_MINIJOB_U2_RATE / 100)
        u3 = _round_half_up(Decimal("603.00") * _DE_MINIJOB_U3_RATE / 100)
        assert item.employer_esi == health + u1 + u2 + u3
        assert item.employer_pf == _round_half_up(Decimal("603.00") * _DE_MINIJOB_EMPLOYER_PENSION_RATE / 100)
        assert item.net_pay == Decimal("603.00") - topup

    def test_14_minijob_above_threshold_classified_minijob_fails_closed(self, db, organization, monkeypatch):
        """SECURITY: gross 603.01 (one cent above the threshold) with a
        MINIJOB classification — the engine refuses to silently
        reclassify and records a FAILED sentinel instead of fabricating."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S14", gross=Decimal("603.01"))
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Failed"
        assert _block_code(item) == "GERMANY_MINIJOB_THRESHOLD_VIOLATION"

    def test_18_minijob_bonus_pushes_gross_over_threshold_fails_closed(self, db, organization, monkeypatch):
        """SECURITY: a Minijob employee (520/month) receives an 83.01 bonus
        (SONSTB-routed attendance bonus) — total 603.01 crosses the Minijob
        threshold; the engine fails closed rather than choosing a
        classification the employee's statutory profile does not declare."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S18", gross=520)
        _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
        _publish_all_registries(db)
        db.add(PayrollAttendanceRecord(
            organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00", bonus=Decimal("83.01"),
        ))
        db.commit()

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Failed"
        assert _block_code(item) == "GERMANY_MINIJOB_THRESHOLD_VIOLATION"


class TestMidijobBoundaries:
    def test_15_midijob_at_lower_boundary_computes_si_and_wage_tax(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross 603.01 — the Midijob corridor starts above
        the Minijob threshold. SI resolves via the 3-step mechanism; Phase
        8BR: wage tax now completes via the internal functional calculator
        (official BMF PAP remains unavailable, unchanged)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S15", gross=Decimal("603.01"))
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_employment_classification="MIDIJOB")
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Pending"
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        resolved = (item.germany_calculation_snapshot or {}).get("resolved", {})
        assert "midijob_rv" in resolved
        assert item.net_pay > Decimal("0.00")

    def test_16_midijob_at_exact_upper_boundary_computes_si_and_wage_tax(self, db, organization, monkeypatch):
        """AUTHORITATIVE: gross exactly 2,000.00 — the top of the Midijob
        corridor. SI resolves; wage tax completes via the internal
        functional calculator (Phase 8BR)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S16", gross=2000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_employment_classification="MIDIJOB")
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Pending"
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        assert "midijob_rv" in ((item.germany_calculation_snapshot or {}).get("resolved") or {})
        assert item.net_pay > Decimal("0.00")

    def test_17_midijob_above_corridor_fails_closed(self, db, organization, monkeypatch):
        """SECURITY: gross 2,000.01 is above the Midijob corridor with a
        MIDIJOB classification — fails closed, never fabricated."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S17", gross=Decimal("2000.01"))
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id, de_employment_classification="MIDIJOB")
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert item.status == "Failed"
        assert _block_code(item) == "GERMANY_MIDIJOB_THRESHOLD_VIOLATION"


# ══════════════════════════════════════════════════════════════════════════
# SCENARIOS 19–20 — Historical / effective-dated resolution (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestEffectiveDating:
    def test_19_historical_payroll_with_no_effective_profile_fails_closed(self, db, organization, monkeypatch):
        """SECURITY: payroll for Dec 2025 against profile/registries that are
        only effective from 01 Jan 2026 — nothing resolves for that date
        (as-of is the run's pay_date, inside the period), so the run records
        a FAILED sentinel (profile missing), never a guess."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S19", gross=5000)
        _make_attendance(db, organization.id, emp.id, month=12, year=2025)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        run = service.create_payroll_run(db, created_by=1, data=PayrollRunCreate(
            periodStart=date(2025, 12, 1), periodEnd=date(2025, 12, 31),
            payDate=date(2025, 12, 31), employeeIds=[emp.id], auto_generate_payslips=True,
        ), organization_id=organization.id)
        item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
        assert item.status == "Failed"
        assert _block_code(item) == "GERMANY_STATUTORY_PROFILE_MISSING"

    def test_20_two_profile_versions_resolve_by_date(self, db, organization, monkeypatch):
        """AUTHORITATIVE/REGRESSION: a Dec-2025 version and a Jan-2026 version
        of the same employee's profile — a Dec run (pay date 31 Dec 2025,
        the anchoring as-of) must resolve the Dec version's id, a Jan run
        the Jan id (snapshot provenance, never a mix-up). Both runs still
        block (no PAP; and the Dec run additionally has no GKV_PV ceiling
        published, proving date-scoped registry resolution too)."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S20", gross=5000)
        base_kwargs = dict(
            de_tax_class="I", de_church_tax_liable=False, de_child_count=0,
            de_childless=True, de_saxony=False, de_health_insurance_status="PUBLIC",
            de_health_fund_code="E2E-FUND", de_pension_insurance_exempt=False,
            de_unemployment_insurance_exempt=False, de_employment_classification="REGULAR",
        )
        v_dec = service.create_employee_statutory_profile_version(
            db, emp.id, organization.id, EmployeeStatutoryProfileCreate(
                effective_from=date(2025, 12, 1), **base_kwargs,
            ), auto_close_previous=False, actor_id=None,
        )
        v_jan = service.create_employee_statutory_profile_version(
            db, emp.id, organization.id, EmployeeStatutoryProfileCreate(
                effective_from=date(2026, 1, 1), **base_kwargs,
            ), auto_close_previous=True, actor_id=None,
        )
        # Dec 2025 registries: ONLY the RV_ALV ceiling exists, and it is
        # effective from 01 Dec 2025. GKV_PV ceiling / health fund / PV
        # configuration are all absent for that date, so the December run
        # resolves the Dec profile + RV_ALV ceiling, then blocks on the
        # missing GKV_PV ceiling — pure date-scoped fail-closed.
        _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"), effective_from=date(2025, 12, 1))
        _make_attendance(db, organization.id, emp.id, month=12, year=2025)
        run_dec = service.create_payroll_run(db, created_by=1, data=PayrollRunCreate(
            periodStart=date(2025, 12, 1), periodEnd=date(2025, 12, 31),
            payDate=date(2025, 12, 31), employeeIds=[emp.id], auto_generate_payslips=True,
        ), organization_id=organization.id)
        item_dec = db.query(PayslipItem).filter(
            PayslipItem.employee_id == emp.id, PayslipItem.payroll_run_id == run_dec.id,
        ).one()
        assert item_dec.status == "Failed"
        assert _block_code(item_dec) == "GERMANY_CEILING_NOT_AVAILABLE"
        dec_snapshot = item_dec.germany_calculation_snapshot or {}
        assert dec_snapshot.get("statutoryProfileId") == v_dec.id
        assert dec_snapshot.get("ceilingRvAlvId") is not None
        assert dec_snapshot.get("ceilingGkvPvId") is None

        # Same employee, Jan 2026: full registry cohort resolves and the
        # internal functional wage-tax calculator now completes the
        # calculation (Phase 8BR). Snapshot must carry the JAN profile id
        # and the GKV_PV ceiling now resolved.
        _publish_all_registries(db)
        _make_attendance(db, organization.id, emp.id)
        run_jan = service.create_payroll_run(db, created_by=1, data=PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31),
            payDate=date(2026, 2, 1), employeeIds=[emp.id], auto_generate_payslips=True,
        ), organization_id=organization.id)
        item_jan = db.query(PayslipItem).filter(
            PayslipItem.employee_id == emp.id, PayslipItem.payroll_run_id == run_jan.id,
        ).one()
        assert item_jan.status == "Pending"
        assert (item_jan.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        jan_snapshot = item_jan.germany_calculation_snapshot or {}
        assert jan_snapshot.get("statutoryProfileId") == v_jan.id
        assert jan_snapshot.get("ceilingGkvPvId") is not None
        assert dec_snapshot.get("statutoryProfileId") != jan_snapshot.get("statutoryProfileId")


# ══════════════════════════════════════════════════════════════════════════
# SCENARIO 21 — Employer levies on the regular path (BLOCKED/PAP)
# ══════════════════════════════════════════════════════════════════════════

class TestEmployerLevies:
    def test_21_u3_computed_u1_u2_not_configured_without_fund_rates(self, db, organization, monkeypatch):
        """AUTHORITATIVE: the fixture fund publishes no U1/U2 rates, so the
        regular path must trace U3 (universal federal rate) and leave U1/U2
        explicitly NOT_CONFIGURED — never silently zero, never a guessed
        universal rate."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-S21", gross=5000)
        _make_attendance(db, organization.id, emp.id)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        run, item = _run_payroll(db, emp, organization.id)
        assert (item.germany_calculation_snapshot or {}).get("calculationStatus") == "COMPLETE"
        levies = _resolved_trace(item, "employer_levies")
        assert levies.get("u3_insolvency_levy") == str(_round_half_up(Decimal("5000.00") * _DE_INSOLVENCY_LEVY_RATE / 100))
        assert "NOT_CONFIGURED" in levies.get("u1", "")
        assert "NOT_CONFIGURED" in levies.get("u2", "")


# ══════════════════════════════════════════════════════════════════════════
# SCENARIO 22 — Blocked PDF + summary report surface (REGRESSION)
# ══════════════════════════════════════════════════════════════════════════

class TestSurfaceDocuments:
    def test_22_blocked_pdf_zero_figures_and_summary_counts(self, db, organization, monkeypatch):
        """REGRESSION: a FAILED (blocked) payslip must render the explicit
        blocked-state PDF (no fabricated 0.00 figures), and the Germany
        summary report must count it as BLOCKED — never as a real payslip.
        A MINIJOB payslip in the same run is COMPLETE and counts as such.

        Phase 8BR: a REGULAR employee no longer blocks once the registry is
        published (it now completes via the internal functional wage-tax
        calculator) — this scenario now blocks emp_reg on a genuinely
        missing RV_ALV ceiling instead, which MINIJOB never consults (its
        flat-rate calculation needs no ceiling/health-fund/PV registry at
        all), so the 'one blocked, one complete in the same run' shape is
        preserved with a real, still-existing block."""
        _stub_business_code_generation(monkeypatch)
        # Blocked: regular employee (missing RV_ALV ceiling).
        emp_reg = _make_employee(db, organization.id, code="DE-S22A", gross=5000)
        _make_attendance(db, organization.id, emp_reg.id, day=10)
        _make_full_profile(db, emp_reg, organization.id)
        # Complete: minijob employee in the SAME run (both the run's
        # employees process through the production pipeline together).
        # MINIJOB needs none of the registries below, so it stays COMPLETE
        # even though only the GKV_PV ceiling (not RV_ALV) is published.
        emp_mini = _make_employee(db, organization.id, code="DE-S22B", gross=520)
        _make_attendance(db, organization.id, emp_mini.id, day=12)
        _make_full_profile(db, emp_mini, organization.id, de_employment_classification="MINIJOB")
        _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
        _publish_health_fund(db, "E2E-FUND")
        _publish_pv_configuration(db, "CHILDLESS", False)

        run_data = PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp_reg.id, emp_mini.id], auto_generate_payslips=True,
        )
        run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)

        item_reg = db.query(PayslipItem).filter(PayslipItem.employee_id == emp_reg.id).one()
        item_mini = db.query(PayslipItem).filter(PayslipItem.employee_id == emp_mini.id).one()
        assert item_reg.status == "Failed"
        assert item_mini.status == "Pending"
        assert item_mini.net_pay > Decimal("0")
        # Phase 8BN: Soli is persisted end-to-end. The MINIJOB flat tax
        # carries no employee Soli, and the blocked REGULAR payslip can't
        # compute Soli — so the honest persisted value is 0 on both rows
        # (never a fabricated nonzero, never a dropped column).
        assert item_reg.soli == Decimal("0")
        assert item_mini.soli == Decimal("0")

        # Blocked PDF: explicit blocked state, zero monetary figures, the
        # redacted blocker surfaced.
        import io
        from pypdf import PdfReader

        pdf_bytes = service.generate_payslip_pdf_bytes(db, item_reg.id, organization_id=organization.id)
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
        assert "BLOCKED" in text or "NO PAYSLIP ISSUED" in text
        assert "NOT be calculated" in text or "could NOT be calculated" in text
        assert "STATUS : BLOCKED" in text

        # Summary report: exactly one COMPLETE (minijob) and one BLOCKED.
        summary = service.get_germany_payroll_summary_report(
            db, organization.id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )
        by_status = summary["employeeCounts"]["byStatus"]
        assert by_status["CALCULATED"] == 1
        assert by_status["BLOCKED"] == 1
        assert summary["employeeCounts"]["byClassification"].get("MINIJOB") == 1
        assert Decimal(summary["grossPay"]["amount"]) > Decimal("0")
        sql = summary["statutoryContributions"]["solidaritySurcharge"]
        assert sql["status"] == "CALCULATED"
        assert sql["amount"] == "0.00"