"""
tests/test_germany_pap_calculation.py
---------------------------------------
Phase 7 (docs/PHASE_7_GERMANY_PAP_CALCULATION_INTEGRATION_REPORT.md) —
coverage for the BMF PAP execution scaffolding and the real, branch-aware
RV/ALV/GKV/PV social-insurance calculations that now sit behind
engine/countries/germany.py's production `calculate()`.

No real BMF PAP source exists anywhere in this repository (confirmed at
the start of this phase) — every test that reaches the PAP step therefore
asserts the deterministic GERMANY_PAP_NOT_AVAILABLE block, never a
fabricated Lohnsteuer/Soli/Kirchensteuer result. This is the CORRECT,
intended outcome per this phase's "Absolute PAP Rule," not a gap in test
coverage.

Two layers of coverage:
1. Pure unit tests against engine/countries/germany_pap.py's functions —
   no DB, lightweight fake objects standing in for ORM rows (same style
   as test_engine_standard.py's Rate/Slab dataclasses).
2. DB-integration tests (db/organization fixtures) exercising the full
   orchestration in germany.calculate() via real
   EmployeeStatutoryProfile / GermanyContributionCeiling /
   GermanyHealthFund / GermanyPvConfiguration rows, and the real payroll
   run pipeline (service.create_payroll_run) end to end.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, GermanyCalculationBlockedException
from app.modules.payroll import service
from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import germany
from app.modules.payroll.engine.germany_pap.core import (
    CHURCH_TAX_LAND_RATES,
    GermanyCalculationTrace,
    GermanyCeilingNotAvailableError,
    GermanyHealthFundNotAvailableError,
    GermanyPapNotAvailableError,
    GermanyPvConfigurationNotAvailableError,
    GermanyStatutoryProfileMissingError,
    GermanyMinijobThresholdViolationError,
    GermanyMidijobThresholdViolationError,
    build_pap_input,
    calculate_alv,
    calculate_employer_insolvency_levy,
    calculate_gkv,
    calculate_pv,
    calculate_rv,
    check_gkv_coverage_threshold,
    check_main_secondary_employment_consistency,
    resolve_church_tax_rate,
    resolve_pap_executor,
    resolve_pv_child_category,
    trace_tax_data_used,
)
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayrollRun, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
    PayslipItemCreate,
)

MONTHS_PER_YEAR = Decimal("12")


@dataclass
class _FakeCeiling:
    annual_ceiling: Decimal
    id: int = 1


@dataclass
class _FakeHealthFund:
    supplementary_rate_pct: Decimal
    id: int = 1
    health_fund_id: str = "TEST-FUND"


@dataclass
class _FakePvConfig:
    is_saxony: bool
    standard_employee_rate_pct: Decimal = Decimal("2.4000")
    employer_rate_pct: Decimal = Decimal("1.8000")
    saxony_employee_rate_pct: Decimal = Decimal("2.9000")
    saxony_employer_rate_pct: Decimal = Decimal("1.3000")
    id: int = 1


@dataclass
class _FakeChurchTaxException:
    """Phase 8AP — minimal stand-in for GermanyChurchTaxException; only
    the one attribute germany.py's engine branch reads."""
    exception_rate_pct: Decimal


@dataclass
class _FakeProfile:
    """Minimal stand-in for EmployeeStatutoryProfile — only the attributes
    build_pap_input/resolve_pv_child_category/germany.calculate() read."""
    id: int = 1
    effective_from: date = date(2026, 1, 1)
    de_tax_class: str = "I"
    de_factor: Decimal = None
    de_child_count: int = 0
    de_childless: bool = True
    de_saxony: bool = False
    de_church_tax_liable: bool = False
    de_church_tax_land: str = None
    de_health_insurance_status: str = "PUBLIC"
    de_health_fund_code: str = "TEST-FUND"
    de_pension_insurance_exempt: bool = False
    de_unemployment_insurance_exempt: bool = False
    de_employment_classification: str = "REGULAR"
    # Phase 8N — ELStAM / employee-withholding-state completion.
    de_zkf_override: Decimal = None
    de_jfreib: Decimal = None
    de_lzzfreib: Decimal = None
    de_jhinzu: Decimal = None
    de_lzzhinzu: Decimal = None
    de_pkpv: Decimal = None
    de_pkpvagz: Decimal = None
    de_main_employment: bool = None


# ── PAP input contract / executor (pure, no DB) ─────────────────────────

def test_build_pap_input_maps_profile_fields():
    profile = _FakeProfile(de_tax_class="iii", de_factor=None)
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("5000"), kvz_rate=Decimal("1.7"))
    assert pap_input.stkl == "III"
    assert pap_input.af is False
    assert pap_input.re4_cents == 500000
    assert pap_input.kvz == Decimal("1.7")


def test_build_pap_input_factor_method_class_iv():
    profile = _FakeProfile(de_tax_class="IV", de_factor=Decimal("0.8"))
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    assert pap_input.af is True
    assert pap_input.f == Decimal("0.8")


# ── Phase 8N: ELStAM / employee-withholding-state completion ────────────

def test_build_pap_input_zkf_defaults_to_child_count_when_no_override():
    profile = _FakeProfile(de_child_count=2, de_zkf_override=None)
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    assert pap_input.zkf == Decimal("2")


def test_build_pap_input_zkf_uses_override_when_set():
    """Spec §5/§6 split-custody case — de_zkf_override (can be a
    half-integer) takes precedence over de_child_count, which keeps
    driving the PV branch unchanged (Phase 8K's own distinction)."""
    profile = _FakeProfile(de_child_count=2, de_childless=False, de_zkf_override=Decimal("0.5"))
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    assert pap_input.zkf == Decimal("0.5")
    # PV/PVA still derive from de_child_count, untouched by the override.
    assert resolve_pv_child_category(profile) == "2"
    assert pap_input.pva == 2


def test_build_pap_input_allowance_addback_and_private_insurance_mapped_to_cents():
    profile = _FakeProfile(
        de_jfreib=Decimal("1200.00"), de_lzzfreib=Decimal("100.00"),
        de_jhinzu=Decimal("600.50"), de_lzzhinzu=Decimal("50.00"),
        de_pkpv=Decimal("350.00"), de_pkpvagz=Decimal("150.00"),
    )
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    assert pap_input.jfreib_cents == 120000
    assert pap_input.lzzfreib_cents == 10000
    assert pap_input.jhinzu_cents == 60050
    assert pap_input.lzzhinzu_cents == 5000
    assert pap_input.pkpv_cents == 35000
    assert pap_input.pkpvagz_cents == 15000


def test_build_pap_input_allowance_addback_defaults_to_zero_when_unset():
    profile = _FakeProfile()
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    assert pap_input.jfreib_cents == 0
    assert pap_input.lzzfreib_cents == 0
    assert pap_input.jhinzu_cents == 0
    assert pap_input.lzzhinzu_cents == 0
    assert pap_input.pkpv_cents == 0
    assert pap_input.pkpvagz_cents == 0


def test_trace_tax_data_used_records_new_fields():
    profile = _FakeProfile(
        de_jfreib=Decimal("1200.00"), de_pkpv=Decimal("350.00"), de_main_employment=True,
    )
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    trace = GermanyCalculationTrace()
    trace_tax_data_used(trace, profile, pap_input)
    assert trace.jfreib_used == "1200.00"
    assert trace.pkpv_used == "350.00"
    assert trace.main_employment_used is True
    assert trace.lzzfreib_used is None  # not recorded on this profile — never fabricated as "0.00"


def test_main_secondary_employment_consistency_warns_for_main_plus_class_vi():
    warning = check_main_secondary_employment_consistency(tax_class="VI", is_main_employment=True)
    assert warning is not None
    assert "VI" in warning


def test_main_secondary_employment_consistency_silent_for_secondary_class_vi():
    assert check_main_secondary_employment_consistency(tax_class="VI", is_main_employment=False) is None
    assert check_main_secondary_employment_consistency(tax_class="VI", is_main_employment=None) is None


def test_main_secondary_employment_consistency_silent_for_non_vi_main():
    assert check_main_secondary_employment_consistency(tax_class="III", is_main_employment=True) is None


# ── Phase 8T: SONSTB / bonus routing ─────────────────────────────────────

def test_build_pap_input_no_sonstb_defaults_to_zero_and_re4_is_full_gross():
    profile = _FakeProfile()
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("5000"), kvz_rate=Decimal("1.0"))
    assert pap_input.sonstb_cents == 0
    assert pap_input.jre4_cents == 0
    assert pap_input.re4_cents == 500000


def test_build_pap_input_with_sonstb_splits_re4_and_routes_bonus():
    """Spec §5/§15: SONSTB is a SEPARATE PAP input from RE4 — a bonus must
    not be double-counted into both."""
    profile = _FakeProfile()
    pap_input = build_pap_input(
        profile=profile, gross_monthly=Decimal("6000"), kvz_rate=Decimal("1.0"), sonstb=Decimal("1000"),
    )
    assert pap_input.sonstb_cents == 100000
    assert pap_input.re4_cents == 500000  # 6000 - 1000 = 5000 regular wage
    # JRE4 = 12x the REGULAR (non-SONSTB) monthly wage, only when a bonus exists this period.
    assert pap_input.jre4_cents == 500000 * 12


def test_build_pap_input_zero_sonstb_explicit_is_same_as_none():
    profile = _FakeProfile()
    a = build_pap_input(profile=profile, gross_monthly=Decimal("5000"), kvz_rate=Decimal("1.0"), sonstb=Decimal("0"))
    b = build_pap_input(profile=profile, gross_monthly=Decimal("5000"), kvz_rate=Decimal("1.0"), sonstb=None)
    assert a.sonstb_cents == b.sonstb_cents == 0
    assert a.jre4_cents == b.jre4_cents == 0
    assert a.re4_cents == b.re4_cents == 500000


def test_trace_tax_data_used_records_sonstb_from_pap_input_not_reguessed():
    profile = _FakeProfile()
    pap_input = build_pap_input(
        profile=profile, gross_monthly=Decimal("6000"), kvz_rate=Decimal("1.0"), sonstb=Decimal("1000"),
    )
    trace = GermanyCalculationTrace()
    trace_tax_data_used(trace, profile, pap_input)
    assert trace.sonstb_used == "1000"
    assert trace.regular_wage_used == "5000"
    assert trace.jre4_used == "60000"


def test_trace_tax_data_used_jre4_none_when_no_bonus():
    profile = _FakeProfile()
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("5000"), kvz_rate=Decimal("1.0"))
    trace = GermanyCalculationTrace()
    trace_tax_data_used(trace, profile, pap_input)
    assert trace.sonstb_used == "0"
    assert trace.jre4_used is None


def test_calculate_end_to_end_routes_bonus_via_sonstb_and_reduces_re4():
    """End-to-end via germany.calculate(): a German employee with a bonus
    this period has it routed through SONSTB, not blindly summed into RE4."""
    profile = _FakeProfile()
    result = germany.calculate(_ctx(gross=Decimal("6000"), germany_statutory_profile=profile, germany_sonstb=Decimal("1000")))
    snap = result["_germany_calculation_snapshot"]
    assert snap["sonstbUsed"] == "1000"
    assert snap["regularWageUsed"] == "5000"


def test_calculate_end_to_end_no_bonus_field_defaults_sonstb_to_zero():
    """PayrollContext.germany_sonstb is None by default (every non-German
    call site, and every Germany call site with no bonus this period) —
    calculate() must not crash and must trace a real, explicit zero."""
    profile = _FakeProfile()
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert snap["sonstbUsed"] == "0"
    assert snap["regularWageUsed"] == "5000"


def test_field_sources_documents_every_field():
    profile = _FakeProfile()
    pap_input = build_pap_input(profile=profile, gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    sources = pap_input.field_sources()
    for f in pap_input.__dataclass_fields__:
        assert f in sources, f"PapInputContract.{f} has no documented source"


def test_resolve_pap_executor_no_asset_raises_with_clear_reason():
    executor = resolve_pap_executor(None)
    pap_input = build_pap_input(profile=_FakeProfile(), gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    with pytest.raises(GermanyPapNotAvailableError, match="No PUBLISHED Germany PAP asset"):
        executor.execute(pap_input)


def test_resolve_pap_executor_asset_exists_but_no_interpreter_raises():
    @dataclass
    class _FakeAsset:
        id: int = 99
        pap_version: str = "2026-11-12-final"
    executor = resolve_pap_executor(_FakeAsset())
    pap_input = build_pap_input(profile=_FakeProfile(), gross_monthly=Decimal("4000"), kvz_rate=Decimal("1.0"))
    with pytest.raises(GermanyPapNotAvailableError, match="no PAP execution engine is implemented"):
        executor.execute(pap_input)


# ── Church tax Land table ────────────────────────────────────────────────

def test_church_tax_rate_baden_wurttemberg_and_bavaria_are_8_percent():
    assert resolve_church_tax_rate("DE-BW") == Decimal("8")
    assert resolve_church_tax_rate("DE-BY") == Decimal("8")


def test_church_tax_rate_other_laender_are_9_percent():
    for code in ("DE-BE", "DE-NW", "DE-SN", "DE-TH"):
        assert resolve_church_tax_rate(code) == Decimal("9")


def test_church_tax_rate_all_16_laender_present():
    assert len(CHURCH_TAX_LAND_RATES) == 16


def test_church_tax_rate_missing_land_raises():
    with pytest.raises(GermanyStatutoryProfileMissingError):
        resolve_church_tax_rate(None)


def test_church_tax_rate_unrecognized_land_raises():
    with pytest.raises(GermanyStatutoryProfileMissingError):
        resolve_church_tax_rate("DE-XX")


# ── PV child-category resolution ─────────────────────────────────────────

def test_pv_child_category_childless_flag_overrides_count():
    profile = _FakeProfile(de_childless=True, de_child_count=3)
    assert resolve_pv_child_category(profile) == "CHILDLESS"


@pytest.mark.parametrize("count,expected", [(0, "CHILDLESS"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5_PLUS"), (9, "5_PLUS")])
def test_pv_child_category_bucketing(count, expected):
    profile = _FakeProfile(de_childless=False, de_child_count=count)
    assert resolve_pv_child_category(profile) == expected


def test_pv_child_category_raises_when_both_unset():
    profile = _FakeProfile(de_childless=None, de_child_count=None)
    with pytest.raises(GermanyStatutoryProfileMissingError):
        resolve_pv_child_category(profile)


# ── RV (pension insurance) ───────────────────────────────────────────────

def test_calculate_rv_exempt_employee_is_zero():
    employee, employer = calculate_rv(
        annual_gross=Decimal("120000"), ceiling_rv_alv=_FakeCeiling(Decimal("101400")), rate_map={},
        exempt=True, rv_employee_default=Decimal("9.30"), rv_employer_default=Decimal("9.30"),
        months_per_year=MONTHS_PER_YEAR,
    )
    assert employee == Decimal("0")
    assert employer == Decimal("0")


def test_calculate_rv_capped_at_ceiling():
    employee, employer = calculate_rv(
        annual_gross=Decimal("120000"), ceiling_rv_alv=_FakeCeiling(Decimal("101400")), rate_map={},
        exempt=False, rv_employee_default=Decimal("9.30"), rv_employer_default=Decimal("9.30"),
        months_per_year=MONTHS_PER_YEAR,
    )
    # (101400 * 9.30%) / 12 = 785.85
    assert employee == Decimal("785.85")
    assert employer == Decimal("785.85")


def test_calculate_rv_no_ceiling_raises():
    with pytest.raises(GermanyCeilingNotAvailableError):
        calculate_rv(
            annual_gross=Decimal("60000"), ceiling_rv_alv=None, rate_map={}, exempt=False,
            rv_employee_default=Decimal("9.30"), rv_employer_default=Decimal("9.30"), months_per_year=MONTHS_PER_YEAR,
        )


# ── ALV (unemployment insurance) ─────────────────────────────────────────

def test_calculate_alv_exempt_employee_is_zero():
    employee, employer = calculate_alv(
        annual_gross=Decimal("60000"), ceiling_rv_alv=_FakeCeiling(Decimal("101400")), rate_map={},
        exempt=True, alv_employee_default=Decimal("1.30"), alv_employer_default=Decimal("1.30"),
        months_per_year=MONTHS_PER_YEAR,
    )
    assert employee == Decimal("0") and employer == Decimal("0")


def test_calculate_alv_below_ceiling_uses_full_gross():
    employee, employer = calculate_alv(
        annual_gross=Decimal("60000"), ceiling_rv_alv=_FakeCeiling(Decimal("101400")), rate_map={},
        exempt=False, alv_employee_default=Decimal("1.30"), alv_employer_default=Decimal("1.30"),
        months_per_year=MONTHS_PER_YEAR,
    )
    # (60000 * 1.30%) / 12 = 65.00
    assert employee == Decimal("65.00") and employer == Decimal("65.00")


# ── GKV (health insurance) ───────────────────────────────────────────────

def test_calculate_gkv_private_employee_is_zero():
    employee, employer, supplementary = calculate_gkv(
        annual_gross=Decimal("72000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")), rate_map={},
        health_insurance_status="PRIVATE", health_fund=None,
        gkv_employee_default=Decimal("7.30"), gkv_employer_default=Decimal("7.30"), months_per_year=MONTHS_PER_YEAR,
    )
    assert employee == Decimal("0") and employer == Decimal("0") and supplementary == Decimal("0")


def test_calculate_gkv_missing_status_raises():
    with pytest.raises(GermanyStatutoryProfileMissingError):
        calculate_gkv(
            annual_gross=Decimal("60000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")), rate_map={},
            health_insurance_status=None, health_fund=None,
            gkv_employee_default=Decimal("7.30"), gkv_employer_default=Decimal("7.30"), months_per_year=MONTHS_PER_YEAR,
        )


def test_calculate_gkv_public_missing_fund_raises_average_rate_warning():
    with pytest.raises(GermanyHealthFundNotAvailableError, match="2.9%"):
        calculate_gkv(
            annual_gross=Decimal("60000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")), rate_map={},
            health_insurance_status="PUBLIC", health_fund=None,
            gkv_employee_default=Decimal("7.30"), gkv_employer_default=Decimal("7.30"), months_per_year=MONTHS_PER_YEAR,
        )


def test_calculate_gkv_public_with_fund_computes_general_plus_supplementary():
    employee, employer, supplementary = calculate_gkv(
        annual_gross=Decimal("60000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")), rate_map={},
        health_insurance_status="PUBLIC", health_fund=_FakeHealthFund(Decimal("1.7000")),
        gkv_employee_default=Decimal("7.30"), gkv_employer_default=Decimal("7.30"), months_per_year=MONTHS_PER_YEAR,
    )
    # general: (60000 * 7.30%)/12 = 365.00 each side
    # supplementary: full 1.7% split 50/50 -> 0.85% each -> (60000*0.85%)/12 = 42.50 each
    assert employee == Decimal("407.50")
    assert employer == Decimal("407.50")
    assert supplementary == Decimal("1.7000")


def test_calculate_gkv_capped_at_ceiling():
    employee, employer, _ = calculate_gkv(
        annual_gross=Decimal("120000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")), rate_map={},
        health_insurance_status="PUBLIC", health_fund=_FakeHealthFund(Decimal("0")),
        gkv_employee_default=Decimal("7.30"), gkv_employer_default=Decimal("7.30"), months_per_year=MONTHS_PER_YEAR,
    )
    # (69750 * 7.30%) / 12 = 424.3125 -> rounds to 424.31
    assert employee == Decimal("424.31")


# ── Employer insolvency levy (U3), spec §14 — Phase 8M ──────────────────

def test_calculate_employer_insolvency_levy_is_flat_rate_of_gross():
    levy = calculate_employer_insolvency_levy(Decimal("5000.00"), Decimal("0.15"))
    # 5000 * 0.15% = 7.50
    assert levy == Decimal("7.50")


def test_calculate_employer_insolvency_levy_zero_gross_is_zero():
    assert calculate_employer_insolvency_levy(Decimal("0"), Decimal("0.15")) == Decimal("0.00")


# ── JAEG coverage-status warning, spec §9 / acceptance criterion #20 ────

def test_jaeg_warning_none_when_public():
    assert check_gkv_coverage_threshold(
        health_insurance_status="PUBLIC", annual_gross=Decimal("50000"), jaeg_annual_threshold=Decimal("77400"),
    ) is None


def test_jaeg_warning_none_when_private_above_threshold():
    assert check_gkv_coverage_threshold(
        health_insurance_status="PRIVATE", annual_gross=Decimal("90000"), jaeg_annual_threshold=Decimal("77400"),
    ) is None


def test_jaeg_warning_fires_when_private_at_or_below_threshold():
    warning = check_gkv_coverage_threshold(
        health_insurance_status="PRIVATE", annual_gross=Decimal("60000"), jaeg_annual_threshold=Decimal("77400"),
    )
    assert warning is not None
    assert "JAEG" in warning
    # Never a hard reject — see check_gkv_coverage_threshold's own docstring.
    assert "not blocked automatically".upper() in warning.upper() or "not blocked" in warning.lower()


# ── PV (long-term care insurance) ────────────────────────────────────────

def test_calculate_pv_standard_split():
    employee, employer = calculate_pv(
        annual_gross=Decimal("60000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")),
        pv_configuration=_FakePvConfig(is_saxony=False), months_per_year=MONTHS_PER_YEAR,
    )
    # (60000 * 2.4%)/12 = 120.00 ; employer (60000*1.8%)/12 = 90.00
    assert employee == Decimal("120.00")
    assert employer == Decimal("90.00")


def test_calculate_pv_saxony_split_differs():
    employee, employer = calculate_pv(
        annual_gross=Decimal("60000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")),
        pv_configuration=_FakePvConfig(is_saxony=True), months_per_year=MONTHS_PER_YEAR,
    )
    # (60000 * 2.9%)/12 = 145.00 ; employer (60000*1.3%)/12 = 65.00
    assert employee == Decimal("145.00")
    assert employer == Decimal("65.00")


def test_calculate_pv_missing_configuration_raises():
    with pytest.raises(GermanyPvConfigurationNotAvailableError):
        calculate_pv(
            annual_gross=Decimal("60000"), ceiling_gkv_pv=_FakeCeiling(Decimal("69750")),
            pv_configuration=None, months_per_year=MONTHS_PER_YEAR,
        )


def test_calculate_pv_missing_ceiling_raises():
    with pytest.raises(GermanyCeilingNotAvailableError):
        calculate_pv(
            annual_gross=Decimal("60000"), ceiling_gkv_pv=None,
            pv_configuration=_FakePvConfig(is_saxony=False), months_per_year=MONTHS_PER_YEAR,
        )


# ── germany.calculate() orchestration (pure ctx, no DB) ──────────────────

def _ctx(**overrides):
    kwargs = dict(
        gross=Decimal("5000"), basic=Decimal("5000"), country="DE",
        germany_statutory_profile=_FakeProfile(),
        germany_pap_asset=None,
        germany_health_fund=_FakeHealthFund(Decimal("1.7000")),
        germany_ceiling_gkv_pv=_FakeCeiling(Decimal("69750")),
        germany_ceiling_rv_alv=_FakeCeiling(Decimal("101400")),
        germany_pv_configuration=_FakePvConfig(is_saxony=False),
    )
    kwargs.update(overrides)
    return PayrollContext(**kwargs)


def test_calculate_raises_when_no_statutory_profile():
    with pytest.raises(GermanyStatutoryProfileMissingError):
        germany.calculate(_ctx(germany_statutory_profile=None))


def test_calculate_raises_for_minijob_classification_with_out_of_range_earnings():
    """Phase 8I: Minijob/Midijob are now genuinely implemented (see
    test_germany_minijob_midijob.py) — this test's own default `_ctx()`
    gross (5,000/month) is far outside the Minijob corridor, so it now
    correctly exercises the NEW, more specific threshold-violation guard
    rather than the old "not implemented" block. Employment classification
    is never silently corrected by the engine."""
    profile = _FakeProfile(de_employment_classification="MINIJOB")
    with pytest.raises(GermanyMinijobThresholdViolationError):
        germany.calculate(_ctx(germany_statutory_profile=profile))


def test_calculate_raises_for_midijob_classification_with_out_of_range_earnings():
    """Phase 8I: same reasoning as the Minijob test above — 5,000/month is
    outside the Midijob corridor (603.01-2,000.00) too."""
    profile = _FakeProfile(de_employment_classification="MIDIJOB")
    with pytest.raises(GermanyMidijobThresholdViolationError):
        germany.calculate(_ctx(germany_statutory_profile=profile))


def test_calculate_completes_via_internal_tax_calculator_with_everything_resolved():
    """Phase 8BR: with a full statutory profile, both ceilings, a health
    fund, and a PV configuration all resolved, the calculation now reaches
    COMPLETE via the internal functional wage-tax calculator (no certified
    BMF PAP asset exists, so the official path still isn't used — see
    test_calculate_falls_back_to_internal_tax_when_pap_unavailable below)
    — and the trace shows RV/ALV/GKV/PV/employer_levies all resolved, same
    as before this phase."""
    result = germany.calculate(_ctx())
    snap = result["_germany_calculation_snapshot"]
    assert snap["calculationStatus"] == "COMPLETE"
    assert {"rv", "alv", "gkv", "pv", "employer_levies"} <= set(snap["resolved"].keys())
    assert Decimal(snap["resolved"]["rv"]["employee"]) > 0
    # Phase 8M: U3 (Insolvenzumlage) now computed for REGULAR too (spec
    # §14 — a flat federal rate, not Minijob-specific); U1/U2/accident
    # insurance stay explicitly disclosed, never silently zero.
    assert Decimal(snap["resolved"]["employer_levies"]["u3_insolvency_levy"]) > 0
    assert snap["resolved"]["employer_levies"]["u1"] == "NOT_CONFIGURED — health-fund/tariff-specific rate not available"
    assert snap["accidentInsuranceStatus"] == "NOT_CONFIGURED — carrier-specific rate not available"
    # Phase 8BR: wage tax/Soli are real, non-fabricated, INTERNAL_FUNCTIONAL_REFERENCE numbers.
    assert result["tds"] > 0
    assert any("INTERNAL_FUNCTIONAL_REFERENCE" in w for w in snap["warnings"])


def test_calculate_falls_back_to_internal_tax_when_pap_unavailable():
    """The specific fallback mechanics: resolve_pap_executor() still
    always returns UnavailablePapExecutor (unchanged, official path still
    genuinely blocked) — germany.calculate() catches that specific
    GermanyPapNotAvailableError and completes via
    germany_internal_tax.InternalGermanyWageTaxCalculator instead."""
    executor = resolve_pap_executor(None)
    with pytest.raises(GermanyPapNotAvailableError):
        executor.execute(build_pap_input(profile=_FakeProfile(), gross_monthly=Decimal("5000"), kvz_rate=Decimal("1.0")))
    result = germany.calculate(_ctx())
    assert result["_germany_calculation_snapshot"]["papVersion"] == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"


def test_calculate_raises_ceiling_missing_before_pap():
    with pytest.raises(GermanyCeilingNotAvailableError):
        germany.calculate(_ctx(germany_ceiling_rv_alv=None))


def test_calculate_jaeg_warning_surfaces_on_trace_for_private_below_threshold():
    """Phase 8M: PRIVATE health-insurance status with annualized earnings
    (5,000 * 12 = 60,000) at/below the JAEG threshold (77,400) is not
    blocked (see check_gkv_coverage_threshold's own docstring for why this
    is advisory, not a hard reject) but must be visible on the trace for
    Tax Operations/QA review — never silently accepted."""
    profile = _FakeProfile(de_health_insurance_status="PRIVATE")
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert any("JAEG" in w for w in snap["warnings"])


def test_calculate_no_jaeg_warning_for_private_above_threshold():
    profile = _FakeProfile(de_health_insurance_status="PRIVATE")
    result = germany.calculate(_ctx(germany_statutory_profile=profile, gross=Decimal("8000")))
    snap = result["_germany_calculation_snapshot"]
    assert not any("JAEG" in w for w in snap["warnings"])


def test_calculate_main_secondary_warning_surfaces_on_trace():
    """Phase 8N: MAIN employment recorded alongside tax class VI is
    advisory, not blocking — but must reach the trace for QA review."""
    profile = _FakeProfile(de_tax_class="VI", de_main_employment=True)
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert any("VI" in w for w in snap["warnings"])
    assert snap["mainEmploymentUsed"] is True


def test_calculate_no_main_secondary_warning_for_secondary_class_vi():
    profile = _FakeProfile(de_tax_class="VI", de_main_employment=False)
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert not any("tax class is VI" in w for w in snap["warnings"])


def test_calculate_traces_new_elstam_fields_end_to_end():
    profile = _FakeProfile(
        de_jfreib=Decimal("1200.00"), de_pkpv=Decimal("350.00"), de_zkf_override=Decimal("0.5"),
    )
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert snap["jfreibUsed"] == "1200.00"
    assert snap["pkpvUsed"] == "350.00"
    assert snap["zkfUsed"] == "0.5"


def test_calculate_raises_health_fund_missing_before_pap():
    with pytest.raises(GermanyHealthFundNotAvailableError):
        germany.calculate(_ctx(germany_health_fund=None))


def test_calculate_raises_pv_configuration_missing_before_pap():
    with pytest.raises(GermanyPvConfigurationNotAvailableError):
        germany.calculate(_ctx(germany_pv_configuration=None))


def test_calculate_skips_gkv_and_pv_for_private_health_insurance():
    profile = _FakeProfile(de_health_insurance_status="PRIVATE")
    # PV configuration/health fund both None — must NOT block on either,
    # since a privately-insured employee needs neither.
    result = germany.calculate(_ctx(
        germany_statutory_profile=profile, germany_health_fund=None, germany_pv_configuration=None,
    ))
    snap = result["_germany_calculation_snapshot"]
    assert snap["resolved"]["gkv"]["employee"] == "0"
    assert "pv" not in snap["resolved"]


def test_calculate_church_tax_land_resolved_before_pap_block():
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land="DE-BY")
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert any("church tax Land rate: 8" in s for s in snap["steps"])
    assert result["church_tax"] > 0


def test_calculate_church_tax_missing_land_is_partial_not_blocked():
    """Phase 8BU (Part 21 — "remove unnecessary internal blocking"): a
    church-tax-liable employee whose Land is unresolved must NOT lose their
    entire payroll calculation over one unresolvable component. RV/ALV/GKV/
    PV and wage tax/Soli (independent of church tax) all still calculate as
    real, non-fabricated figures; only church_tax itself is forced to 0 and
    explicitly flagged as unavailable — never silently presented as "not
    liable"."""
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land=None)
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert snap["calculationStatus"] == "PARTIALLY_CALCULATED"
    assert snap["unavailableComponents"] == ["church_tax"]
    assert result["_germany_unavailable_components"] == ["church_tax"]
    # Church tax itself is the unavailable component — forced to 0, never
    # fabricated as a real figure.
    assert result["church_tax"] == Decimal("0")
    # Everything independent of church tax is still a real, calculated
    # figure — not discarded just because church tax couldn't resolve.
    assert result["employee_pf"] > 0
    assert result["employee_esi"] > 0
    assert result["tds"] > 0


def test_calculate_wage_tax_unavailable_is_partial_with_si_preserved():
    """Phase 8BU: a payroll date before this codebase's earliest verified
    internal §32a tariff (see germany_internal_tax._TARIFF_VERSIONS) makes
    wage tax/Soli/church tax genuinely unavailable — this must NOT discard
    the RV/ALV/GKV/PV social-insurance figures already computed earlier in
    the same calculation. net pay itself is a strategy-layer concern
    (engine/standard.py forces it to 0.00); this test covers only the
    country-calculator dict germany.calculate() returns."""
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land="DE-BY")
    result = germany.calculate(_ctx(
        germany_statutory_profile=profile, germany_payroll_date=date(2022, 12, 31),
    ))
    snap = result["_germany_calculation_snapshot"]
    assert snap["calculationStatus"] == "PARTIALLY_CALCULATED"
    assert set(snap["unavailableComponents"]) == {"wage_tax", "soli", "church_tax"}
    assert set(result["_germany_unavailable_components"]) == {"wage_tax", "soli", "church_tax"}
    # Wage tax/Soli/church tax are all unavailable — forced to 0, never a
    # fabricated real-looking figure.
    assert result["tds"] == Decimal("0")
    assert result["soli"] == Decimal("0")
    assert result["church_tax"] == Decimal("0")
    # Social insurance resolves BEFORE the wage-tax stage and is completely
    # independent of it — still real, still calculated.
    assert result["employee_pf"] > 0
    assert result["employee_esi"] > 0
    assert result["employer_pf"] > 0
    assert result["employer_esi"] > 0


# ── Phase 8AM church-tax EXCEPTION (Bad Wimpfen) engine wiring — added
# Phase 8AP after a forensic audit found ZERO test anywhere in this repo
# actually exercised germany.py's exception-aware branch (germany.py:686-701)
# or the "germany_church_tax_exception" context field end-to-end, despite
# Phase 8AM's own report claiming regression coverage. The lifecycle/CRUD
# for GermanyChurchTaxException WAS tested (test_germany_2026_registry_seed.py)
# — only the actual engine override behavior was not. ─────────────────────

def test_calculate_uses_church_tax_exception_rate_when_context_provides_one():
    """A resolved exception (however it got resolved — that's the
    service layer's job, tested separately) must override the ordinary
    Land rate in the actual calculation trace."""
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land="DE-BW")
    exception = _FakeChurchTaxException(exception_rate_pct=Decimal("9.00"))
    result = germany.calculate(_ctx(germany_statutory_profile=profile, germany_church_tax_exception=exception))
    snap = result["_germany_calculation_snapshot"]
    assert any("EXCEPTION" in s and "9" in s for s in snap["steps"]), (
        f"expected an exception-rate trace step mentioning 9%, got: {snap['steps']}"
    )
    assert not any("church tax Land rate: 8" in s for s in snap["steps"]), (
        "the ordinary 8% Baden-Württemberg Land rate must NOT be used once an exception is resolved"
    )


def test_calculate_ignores_absent_church_tax_exception_and_uses_ordinary_land_rate():
    """The overwhelmingly common case: no exception resolved (None) —
    byte-identical to pre-8AM behavior, re-pinned here explicitly against
    the SAME context shape the exception test above uses, not just the
    pre-existing test_calculate_church_tax_land_resolved_before_pap_block
    (which never even sets germany_church_tax_exception, so it can't by
    itself prove the None-case is handled — only that the field's absence
    from _ctx()'s defaults doesn't crash)."""
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land="DE-BW")
    result = germany.calculate(_ctx(germany_statutory_profile=profile, germany_church_tax_exception=None))
    snap = result["_germany_calculation_snapshot"]
    assert any("church tax Land rate: 8" in s for s in snap["steps"])
    assert not any("EXCEPTION" in s for s in snap["steps"])


def test_calculate_rv_alv_exempt_flags_honored_end_to_end():
    profile = _FakeProfile(de_pension_insurance_exempt=True, de_unemployment_insurance_exempt=True)
    result = germany.calculate(_ctx(germany_statutory_profile=profile))
    snap = result["_germany_calculation_snapshot"]
    assert snap["resolved"]["rv"]["employee"] == "0"
    assert snap["resolved"]["alv"]["employee"] == "0"


def test_legacy_simplified_calculator_still_importable_and_unused_by_production_path():
    """Confirms _calculate_legacy_simplified was retained (not deleted)
    and confirms `calculate` (the production entry point actually
    registered in engine/standard.py's _COUNTRY_CALC) is a different
    function object."""
    assert germany._calculate_legacy_simplified is not germany.calculate
    ctx = PayrollContext(gross=Decimal("5000"), basic=Decimal("5000"), country="DE", rate_map={}, slabs=[])
    result = germany._calculate_legacy_simplified(ctx)
    assert isinstance(result, dict)
    assert "employee_pf" in result


# ── DB-integration: full orchestration via real registries ──────────────

def _make_employee(db, org_id, code="DE-E2E-001"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=72000, basic=6000, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Phase 7 test source", checksum_sha256=None)
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


def test_resolve_germany_calc_inputs_returns_all_registries(db, organization):
    emp = _make_employee(db, organization.id)
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)

    resolved = service._resolve_germany_calc_inputs(db, organization.id, emp, date(2026, 6, 1))
    assert resolved["statutory_profile"] is not None
    assert resolved["ceiling_gkv_pv"].branch == "GKV_PV"
    assert resolved["ceiling_rv_alv"].branch == "RV_ALV"
    assert resolved["health_fund"].health_fund_id == "E2E-FUND"
    assert resolved["pv_configuration"].child_category == "CHILDLESS"


def test_preview_germany_calculation_completes_regular_via_internal_tax_with_full_registry(db, organization):
    """Phase 8BR: with a full registry, the official BMF PAP is still
    unavailable (unchanged), but the diagnostic preview now reaches
    blocked=False via the internal functional wage-tax calculator."""
    emp = _make_employee(db, organization.id)
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)

    result = service.preview_germany_calculation(db, organization.id, emp.id, date(2026, 6, 1))
    assert result["blocked"] is False
    assert result["result"]["monthlyTax"] > 0
    assert result["trace"]["resolved"]["rv"]["employee"] is not None
    assert result["trace"]["papVersion"] == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"


def test_preview_germany_calculation_still_blocks_when_ceiling_genuinely_missing(db, organization):
    """The 'never fabricate' guarantee still holds for a GENUINE block —
    a missing RV_ALV ceiling has nothing to do with wage tax and must
    still block, regardless of the internal tax calculator's existence."""
    emp = _make_employee(db, organization.id)
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)

    result = service.preview_germany_calculation(db, organization.id, emp.id, date(2026, 6, 1))
    assert result["blocked"] is True
    assert result["blockedReasonCode"] == "GERMANY_CEILING_NOT_AVAILABLE"


def test_preview_germany_calculation_rejects_non_german_employee(db, organization):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="IN-001", name="Indian Employee",
        country_code="IN", ctc=600000,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    with pytest.raises(BadRequestException):
        service.preview_germany_calculation(db, organization.id, emp.id, date(2026, 6, 1))


def _stub_business_code_generation(monkeypatch):
    """generate_payslips_for_run/create_payroll_run number records via
    generate_business_code, which takes a Postgres advisory lock
    (pg_advisory_xact_lock) — real production-only Postgres behavior, not
    something to weaken. This test DB is SQLite (see conftest.py); stub
    the numbering call exactly like
    test_engine_jurisdiction_db_integration.py's own
    _stub_business_code_generation does, since these tests are about
    Germany calculation blocking, not concurrent code numbering."""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_create_payroll_run_completes_regular_employee_via_internal_tax_calculator(db, organization, monkeypatch):
    """The full E2E path this phase's §33 requires: real employee, real
    attendance, real full registry setup — Phase 8BR: a Regular employee
    now reaches a real, persisted, non-fabricated calculation via the
    internal functional wage-tax calculator (official BMF PAP remains
    genuinely unavailable — see test_create_payroll_run_still_blocks_on_missing_ceiling
    below for proof the 'never fabricate when genuinely blocked' guarantee
    still holds for an actual block)."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id)
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)

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
    assert run.status == "Draft"

    from app.modules.payroll.models import PayslipItem, PayrollRun

    item = db.query(PayslipItem).one()
    assert item.status == "Pending"  # calculated, awaiting payslip generation — never "Failed"
    assert item.gross_pay > Decimal("0.00")
    assert item.net_pay > Decimal("0.00")
    assert item.net_pay < item.gross_pay
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("calculationStatus") == "COMPLETE"
    assert trace.get("papVersion") == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"
    assert trace.get("resolved", {}).get("rv") is not None

    remaining_run = db.query(PayrollRun).one()
    assert remaining_run.status == "Draft"
    assert remaining_run.employee_count == 1


def test_create_payroll_run_still_blocks_on_missing_ceiling(db, organization, monkeypatch):
    """The 'never fabricate a payslip' guarantee still applies to a
    genuinely blocked calculation (a missing RV_ALV ceiling has nothing
    to do with wage tax) — Phase 8BI's FAILED-sentinel-per-employee
    behavior, re-pinned against a real block that still exists today."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id)
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)

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
    assert run.status == "Draft"

    from app.modules.payroll.models import PayslipItem, PayrollRun

    item = db.query(PayslipItem).one()
    assert item.status == "Failed"
    assert item.gross_pay == Decimal("0.00")
    assert item.net_pay == Decimal("0.00")
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("blockedReasonCode") == "GERMANY_CEILING_NOT_AVAILABLE"

    remaining_run = db.query(PayrollRun).one()
    assert remaining_run.status == "Draft"
    assert remaining_run.employee_count == 0  # FAILED items never counted


def test_create_payroll_run_blocks_on_missing_statutory_profile(db, organization, monkeypatch):
    """No EmployeeStatutoryProfile at all is the FIRST thing that blocks —
    proves the profile requirement is enforced even before any registry
    lookup happens. Phase 8BI: recorded as a FAILED sentinel, not a
    raised exception — see the test above for the rationale."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="DE-E2E-002")
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

    from app.modules.payroll.models import PayslipItem
    item = db.query(PayslipItem).one()
    assert item.status == "Failed"
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("blockedReasonCode") == "GERMANY_STATUTORY_PROFILE_MISSING"


# ── Phase 8E: snapshot value capture + manual payslip Germany wiring ────

@dataclass
class _RichCeiling:
    id: int = 1
    branch: str = "RV_ALV"
    monthly_ceiling: Decimal = Decimal("8450.00")
    annual_ceiling: Decimal = Decimal("101400.00")
    effective_from: date = date(2026, 1, 1)


@dataclass
class _RichHealthFund:
    id: int = 1
    health_fund_id: str = "TEST-FUND"
    fund_name: str = "Test Fund"
    supplementary_rate_pct: Decimal = Decimal("1.7000")
    effective_from: date = date(2026, 1, 1)
    is_average_rate: bool = False


@dataclass
class _RichPvConfig:
    id: int = 1
    is_saxony: bool = False
    child_category: str = "CHILDLESS"
    effective_from: date = date(2026, 1, 1)
    total_rate_pct: Decimal = Decimal("4.2000")
    standard_employee_rate_pct: Decimal = Decimal("2.4000")
    employer_rate_pct: Decimal = Decimal("1.8000")
    saxony_employee_rate_pct: Decimal = Decimal("2.9000")
    saxony_employer_rate_pct: Decimal = Decimal("1.3000")


def test_calculate_snapshot_captures_statutory_values():
    """Phase 8E §24/§42: the calculation trace must capture the ACTUAL
    statutory VALUES (ceiling amounts, PV rates, health-fund identity,
    PAP identity), not just registry row IDs, so a finalized Germany
    payslip's statutory context is fully reproducible even if a registry
    row is later superseded."""
    profile = _FakeProfile()
    ctx = PayrollContext(
        gross=Decimal("5000"), basic=Decimal("5000"), country="DE",
        germany_statutory_profile=profile,
        germany_pap_asset=None,
        germany_health_fund=_RichHealthFund(),
        germany_ceiling_gkv_pv=_RichCeiling(branch="GKV_PV", monthly_ceiling=Decimal("5812.50"), annual_ceiling=Decimal("69750.00")),
        germany_ceiling_rv_alv=_RichCeiling(branch="RV_ALV", monthly_ceiling=Decimal("8450.00"), annual_ceiling=Decimal("101400.00")),
        germany_pv_configuration=_RichPvConfig(),
    )
    result = germany.calculate(ctx)
    # Phase 8BR: calculate() now returns a plain result dict (COMPLETE via
    # the internal tax calculator) rather than raising — the snapshot is
    # the same JSON-safe GermanyCalculationTrace.to_dict() as before,
    # just reached via the success path instead of an exception's .trace.
    snap = result["_germany_calculation_snapshot"]

    assert snap["ceilingGkvPvMonthly"] == "5812.50"
    assert snap["ceilingGkvPvAnnual"] == "69750.00"
    assert snap["ceilingRvAlvMonthly"] == "8450.00"
    assert snap["ceilingRvAlvAnnual"] == "101400.00"

    assert snap["healthFundName"] == "Test Fund"
    assert snap["healthFundEffectiveFrom"] == "2026-01-01"
    assert snap["healthFundIsAverageRate"] is False
    assert snap["healthFundSupplementaryRatePct"] == "1.7000"

    assert snap["pvConfigurationTotalRatePct"] == "4.2000"
    assert snap["pvConfigurationStandardEmployeeRatePct"] == "2.4000"
    assert snap["pvConfigurationEmployerRatePct"] == "1.8000"
    assert snap["pvConfigurationSaxonyEmployeeRatePct"] == "2.9000"
    assert snap["pvConfigurationEffectiveFrom"] == "2026-01-01"


def _make_run(db, emp, org_id, period_start=date(2026, 1, 1), pay_date=date(2026, 2, 1)):
    run = PayrollRun(
        organization_id=org_id, period_label="Jan 2026", period_start=period_start,
        period_end=date(2026, 1, 31), pay_date=pay_date, status="Draft",
        calculation_mode="standard",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_manual_payslip_germany_path_completes_via_internal_tax_calculator(db, organization, monkeypatch):
    """Phase 8E §25/§26: the MANUAL single-payslip path (add_payslip_item)
    for a Germany employee consumes the same effective-dated statutory
    inputs as a batch run. Phase 8BR: with a full registry, this now
    completes via the internal functional wage-tax calculator (official
    BMF PAP remains genuinely unavailable, unchanged) — see the test below
    for proof a genuine block still refuses to fabricate a wageslip."""
    emp = _make_employee(db, organization.id, code="DE-MANUAL-001")
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)
    run = _make_run(db, emp, organization.id)

    data = PayslipItemCreate(
        employee_id=emp.id, basic_salary=Decimal("5000"), hra=Decimal("0"),
        special_allowance=Decimal("0"), notes="manual DE payslip",
    )
    item = service.add_payslip_item(db, run.id, data, organization.id)

    assert item.net_pay > Decimal("0.00")
    assert item.net_pay < item.gross_pay
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("calculationStatus") == "COMPLETE"
    assert trace.get("resolved", {}).get("rv") is not None
    assert db.query(PayslipItem).count() == 1


def test_manual_payslip_germany_path_still_blocks_on_genuine_block(db, organization, monkeypatch):
    """Same manual path, but with a genuinely missing registry (RV_ALV
    ceiling) — must still fail closed with the structured 400 and never
    fabricate a wageslip row, exactly as before this phase."""
    emp = _make_employee(db, organization.id, code="DE-MANUAL-002")
    _make_full_profile(db, emp, organization.id)
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_health_fund(db, "E2E-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)
    run = _make_run(db, emp, organization.id)

    data = PayslipItemCreate(
        employee_id=emp.id, basic_salary=Decimal("5000"), hra=Decimal("0"),
        special_allowance=Decimal("0"), notes="manual DE payslip",
    )
    with pytest.raises(GermanyCalculationBlockedException) as excinfo:
        service.add_payslip_item(db, run.id, data, organization.id)

    assert excinfo.value.error_code == "GERMANY_CEILING_NOT_AVAILABLE"
    # The one thing this rule guarantees: no wageslip row was fabricated.
    assert db.query(PayslipItem).count() == 0
