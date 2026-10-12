"""
tests/test_germany_compliance_payroll_integration.py
------------------------------------------------------------
Phase 8CJ — Germany Compliance-to-Payroll Integration & Production-Shaped
Validation.

ARCHITECTURE FINDING THIS FILE PROVES (Section 4 of the phase brief —
"is JurisdictionPack a governance wrapper, or a parent object with
explicit FK associations to registries?"): fresh evidence, not assumed.

    grep "jurisdiction_pack_id" app/modules/payroll/models.py

shows exactly THREE columns reference payroll_jurisdiction_packs.id:
ContributionRate.jurisdiction_pack_id, TaxSlab.jurisdiction_pack_id, and
TaxConfigurationAudit.jurisdiction_pack_id (audit linkage only). NONE of
Germany's 21 Germany-specific registry classes (GermanyHealthFund,
GermanyContributionCeiling, GermanyPvConfiguration,
GermanyMinijobMidijobParameter, GermanyEarningTaxabilityRule,
GermanyOvertimePremiumCategory, GermanyOvertimeGrundlohnCap,
GermanyAccidentInsuranceProfile, GermanyChurchTaxException,
PapAlgorithmAsset, GermanyPapRelease, the ELStAM/ELSTER tables) has a
jurisdiction_pack_id column. Conclusion: USA/UK's OWN architecture only
ever associates a pack with the generic ContributionRate/TaxSlab row
shape (Option B, narrowly) — there is no generic "any registry can
belong to a pack" mechanism in this codebase for ANY country, USA/UK
included. Germany's own richer registries have no USA/UK equivalent to
mirror an FK relationship onto in the first place. The correct answer is
Option A (JurisdictionPack = top-level governance/version metadata,
Germany's registries independently effective-dated) for everything except
the one narrow slice (rv_pension/alv_unemployment/gkv_general) that
already, deliberately, optionally rides the same ContributionRate rails
USA/UK use — Phase 8BJ's mechanism, exercised for real in this file
(TestContributionRateOptIn) rather than merely re-described.

This file builds on, and does not duplicate, existing coverage:
- tests/test_germany_compliance_pack_framework.py (Phase 8CH/8CI) already
  proves the pack's own lifecycle/versioning/effective-dating in isolation.
- tests/test_germany_contribution_rate_effective_dating.py (Phase 8BJ)
  already proves the ContributionRate opt-in mechanism in isolation.
This file proves the two INTEGRATE correctly with a real demo
organization and real demo employees, end to end through an actual
payroll run, and that cross-tenant isolation holds.

Fixtures reused directly from tests/test_germany_contribution_rate_
effective_dating.py (same tests/ package) rather than re-derived — that
file's own helpers (_make_employee, _make_full_profile,
_publish_all_registries, _add_attendance, _run_data, _make_de_tax_pack,
_opt_in, _run_and_get_blocked_trace) are already the established,
working Germany fixture toolkit this whole project's Germany test suite
depends on.

All real statutory VALUES asserted on below (RV 9.30%, ALV 1.30%, GKV
Zusatzbeitrag 1.70%, PV 4.20%/2.40%/1.80% CHILDLESS, PV "1"-child Saxony
2.30%/1.30%, Church Tax Baden-Württemberg 8% general / 9% Bad-Wimpfen
exception, Minijob/Midijob thresholds) were independently confirmed via a
throwaway, isolated (`sqlite:///:memory:`) inspection script THIS phase,
reading the real computed trace — not re-typed from a docstring, not
guessed.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
from app.modules.payroll.hardcoded_defaults import (
    _DE_ALV_EMPLOYEE_RATE, _DE_ALV_EMPLOYER_RATE, _DE_RV_EMPLOYEE_RATE, _DE_RV_EMPLOYER_RATE,
)
from app.modules.payroll.models import CompanyComplianceDetails, PayslipItem, SourceArtifact
from app.modules.payroll.schemas import (
    CanonicalContributionRateUpsert, GermanyChurchTaxExceptionCreate, GermanyPvConfigurationCreate,
    JurisdictionPackUpsert,
)
from app.modules.organizations.models import Organization

from tests.test_germany_contribution_rate_effective_dating import (
    _add_attendance, _make_de_tax_pack, _make_employee, _make_full_profile, _make_source, _opt_in,
    _publish_all_registries, _r2, _run_and_get_blocked_trace, _run_data, _stub_business_code_generation,
)


def _publish_pv_configuration_with_real_2026_rates(db, child_category, is_saxony, maker=1, checker=2):
    """Unlike test_germany_contribution_rate_effective_dating.py's own
    _publish_pv_configuration (deliberately fixed dummy rates for
    mechanism/effective-dating tests, not real statutory values), this
    publishes the REAL 2026 PV matrix values for one (child_category,
    is_saxony) pair — transcribed verbatim from
    scripts/seed_germany_2026_registries.py's own _PV_RATE_MATRIX, not
    invented — so a resolved rate can be checked against the actual 2026
    figure, not an arbitrary test fixture value."""
    real_matrix = {
        ("CHILDLESS", False): ("4.20", "2.40", "1.80", "2.90", "1.30"),
        ("1", True): ("3.60", "1.80", "1.80", "2.30", "1.30"),
    }
    total, std_emp, employer, sax_emp, sax_employer = real_matrix[(child_category, is_saxony)]
    source = _make_source(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category=child_category, is_saxony=is_saxony,
            total_rate_pct=Decimal(total), standard_employee_rate_pct=Decimal(std_emp),
            employer_rate_pct=Decimal(employer), saxony_employee_rate_pct=Decimal(sax_emp),
            saxony_employer_rate_pct=Decimal(sax_employer),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _make_org(db, name="QA-GERMANY-2026-DEMO", code="QAGER2026DEMO"):
    """A completely isolated, obviously-fake demo organization — same
    lightweight ORM construction tests/conftest.py's own `organization`
    fixture already uses; QA-GERMANY-2026-DEMO is never a real customer."""
    org = Organization(organization_name=name, organization_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_de_compliance_details(db, org_id):
    details = CompanyComplianceDetails(organization_id=org_id, jurisdiction_country="DE")
    db.add(details)
    db.commit()
    return details


def _make_de_2026_pack(db, maker=901, checker=902):
    """The real, governed DE-PAYROLL-CY2026-V1 metadata (Phase 8CI),
    recreated here via the real service chain against this test's own
    isolated in-memory database (Phase 8CI's own seed script targets a
    separate, standalone SQLite file — not shared with pytest's isolated
    per-test fixture)."""
    pack = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId="DE-PAYROLL-CY2026-V1", jurisdictionCountry="DE", packType="tax",
            version="1.0", status="Draft", effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31),
            taxYear="2026", currency="EUR",
            regulatoryAuthority="Bundesministerium der Finanzen (BMF) / ITZBund",
        ), actor_id=maker,
    )
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=checker)
    return service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=checker)


# ══════════════════════════════════════════════════════════════════════════
# 1. Demo organization + governed pack assignment (Section 6)
# ══════════════════════════════════════════════════════════════════════════

def test_demo_organization_eligible_and_assignable_via_real_service(db):
    org = _make_org(db)
    _make_de_compliance_details(db, org.id)
    pack = _make_de_2026_pack(db)

    eligible = service.get_organizations_eligible_for_pack(db, pack.id)
    assert any(o["id"] == org.id for o in eligible), "QA-GERMANY-2026-DEMO must be eligible for a country-level DE pack"

    # The actual governed service — never a direct DB write, per phase brief §6.
    service.assign_pack_to_organizations(db, pack.id, [org.id], actor_id=902)

    assigned = service.get_pack_applicable_organizations(db, pack.id)
    assert any(o["id"] == org.id for o in assigned)

    details = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == org.id).first()
    assert details.active_pack_id == pack.id

    # Audit trail — assignment itself doesn't call record_tax_audit today
    # (assign_pack_to_organizations only touches CompanyComplianceDetails,
    # not JurisdictionPack/ContributionRate/TaxSlab); the pack's own
    # create/approve/activate lifecycle IS audited, confirmed here rather
    # than assumed.
    entries = service.list_tax_configuration_audit(db, jurisdiction_pack_id=pack.id)
    assert {"create", "status_change"}.issubset({e.action for e in entries})


def test_pack_visible_and_resolvable_from_organization_context(db):
    org = _make_org(db)
    _make_de_compliance_details(db, org.id)
    pack = _make_de_2026_pack(db)
    service.assign_pack_to_organizations(db, pack.id, [org.id], actor_id=902)

    details = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == org.id).first()
    assert details.active_pack_id == pack.id

    _, _, resolved = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=date(2026, 6, 15))
    assert resolved.id == pack.id


# ══════════════════════════════════════════════════════════════════════════
# 2. Demo employees (Section 7) + regular payroll integration (Section 8)
# ══════════════════════════════════════════════════════════════════════════

def test_regular_employee_full_payroll_integration_gross_to_net_components(db, monkeypatch):
    """Employee A — regular employment. Proves the compliance/pack
    framework does not bypass or conflict with Germany's own resolver
    chain: gross -> RV -> ALV -> GKV -> PV -> wage tax/Soli, all COMPLETE,
    using the real (unmodified) registry resolvers. No JurisdictionPack
    opt-in is active here — this is the pre-8BJ, still-correct hardcoded
    path, proving the compliance pack's mere existence never interferes
    with an organization that hasn't opted in (see also
    TestContributionRateOptIn below for the opted-in path)."""
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db)
    emp = _make_employee(db, org.id, code="DE-QA-REGULAR", gross=4000)
    _make_full_profile(db, emp, org.id, de_tax_class="I", de_church_tax_liable=False)
    _publish_all_registries(db)
    _add_attendance(db, org.id, emp.id)

    trace = _run_and_get_blocked_trace(db, emp.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    assert trace["calculationStatus"] == "COMPLETE"
    assert trace["unavailableComponents"] == []

    gross = Decimal("4000.00")
    assert Decimal(trace["resolved"]["rv"]["employee"]) == _r2(gross * _DE_RV_EMPLOYEE_RATE / 100)
    assert Decimal(trace["resolved"]["rv"]["employer"]) == _r2(gross * _DE_RV_EMPLOYER_RATE / 100)
    assert Decimal(trace["resolved"]["alv"]["employee"]) == _r2(gross * _DE_ALV_EMPLOYEE_RATE / 100)
    # GKV resolved via the real published health-fund registry (CR-FUND,
    # 1.7000% Zusatzbeitrag) — independently confirmed this phase via a
    # throwaway isolated inspection run, not guessed.
    assert Decimal(trace["resolved"]["gkv"]["employee"]) == Decimal("326.00")
    assert trace["healthFundId"] == "CR-FUND"
    assert trace["healthFundSupplementaryRatePct"] == "1.7000"
    assert trace["pvChildCategory"] == "CHILDLESS"
    assert trace["pvIsSaxony"] is False
    assert Decimal(trace["resolved"]["pv"]["employee"]) == _r2(gross * Decimal("2.40") / 100)
    assert Decimal(trace["resolved"]["pv"]["employer"]) == _r2(gross * Decimal("1.80") / 100)
    # Wage tax / Soli — internal functional calculator (PAP still fail-closed).
    assert trace["papVersion"] == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2026"
    assert "internal_wage_tax" in trace["resolved"]
    assert any("INTERNAL_FUNCTIONAL_REFERENCE" in w for w in trace["warnings"])
    assert any("not the certified bmf" in w.lower() for w in trace["warnings"]), \
        "wage tax result must explicitly disclose it is not BMF-certified"


def test_health_fund_resolution_no_cross_tenant_leakage(db, monkeypatch):
    """Section 10 — exercises the real seeded/published health-fund
    registry via two organizations, confirming both independently resolve
    the SAME global (non-org-scoped, per Phase 8CH's own architecture
    finding) fund record correctly, with no state bleeding between the two
    payroll runs."""
    _stub_business_code_generation(monkeypatch)
    org_a = _make_org(db, "QA-GERMANY-2026-DEMO-A", "QAGERDEMOA")
    org_b = _make_org(db, "QA-GERMANY-2026-DEMO-B", "QAGERDEMOB")
    _publish_all_registries(db)

    emp_a = _make_employee(db, org_a.id, code="DE-HF-A", gross=3500)
    _make_full_profile(db, emp_a, org_a.id, de_health_fund_code="CR-FUND")
    _add_attendance(db, org_a.id, emp_a.id)
    emp_b = _make_employee(db, org_b.id, code="DE-HF-B", gross=3500)
    _make_full_profile(db, emp_b, org_b.id, de_health_fund_code="CR-FUND")
    _add_attendance(db, org_b.id, emp_b.id)

    trace_a = _run_and_get_blocked_trace(db, emp_a.id, org_a.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    trace_b = _run_and_get_blocked_trace(db, emp_b.id, org_b.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    for trace in (trace_a, trace_b):
        assert trace["healthFundId"] == "CR-FUND"
        assert trace["healthFundSupplementaryRatePct"] == "1.7000"
        assert trace["healthFundEffectiveFrom"] == "2025-01-01"
        assert Decimal(trace["resolved"]["gkv"]["employee"]) == Decimal(trace_a["resolved"]["gkv"]["employee"])
    assert trace_a["employeeId"] != trace_b["employeeId"]
    assert trace_a["organizationId"] != trace_b["organizationId"]


# ══════════════════════════════════════════════════════════════════════════
# 3. PV — standard, one-child, Saxony (Section 11)
# ══════════════════════════════════════════════════════════════════════════

def test_pv_standard_one_child_and_saxony_resolve_correctly(db, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db)
    _publish_all_registries(db)  # CHILDLESS, non-Saxony (real 2026 rate, via the shared fixture helper)
    _publish_pv_configuration_with_real_2026_rates(db, "1", True)  # one-child, Saxony

    emp_standard = _make_employee(db, org.id, code="DE-PV-STD", gross=4000)
    _make_full_profile(db, emp_standard, org.id, de_child_count=0, de_childless=True, de_saxony=False)
    _add_attendance(db, org.id, emp_standard.id)
    trace_std = _run_and_get_blocked_trace(db, emp_standard.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace_std["pvChildCategory"] == "CHILDLESS"
    assert trace_std["pvIsSaxony"] is False
    assert Decimal(trace_std["resolved"]["pv"]["employee"]) == _r2(Decimal("4000.00") * Decimal("2.40") / 100)

    emp_1child_sax = _make_employee(db, org.id, code="DE-PV-1CHILD-SAX", gross=4000)
    _make_full_profile(db, emp_1child_sax, org.id, de_child_count=1, de_childless=False, de_saxony=True)
    _add_attendance(db, org.id, emp_1child_sax.id)
    trace_sax = _run_and_get_blocked_trace(db, emp_1child_sax.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace_sax["pvChildCategory"] == "1"
    assert trace_sax["pvIsSaxony"] is True
    # Real seeded 2026 matrix: "1"-child Saxony employee rate 2.30%, employer 1.30%.
    assert Decimal(trace_sax["resolved"]["pv"]["employee"]) == _r2(Decimal("4000.00") * Decimal("2.30") / 100)
    assert Decimal(trace_sax["resolved"]["pv"]["employer"]) == _r2(Decimal("4000.00") * Decimal("1.30") / 100)

    # Direct resolver proof (Section 11) — independent of the engine wiring above.
    resolved_std = service.resolve_germany_pv_configuration(db, "CHILDLESS", False, as_of=date(2026, 6, 1))
    assert resolved_std.standard_employee_rate_pct == Decimal("2.4000")
    resolved_sax = service.resolve_germany_pv_configuration(db, "1", True, as_of=date(2026, 6, 1))
    assert resolved_sax.saxony_employee_rate_pct == Decimal("2.3000")


# ══════════════════════════════════════════════════════════════════════════
# 4. Church Tax — 9% Land, 8% Baden-Württemberg, Bad Wimpfen exception (Section 12/17)
# ══════════════════════════════════════════════════════════════════════════

def _publish_bad_wimpfen_exception(db, maker=1, checker=2):
    source = SourceArtifact(agency="Test Fixture", title="Bad Wimpfen test fixture evidence", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    row = service.create_germany_church_tax_exception_record(
        db, GermanyChurchTaxExceptionCreate(
            land_code="DE-BW", denomination="ROMAN_CATHOLIC", municipality_postal_code="74206",
            scope_description="Bad Wimpfen — Diocese of Mainz enclave in BW (test fixture, mirrors real seed data).",
            exception_rate_pct=Decimal("9.00"), effective_from=date(2016, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_germany_church_tax_exception_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_germany_church_tax_exception_approver(db, row.id, actor_id=checker)
    return service.set_germany_church_tax_exception_status(db, row.id, "PUBLISHED", actor_id=checker)


def test_church_tax_land_rate_and_bad_wimpfen_exception(db, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db)
    _publish_all_registries(db)
    _publish_bad_wimpfen_exception(db)

    # A 9%-Land employee (Bremen/HB is 9% per CHURCH_TAX_LAND_RATES) — no exception involved.
    emp_9 = _make_employee(db, org.id, code="DE-CT-HB", gross=3000)
    _make_full_profile(db, emp_9, org.id, de_church_tax_liable=True, de_church_tax_land="DE-HB")
    _add_attendance(db, org.id, emp_9.id)
    trace_9 = _run_and_get_blocked_trace(db, emp_9.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace_9["churchTaxRateUsed"] == "9"

    # Plain Baden-Württemberg employee — general 8%, no exception fields set.
    emp_bw = _make_employee(db, org.id, code="DE-CT-BW-PLAIN", gross=3000)
    _make_full_profile(db, emp_bw, org.id, de_church_tax_liable=True, de_church_tax_land="DE-BW")
    _add_attendance(db, org.id, emp_bw.id)
    trace_bw = _run_and_get_blocked_trace(db, emp_bw.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace_bw["churchTaxRateUsed"] == "8"

    # Bad Wimpfen employee — same Land, but the exact (Land, denomination,
    # postal code) tuple the published exception covers -> 9%, not BW's 8%.
    emp_bad_wimpfen = _make_employee(db, org.id, code="DE-CT-BAD-WIMPFEN", gross=3000)
    _make_full_profile(
        db, emp_bad_wimpfen, org.id, de_church_tax_liable=True, de_church_tax_land="DE-BW",
        de_church_tax_denomination="ROMAN_CATHOLIC", de_church_tax_municipality_postal_code="74206",
    )
    _add_attendance(db, org.id, emp_bad_wimpfen.id)
    trace_exc = _run_and_get_blocked_trace(db, emp_bad_wimpfen.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace_exc["churchTaxRateUsed"] == "9.00"
    assert any("EXCEPTION" in step for step in trace_exc["steps"])

    # Direct resolver proof, independent of engine wiring.
    exception_row = service.resolve_germany_church_tax_exception(
        db, "DE-BW", "ROMAN_CATHOLIC", "74206", as_of=date(2026, 6, 1),
    )
    assert exception_row is not None
    assert exception_row.exception_rate_pct == Decimal("9.00")
    # A denomination/postal-code combination the exception does NOT cover
    # must fall back to the ordinary Land rate (fail-closed-to-the-ordinary
    # -rate design, per the resolver's own docstring) — not None, not 9%.
    assert service.resolve_germany_church_tax_exception(db, "DE-BW", "PROTESTANT", "74206", as_of=date(2026, 6, 1)) is None


# ══════════════════════════════════════════════════════════════════════════
# 5. Minijob (Section 13) and Midijob (Section 14)
# ══════════════════════════════════════════════════════════════════════════

def test_minijob_calculation_uses_existing_2026_registry_unchanged(db, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db)
    emp = _make_employee(db, org.id, code="DE-QA-MINIJOB", gross=520)
    _make_full_profile(db, emp, org.id, de_employment_classification="MINIJOB", de_church_tax_liable=False)
    _add_attendance(db, org.id, emp.id)

    trace = _run_and_get_blocked_trace(db, emp.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace["calculationStatus"] == "COMPLETE"
    assert trace["employmentClassification"] == "MINIJOB"
    assert Decimal(trace["monthlyGrossUsed"]) == Decimal("520.00")
    assert Decimal(trace["monthlyGrossUsed"]) < Decimal("603.00"), "must stay under the 2026 Minijob upper threshold for flat treatment to apply"
    resolved = trace["resolved"]
    assert Decimal(resolved["minijob_employer"]["health"]) == _r2(Decimal("520.00") * Decimal("13") / 100)
    assert Decimal(resolved["minijob_employer"]["pension"]) == _r2(Decimal("520.00") * Decimal("15") / 100)
    assert Decimal(resolved["minijob_employee"]["pension_topup"]) == _r2(Decimal("520.00") * Decimal("3.60") / 100)
    assert Decimal(resolved["minijob_tax"]["flat_tax_employer_remitted"]) == _r2(Decimal("520.00") * Decimal("2") / 100)
    assert "u1" in resolved["minijob_employer"] and "u2" in resolved["minijob_employer"] and "u3" in resolved["minijob_employer"]
    # Church tax is explicitly NOT SPECIFIED for the Minijob flat-tax
    # treatment (Pauschsteuer subsumes it) — proven, not assumed.
    assert any("NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION" in step for step in trace["steps"] if "Church tax" in step)


def test_midijob_calculation_uses_existing_2026_transition_corridor(db, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db)
    _publish_all_registries(db)
    emp = _make_employee(db, org.id, code="DE-QA-MIDIJOB", gross=1500)
    _make_full_profile(db, emp, org.id, de_employment_classification="MIDIJOB", de_church_tax_liable=False)
    _add_attendance(db, org.id, emp.id)

    trace = _run_and_get_blocked_trace(db, emp.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert trace["calculationStatus"] == "COMPLETE"
    assert trace["employmentClassification"] == "MIDIJOB"
    assert Decimal("603.00") < Decimal(trace["monthlyGrossUsed"]) < Decimal("2000.00"), "must stay inside the 2026 Midijob corridor"
    assert trace["midijobTotalContributionBase"] is not None
    assert trace["midijobEmployeeContributionBase"] is not None
    # The reduced employee contribution base must be strictly less than the
    # employer's total contribution base — the entire point of the Midijob
    # corridor's employee-favoring sliding scale.
    assert Decimal(trace["midijobEmployeeContributionBase"]) < Decimal(trace["midijobTotalContributionBase"])
    resolved = trace["resolved"]
    for branch in ("midijob_rv", "midijob_alv", "midijob_gkv"):
        assert Decimal(resolved[branch]["employee"]) < Decimal(resolved[branch]["employer"]), \
            f"{branch} employee share should be reduced relative to employer's under the Midijob corridor"
    # PV is the one branch where the childless surcharge can push the
    # employee share above the employer's — not a defect, so not asserted
    # the same way as the other three branches.
    assert "employee" in resolved["midijob_pv"] and "employer" in resolved["midijob_pv"]
    # Confirms Midijob resolves ceilings/health-fund/PV from the SAME
    # global registries Regular uses — no separate Midijob-only config path.
    assert trace["ceilingRvAlvId"] is not None
    assert trace["healthFundId"] == "CR-FUND"


# ══════════════════════════════════════════════════════════════════════════
# 6. Phase 8BJ ContributionRate canonical opt-in, exercised against the
#    demo organization (Section 9/20)
# ══════════════════════════════════════════════════════════════════════════

def test_contribution_rate_opt_in_overrides_hardcoded_default_for_the_opted_in_org(db, monkeypatch):
    """Isolated to a single org + single canonical pack, matching
    test_germany_contribution_rate_effective_dating.py's own established
    pattern exactly (its opt-in and not-opted-in scenarios are always
    separate tests, never combined — see the next test's docstring for
    why combining them is unsafe)."""
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db, "QA-GERMANY-2026-DEMO-A", "QAGERDEMOA2")
    _publish_all_registries(db)

    pack = _make_de_tax_pack(
        db, "DE-TEST-TAX-8CJ", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("10.00"), rv_employer_pct=Decimal("11.00"),
    )
    _opt_in(db, org.id, pack)

    emp = _make_employee(db, org.id, code="DE-OPTIN-A", gross=4000)
    _make_full_profile(db, emp, org.id)
    _add_attendance(db, org.id, emp.id)
    trace = _run_and_get_blocked_trace(db, emp.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert Decimal(trace["resolved"]["rv"]["employee"]) == Decimal("400.00")  # 4000 * 10.00% TEST override


def test_canonical_pack_auto_seed_is_not_opt_in_gated_pre_existing_finding(db, monkeypatch):
    """A genuine, freshly-reconfirmed finding, not a test bug — this is
    NOT the assign_pack_to_organizations opt-in path itself (proven above
    and in test_germany_compliance_pack_framework.py), it is a SEPARATE,
    pre-existing, cross-jurisdiction mechanism Phase 8BJ already
    documented and explicitly did NOT fix (see that phase's own
    test_first_use_auto_seed_is_not_date_aware and its report's
    disclosure): get_contribution_rates()'s first-use auto-seed
    (_seed_org_rates_for_country -> sync_org_rates_from_canonical, called
    with no opt-in check at all — see service.py:167-226) copies ANY
    Active canonical tax pack's rates into ANY org's own permanent rows
    the first time that org has zero DE rate rows, REGARDLESS of whether
    that org was ever explicitly assigned via assign_pack_to_organizations.

    This was first discovered by this phase's own initial (incorrect) test
    draft, which combined an opted-in org and a never-opted-in org in one
    test expecting isolation — it failed because org B's payroll ALSO
    auto-seeded from the same canonical pack the moment its own first
    payroll ran, purely because a canonical DE pack existed in the
    database at all, not because of anything org-specific. Documented
    here explicitly rather than silently avoided, per this project's own
    disclosure discipline — NOT fixed in this phase (cross-jurisdiction
    blast radius, needs separate authorization, exactly as Phase 8BJ's
    own report already concluded)."""
    _stub_business_code_generation(monkeypatch)
    org_never_assigned = _make_org(db, "QA-GERMANY-2026-DEMO-B", "QAGERDEMOB2")
    _publish_all_registries(db)

    _make_de_tax_pack(
        db, "DE-TEST-TAX-8CJ-AUTOSEED", "2026", date(2026, 1, 1), None,
        rv_employee_pct=Decimal("10.00"), rv_employer_pct=Decimal("11.00"),
    )
    # Deliberately never call assign_pack_to_organizations/_opt_in for this org.

    emp = _make_employee(db, org_never_assigned.id, code="DE-OPTIN-B", gross=4000)
    _make_full_profile(db, emp, org_never_assigned.id)
    _add_attendance(db, org_never_assigned.id, emp.id)
    trace = _run_and_get_blocked_trace(db, emp.id, org_never_assigned.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    # This is the auto-seed behavior, not the hardcoded default — asserted
    # explicitly (not just "not equal to hardcoded") so a future fix to
    # this gap makes this test fail loudly rather than silently pass.
    assert Decimal(trace["resolved"]["rv"]["employee"]) == Decimal("400.00")
    assert Decimal(trace["resolved"]["rv"]["employee"]) != _r2(Decimal("4000.00") * _DE_RV_EMPLOYEE_RATE / 100)


def test_org_with_zero_canonical_packs_in_its_database_uses_hardcoded_default(db, monkeypatch):
    """The TRUE 'not opted in' baseline — no canonical DE tax pack exists
    anywhere in this test's database at all, so there is nothing for the
    auto-seed mechanism above to seed from; this is the scenario every
    real, current Germany organization is actually in today (no Germany
    canonical pack has ever been created in any real environment)."""
    _stub_business_code_generation(monkeypatch)
    org = _make_org(db, "QA-GERMANY-2026-DEMO-C", "QAGERDEMOC2")
    _publish_all_registries(db)

    emp = _make_employee(db, org.id, code="DE-NOOPTIN-C", gross=4000)
    _make_full_profile(db, emp, org.id)
    _add_attendance(db, org.id, emp.id)
    trace = _run_and_get_blocked_trace(db, emp.id, org.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    assert Decimal(trace["resolved"]["rv"]["employee"]) == _r2(Decimal("4000.00") * _DE_RV_EMPLOYEE_RATE / 100)


# ══════════════════════════════════════════════════════════════════════════
# 7. Cross-tenant isolation (Section 16)
# ══════════════════════════════════════════════════════════════════════════

def test_cross_tenant_isolation_compliance_and_employees(db, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    org_a = _make_org(db, "QA-GERMANY-2026-DEMO-A", "QAGERDEMOA3")
    org_b = _make_org(db, "QA-GERMANY-2026-DEMO-B", "QAGERDEMOB3")
    _make_de_compliance_details(db, org_a.id)
    _make_de_compliance_details(db, org_b.id)
    pack = _make_de_2026_pack(db)
    service.assign_pack_to_organizations(db, pack.id, [org_a.id], actor_id=902)

    assigned = service.get_pack_applicable_organizations(db, pack.id)
    assigned_ids = {o["id"] for o in assigned}
    assert org_a.id in assigned_ids
    assert org_b.id not in assigned_ids, "org B must not appear as assigned to a pack only org A opted into"

    details_a = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == org_a.id).first()
    details_b = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == org_b.id).first()
    assert details_a.active_pack_id == pack.id
    assert details_b.active_pack_id is None, "org B's own compliance record must be untouched by org A's assignment"

    _publish_all_registries(db)
    emp_a = _make_employee(db, org_a.id, code="DE-ISO-A", gross=4200)
    _make_full_profile(db, emp_a, org_a.id)
    _add_attendance(db, org_a.id, emp_a.id)
    emp_b = _make_employee(db, org_b.id, code="DE-ISO-B", gross=4200)
    _make_full_profile(db, emp_b, org_b.id)
    _add_attendance(db, org_b.id, emp_b.id)

    run_a = service.create_payroll_run(
        db, created_by=1,
        data=_run_data([emp_a.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=org_a.id,
    )
    # Org B's payroll items must be scoped to org B only — no cross-tenant read.
    items_b_scope = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run_a.id, PayslipItem.employee_id == emp_b.id).all()
    assert items_b_scope == [], "org A's payroll run must never contain org B's employee"

    audit_a = service.list_tax_configuration_audit(db, jurisdiction_pack_id=pack.id)
    # The pack itself is a single shared jurisdiction-level record (by
    # design, per Phase 8CH — packs describe a jurisdiction, not an org),
    # so its OWN audit trail is legitimately visible platform-wide; what
    # must NOT leak is org-scoped data (employees/payslips), asserted above.
    assert all(e.jurisdiction_pack_id == pack.id for e in audit_a)


# ══════════════════════════════════════════════════════════════════════════
# 8. Effective-date resolution re-confirmed in this integration context
#    (Section 15) — five required boundary dates.
# ══════════════════════════════════════════════════════════════════════════

def test_effective_date_boundaries_de_pack_and_org_context(db):
    org = _make_org(db)
    _make_de_compliance_details(db, org.id)
    pack_2026 = _make_de_2026_pack(db)
    service.assign_pack_to_organizations(db, pack_2026.id, [org.id], actor_id=902)

    boundaries_inside = [date(2026, 1, 1), date(2026, 6, 15), date(2026, 12, 31)]
    for d in boundaries_inside:
        _, _, resolved = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=d)
        assert resolved is not None and resolved.id == pack_2026.id, f"{d} must resolve to the 2026 pack"

    boundaries_outside = [date(2025, 12, 31), date(2027, 1, 1)]
    for d in boundaries_outside:
        _, _, resolved = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=d)
        assert resolved is None, f"{d} must NOT resolve to the 2026 pack (outside its effective range)"
