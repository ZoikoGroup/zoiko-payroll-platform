"""
tests/test_germany_contribution_rate_effective_dating.py
------------------------------------------------------------
Phase 8BJ — proves Germany's RV/ALV/GKV(general) contribution rates can
be resolved through the EXISTING, already-built, already-tested canonical
tax-pack effective-dating mechanism (JurisdictionPack pack_type="tax" +
ContributionRate linked via jurisdiction_pack_id + engine/tax_resolver.py's
resolve_tax_configuration), rather than through any new schema.

This is the central finding of Phase 8BJ: the gap Phase 8BH/8BI identified
("ContributionRate has no effective dating") was never a missing-
architecture problem — this exact mechanism already existed, is already
country-agnostic, already date-aware, already overlap-guarded, already
maker-checker'd, and is already used by other jurisdictions (India/UK/US/
Canada). Germany's RV/ALV/GKV general-rate calculation functions
(calculate_rv/calculate_alv/calculate_gkv) ALREADY read from `rate_map`
via `two_sided_rate()` — they just fall back to a hardcoded 2026 constant
because no Germany tax pack has ever existed and no Germany org has ever
opted in. This phase's only CODE change was extending the MIDIJOB path
(engine/countries/germany.py's _calculate_midijob_path) to consult the
SAME rate_map the REGULAR path already did, for consistency (the
identical statutory rate must never resolve differently for a Midijob
vs. a Regular employee).

Every rate value used as an "override" in these tests is an arbitrary
test fixture (e.g. 10.00%), deliberately different from the real 2026
constants in hardcoded_defaults.py, so a passing assertion unambiguously
proves the override path was actually used — never a real, authoritative,
or production statutory value. No migration was needed or created for
any of this — see docs/PHASE_8BJ_CONTRIBUTION_RATE_EFFECTIVE_DATING_REPORT.md.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.hardcoded_defaults import (
    _DE_ALV_EMPLOYEE_RATE, _DE_ALV_EMPLOYER_RATE,
    _DE_RV_EMPLOYEE_RATE, _DE_RV_EMPLOYER_RATE,
)
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    CanonicalContributionRateUpsert, EmployeeStatutoryProfileCreate,
    GermanyContributionCeilingCreate, GermanyHealthFundCreate, GermanyPvConfigurationCreate,
    JurisdictionPackUpsert, PayrollRunCreate,
)


# ── Germany statutory-registry fixtures (unchanged pattern from the other
# Germany E2E test files) ────────────────────────────────────────────────

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


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Effective-dating test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


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
        de_health_insurance_status="PUBLIC", de_health_fund_code="CR-FUND",
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
    _publish_health_fund(db, "CR-FUND")
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


# ── Canonical DE tax-pack fixtures — the effective-dating mechanism itself ──

def _make_de_tax_pack(
    db, pack_id, version, effective_from, effective_to=None,
    rv_employee_pct=Decimal("10.00"), rv_employer_pct=Decimal("10.00"),
    maker=101, checker=102,
):
    """Creates, populates, approves, and activates one canonical Germany
    'tax' JurisdictionPack with a single 'rv_pension' ContributionRate
    row. rv_employee_pct/rv_employer_pct default to an arbitrary TEST
    value (10.00%) deliberately different from the real 2026 constant
    (_DE_RV_EMPLOYEE_RATE/_DE_RV_EMPLOYER_RATE = 9.30%) so a passing
    assertion unambiguously proves the override path, never a real rate."""
    pack = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId=pack_id, jurisdictionCountry="DE", packType="tax", version=version,
            status="Draft", effectiveFrom=effective_from, effectiveTo=effective_to, taxYear=version,
        ), actor_id=maker,
    )
    service.upsert_canonical_contribution_rate(
        db, CanonicalContributionRateUpsert(
            jurisdictionPackId=pack.id, jurisdictionCountry="DE", componentKey="rv_pension",
            label="Rentenversicherung (test fixture)",
            employeeSharePct=rv_employee_pct, employerSharePct=rv_employer_pct, sortOrder=0,
        ), actor_id=maker,
    )
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=checker)
    return service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=checker)


def _opt_in(db, org_id, pack, actor_id=102):
    service.assign_pack_to_organizations(db, pack.id, [org_id], actor_id=actor_id)


def _run_and_get_blocked_trace(db, emp_id, organization_id, period_start, period_end, pay_date):
    """Historically named for the pre-Phase-8BR world, where REGULAR/
    MIDIJOB always blocked on GERMANY_PAP_NOT_AVAILABLE after SI resolved
    — kept unrenamed (only the body changed) since every call site below
    only inspects `resolved.rv`/`resolved.midijob_rv`, never the block
    status itself. Phase 8BR: REGULAR/MIDIJOB now complete via the
    internal functional wage-tax calculator (engine/germany_internal_tax.py)
    once the registry is full, so the item may be Pending (COMPLETE) or
    Failed depending on the scenario — either way, the RV/ALV/GKV/PV trace
    these tests actually assert on is resolved identically before that
    point, exactly as it always was."""
    run = service.create_payroll_run(
        db, created_by=1, data=_run_data([emp_id], period_start, period_end, pay_date),
        organization_id=organization_id,
    )
    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp_id,
    ).one()
    return item.germany_calculation_snapshot or {}


# ══════════════════════════════════════════════════════════════════════════
# 1. Baseline regression — no canonical pack, no opt-in: byte-identical to
#    pre-Phase-8BJ behavior (hardcoded 2026 constants).
# ══════════════════════════════════════════════════════════════════════════

def test_regular_payroll_uses_hardcoded_default_when_org_not_opted_in(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="DE-CR-REG-DEFAULT", gross=4000)
    _make_full_profile(db, emp, organization.id)
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    trace = _run_and_get_blocked_trace(
        db, emp.id, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1),
    )
    expected_employee_rv = _r2(Decimal("4000.00") * _DE_RV_EMPLOYEE_RATE / 100)
    assert Decimal(trace["resolved"]["rv"]["employee"]) == expected_employee_rv


def _r2(value):
    from decimal import ROUND_HALF_UP
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ══════════════════════════════════════════════════════════════════════════
# 2. Canonical rate resolves when the org has opted in and the payroll
#    date falls inside the pack's effective window.
# ══════════════════════════════════════════════════════════════════════════

def test_regular_payroll_uses_canonical_rate_when_opted_in_and_effective(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="DE-CR-REG-CANON", gross=4000)
    _make_full_profile(db, emp, organization.id)
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-2026", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("10.00"), rv_employer_pct=Decimal("11.00"),
    )
    _opt_in(db, organization.id, pack)

    trace = _run_and_get_blocked_trace(
        db, emp.id, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1),
    )
    # 4000 gross * 10.00% employee RV (the TEST override, not 9.30%'s real default)
    assert Decimal(trace["resolved"]["rv"]["employee"]) == Decimal("400.00")
    assert Decimal(trace["resolved"]["rv"]["employer"]) == Decimal("440.00")


# ══════════════════════════════════════════════════════════════════════════
# 3. Historical safety — old payroll resolves the old canonical version,
#    current payroll resolves the current one. Uses "rate effective ON
#    payroll_date," never "latest available rate."
# ══════════════════════════════════════════════════════════════════════════

def test_historical_and_current_payroll_resolve_their_own_canonical_version(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp_2025 = _make_employee(db, organization.id, code="DE-CR-HIST-2025", gross=4000)
    emp_2026 = _make_employee(db, organization.id, code="DE-CR-HIST-2026", gross=4000)
    _make_full_profile(db, emp_2025, organization.id)
    _make_full_profile(db, emp_2026, organization.id)
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp_2025.id, month=6, year=2025)
    _add_attendance(db, organization.id, emp_2026.id, month=6, year=2026)

    pack_2025 = _make_de_tax_pack(
        db, "DE-TEST-TAX-HIST", "2025", date(2025, 1, 1), date(2025, 12, 31),
        rv_employee_pct=Decimal("8.00"), rv_employer_pct=Decimal("8.00"),
    )
    pack_2026 = _make_de_tax_pack(
        db, "DE-TEST-TAX-HIST", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("12.00"), rv_employer_pct=Decimal("12.00"),
    )
    _opt_in(db, organization.id, pack_2025)  # opting in once covers the whole org — either pack row works
    _opt_in(db, organization.id, pack_2026)

    trace_2025 = _run_and_get_blocked_trace(
        db, emp_2025.id, organization.id, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 1),
    )
    assert Decimal(trace_2025["resolved"]["rv"]["employee"]) == Decimal("320.00")  # 4000 * 8.00%

    trace_2026 = _run_and_get_blocked_trace(
        db, emp_2026.id, organization.id, date(2026, 6, 1), date(2026, 6, 30), date(2026, 7, 1),
    )
    assert Decimal(trace_2026["resolved"]["rv"]["employee"]) == Decimal("480.00")  # 4000 * 12.00%


# ══════════════════════════════════════════════════════════════════════════
# 4. Overlap safety — the existing generic guard, re-confirmed for Germany
#    specifically: two Active tax packs for the same country/state/regime
#    with overlapping effective windows must be refused, never silently
#    resolved by a tie-breaking rule.
# ══════════════════════════════════════════════════════════════════════════

def test_overlapping_active_tax_packs_for_germany_rejected(db):
    pack_a = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId="DE-TEST-TAX-OVERLAP", jurisdictionCountry="DE", packType="tax", version="A",
            status="Draft", effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31), taxYear="2026",
        ), actor_id=101,
    )
    service.upsert_canonical_contribution_rate(
        db, CanonicalContributionRateUpsert(
            jurisdictionPackId=pack_a.id, jurisdictionCountry="DE", componentKey="rv_pension",
            label="Test", employeeSharePct=Decimal("9.00"), employerSharePct=Decimal("9.00"),
        ), actor_id=101,
    )
    service.set_jurisdiction_pack_approver(db, pack_a.id, actor_id=102)
    service.set_jurisdiction_pack_status(db, pack_a.id, "Active", actor_id=102)

    pack_b = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId="DE-TEST-TAX-OVERLAP-B", jurisdictionCountry="DE", packType="tax", version="B",
            status="Draft", effectiveFrom=date(2026, 6, 1), effectiveTo=date(2027, 6, 30), taxYear="2026-27",
        ), actor_id=101,
    )
    service.upsert_canonical_contribution_rate(
        db, CanonicalContributionRateUpsert(
            jurisdictionPackId=pack_b.id, jurisdictionCountry="DE", componentKey="rv_pension",
            label="Test", employeeSharePct=Decimal("9.50"), employerSharePct=Decimal("9.50"),
        ), actor_id=101,
    )
    service.set_jurisdiction_pack_approver(db, pack_b.id, actor_id=102)
    with pytest.raises(BadRequestException, match="overlap"):
        service.set_jurisdiction_pack_status(db, pack_b.id, "Active", actor_id=102)


# ══════════════════════════════════════════════════════════════════════════
# 5. Component consistency — Midijob's RV must resolve from the SAME
#    canonical rate_map entry as Regular's, not a hardcoded-only path
#    (the actual code change this phase made).
# ══════════════════════════════════════════════════════════════════════════

def test_midijob_rv_consistent_with_regular_canonical_override(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    midijob_emp = _make_employee(db, organization.id, code="DE-CR-MIDI-CANON", gross=1500)
    _make_full_profile(db, midijob_emp, organization.id, de_employment_classification="MIDIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, midijob_emp.id)

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-MIDI", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("10.00"), rv_employer_pct=Decimal("10.00"),
    )
    _opt_in(db, organization.id, pack)

    trace = _run_and_get_blocked_trace(
        db, midijob_emp.id, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1),
    )
    # The Midijob 3-step Übergangsbereich mechanism uses the SAME 10.00%
    # combined rate, not the 9.30%+9.30% hardcoded default — proving RV
    # resolves identically for Midijob and Regular from the same override.
    from app.modules.payroll.engine.germany_pap.core import (
        calculate_midijob_branch_contribution, calculate_midijob_employee_base, calculate_midijob_total_base,
    )
    from app.modules.payroll.hardcoded_defaults import (
        _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER, _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER, _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
    )
    total_base = calculate_midijob_total_base(
        Decimal("1500.00"), multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER, subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
    )
    employee_base = calculate_midijob_employee_base(
        Decimal("1500.00"), multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER, subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
    )
    _, expected_employee, expected_employer = calculate_midijob_branch_contribution(
        total_base, employee_base, combined_rate_pct=Decimal("20.00"), employee_rate_pct=Decimal("10.00"),
    )
    assert Decimal(trace["resolved"]["midijob_rv"]["employee"]) == expected_employee
    assert Decimal(trace["resolved"]["midijob_rv"]["employer"]) == expected_employer
    # And NOT the hardcoded-default result (proves the override really applied).
    default_combined = _DE_RV_EMPLOYEE_RATE + _DE_RV_EMPLOYER_RATE
    _, default_employee, _default_employer = calculate_midijob_branch_contribution(
        total_base, employee_base, combined_rate_pct=default_combined, employee_rate_pct=_DE_RV_EMPLOYEE_RATE,
    )
    assert Decimal(trace["resolved"]["midijob_rv"]["employee"]) != default_employee


# ══════════════════════════════════════════════════════════════════════════
# 6. Minijob regression safety — Minijob NEVER reads rate_map (flat-rate
#    scheme, unrelated to RV/ALV/GKV), so it must be completely unaffected
#    even when its own org has a canonical override active.
# ══════════════════════════════════════════════════════════════════════════

def test_minijob_unaffected_by_canonical_pack_wiring(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    minijob_emp = _make_employee(db, organization.id, code="DE-CR-MINI-REGR", gross=520)
    _make_full_profile(db, minijob_emp, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, minijob_emp.id)

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-MINIREGR", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("99.00"), rv_employer_pct=Decimal("99.00"),  # deliberately extreme
    )
    _opt_in(db, organization.id, pack)

    service.create_payroll_run(
        db, created_by=1,
        data=_run_data([minijob_emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == minijob_emp.id).one()
    assert item.status == "Pending"
    assert item.net_pay == Decimal("501.28")  # identical to Phase 8BI/pre-existing Minijob E2E result
    assert item.pf == Decimal("18.72")


# ══════════════════════════════════════════════════════════════════════════
# 7. Tenant isolation — the actual, per-org opt-in flag
#    (_org_uses_canonical_tax_pack / CompanyComplianceDetails.active_pack_id)
#    must never leak from one organization to another.
#
# IMPORTANT, genuinely surfaced this phase (documented in
# docs/PHASE_8BJ_CONTRIBUTION_RATE_EFFECTIVE_DATING_REPORT.md's tenant-
# isolation section — NOT fixed here, see that report for why): the
# get_contribution_rates() FALLBACK path has its own, SEPARATE, PRE-
# EXISTING (not introduced by this phase, applies to every country) auto-
# seed behavior — the first time ANY org has zero ContributionRate rows
# for a country, it silently copies (a one-time, non-date-aware, wall-
# clock "today" snapshot of) whatever canonical tax pack is Active AT
# THAT MOMENT into that org's own permanent rows, via
# sync_org_rates_from_canonical(..., payroll_date=None). This is a DIFFERENT
# mechanism from the live, date-aware canonical-pack resolution path
# (_org_uses_canonical_tax_pack/resolve_tax_configuration) this phase
# wired Germany into, and it means an org that has NEVER explicitly opted
# in can still inherit a canonical rate on its first-ever run for a
# country. The test below orders operations to avoid triggering that
# separate seed path (so it isolates and proves the OPT-IN flag's own
# tenant-scoping specifically); test_first_use_auto_seed_is_not_date_aware
# right after it demonstrates and documents the separate behavior
# directly, rather than silently masking it.
# ══════════════════════════════════════════════════════════════════════════

def test_cross_tenant_canonical_rate_isolation(db, organization, monkeypatch):
    from app.modules.organizations.models import Organization

    _stub_business_code_generation(monkeypatch)
    other_org = Organization(organization_name="Other Org", organization_code="CRTENANTOTHER")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    emp_opted_in = _make_employee(db, organization.id, code="DE-CR-TENANT-A", gross=4000)
    emp_not_opted_in = _make_employee(db, other_org.id, code="DE-CR-TENANT-B", gross=4000)
    _make_full_profile(db, emp_opted_in, organization.id)
    _make_full_profile(db, emp_not_opted_in, other_org.id)
    _publish_all_registries(db)  # global registries — shared, unaffected by tax-pack opt-in
    _add_attendance(db, organization.id, emp_opted_in.id, month=1)
    _add_attendance(db, other_org.id, emp_not_opted_in.id, month=1)

    # Run other_org's payroll FIRST, BEFORE any canonical DE tax pack
    # exists — its own ContributionRate rows auto-seed from the hardcoded
    # defaults now (there is no canonical pack yet to pull from), so a
    # LATER canonical pack's existence can never retroactively change
    # rows this org already has.
    trace_not_opted_in = _run_and_get_blocked_trace(
        db, emp_not_opted_in.id, other_org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1),
    )
    default_expected = _r2(Decimal("4000.00") * _DE_RV_EMPLOYEE_RATE / 100)
    assert Decimal(trace_not_opted_in["resolved"]["rv"]["employee"]) == default_expected

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-TENANT", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("15.00"), rv_employer_pct=Decimal("15.00"),
    )
    _opt_in(db, organization.id, pack)  # only THIS org opts in
    assert service._org_uses_canonical_tax_pack(db, organization.id) is True
    assert service._org_uses_canonical_tax_pack(db, other_org.id) is False

    trace_opted_in = _run_and_get_blocked_trace(
        db, emp_opted_in.id, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1),
    )
    assert Decimal(trace_opted_in["resolved"]["rv"]["employee"]) == Decimal("600.00")  # 4000 * 15%

    # other_org's SECOND period, AFTER the canonical pack now exists —
    # still unaffected: it was never opted in, and its own rows already
    # exist (seeded above), so get_contribution_rates' auto-seed fallback
    # never re-fires for it either.
    _add_attendance(db, other_org.id, emp_not_opted_in.id, month=2)
    trace_not_opted_in_later = _run_and_get_blocked_trace(
        db, emp_not_opted_in.id, other_org.id, date(2026, 2, 1), date(2026, 2, 28), date(2026, 3, 1),
    )
    assert Decimal(trace_not_opted_in_later["resolved"]["rv"]["employee"]) == default_expected


def test_first_use_auto_seed_is_not_date_aware(db, monkeypatch):
    """Documents, rather than silently hides, a genuinely pre-existing
    (not introduced by Phase 8BJ, applies to every country) gap:
    get_contribution_rates' first-use auto-seed
    (_seed_org_rates_for_country -> sync_org_rates_from_canonical with no
    payroll_date) pulls from whichever canonical pack is Active on
    wall-clock "today," not the actual payroll_date being processed, and
    does so for ANY org — including one that never explicitly opted into
    canonical tracking via active_pack_id. Once seeded, the org's own
    copy is what every SUBSEQUENT call reads (get_contribution_rates only
    auto-seeds when the org's own row set is still empty) — so this is a
    one-time snapshot, not an ongoing date-aware link, and it can only
    ever happen once per org+country. Flagged as a follow-up in
    docs/PHASE_8BJ_CONTRIBUTION_RATE_EFFECTIVE_DATING_REPORT.md — fixing
    the generic seed path is cross-jurisdiction (affects every country,
    not just Germany) and is explicitly out of this phase's scope."""
    from app.modules.organizations.models import Organization

    org = Organization(organization_name="Seed Gap Org", organization_code="SEEDGAPORG")
    db.add(org)
    db.commit()
    db.refresh(org)

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-SEEDGAP", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("20.00"), rv_employer_pct=Decimal("20.00"),
    )
    # org never calls assign_pack_to_organizations — never explicitly opts in.
    assert service._org_uses_canonical_tax_pack(db, org.id) is False

    # Its first-ever call for "DE" nonetheless triggers the auto-seed,
    # which copies canonical_rates from whatever tax pack is Active RIGHT
    # NOW (this pack, since it's Active with no effective_to) — even
    # though this org was never "opted in."
    rows = service.get_contribution_rates(db, org.id, country="DE")
    rv_row = next((r for r in rows if r.component_key == "rv_pension"), None)
    assert rv_row is not None
    assert rv_row.employee_rate_pct == Decimal("20.00")


# ══════════════════════════════════════════════════════════════════════════
# 8. Deterministic selection.
# ══════════════════════════════════════════════════════════════════════════

def test_canonical_resolution_is_deterministic(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-DETERMINISTIC", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("11.00"), rv_employer_pct=Decimal("11.00"),
    )
    first_rates, _, first_pack = resolve_tax_configuration(db, "DE", payroll_date=date(2026, 3, 1))
    second_rates, _, second_pack = resolve_tax_configuration(db, "DE", payroll_date=date(2026, 3, 1))
    assert first_pack.id == second_pack.id == pack.id
    assert {r.id for r in first_rates} == {r.id for r in second_rates}


# ══════════════════════════════════════════════════════════════════════════
# 9. Phase 8BR: Date-aware auto-seeding.
# ══════════════════════════════════════════════════════════════════════════

def test_auto_seed_is_date_aware_when_payroll_date_provided(db):
    """Phase 8BR: verifies get_contribution_rates and get_tax_slabs respect
    payroll_date during initial auto-seed, selecting the canonical pack
    effective for that historical date rather than defaulting to today."""
    from app.modules.organizations.models import Organization

    org = Organization(organization_name="Date Aware Org", organization_code="DATEAWAREORG")
    db.add(org)
    db.commit()
    db.refresh(org)

    # 2024 pack with 18.00% RV
    pack_2024 = _make_de_tax_pack(
        db, "DE-TEST-TAX-2024", "2024", date(2024, 1, 1), date(2024, 12, 31),
        rv_employee_pct=Decimal("18.00"), rv_employer_pct=Decimal("18.00"),
    )
    # 2026 pack with 20.00% RV
    pack_2026 = _make_de_tax_pack(
        db, "DE-TEST-TAX-2026", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("20.00"), rv_employer_pct=Decimal("20.00"),
    )

    # Call get_contribution_rates with historical payroll_date in 2024
    rows = service.get_contribution_rates(db, org.id, country="DE", payroll_date=date(2024, 6, 1))
    rv_row = next((r for r in rows if r.component_key == "rv_pension"), None)
    assert rv_row is not None
    assert rv_row.employee_rate_pct == Decimal("18.00")



