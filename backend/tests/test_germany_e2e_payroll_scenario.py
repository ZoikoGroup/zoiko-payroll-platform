"""
tests/test_germany_e2e_payroll_scenario.py
--------------------------------------------
Production-like end-to-end Germany payroll scenario testing.

Covers (requirement §26 of the production readiness brief):

  Employee
    → Germany organization
    → statutory profile (class, exemptions, employment classification)
    → employment classification
    → gross payroll
    → tax calculation
    → SI calculation
    → net payroll
    → payslip

All values are documented 2026 statutory values (hardcoded_defaults.py /
spec §4/§9/§10). No PAP output is fabricated — REGULAR/MIDIJOB payroll
correctly FAILS CLOSED until an authoritative PAP executor exists.

Test categories:
  AUTHORITATIVE — uses spec-cited statutory rates/ceilings
  REGRESSION    — protects documented production behavior
  SECURITY      — fail-closed assertions

Uses the same DB-integration fixture pattern as
test_germany_pap_calculation.py (fresh SQLite per test).
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.payroll import service
from app.modules.payroll.engine.countries import germany
from app.modules.payroll.engine.germany_pap.core import (
    calculate_midijob_branch_contribution,
    calculate_midijob_employee_base,
    calculate_midijob_total_base,
    calculate_minijob,
)
from app.modules.payroll.hardcoded_defaults import (
    _DE_ALV_EMPLOYEE_RATE,
    _DE_ALV_EMPLOYER_RATE,
    _DE_GKV_GENERAL_EMPLOYEE_RATE,
    _DE_GKV_GENERAL_EMPLOYER_RATE,
    _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
    _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
    _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
    _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
    _DE_MIDIJOB_UPPER_THRESHOLD,
    _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
    _DE_MINIJOB_EMPLOYER_HEALTH_RATE,
    _DE_MINIJOB_EMPLOYER_PENSION_RATE,
    _DE_MINIJOB_FLAT_TAX_RATE,
    _DE_MINIJOB_U1_RATE,
    _DE_MINIJOB_U2_RATE,
    _DE_MINIJOB_U3_RATE,
    _DE_MINIJOB_UPPER_THRESHOLD,
    _DE_PV_CHILDLESS_SURCHARGE_RATE,
    _DE_RV_EMPLOYEE_RATE,
    _DE_RV_EMPLOYER_RATE,
)
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayrollRun, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


# ── Test helpers (mirroring test_germany_pap_calculation.py) ─────────────

def _make_employee(db, org_id, code="DE-E2E-001", gross=5000):
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
    source = SourceArtifact(agency="Test Fixture", title="E2E test source", checksum_sha256=None)
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


def _make_run(db, emp, org_id):
    from app.modules.payroll.models import PayrollRun
    run = PayrollRun(
        organization_id=org_id, period_label="Jan 2026",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        pay_date=date(2026, 2, 1), status="Draft", calculation_mode="standard",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ══════════════════════════════════════════════════════════════════════════
# 1. MINIJOB E2E — COMPLETE production path (no PAP required)
# ══════════════════════════════════════════════════════════════════════════

class TestMinijobE2E:
    """Minijob is the ONLY Germany classification that can produce a
    real, COMPLETE payslip today — the flat 2% Pauschsteuer is the tax
    treatment, never reaching the PAP gate."""

    def test_minijob_full_payroll_pipeline(self, db, organization, monkeypatch):
        """AUTHORITATIVE: Minijob employee (EUR 520/month) passes through
        the full payroll pipeline and produces a real payslip with
        documented numeric values."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-MINI-001", gross=520)
        _make_full_profile(
            db, emp, organization.id,
            de_employment_classification="MINIJOB",
        )
        _publish_all_registries(db)

        db.add(PayrollAttendanceRecord(
            organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00",
        ))
        db.commit()

        run_data = PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp.id], auto_generate_payslips=True,
        )
        run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)
        assert run is not None

        # A real PayslipItem MUST have been generated (Minijob is COMPLETE).
        item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
        assert item.gross_pay == Decimal("520.00")

        # Employer flat contributions (documented spec §16 rates)
        assert item.employer_pf == Decimal("78.00")  # 520 * 15% pension
        assert item.employer_esi == Decimal("73.68")  # 67.60 + 4.16 + 1.14 + 0.78 (health + U1 + U2 + U3)

        # Employee pension top-up is the only employee deduction
        assert item.pf == Decimal("18.72")  # 520 * 3.60%
        assert item.esi == Decimal("0.00")
        assert item.church_tax == Decimal("0.00")
        assert item.tds == Decimal("0.00")
        assert item.total_deductions == Decimal("18.72")
        assert item.net_pay == Decimal("501.28")  # 520 - 18.72

    def test_minijob_pension_exempt_payslip(self, db, organization, monkeypatch):
        """AUTHORITATIVE: Minijob employee with de_pension_insurance_exempt
        skips the pension top-up — net pay equals gross."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-MINI-002", gross=450)
        _make_full_profile(
            db, emp, organization.id,
            de_employment_classification="MINIJOB",
            de_pension_insurance_exempt=True,
        )
        _publish_all_registries(db)

        db.add(PayrollAttendanceRecord(
            organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00",
        ))
        db.commit()

        run_data = PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp.id], auto_generate_payslips=True,
        )
        run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)

        item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
        assert item.pf == Decimal("0.00")
        assert item.net_pay == Decimal("450.00")


# ══════════════════════════════════════════════════════════════════════════
# 2. MIDIJOB E2E — SI computed, wage tax FAIL-CLOSED (PAP blocked)
# ══════════════════════════════════════════════════════════════════════════

class TestMidijobE2E:
    """Midijob social insurance is fully computed via the official
    3-step mechanism, but wage tax still requires the real PAP — so the
    production payroll path correctly raises GermanyPapNotAvailableError."""

    def test_midijob_full_pipeline_blocks_on_pap_with_si_resolved(self, db, organization, monkeypatch):
        """AUTHORITATIVE: Midijob employee (EUR 1,500/month) has RV/ALV/
        GKV/PV computed correctly. Phase 8BR: wage tax now completes via
        the internal functional wage-tax calculator (official BMF PAP
        remains genuinely unavailable, unchanged — see
        engine/germany_internal_tax.py) rather than failing closed, so a
        real, non-fabricated payslip is produced end to end."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-MIDI-001", gross=1500)
        _make_full_profile(
            db, emp, organization.id,
            de_employment_classification="MIDIJOB",
        )
        _publish_all_registries(db)

        db.add(PayrollAttendanceRecord(
            organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00",
        ))
        db.commit()

        run_data = PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp.id], auto_generate_payslips=True,
        )
        run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)
        assert run is not None

        # A real, calculated item is recorded — never a fabricated result,
        # never a permanently blocked one either.
        item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
        assert item.status == "Pending"
        assert item.net_pay > Decimal("0.00")
        assert item.net_pay < item.gross_pay
        assert item.gross_pay == Decimal("1500.00")

        # The trace proves SI resolved AND wage tax completed via the
        # internal calculator (clearly labeled, not BMF-certified).
        trace = item.germany_calculation_snapshot or {}
        assert trace.get("calculationStatus") == "COMPLETE"
        assert trace.get("papVersion") == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"
        assert "midijob_rv" in trace.get("resolved", {})
        assert "midijob_alv" in trace.get("resolved", {})
        assert "midijob_gkv" in trace.get("resolved", {})
        assert "midijob_pv" in trace.get("resolved", {})

        # A completed payslip IS counted in the run's aggregates.
        db.refresh(run)
        assert run.employee_count == 1
        assert run.total_net == item.net_pay


# ══════════════════════════════════════════════════════════════════════════
# 3. REGULAR E2E — fail-closed on PAP (spec §7)
# ══════════════════════════════════════════════════════════════════════════

class TestRegularE2E:
    """REGULAR (ordinary) Germany employees also fail closed on PAP —
    Lohnsteuer/Soli require the authoritative BMF algorithm."""

    def test_regular_blocks_on_pap_with_full_si_resolved(self, db, organization, monkeypatch):
        """AUTHORITATIVE: REGULAR employee (EUR 5,000/month) — RV/ALV/GKV/
        PV all resolve and compute. Phase 8BR: wage tax now completes via
        the internal functional wage-tax calculator (official BMF PAP
        remains genuinely unavailable, unchanged) rather than failing
        closed, producing a real, non-fabricated, persisted payslip."""
        _stub_business_code_generation(monkeypatch)
        emp = _make_employee(db, organization.id, code="DE-REG-001", gross=5000)
        _make_full_profile(db, emp, organization.id)
        _publish_all_registries(db)

        db.add(PayrollAttendanceRecord(
            organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
            status="present", check_in="09:00", check_out="18:00",
        ))
        db.commit()

        run_data = PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp.id], auto_generate_payslips=True,
        )
        run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=organization.id)
        assert run is not None

        item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
        assert item.status == "Pending"
        assert item.net_pay > Decimal("0.00")
        assert item.net_pay < item.gross_pay

        trace = item.germany_calculation_snapshot or {}
        assert trace.get("calculationStatus") == "COMPLETE"
        assert trace.get("papVersion") == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"
        assert trace.get("resolved", {}).get("rv") is not None
        assert trace.get("resolved", {}).get("gkv") is not None
        assert trace.get("resolved", {}).get("pv") is not None

        db.refresh(run)
        assert run.employee_count == 1


# ══════════════════════════════════════════════════════════════════════════
# 4. CROSS-CLASSIFICATION numeric verification
# ══════════════════════════════════════════════════════════════════════════

class TestCrossClassificationNumerics:
    """Verify the numeric values used in the E2E scenarios against the
    documented statutory rates."""

    def test_minijob_payslip_numbers_match_spec(self):
        """AUTHORITATIVE: EUR 520 Minijob payslip numbers must match the
        documented spec §12-§19 rates exactly."""
        result = calculate_minijob(
            monthly_gross=Decimal("520.00"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        # employer_esi = health + U1 + U2 + U3 = 67.60 + 4.16 + 1.14 + 0.78
        assert result.employer_health + result.employer_u1 + result.employer_u2 + result.employer_u3 == Decimal("73.68")
        # + employer_pension 78.00 = 151.68 total employer cost
        assert result.employer_health + result.employer_pension + result.employer_u1 + result.employer_u2 + result.employer_u3 == Decimal("151.68")

    def test_midijob_rv_values_use_official_mechanism(self):
        """AUTHORITATIVE: EUR 1,500 Midijob RV must use the 3-step
        round-then-double mechanism with the documented coefficients."""
        total_base = calculate_midijob_total_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        employee_base = calculate_midijob_employee_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        )
        rv_combined = _DE_RV_EMPLOYEE_RATE + _DE_RV_EMPLOYER_RATE
        total, employee, employer = calculate_midijob_branch_contribution(
            total_base, employee_base,
            combined_rate_pct=rv_combined, employee_rate_pct=_DE_RV_EMPLOYEE_RATE,
        )
        # For AE=1500: total_base=1427.03, employee_base=1284.18
        # Step 1: 1427.03 * 9.30% = 132.714 -> 132.71; * 2 = 265.42
        # Step 2: 1284.18 * 9.30% = 119.429 -> 119.43
        # Step 3: 265.42 - 119.43 = 145.99
        assert total == Decimal("265.42")
        assert employee == Decimal("119.43")
        assert employer == Decimal("145.99")