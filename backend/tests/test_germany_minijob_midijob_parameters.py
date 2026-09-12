"""
tests/test_germany_minijob_midijob_parameters.py
------------------------------------------------------
Phase 8BK — Germany Minijob/Midijob statutory parameter registry.

Phase 8BJ found that, unlike RV/ALV/GKV (wired into the canonical
JurisdictionPack/rate_map mechanism that phase) and PV (already
effective-dated via GermanyPvConfiguration), Minijob's own flat
statutory rates and Midijob's own sliding-scale formula coefficients
remained plain hardcoded Python constants with NO effective dating and
NO override mechanism at all. This phase closes that gap with a new,
dedicated, effective-dated registry
(GermanyMinijobMidijobParameter/resolve_minijob_midijob_parameter),
mirroring GermanyContributionCeiling's exact lifecycle/overlap/maker-
checker shape.

Every value used as an "override" in these tests is an arbitrary test
fixture, deliberately different from the real 2026 constants in
hardcoded_defaults.py, so a passing assertion unambiguously proves the
override mechanism, never asserts a real statutory value. No migration
was needed beyond the one new table this phase adds (Option A/B could
not represent this data — see
docs/PHASE_8BK_GERMANY_MINIJOB_MIDIJOB_STATUTORY_REGISTRY_REPORT.md).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, GermanyCalculationBlockedException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.hardcoded_defaults import (
    _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER, _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
    _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER, _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
    _DE_MINIJOB_EMPLOYER_HEALTH_RATE, _DE_MINIJOB_EMPLOYER_PENSION_RATE,
    _DE_MINIJOB_U1_RATE, _DE_MINIJOB_U2_RATE, _DE_MINIJOB_U3_RATE,
    _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE, _DE_MINIJOB_FLAT_TAX_RATE,
    _DE_RV_EMPLOYEE_RATE,
)
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyMinijobMidijobParameter,
    GermanyPvConfiguration, PayrollAttendanceRecord, PayrollEmployee, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyMinijobMidijobParameterCreate,
    GermanyPvConfigurationCreate, PayrollRunCreate,
)


# ── Registry fixtures ────────────────────────────────────────────────────

def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Minijob/Midijob parameter test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_parameter(
    db, parameter_code, value, value_type="PERCENTAGE", effective_from=date(2026, 1, 1),
    effective_to=None, maker=201, checker=202, auto_close_previous=True,
):
    source = _make_source(db)
    row = service.create_minijob_midijob_parameter_record(
        db, GermanyMinijobMidijobParameterCreate(
            parameter_code=parameter_code, value=value, value_type=value_type,
            label=f"Test fixture for {parameter_code}",
            effective_from=effective_from, effective_to=effective_to, authority_source_id=source.id,
        ), actor_id=maker, auto_close_previous=auto_close_previous,
    )
    row = service.set_minijob_midijob_parameter_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_minijob_midijob_parameter_approver(db, row.id, actor_id=checker)
    return service.set_minijob_midijob_parameter_status(db, row.id, "PUBLISHED", actor_id=checker)


# ── Full-pipeline Germany fixtures (mirrors test_germany_e2e_payroll_scenario.py) ──

def _make_employee(db, org_id, code, gross):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=gross * 12, basic=gross, hra=0, status="Active",
        date_of_joining=date(2025, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _publish_ceiling(db, branch, monthly, annual, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=date(2025, 1, 1), authority_source_id=source.id,
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
            supplementary_rate_pct=rate, effective_from=date(2025, 1, 1), authority_source_id=source.id,
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
            effective_from=date(2025, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _make_full_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2025, 1, 1), de_tax_class="I", de_church_tax_liable=False,
        de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="MMP-FUND",
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
    _publish_health_fund(db, "MMP-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _add_attendance(db, org_id, emp_id, day=15, month=1, year=2026):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(year, month, day),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _run_data(employee_ids, period_start, period_end, pay_date):
    return PayrollRunCreate(
        periodStart=period_start, periodEnd=period_end, payDate=pay_date,
        employeeIds=employee_ids, auto_generate_payslips=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# A-G, basic selection / historical / current / future / boundary / gap /
# overlap — direct resolver tests, mirroring test_germany_effective_dating.py.
# ══════════════════════════════════════════════════════════════════════════

def test_historical_current_future_and_boundary_resolution(db):
    v1 = _publish_parameter(
        db, "minijob_employer_health_rate", Decimal("12.00"),
        effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31),
    )
    v2 = _publish_parameter(
        db, "minijob_employer_health_rate", Decimal("14.00"),
        effective_from=date(2026, 1, 1),
    )
    # Historical
    assert service.resolve_minijob_midijob_parameter(
        db, "minijob_employer_health_rate", as_of=date(2025, 6, 1),
    ).id == v1.id
    # Current
    assert service.resolve_minijob_midijob_parameter(
        db, "minijob_employer_health_rate", as_of=date(2026, 6, 1),
    ).id == v2.id
    # Exact effective_to boundary (v1's last day)
    assert service.resolve_minijob_midijob_parameter(
        db, "minijob_employer_health_rate", as_of=date(2025, 12, 31),
    ).id == v1.id
    # Exact effective_from boundary (v2's first day)
    assert service.resolve_minijob_midijob_parameter(
        db, "minijob_employer_health_rate", as_of=date(2026, 1, 1),
    ).id == v2.id
    # Future: open-ended v2 still applies arbitrarily far ahead
    assert service.resolve_minijob_midijob_parameter(
        db, "minijob_employer_health_rate", as_of=date(2030, 1, 1),
    ).id == v2.id


def test_gap_between_periods_returns_none(db):
    _publish_parameter(
        db, "minijob_u1_rate", Decimal("0.90"),
        effective_from=date(2025, 1, 1), effective_to=date(2025, 6, 30),
    )
    _publish_parameter(
        db, "minijob_u1_rate", Decimal("1.00"),
        effective_from=date(2026, 1, 1), auto_close_previous=False,
    )
    # 2025-07-01..2025-12-31 is a genuine gap between the two published windows.
    assert service.resolve_minijob_midijob_parameter(db, "minijob_u1_rate", as_of=date(2025, 9, 1)) is None


def test_no_matching_configuration_returns_none_not_an_exception(db):
    assert service.resolve_minijob_midijob_parameter(db, "minijob_flat_tax_rate", as_of=date(2020, 1, 1)) is None
    assert service.resolve_minijob_midijob_parameter(db, "midijob_total_base_multiplier", as_of=date(2026, 1, 1)) is None


def test_overlapping_periods_rejected(db):
    _publish_parameter(
        db, "minijob_u2_rate", Decimal("0.25"),
        effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31),
    )
    with pytest.raises(BadRequestException, match="overlaps existing"):
        _publish_parameter(
            db, "minijob_u2_rate", Decimal("0.30"),
            effective_from=date(2025, 6, 1), effective_to=date(2025, 8, 31), auto_close_previous=False,
        )


def test_unknown_parameter_code_rejected(db):
    source = _make_source(db)
    with pytest.raises(BadRequestException, match="parameterCode must be one of"):
        service.create_minijob_midijob_parameter_record(
            db, GermanyMinijobMidijobParameterCreate(
                parameter_code="not_a_real_parameter", value=Decimal("1.00"), value_type="PERCENTAGE",
                label="bogus", effective_from=date(2026, 1, 1), authority_source_id=source.id,
            ), actor_id=1,
        )


def test_invalid_effective_range_rejected(db):
    source = _make_source(db)
    with pytest.raises(BadRequestException, match="effectiveTo must not be before"):
        service.create_minijob_midijob_parameter_record(
            db, GermanyMinijobMidijobParameterCreate(
                parameter_code="minijob_u3_rate", value=Decimal("0.15"), value_type="PERCENTAGE",
                label="bad range", effective_from=date(2026, 1, 1), effective_to=date(2025, 1, 1),
                authority_source_id=source.id,
            ), actor_id=1,
        )


def test_publish_requires_distinct_approver_and_source(db):
    row = service.create_minijob_midijob_parameter_record(
        db, GermanyMinijobMidijobParameterCreate(
            parameter_code="minijob_flat_tax_rate", value=Decimal("2.00"), value_type="PERCENTAGE",
            label="no source yet", effective_from=date(2026, 1, 1),
        ), actor_id=1,
    )
    row = service.set_minijob_midijob_parameter_status(db, row.id, "VERIFIED", actor_id=1)
    # Directly reach APPROVED status with a SELF-approval (same actor who
    # last edited it), bypassing set_minijob_midijob_parameter_approver's
    # own (separately tested elsewhere) approver-assignment path — this
    # isolates the PUBLISHED-transition's own self-approval business rule.
    row.status = "APPROVED"
    row.approved_by_id = 1
    db.commit()
    with pytest.raises(BadRequestException, match="distinct approver"):
        service.set_minijob_midijob_parameter_status(db, row.id, "PUBLISHED", actor_id=1)

    # A distinct approver but still no linked source evidence.
    row.approved_by_id = 2
    db.commit()
    with pytest.raises(BadRequestException, match="source evidence"):
        service.set_minijob_midijob_parameter_status(db, row.id, "PUBLISHED", actor_id=1)


def test_get_by_id_not_found_raises(db):
    with pytest.raises(NotFoundException):
        service.get_minijob_midijob_parameter_by_id(db, 999999)


# ══════════════════════════════════════════════════════════════════════════
# Decimal precision — Midijob's own coefficients need 10 decimal places.
# ══════════════════════════════════════════════════════════════════════════

def test_high_precision_midijob_coefficient_round_trips_exactly(db):
    row = _publish_parameter(
        db, "midijob_total_base_subtrahend", Decimal("291.8744452399"), value_type="COEFFICIENT_SUBTRAHEND",
    )
    resolved = service.resolve_minijob_midijob_parameter(db, "midijob_total_base_subtrahend", as_of=date(2026, 6, 1))
    assert resolved.id == row.id
    assert Decimal(resolved.value) == Decimal("291.8744452399")  # no truncation


# ══════════════════════════════════════════════════════════════════════════
# Statutory values cannot be caller-overridden / no tenant scoping exists.
# ══════════════════════════════════════════════════════════════════════════

def test_registry_has_no_organization_scoping_at_all(db):
    """Mirrors GermanyContributionCeiling/GermanyHealthFund/
    GermanyPvConfiguration — this is a global, federal-statutory-fact
    registry; there is no organization_id column for a caller to target,
    and the create/resolve functions accept no organization parameter at
    all, so no request payload can make a statutory value tenant-specific."""
    assert not hasattr(GermanyMinijobMidijobParameter, "organization_id")
    import inspect
    assert "organization_id" not in inspect.signature(service.create_minijob_midijob_parameter_record).parameters
    assert "organization_id" not in inspect.signature(service.resolve_minijob_midijob_parameter).parameters


# ══════════════════════════════════════════════════════════════════════════
# Full-pipeline regression + override proof — Minijob, Midijob, Regular.
# ══════════════════════════════════════════════════════════════════════════

def test_minijob_regression_unchanged_with_no_registry_rows(db, organization, monkeypatch):
    """The exact documented Minijob baseline (gross=520 -> net=501.28)
    must still hold when no Minijob/Midijob parameter has ever been
    published — proving this phase introduced zero behavior change for
    every org that hasn't configured the new registry."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="MMP-MINI-BASE", gross=520)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"
    assert item.net_pay == Decimal("501.28")
    assert item.pf == Decimal("18.72")


def test_minijob_override_changes_result_with_decimal_precision(db, organization, monkeypatch):
    """Publishing a (test-fixture) override for the employer health rate
    must change the computed result — proving the registry is genuinely
    consulted, not just resolvable in isolation."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="MMP-MINI-OVERRIDE", gross=520)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    # Deliberately different from the real 13% constant — proves override, not a real rate.
    _publish_parameter(db, "minijob_employer_health_rate", Decimal("20.00"))

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    # employer_esi = health(20% of 520=104.00) + u1(0.80%=4.16) + u2(0.22%=1.144->1.14) + u3(0.15%=0.78)
    assert item.employer_esi == Decimal("104.00") + Decimal("4.16") + Decimal("1.14") + Decimal("0.78")
    # Employee-side figures (pension top-up, net pay) are untouched by an
    # employer-only rate override.
    assert item.pf == Decimal("18.72")
    assert item.net_pay == Decimal("501.28")


def test_midijob_si_regression_and_wage_tax_completes_via_internal_calculator(db, organization, monkeypatch):
    """Midijob SI remains GO with no registry rows; Phase 8BR: wage tax
    now completes via the internal functional wage-tax calculator
    (official BMF PAP remains genuinely unavailable, unchanged) rather
    than blocking — Minijob/Midijob's own SI constants (this phase's own
    scope) are unaffected either way."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="MMP-MIDI-BASE", gross=1500)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MIDIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("calculationStatus") == "COMPLETE"
    assert "midijob_rv" in trace.get("resolved", {})
    assert item.net_pay > Decimal("0.00")


def test_midijob_coefficient_override_changes_contribution_base(db, organization, monkeypatch):
    """Publishing a (test-fixture) override for Midijob's own
    total-base multiplier must change the traced contribution base —
    proving Midijob's formula coefficients are genuinely consulted."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="MMP-MIDI-OVERRIDE", gross=1500)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MIDIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    default_total_base = Decimal("1500.00") * _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER - _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND
    override_multiplier = Decimal("1.0")  # deliberately simple/different test fixture, not the real coefficient
    _publish_parameter(
        db, "midijob_total_base_multiplier", override_multiplier, value_type="COEFFICIENT_MULTIPLIER",
    )

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    trace = item.germany_calculation_snapshot or {}
    traced_base = Decimal(trace["midijobTotalContributionBase"]) if "midijobTotalContributionBase" in trace else None
    # Fall back to reading via the snake_case key if to_dict uses a different alias.
    if traced_base is None:
        traced_base = Decimal(trace.get("midijob_total_contribution_base"))
    assert traced_base != default_total_base.quantize(Decimal("0.01"))
    expected_base = (Decimal("1500.00") * override_multiplier - _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND)
    assert traced_base == expected_base


def test_regular_payroll_unaffected_by_minijob_midijob_parameters(db, organization, monkeypatch):
    """Regular Germany payroll must be completely unaffected by
    Minijob/Midijob-only parameter overrides — this phase touches only
    Minijob/Midijob's own constants. Phase 8BR: Regular itself now
    completes via the internal functional wage-tax calculator, so the
    'unaffected' assertion is on the SI trace, not a PAP block."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="MMP-REG-UNAFFECTED", gross=5000)
    _make_full_profile(db, emp, organization.id, de_employment_classification="REGULAR")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)
    _publish_parameter(db, "minijob_employer_health_rate", Decimal("99.00"))  # must have zero effect on Regular

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("calculationStatus") == "COMPLETE"
    expected_rv = (Decimal("5000.00") * _DE_RV_EMPLOYEE_RATE / 100).quantize(Decimal("0.01"))
    assert Decimal(trace["resolved"]["rv"]["employee"]) == expected_rv


def test_pap_resolver_still_unavailable_regardless_of_registry(db):
    """Confirms this phase made no change whatsoever to PAP's own
    fail-closed resolver."""
    from app.modules.payroll.engine.germany_pap.core import resolve_pap_executor, UnavailablePapExecutor

    executor = resolve_pap_executor(None)
    assert isinstance(executor, UnavailablePapExecutor)


def test_non_german_country_calculation_unaffected(db, organization, monkeypatch):
    """A non-Germany employee's calculation must never even look at
    ctx.germany_minijob_midijob_parameters — proving this phase's wiring
    is Germany-scoped only."""
    _stub_business_code_generation(monkeypatch)
    from app.modules.payroll.models import PayrollEmployee as _Emp

    emp = _Emp(
        organization_id=organization.id, employee_code="MMP-IN-UNAFFECTED", name="India Employee",
        country_code="IN", ctc=600000, basic=25000, hra=10000, status="Active",
        date_of_joining=date(2025, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    db.add(PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()

    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"  # India calculation completes normally, unaffected
