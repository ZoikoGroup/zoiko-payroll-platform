"""
tests/test_engine_jurisdiction_db_integration.py
-------------------------------------------------
DB-integration coverage for the legacy jurisdiction-tax-hierarchy upgrade
(Phase 4 of the payroll-engine-upgrade plan). Complements
test_engine_jurisdiction_upgrade.py's calculation-only (hand-rolled
dataclass) tests with real reads/writes against the `db` fixture
(tests/conftest.py's isolated SQLite database):

- canonical vs. org vs. hardcoded-fallback rate/slab resolution
- the state-scoped resolver (get_state_scoped_config)
- multi-region resolution within one org, via real payslip generation
- historical reproducibility: an edit to rates after generation must not
  retroactively change an already-generated payslip
- clean fallback (no crash) for a jurisdiction with no configuration at all
- a boundary value exactly at a configured threshold (ESI wage ceiling)
"""

from decimal import Decimal

from datetime import date

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, TaxSlab, PayrollEmployee, PayrollRun, PayslipItem, JurisdictionPack,
    CompanyComplianceDetails, EmployerTaxProfile, LocalityDataset, LocalityRate, TaxConfigurationAudit,
    EmployeeEstablishment, SourceArtifact, PayrollAttendanceRecord, TaxabilityRule,
)
from app.modules.payroll.schemas import (
    EmployeeCreate, EmployerTaxProfileUpsert, ReciprocityRuleUpsert, LocalityRateUpsert, SourceArtifactCreate,
)


def _make_rate(country, component_key, organization_id=None, state=None, flat_amount=None, rate_pct=None, tax_regime=None, locality=None):
    return ContributionRate(
        organization_id=organization_id,
        jurisdiction_country=country,
        jurisdiction_state=state,
        jurisdiction_locality=locality,
        tax_regime=tax_regime,
        component_key=component_key,
        label=component_key,
        employee_share="—", employer_share="—", total="—",
        flat_amount=flat_amount, employee_rate_pct=rate_pct,
    )


def _make_employee(db, org_id, code, country="IN", work_state=None, ctc=Decimal("600000"), tax_regime=None):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code=country, work_state=work_state, ctc=ctc, tax_regime=tax_regime,
        basic=ctc * Decimal("0.5"), hra=ctc * Decimal("0.2"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_pt_bracket(country, state, min_amount, max_amount, flat_amount, locality=None, assessment_basis=None):
    return TaxSlab(
        organization_id=None, jurisdiction_country=country, jurisdiction_state=state,
        jurisdiction_locality=locality, assessment_basis=assessment_basis,
        min_amount=min_amount, max_amount=max_amount, rate_pct=Decimal("0"), rate_label="PT",
        tax_formula="", rule_type="PT_FLAT", flat_amount=flat_amount,
    )


def _make_employee_with_monthly_gross(db, org_id, code, monthly_gross, country="IN", work_state=None):
    # basic/hra deliberately left unset — _compute_payslip_values then
    # derives basic/hra/special from the org's salary-split percentages
    # and reconstructs the remainder into "special", so gross always comes
    # out to exactly ctc/12, letting a boundary test target gross directly.
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code=country, work_state=work_state, ctc=monthly_gross * 12,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_active_tax_pack(db, country, state=None, pack_id="TEST-PACK-V1"):
    """A minimal Active canonical tax pack — required for
    resolve_tax_configuration/_find_active_tax_pack to pick up a
    canonical ContributionRate/TaxSlab row via its jurisdiction_pack_id.
    (get_state_scoped_config, by contrast, reads ContributionRate/TaxSlab
    directly by country+state and needs no pack at all.)"""
    pack = JurisdictionPack(
        pack_id=pack_id, jurisdiction_country=country, jurisdiction_state=state,
        pack_type="tax", version="1.0", status="Active",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def _make_run(db, org_id, period_start, period_end, pay_date, label="Test Run"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=period_start, period_end=period_end, pay_date=pay_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ── Canonical vs. org vs. hardcoded-fallback tiering ────────────────────

def test_org_own_rate_wins_even_when_canonical_differs(db, organization):
    # Org already has its own "pt" row (e.g. from a prior manual edit) —
    # get_contribution_rates must return it untouched, even though a
    # canonical row also exists with a different value.
    db.add(_make_rate("IN", "pt", organization_id=organization.id, flat_amount=Decimal("150")))
    db.add(_make_rate("IN", "pt", organization_id=None, flat_amount=Decimal("999")))
    db.commit()

    rows = service.get_contribution_rates(db, organization.id, country="IN")
    pt = next(r for r in rows if r.component_key == "pt")
    assert pt.flat_amount == Decimal("150")


def test_canonical_rate_seeds_org_on_first_use(db, organization):
    # Org has zero rows for this country; a canonical row exists (linked to
    # an Active tax pack, exactly as Super Admin's "Apply Tax & Sync Rates"
    # flow creates them) with a value that differs from the hardcoded
    # default (hardcoded India "pt" default is 200) — first read must seed
    # the org from canonical, not from the hardcoded dict.
    pack = _make_active_tax_pack(db, "IN")
    rate = _make_rate("IN", "pt", organization_id=None, flat_amount=Decimal("300"))
    rate.jurisdiction_pack_id = pack.id
    db.add(rate)
    db.commit()

    rows = service.get_contribution_rates(db, organization.id, country="IN")
    pt = next(r for r in rows if r.component_key == "pt")
    assert pt.flat_amount == Decimal("300")
    assert pt.organization_id == organization.id  # seeded as the org's own row


def test_hardcoded_fallback_when_no_canonical_and_no_org_row(db, organization):
    # Nothing configured anywhere for this org+country — must fall back to
    # the hardcoded _CONTRIBUTION_RATES_BY_COUNTRY default (India "pt" = 200)
    # instead of returning empty or raising.
    rows = service.get_contribution_rates(db, organization.id, country="IN")
    pt = next(r for r in rows if r.component_key == "pt")
    assert pt.flat_amount == Decimal("200")


def test_unknown_country_falls_back_cleanly_with_no_rows(db, organization):
    # A jurisdiction with zero canonical data AND no hardcoded defaults
    # must not crash — just return an empty list.
    rows = service.get_contribution_rates(db, organization.id, country="ZZ")
    assert rows == []
    slabs = service.get_tax_slabs(db, organization.id, country="ZZ")
    assert slabs == []


# ── State-scoped resolver ────────────────────────────────────────────────

def test_state_scoped_config_resolves_seeded_state_only(db, organization):
    db.add(_make_rate("IN", "pt", organization_id=None, state="Maharashtra", flat_amount=Decimal("200")))
    db.add(_make_rate("IN", "pt", organization_id=None, state="Karnataka", flat_amount=Decimal("300")))
    db.commit()

    mh_rates, mh_slabs = service.get_state_scoped_config(db, "IN", "Maharashtra")
    assert mh_rates["pt"].flat_amount == Decimal("200")

    ka_rates, _ = service.get_state_scoped_config(db, "IN", "Karnataka")
    assert ka_rates["pt"].flat_amount == Decimal("300")

    # A state with nothing seeded resolves to empty, not a crash or a
    # borrowed value from another state.
    empty_rates, empty_slabs = service.get_state_scoped_config(db, "IN", "Gujarat")
    assert empty_rates == {}
    assert empty_slabs == []


def test_state_scoped_config_returns_empty_when_state_is_none(db, organization):
    rates, slabs = service.get_state_scoped_config(db, "IN", None)
    assert rates == {}
    assert slabs == []


def test_state_scoped_config_ignores_org_scoped_rows(db, organization):
    # get_state_scoped_config reads canonical (organization_id IS NULL)
    # rows only — an org-scoped state row must never leak in here, since
    # this resolver is meant to answer "what does Super Admin define for
    # this region," not "what does this one org have."
    db.add(_make_rate("IN", "pt", organization_id=organization.id, state="Maharashtra", flat_amount=Decimal("999")))
    db.commit()

    rates, _ = service.get_state_scoped_config(db, "IN", "Maharashtra")
    assert rates == {}


# ── State-scoped resolver: local-authority PT (§12/§14.1, Phase C) ──────
# Greater Chennai Corporation's own local schedule under Tamil Nadu —
# get_state_scoped_config's `locality` param, added 2026-09-10.

def test_state_scoped_config_locality_specific_row_wins_for_matching_locality(db, organization):
    db.add(_make_pt_bracket("IN", "Tamil Nadu", Decimal("0"), None, Decimal("1250"), locality="Chennai", assessment_basis="HALF_YEAR_INCOME"))
    db.commit()

    chennai_rates, chennai_slabs = service.get_state_scoped_config(db, "IN", "Tamil Nadu", locality="Chennai")
    assert len(chennai_slabs) == 1
    assert chennai_slabs[0].flat_amount == Decimal("1250")
    assert chennai_slabs[0].assessment_basis == "HALF_YEAR_INCOME"


def test_state_scoped_config_locality_row_does_not_leak_to_a_different_locality(db, organization):
    db.add(_make_pt_bracket("IN", "Tamil Nadu", Decimal("0"), None, Decimal("1250"), locality="Chennai"))
    db.commit()

    # Do not create a single statewide Chennai schedule (§14.1's own
    # instruction) — an employee elsewhere in Tamil Nadu (or with no
    # locality at all) must resolve NOTHING, not Chennai's rate.
    coimbatore_rates, coimbatore_slabs = service.get_state_scoped_config(db, "IN", "Tamil Nadu", locality="Coimbatore")
    assert coimbatore_slabs == []
    no_locality_rates, no_locality_slabs = service.get_state_scoped_config(db, "IN", "Tamil Nadu")
    assert no_locality_slabs == []


def test_state_scoped_config_locality_specific_wins_over_statewide_row(db, organization):
    # If a state-wide PT_FLAT row ALSO existed for the same state, an
    # employee's own locality-matching row wins entirely (not merged) —
    # never both summed together.
    db.add(_make_pt_bracket("IN", "Tamil Nadu", Decimal("0"), None, Decimal("200")))            # state-wide
    db.add(_make_pt_bracket("IN", "Tamil Nadu", Decimal("0"), None, Decimal("1250"), locality="Chennai"))  # local
    db.commit()

    chennai_rates, chennai_slabs = service.get_state_scoped_config(db, "IN", "Tamil Nadu", locality="Chennai")
    assert len(chennai_slabs) == 1
    assert chennai_slabs[0].flat_amount == Decimal("1250")

    # A non-Chennai employee in the same state still gets the state-wide row.
    other_rates, other_slabs = service.get_state_scoped_config(db, "IN", "Tamil Nadu", locality="Madurai")
    assert len(other_slabs) == 1
    assert other_slabs[0].flat_amount == Decimal("200")


# ── State/local statutory readiness registry (§16, Phase C) ─────────────

def test_readiness_upsert_creates_new_row(db, organization):
    row = service.upsert_state_local_program_readiness(
        db, "IN", "Karnataka", "STATE_PT", "APPLICABLE", registration_required=True,
    )
    assert row.id is not None
    assert row.legal_status == "APPLICABLE"
    assert row.jurisdiction_locality is None


def test_readiness_upsert_updates_existing_row_instead_of_duplicating(db, organization):
    service.upsert_state_local_program_readiness(db, "IN", "Gujarat", "STATE_PT", "SOURCE_REQUIRED")
    updated = service.upsert_state_local_program_readiness(
        db, "IN", "Gujarat", "STATE_PT", "APPLICABLE", notes="artifact attached",
    )
    rows = service.list_state_local_program_readiness(db, country="IN", state="Gujarat")
    assert len(rows) == 1  # updated in place, not duplicated
    assert rows[0].legal_status == "APPLICABLE"
    assert rows[0].notes == "artifact attached"


def test_readiness_locality_scoped_row_distinct_from_state_row(db, organization):
    service.upsert_state_local_program_readiness(db, "IN", "Tamil Nadu", "LWF", "APPLICABLE")
    service.upsert_state_local_program_readiness(
        db, "IN", "Tamil Nadu", "LOCAL_PT", "APPLICABLE", locality="Chennai", local_authority_required=True,
    )
    rows = service.list_state_local_program_readiness(db, country="IN", state="Tamil Nadu")
    assert len(rows) == 2
    programs = {r.program: r for r in rows}
    assert programs["LWF"].jurisdiction_locality is None
    assert programs["LOCAL_PT"].jurisdiction_locality == "Chennai"
    assert programs["LOCAL_PT"].local_authority_required is True


def test_readiness_list_filters_by_state(db, organization):
    service.upsert_state_local_program_readiness(db, "IN", "Karnataka", "STATE_PT", "APPLICABLE")
    service.upsert_state_local_program_readiness(db, "IN", "Odisha", "STATE_PT", "APPLICABLE")
    ka_rows = service.list_state_local_program_readiness(db, country="IN", state="Karnataka")
    assert len(ka_rows) == 1
    assert ka_rows[0].jurisdiction_state == "Karnataka"


# ── TaxabilityRule CRUD (previously had none — only the read-only ───────
# get_code_wages_classification resolver existed) ────────────────────────

def test_taxability_rule_upsert_creates_and_updates_in_place(db, organization):
    row = service.upsert_taxability_rule(db, "IN", "code_wages", "additional_compensation", True)
    assert row.id is not None
    assert row.is_taxable is True

    updated = service.upsert_taxability_rule(db, "IN", "code_wages", "additional_compensation", False)
    rows = service.list_taxability_rules(db, country="IN", tax_component="code_wages")
    assert len(rows) == 1  # updated in place, not duplicated
    assert updated.is_taxable is False


def test_taxability_rule_delete(db, organization):
    row = service.upsert_taxability_rule(db, "IN", "code_wages", "hra", False)
    service.delete_taxability_rule(db, row.id)
    assert service.list_taxability_rules(db, country="IN", tax_component="code_wages") == []


def test_taxability_rule_delete_missing_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.delete_taxability_rule(db, 999999)


# ── Code Wages classification resolver (ZP-TAX-IN-2026-27-001 §7/§8, Phase B) ──
# get_code_wages_classification backs india.py's _calculate_code_wages —
# see engine/countries/india.py and the "India: Code-wages per-component
# classification" section of service.py for what these rows mean.

def _make_taxability_rule(
    country, earning_type, is_taxable, organization_id=None, tax_component="code_wages",
    effective_from=None, effective_to=None,
):
    return TaxabilityRule(
        jurisdiction_country=country, earning_type=earning_type, tax_component=tax_component,
        is_taxable=is_taxable, organization_id=organization_id,
        effective_from=effective_from, effective_to=effective_to,
    )


def test_code_wages_classification_empty_when_unconfigured(db, organization):
    # No rows at all -> india.py's own default (basic=included, everything
    # else excluded) applies, unchanged from before Phase B.
    assert service.get_code_wages_classification(db, "IN", organization.id) == {}


def test_code_wages_classification_reads_canonical_row(db, organization):
    db.add(_make_taxability_rule("IN", "additional_compensation", True))
    db.commit()
    assert service.get_code_wages_classification(db, "IN", organization.id) == {"additional_compensation": True}


def test_code_wages_classification_org_specific_wins_over_canonical(db, organization):
    db.add(_make_taxability_rule("IN", "hra", False))  # canonical default
    db.add(_make_taxability_rule("IN", "hra", True, organization_id=organization.id))  # this org's override
    db.commit()

    assert service.get_code_wages_classification(db, "IN", organization.id) == {"hra": True}
    # A DIFFERENT org (no override of its own) still sees only the
    # canonical row — one org's override must never leak into another's.
    assert service.get_code_wages_classification(db, "IN", organization.id + 999) == {"hra": False}


def test_code_wages_classification_respects_effective_dates(db, organization):
    db.add(_make_taxability_rule("IN", "overtime", True, effective_from=date(2027, 1, 1)))
    db.commit()

    assert service.get_code_wages_classification(db, "IN", organization.id, as_of=date(2026, 6, 1)) == {}
    assert service.get_code_wages_classification(db, "IN", organization.id, as_of=date(2027, 2, 1)) == {"overtime": True}


def _make_slab(country, min_amount, max_amount, rate_pct, rule_type="MARGINAL_RATE", tax_regime=None, sort_order=0):
    return TaxSlab(
        organization_id=None, jurisdiction_country=country,
        min_amount=min_amount, max_amount=max_amount, rate_pct=rate_pct,
        rate_label=f"{rate_pct}%", tax_formula="", rule_type=rule_type,
        tax_regime=tax_regime, sort_order=sort_order,
    )


# ── India Old/New regime bracket disambiguation (ZP-TAX-IN-2026-27-001) ──
# get_tax_slabs used to return New Regime (tax_regime=NULL) MARGINAL_RATE
# rows CONCATENATED with any Old-regime-tagged rows for the same country,
# for an "Old" regime request — summing two mutually exclusive bracket
# tables together. These tests prove the fix, and that it's a strict
# superset (an employee with no Old-regime data configured, or no regime
# declared at all, sees exactly today's behavior).

def test_get_tax_slabs_old_regime_excludes_new_regime_brackets(db):
    db.add(_make_slab("IN", Decimal("0"), Decimal("400000"), Decimal("0"), sort_order=1))
    db.add(_make_slab("IN", Decimal("400000"), None, Decimal("5"), sort_order=2))
    db.add(_make_slab("IN", Decimal("0"), Decimal("250000"), Decimal("0"), tax_regime="Old", sort_order=11))
    db.add(_make_slab("IN", Decimal("250000"), None, Decimal("5"), tax_regime="Old", sort_order=12))
    db.commit()

    old_slabs = service.get_tax_slabs(db, None, country="IN", tax_regime="Old")
    assert len(old_slabs) == 2
    assert all(s.tax_regime == "Old" for s in old_slabs)
    assert {s.min_amount for s in old_slabs} == {Decimal("0"), Decimal("250000")}


def test_get_tax_slabs_new_regime_unaffected_by_old_regime_rows(db):
    db.add(_make_slab("IN", Decimal("0"), Decimal("400000"), Decimal("0"), sort_order=1))
    db.add(_make_slab("IN", Decimal("400000"), None, Decimal("5"), sort_order=2))
    db.add(_make_slab("IN", Decimal("0"), Decimal("250000"), Decimal("0"), tax_regime="Old", sort_order=11))
    db.commit()

    new_slabs = service.get_tax_slabs(db, None, country="IN", tax_regime="New")
    assert len(new_slabs) == 2
    assert all(s.tax_regime is None for s in new_slabs)


def test_get_tax_slabs_no_old_regime_data_is_unaffected_strict_superset(db):
    # No Old-regime rows configured at all (today's actual live state) —
    # requesting "Old" must fall back to exactly the NULL/shared rows,
    # never an empty result.
    db.add(_make_slab("IN", Decimal("0"), Decimal("400000"), Decimal("0"), sort_order=1))
    db.add(_make_slab("IN", Decimal("400000"), None, Decimal("5"), sort_order=2))
    db.commit()

    old_slabs = service.get_tax_slabs(db, None, country="IN", tax_regime="Old")
    assert len(old_slabs) == 2


def test_get_tax_slabs_surcharge_tiers_not_excluded_by_bracket_disambiguation(db):
    # SURCHARGE rows are additive-override (only the top tier differs by
    # regime), unlike MARGINAL_RATE brackets — an Old-regime request must
    # get the shared tiers AND its own extra top tier, not just the top one.
    db.add(_make_slab("IN", Decimal("0"), Decimal("400000"), Decimal("0"), sort_order=1))
    db.add(_make_slab("IN", Decimal("400000"), None, Decimal("5"), sort_order=2))
    db.add(_make_slab("IN", Decimal("0"), Decimal("250000"), Decimal("0"), tax_regime="Old", sort_order=11))
    db.add(_make_slab("IN", Decimal("250000"), None, Decimal("5"), tax_regime="Old", sort_order=12))
    db.add(_make_slab("IN", Decimal("5000000"), None, Decimal("10"), rule_type="SURCHARGE", sort_order=21))
    db.add(_make_slab("IN", Decimal("50000000"), None, Decimal("37"), rule_type="SURCHARGE", tax_regime="Old", sort_order=24))
    db.commit()

    old_slabs = service.get_tax_slabs(db, None, country="IN", tax_regime="Old")
    surcharge_rows = [s for s in old_slabs if s.rule_type == "SURCHARGE"]
    assert len(surcharge_rows) == 2, "old regime must see both the shared 10% tier and its own 37% tier"
    bracket_rows = [s for s in old_slabs if s.rule_type == "MARGINAL_RATE"]
    assert len(bracket_rows) == 2, "old regime must see only its own 2 brackets, not the new regime's 2 as well"


def test_resolve_tax_configuration_regime_disambiguation_within_one_pack(db):
    # Reproduces a real live bug found on org 1 (2 real India employees,
    # canonical-pack opted in): a single JurisdictionPack held BOTH New
    # Regime (tax_regime=None) and Old Regime (tax_regime="Old")
    # MARGINAL_RATE rows — resolve_tax_configuration used to return every
    # row attached to the pack with NO row-level regime filtering at all,
    # so an employee's tax got computed off 11 summed brackets from two
    # incompatible tables instead of the correct 7 (New) or 4 (Old).
    # get_tax_slabs (the legacy path) already had this exact class of fix
    # for its own callers; this covers the SEPARATE canonical-pack path.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "IN", pack_id="IN-REGIME-TEST")
    for min_a, max_a, rate in [(0, 400000, 0), (400000, 800000, 5), (800000, None, 10)]:
        s = _make_slab("IN", Decimal(min_a), Decimal(max_a) if max_a else None, Decimal(rate))
        s.jurisdiction_pack_id = pack.id
        db.add(s)
    for min_a, max_a, rate in [(0, 250000, 0), (250000, None, 30)]:
        s = _make_slab("IN", Decimal(min_a), Decimal(max_a) if max_a else None, Decimal(rate), tax_regime="Old")
        s.jurisdiction_pack_id = pack.id
        db.add(s)
    db.commit()

    _, new_slabs, new_pack = resolve_tax_configuration(db, "IN", tax_regime=None, payroll_date=date(2026, 9, 1))
    assert new_pack.id == pack.id
    assert len(new_slabs) == 3, "unset regime must resolve to exactly the New Regime's 3 brackets, not 5"
    assert all(s.tax_regime is None for s in new_slabs)

    _, old_slabs, old_pack = resolve_tax_configuration(db, "IN", tax_regime="Old", payroll_date=date(2026, 9, 1))
    assert len(old_slabs) == 2, "Old regime must resolve to exactly its own 2 brackets, not summed with New's 3"
    assert all(s.tax_regime == "Old" for s in old_slabs)


def test_resolve_tax_configuration_contribution_rates_also_regime_filtered(db):
    # resolve_tax_configuration used to return EVERY ContributionRate row
    # on the pack unconditionally, with NO row-level regime filtering at
    # all (unlike TaxSlab rows just above) — a caller building a plain
    # {component_key: row} dict from that unfiltered list would let
    # whichever row happened to sort last silently win for every
    # employee, regardless of their actual regime. A real live example:
    # standard_deduction (75,000 New / 50,000 Old) both tagged on the
    # same pack.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "IN", pack_id="IN-RATE-REGIME-TEST")
    new_row = _make_rate("IN", "standard_deduction", flat_amount=Decimal("75000"), tax_regime="New")
    new_row.jurisdiction_pack_id = pack.id
    old_row = _make_rate("IN", "standard_deduction", flat_amount=Decimal("50000"), tax_regime="Old")
    old_row.jurisdiction_pack_id = pack.id
    shared_row = _make_rate("IN", "cess_pct", flat_amount=Decimal("4"))
    shared_row.jurisdiction_pack_id = pack.id
    db.add_all([new_row, old_row, shared_row])
    db.commit()

    new_rates, _, _ = resolve_tax_configuration(db, "IN", tax_regime="New", payroll_date=date(2026, 9, 1))
    new_by_key = {r.component_key: r for r in new_rates}
    assert new_by_key["standard_deduction"].flat_amount == Decimal("75000")
    assert "cess_pct" in new_by_key

    old_rates, _, _ = resolve_tax_configuration(db, "IN", tax_regime="Old", payroll_date=date(2026, 9, 1))
    old_by_key = {r.component_key: r for r in old_rates}
    assert old_by_key["standard_deduction"].flat_amount == Decimal("50000")
    assert "cess_pct" in old_by_key


def test_regime_label_normalization_matches_wordier_synced_labels(db):
    # A row synced verbatim from a canonical pack (or entered through a
    # free-text Super Admin field) can carry a wordier label than the
    # short "New"/"Old" this engine always resolves with — a live example
    # found on India's canonical pf/esi rows, tagged "New Tax Regime".
    # A plain `==` comparison would silently exclude these; the resolver
    # must still match them via _normalize_regime_label.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "IN", pack_id="IN-LABEL-NORM-TEST")
    pf_row = _make_rate("IN", "pf", rate_pct=Decimal("12"), tax_regime="New Tax Regime")
    pf_row.jurisdiction_pack_id = pack.id
    old_row = _make_rate("IN", "standard_deduction", flat_amount=Decimal("50000"), tax_regime="Old Tax Regime")
    old_row.jurisdiction_pack_id = pack.id
    db.add_all([pf_row, old_row])
    db.commit()

    new_rates, _, _ = resolve_tax_configuration(db, "IN", tax_regime="New", payroll_date=date(2026, 9, 1))
    assert any(r.component_key == "pf" for r in new_rates), "'New Tax Regime' must still match 'New'"
    assert not any(r.component_key == "standard_deduction" for r in new_rates), "Old-tagged row must not leak into New"

    old_rates, _, _ = resolve_tax_configuration(db, "IN", tax_regime="Old", payroll_date=date(2026, 9, 1))
    assert any(r.component_key == "standard_deduction" for r in old_rates), "'Old Tax Regime' must still match 'Old'"
    assert not any(r.component_key == "pf" for r in old_rates), "New-tagged row must not leak into Old"


# ── Row-level effective dating (ZP-TAX-UK-2026-27-001 §3.2 gap-closure ──
# Part 1A, 2026-09-09) — a ContributionRate/TaxSlab row's OWN
# effective_from/effective_to, independent of the pack's own window.
# Canonical-pack path only (resolve_tax_configuration); the legacy
# get_contribution_rates/get_tax_slabs path has no date parameter at all
# and is untouched by this feature.

def test_row_with_no_effective_dates_resolves_regardless_of_payroll_date(db):
    # Every existing row (both fields NULL) must be completely unaffected
    # — this is the regression-safety case for the whole feature.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "UK", pack_id="UK-EFFDATE-REGRESSION")
    row = _make_rate("UK", "personal_allowance", flat_amount=Decimal("12570"))
    row.jurisdiction_pack_id = pack.id
    db.add(row)
    db.commit()

    for as_of in (date(2020, 1, 1), date(2026, 4, 6), date(2099, 12, 31)):
        rates, _, _ = resolve_tax_configuration(db, "UK", payroll_date=as_of)
        assert any(r.component_key == "personal_allowance" for r in rates)


def test_row_level_effective_from_excludes_row_before_its_own_start_date(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "UK", pack_id="UK-EFFDATE-FROM")
    row = _make_rate("UK", "advisory_fuel_petrol_1400", flat_amount=Decimal("0.14"))
    row.jurisdiction_pack_id = pack.id
    row.effective_from = date(2026, 6, 1)
    db.add(row)
    db.commit()

    before, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 5, 31))
    assert not any(r.component_key == "advisory_fuel_petrol_1400" for r in before)

    on_start, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 6, 1))
    assert any(r.component_key == "advisory_fuel_petrol_1400" for r in on_start)

    after, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 7, 1))
    assert any(r.component_key == "advisory_fuel_petrol_1400" for r in after)


def test_row_level_effective_to_excludes_row_after_its_own_end_date(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "UK", pack_id="UK-EFFDATE-TO")
    row = _make_rate("UK", "advisory_fuel_petrol_1400", flat_amount=Decimal("0.13"))
    row.jurisdiction_pack_id = pack.id
    row.effective_to = date(2026, 8, 31)
    db.add(row)
    db.commit()

    on_end, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 8, 31))
    assert any(r.component_key == "advisory_fuel_petrol_1400" for r in on_end)

    after, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 9, 1))
    assert not any(r.component_key == "advisory_fuel_petrol_1400" for r in after)


def test_two_non_overlapping_versions_of_same_key_resolve_by_effective_window(db):
    # The real §3.2 scenario: Advisory Fuel Rates change quarterly inside
    # one tax-year pack. Two rows sharing a component_key with
    # non-overlapping windows must each resolve correctly on their own
    # side of the boundary — the "publish a new effective-dated version,
    # never overwrite" doctrine (§1.2), expressed at the row level.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "UK", pack_id="UK-EFFDATE-SUPERSEDE")
    old_rate = _make_rate("UK", "advisory_fuel_petrol_1400", flat_amount=Decimal("0.13"))
    old_rate.jurisdiction_pack_id = pack.id
    old_rate.effective_to = date(2026, 5, 31)
    new_rate = _make_rate("UK", "advisory_fuel_petrol_1400", flat_amount=Decimal("0.14"))
    new_rate.jurisdiction_pack_id = pack.id
    new_rate.effective_from = date(2026, 6, 1)
    db.add_all([old_rate, new_rate])
    db.commit()

    may_rates, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 5, 15))
    may_row = next(r for r in may_rates if r.component_key == "advisory_fuel_petrol_1400")
    assert may_row.flat_amount == Decimal("0.13")

    june_rates, _, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 6, 15))
    june_row = next(r for r in june_rates if r.component_key == "advisory_fuel_petrol_1400")
    assert june_row.flat_amount == Decimal("0.14")


def test_row_level_effective_dating_also_applies_to_tax_slabs(db):
    # Same mechanism, TaxSlab side — proves parity, not just ContributionRate.
    # resolve_tax_configuration returns (rates, slabs, pack) — this test's
    # pack carries a TaxSlab row only, so the SLABS list (index 1) is what
    # to assert on, not the (always-empty-here) rates list.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    pack = _make_active_tax_pack(db, "UK", pack_id="UK-EFFDATE-SLAB")
    slab = _make_slab("UK", Decimal("0"), Decimal("37700"), Decimal("20"))
    slab.jurisdiction_pack_id = pack.id
    slab.effective_from = date(2026, 6, 1)
    db.add(slab)
    db.commit()

    _, before_slabs, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 5, 1))
    assert len(before_slabs) == 0

    _, after_slabs, _ = resolve_tax_configuration(db, "UK", payroll_date=date(2026, 6, 1))
    assert len(after_slabs) == 1


def test_resolve_effective_rate_inputs_defaults_unset_india_regime_to_new(db, organization):
    # An employee with no declared tax_regime must resolve against New
    # Regime — never the raw "no filter at all" behavior get_tax_slabs
    # has when tax_regime=None is passed straight through, which would
    # concatenate New+Old brackets the moment Old-regime data exists.
    # Uses the org's real seeded data (includes the new Old-regime rows
    # this same change adds to _TAX_SLABS_BY_COUNTRY) rather than a
    # hand-picked minimal set, so this is an end-to-end check against
    # what a real org's rows actually look like today.
    rate_map, slabs, canonical_rates, pack = service._resolve_effective_rate_inputs(
        db, organization.id, "IN", date(2026, 4, 1), org_opted_in=False, tax_regime=None,
    )
    bracket_rows = [s for s in slabs if s.rule_type == "MARGINAL_RATE"]
    assert bracket_rows, "New Regime brackets must still resolve for an employee with no declared regime"
    assert all(s.tax_regime is None for s in bracket_rows), "no Old-regime bracket must leak in for an unset regime"
    assert len(bracket_rows) == 7  # exactly the New Regime's own 7 brackets, never 7+4


# ── H1/H2-style multi-pack disambiguation (ZP-TAX-CA-2026-001 S0 fix) ───
# get_state_scoped_config used to have NO JurisdictionPack/date filtering
# at all — two packages' worth of canonical rows for the same
# (state, component_key)/(state, rule_type) would resolve arbitrarily
# (ContributionRate) or get silently CONCATENATED and summed together
# (TaxSlab). These tests prove the fix, and that it's a strict superset
# of the old behavior (never regresses to fewer/empty rows).

def _make_tax_pack(db, country, state, pack_id, status="Active", effective_from=None, effective_to=None):
    pack = JurisdictionPack(
        pack_id=pack_id, jurisdiction_country=country, jurisdiction_state=state,
        pack_type="tax", version="1.0", status=status,
        effective_from=effective_from, effective_to=effective_to,
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def test_state_scoped_config_disambiguates_by_pack_date_when_active(db, organization):
    h1 = _make_tax_pack(db, "CA", "BC", "TEST-CA-BC-H1", effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30))
    h2 = _make_tax_pack(db, "CA", "BC", "TEST-CA-BC-H2", effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="BC", jurisdiction_pack_id=h1.id,
        component_key="provincial_bpa", label="BPA H1", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("575"),
    ))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="BC", jurisdiction_pack_id=h2.id,
        component_key="provincial_bpa", label="BPA H2", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("805"),
    ))
    db.commit()

    h1_rates, _ = service.get_state_scoped_config(db, "CA", "BC", as_of=date(2026, 3, 1))
    assert h1_rates["provincial_bpa"].flat_amount == Decimal("575")

    h2_rates, _ = service.get_state_scoped_config(db, "CA", "BC", as_of=date(2026, 9, 1))
    assert h2_rates["provincial_bpa"].flat_amount == Decimal("805")


def test_state_scoped_config_falls_back_when_no_pack_qualifies(db, organization):
    # Mirrors BC's ACTUAL live state today: both packages exist but are
    # still Draft. Must not crash and must not return empty — falls back
    # to today's (arbitrary but non-regressing) behavior.
    h1 = _make_tax_pack(db, "CA", "BC", "TEST-CA-BC-H1-DRAFT", status="Draft",
                         effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30))
    h2 = _make_tax_pack(db, "CA", "BC", "TEST-CA-BC-H2-DRAFT", status="Draft",
                         effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="BC", jurisdiction_pack_id=h1.id,
        component_key="provincial_bpa", label="BPA H1", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("575"),
    ))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="BC", jurisdiction_pack_id=h2.id,
        component_key="provincial_bpa", label="BPA H2", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("805"),
    ))
    db.commit()

    rates, _ = service.get_state_scoped_config(db, "CA", "BC", as_of=date(2026, 3, 1))
    assert rates["provincial_bpa"].flat_amount in (Decimal("575"), Decimal("805"))


def test_state_scoped_config_taxslab_no_longer_concatenates_across_packs(db, organization):
    h1 = _make_tax_pack(db, "CA", "BC", "TEST-CA-BC-SLAB-H1", effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30))
    h2 = _make_tax_pack(db, "CA", "BC", "TEST-CA-BC-SLAB-H2", effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="BC", jurisdiction_pack_id=h1.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("5.06"), rate_label="H1", tax_formula="",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="BC", jurisdiction_pack_id=h2.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("6.14"), rate_label="H2", tax_formula="",
    ))
    db.commit()

    _, h1_slabs = service.get_state_scoped_config(db, "CA", "BC", as_of=date(2026, 3, 1))
    assert len(h1_slabs) == 1
    assert h1_slabs[0].rate_pct == Decimal("5.06")

    _, h2_slabs = service.get_state_scoped_config(db, "CA", "BC", as_of=date(2026, 9, 1))
    assert len(h2_slabs) == 1
    assert h2_slabs[0].rate_pct == Decimal("6.14")


def test_state_scoped_config_single_pack_unaffected_by_as_of(db, organization):
    pack = _make_tax_pack(db, "CA", "ON", "TEST-CA-ON-SINGLE")
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON", jurisdiction_pack_id=pack.id,
        component_key="on_eht_exemption", label="ON EHT Exemption", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("1000000"),
    ))
    db.commit()

    rates_early, _ = service.get_state_scoped_config(db, "CA", "ON", as_of=date(2026, 1, 1))
    rates_late, _ = service.get_state_scoped_config(db, "CA", "ON", as_of=date(2026, 12, 31))
    assert rates_early["on_eht_exemption"].flat_amount == Decimal("1000000")
    assert rates_late["on_eht_exemption"].flat_amount == Decimal("1000000")


def test_state_scoped_config_ontario_eht_bands_independent_of_income_tax_brackets(db, organization):
    # ON_EHT_BAND rows and ordinary MARGINAL_RATE brackets share the same
    # (country, state) scope but are functionally separate tables — a
    # pack-ambiguity in one must never affect resolution of the other.
    pack = _make_tax_pack(db, "CA", "ON", "TEST-CA-ON-MIXED")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON", jurisdiction_pack_id=pack.id,
        min_amount=Decimal("0"), max_amount=Decimal("200000"), rate_pct=Decimal("0.980"),
        rate_label="EHT", tax_formula="", rule_type="ON_EHT_BAND",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON", jurisdiction_pack_id=pack.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("5.05"),
        rate_label="Income tax", tax_formula="",
    ))
    db.commit()

    _, slabs = service.get_state_scoped_config(db, "CA", "ON", as_of=date(2026, 3, 1))
    assert len(slabs) == 2
    assert {s.rule_type for s in slabs} == {"ON_EHT_BAND", "MARGINAL_RATE"}


# ── Multi-region resolution within one org, via real payslip generation ─

def _stub_business_code_generation(monkeypatch):
    """generate_payslips_for_run numbers payslips via generate_business_code,
    which takes a Postgres advisory lock (pg_advisory_xact_lock) for safe
    concurrent numbering — real, production-only Postgres behavior, not
    something to weaken. Since this test DB is SQLite (kept isolated and
    hermetic on purpose — see conftest.py) and these tests are about
    jurisdiction/rate resolution, not concurrent numbering, stub the
    numbering call out rather than exercising Postgres-only SQL against a
    database that was never meant to support it."""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_multi_region_resolution_across_employees_in_one_run(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    db.add(_make_rate("IN", "pt", organization_id=None, state="Maharashtra", flat_amount=Decimal("200")))
    db.add(_make_rate("IN", "pt", organization_id=None, state="Karnataka", flat_amount=Decimal("300")))
    db.commit()

    emp_mh = _make_employee(db, organization.id, "E-MH", work_state="Maharashtra")
    emp_ka = _make_employee(db, organization.id, "E-KA", work_state="Karnataka")

    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    by_employee = {i.employee_id: i for i in items}

    assert by_employee[emp_mh.id].professional_tax == Decimal("200")
    assert by_employee[emp_mh.id].work_state == "Maharashtra"
    assert by_employee[emp_ka.id].professional_tax == Decimal("300")
    assert by_employee[emp_ka.id].work_state == "Karnataka"


# ── Historical reproducibility ──────────────────────────────────────────

def test_editing_a_rate_after_generation_does_not_change_the_old_payslip(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    db.add(_make_rate("IN", "pt", organization_id=None, state="Maharashtra", flat_amount=Decimal("200")))
    db.commit()

    emp = _make_employee(db, organization.id, "E-1", work_state="Maharashtra")
    old_run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1), label="January")
    service.generate_payslips_for_run(db, old_run, organization.id)

    old_item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == old_run.id).first()
    assert old_item.professional_tax == Decimal("200")

    # Simulate a later admin edit to the canonical Maharashtra rate.
    canonical_rate = db.query(ContributionRate).filter(
        ContributionRate.organization_id.is_(None),
        ContributionRate.jurisdiction_state == "Maharashtra",
        ContributionRate.component_key == "pt",
    ).first()
    canonical_rate.flat_amount = Decimal("500")
    db.commit()

    # A brand-new run picks up the new rate...
    new_run = _make_run(db, organization.id, date(2026, 2, 1), date(2026, 2, 28), date(2026, 3, 1), label="February")
    service.generate_payslips_for_run(db, new_run, organization.id)
    new_item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == new_run.id).first()
    assert new_item.professional_tax == Decimal("500")

    # ...but the OLD payslip's already-computed figure must be unchanged.
    db.refresh(old_item)
    assert old_item.professional_tax == Decimal("200")


# ── Boundary value at a configured threshold ────────────────────────────

def test_esi_ceiling_boundary_is_inclusive_and_reads_from_configured_rate(db, organization, monkeypatch):
    # India's ESI applies when gross <= the wage ceiling (see
    # engine/countries/india.py: `esi_applicable = gross <= esi_ceiling`).
    # A configured org-level esi_wage_ceiling amount parameter (via the
    # Phase 1 resolve_jurisdiction_parameter mechanism) must be read from
    # the DB row, not the hardcoded 21000 default, and the boundary itself
    # must be inclusive.
    _stub_business_code_generation(monkeypatch)
    ceiling = Decimal("25000.00")
    db.add(_make_rate("IN", "esi_wage_ceiling", organization_id=organization.id, flat_amount=ceiling))
    db.add(_make_rate(
        "IN", "esi", organization_id=organization.id,
        rate_pct=Decimal("0.75"),
    ))
    db.commit()

    emp_at_ceiling = _make_employee_with_monthly_gross(db, organization.id, "E-AT", ceiling)
    emp_above_ceiling = _make_employee_with_monthly_gross(db, organization.id, "E-ABOVE", ceiling + Decimal("0.01"))

    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert items[emp_at_ceiling.id].gross_pay == ceiling
    assert items[emp_at_ceiling.id].esi > Decimal("0")       # exactly at the ceiling — still applicable
    assert items[emp_above_ceiling.id].esi == Decimal("0")   # one cent over — no longer applicable


# ── Income-bracketed state PT (PT Slabs feature) ────────────────────────

def test_pt_bracket_resolution_via_real_payslip_generation(db, organization, monkeypatch):
    # Real, live-shaped Telangana PT brackets (canonical TaxSlab rows,
    # rule_type="PT_FLAT") — the exact data shape the backfilled live
    # IN-PT-TG-2026-V1 pack now has. Two employees at different gross
    # levels in the same org must resolve DIFFERENT professional_tax
    # values from their own bracket, not one flat number for everyone.
    _stub_business_code_generation(monkeypatch)
    db.add(_make_pt_bracket("IN", "Telangana", Decimal("0"), Decimal("15000"), Decimal("0")))
    db.add(_make_pt_bracket("IN", "Telangana", Decimal("15001"), Decimal("20000"), Decimal("150")))
    db.add(_make_pt_bracket("IN", "Telangana", Decimal("20001"), None, Decimal("200")))
    db.commit()

    emp_nil = _make_employee_with_monthly_gross(db, organization.id, "E-NIL", Decimal("12000"), work_state="Telangana")
    emp_mid = _make_employee_with_monthly_gross(db, organization.id, "E-MID", Decimal("18000"), work_state="Telangana")
    emp_top = _make_employee_with_monthly_gross(db, organization.id, "E-TOP", Decimal("50000"), work_state="Telangana")

    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert items[emp_nil.id].professional_tax == Decimal("0")
    assert items[emp_mid.id].professional_tax == Decimal("150")
    assert items[emp_top.id].professional_tax == Decimal("200")


def test_pt_bracket_absent_falls_back_to_flat_rate_for_other_states(db, organization, monkeypatch):
    # Maharashtra-shaped: only a flat ContributionRate "pt" row, zero
    # PT_FLAT TaxSlab rows — must resolve exactly as it did before this
    # feature existed, regardless of the employee's own gross.
    _stub_business_code_generation(monkeypatch)
    db.add(_make_rate("IN", "pt", organization_id=None, state="Maharashtra", flat_amount=Decimal("200")))
    db.commit()

    emp_low = _make_employee_with_monthly_gross(db, organization.id, "E-LOW", Decimal("10000"), work_state="Maharashtra")
    emp_high = _make_employee_with_monthly_gross(db, organization.id, "E-HIGH", Decimal("80000"), work_state="Maharashtra")

    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert items[emp_low.id].professional_tax == Decimal("200")
    assert items[emp_high.id].professional_tax == Decimal("200")


# ── _find_active_tax_pack must not let a PT-only state pack silently ────
# ── replace the country's real income-tax slabs (a real, live bug) ─────

def test_state_pack_with_only_pt_slabs_does_not_override_country_income_tax(db):
    # A state-scoped pack built solely to hold Professional Tax brackets
    # (PT_FLAT, resolved separately/additively via get_state_scoped_config)
    # must NOT win _find_active_tax_pack's state match for income-tax
    # purposes — otherwise the country's real MARGINAL_RATE bands get
    # replaced by a set of 0%-rate PT rows, zeroing income tax for every
    # employee in that state regardless of salary. This reproduces the
    # exact live shape (Telangana's IN-PT-TG-2026-V1 pack) found on a real
    # organization.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    national_pack = _make_active_tax_pack(db, "IN", pack_id="NATIONAL-PACK")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="IN", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=Decimal("400000"), rate_pct=Decimal("0"),
        rate_label="Nil", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=national_pack.id,
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="IN", jurisdiction_state=None,
        min_amount=Decimal("400000"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=national_pack.id,
    ))

    tg_pack = _make_active_tax_pack(db, "IN", state="Telangana", pack_id="TG-PT-PACK")
    pt_bracket = _make_pt_bracket("IN", "Telangana", Decimal("0"), None, Decimal("200"))
    pt_bracket.jurisdiction_pack_id = tg_pack.id
    db.add(pt_bracket)
    db.commit()

    rates, slabs, pack = resolve_tax_configuration(db, "IN", state="Telangana", tax_regime=None, payroll_date=date(2026, 1, 1))
    assert pack.id == national_pack.id, "the PT-only Telangana pack must not win — country-level pack must resolve instead"
    assert {s.rule_type for s in slabs} == {"MARGINAL_RATE"}


def test_state_pack_with_real_income_tax_slabs_still_overrides_country_level(db):
    # Regression guard for the fix above: a state pack that DOES hold real
    # income-tax brackets (UK's Scotland, a US state) must still win the
    # state match exactly as before — the fix only excludes PT_FLAT-only
    # packs, not legitimate state-level income tax overrides.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    national_pack = _make_active_tax_pack(db, "UK", pack_id="UK-NATIONAL")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="UK", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=national_pack.id,
    ))

    scotland_pack = _make_active_tax_pack(db, "UK", state="Scotland", pack_id="UK-SCOTLAND")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="UK", jurisdiction_state="Scotland",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("19"),
        rate_label="Starter 19%", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=scotland_pack.id,
    ))
    db.commit()

    rates, slabs, pack = resolve_tax_configuration(db, "UK", state="Scotland", tax_regime=None, payroll_date=date(2026, 1, 1))
    assert pack.id == scotland_pack.id
    assert slabs[0].rate_pct == Decimal("19")


def test_sync_org_rates_merges_country_income_tax_with_state_pt_brackets(db, organization):
    # Reproduces the exact live bug found on Rughved_Group: a PT-only
    # state pack (Telangana) means resolve_tax_configuration(state=...)
    # correctly returns the COUNTRY pack (per the fix above) — so a naive
    # single sync call would only ever write income-tax brackets OR PT
    # brackets, never both, into the org's own cache (sync_org_rates_
    # from_canonical does a full delete-then-recreate of the org's
    # TaxSlab rows per call). One sync call must produce BOTH.
    national_pack = _make_active_tax_pack(db, "IN", pack_id="NATIONAL-PACK-2")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="IN", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=Decimal("400000"), rate_pct=Decimal("0"),
        rate_label="Nil", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=national_pack.id,
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="IN", jurisdiction_state=None,
        min_amount=Decimal("400000"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=national_pack.id,
    ))
    tg_pack = _make_active_tax_pack(db, "IN", state="Telangana", pack_id="TG-PT-PACK-2")
    pt_bracket = _make_pt_bracket("IN", "Telangana", Decimal("0"), None, Decimal("200"))
    pt_bracket.jurisdiction_pack_id = tg_pack.id
    db.add(pt_bracket)
    db.commit()

    result = service.sync_org_rates_from_canonical(db, organization.id, "IN", state="Telangana", payroll_date=date(2026, 1, 1))
    assert result["synced"] is True

    org_slabs = db.query(TaxSlab).filter(TaxSlab.organization_id == organization.id, TaxSlab.jurisdiction_country == "IN").all()
    rule_types = {s.rule_type for s in org_slabs}
    assert "MARGINAL_RATE" in rule_types, "country income-tax brackets must survive the sync"
    assert "PT_FLAT" in rule_types, "state PT brackets must also be present, not wiped out by the same sync call"


def test_sync_org_rates_does_not_duplicate_a_state_packs_own_income_tax_slabs(db, organization):
    # Regression guard for the fix above: when the STATE pack itself
    # legitimately has real income-tax slabs (UK Scotland), the extra
    # get_state_scoped_config layer must not duplicate what
    # resolve_tax_configuration already returned.
    national_pack = _make_active_tax_pack(db, "UK", pack_id="UK-NATIONAL-2")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="UK", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=national_pack.id,
    ))
    scotland_pack = _make_active_tax_pack(db, "UK", state="Scotland", pack_id="UK-SCOTLAND-2")
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="UK", jurisdiction_state="Scotland",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("19"),
        rate_label="Starter 19%", tax_formula="", rule_type="MARGINAL_RATE",
        jurisdiction_pack_id=scotland_pack.id,
    ))
    db.commit()

    result = service.sync_org_rates_from_canonical(db, organization.id, "UK", state="Scotland", payroll_date=date(2026, 1, 1))
    assert result["synced"] is True

    org_slabs = db.query(TaxSlab).filter(TaxSlab.organization_id == organization.id, TaxSlab.jurisdiction_country == "UK").all()
    assert len(org_slabs) == 1
    assert org_slabs[0].rate_pct == Decimal("19")


# ── Org jurisdiction-state fallback (Venu/Rughved_Group real-world bug) ──

def test_employee_with_no_work_state_falls_back_to_org_jurisdiction_state(db, organization):
    # An employee who was never assigned a work_state must not silently
    # get zero Professional Tax just because of that — the organization's
    # own configured jurisdiction state (Company Details/Compliance) is a
    # reasonable, real-world default: most employees work wherever the
    # org itself is registered unless told otherwise.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", jurisdiction_state="Telangana"))
    tg_pack = _make_active_tax_pack(db, "IN", state="Telangana", pack_id="TG-PT-FALLBACK")
    high_bracket = _make_pt_bracket("IN", "Telangana", Decimal("15001"), Decimal("20000"), Decimal("150"))
    high_bracket.jurisdiction_pack_id = tg_pack.id
    db.add(high_bracket)
    db.commit()

    employee = _make_employee(db, organization.id, "EMP-NO-STATE", work_state=None)
    resolved, _reason = service._resolve_country_aware_state("IN", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "Telangana"


def test_employee_with_own_work_state_is_not_overridden_by_org_fallback(db, organization):
    # The org's jurisdiction state is a FALLBACK only — an employee's own
    # explicitly-set work_state must always win.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", jurisdiction_state="Telangana"))
    db.commit()

    employee = _make_employee(db, organization.id, "EMP-OWN-STATE", work_state="Karnataka")
    resolved, _reason = service._resolve_country_aware_state("IN", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "Karnataka"


def test_org_jurisdiction_state_fallback_ignored_for_a_different_country(db, organization):
    # An org configured for India shouldn't hand a random state to a US
    # employee just because the org has SOME jurisdiction_state on file.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", jurisdiction_state="Telangana"))
    db.commit()

    employee = _make_employee(db, organization.id, "EMP-US", country="US", work_state=None)
    resolved, _reason = service._resolve_country_aware_state("US", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved is None


# ── Canada Province of Employment (ZP-TAX-CA-2026-001 §5, partial) ──────

def test_ca_employee_with_own_province_resolves_physical_single(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-ON", country="CA", work_state="ON")
    resolved, _reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "ON"
    assert service._resolve_ca_poe_with_source(employee.work_state, None) == ("ON", "PHYSICAL_SINGLE")


# ── ZP-TAX-CA-2026-001 §3/§5 step 7: CA-XP "beyond limits" (Phase 9) ────
# A deliberately-typed work_state, not inferred — see
# _CA_BEYOND_LIMITS_CODE's own comment in service.py for why this needs
# no rollout switch (it only changes audit metadata, not any dollar
# amount; the pure-calculation surtax effect is already gated by Phase
# 8's own switch).

def test_ca_employee_with_xp_work_state_resolves_beyond_limits(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-XP", country="CA", work_state="XP")
    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "XP"
    assert reason == "BEYOND_LIMITS"
    assert service._resolve_ca_poe_with_source(employee.work_state, None) == ("XP", "BEYOND_LIMITS")


def test_ca_xp_wins_over_org_jurisdiction_fallback(db, organization):
    # "XP" is checked before any fallback tier — an org's own configured
    # jurisdiction state must never override an employee's explicit
    # beyond-limits declaration.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="ON"))
    db.commit()
    employee = _make_employee(db, organization.id, "EMP-CA-XP-2", country="CA", work_state="XP")
    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "XP"
    assert reason == "BEYOND_LIMITS"


def test_ca_unresolved_still_returns_none_when_nothing_configured(db, organization):
    # Confirms the fix is scoped to the literal "XP" declaration only —
    # an employee with genuinely no data configured anywhere must still
    # resolve to UNRESOLVED, never silently guessed as beyond-province.
    employee = _make_employee(db, organization.id, "EMP-CA-NODATA", country="CA", work_state=None)
    assert service._resolve_ca_poe_with_source(employee.work_state, None) == (None, "UNRESOLVED")


def test_generate_payslips_for_run_persists_beyond_limits_poe_snapshot(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    employee = _make_employee(db, organization.id, "EMP-CA-XP-3", country="CA", work_state="XP")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.poe_snapshot == {"poe_result": "XP", "poe_reason": "BEYOND_LIMITS"}
    assert item.state_income_tax == Decimal("0")  # no province to tax


# ── ZP-TAX-CA-2026-001 CA-D03/AC-07: POE reason persisted, not discarded ──

def test_resolve_employee_calc_inputs_returns_poe_reason_and_result_for_ca(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-POE-1", country="CA", work_state="AB")
    result = service._resolve_employee_calc_inputs(db, organization.id, employee, payroll_date=date(2026, 1, 15))
    poe_reason, poe_result = result[-2], result[-1]
    assert poe_reason == "PHYSICAL_SINGLE"
    assert poe_result == "AB"


def test_resolve_employee_calc_inputs_poe_reason_none_for_non_ca(db, organization):
    employee = _make_employee(db, organization.id, "EMP-IN-POE-1", country="IN", work_state="Telangana")
    result = service._resolve_employee_calc_inputs(db, organization.id, employee, payroll_date=date(2026, 1, 15))
    poe_reason = result[-2]
    assert poe_reason is None


def test_generate_payslips_for_run_persists_poe_snapshot_for_ca(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    employee = _make_employee(db, organization.id, "EMP-CA-POE-2", country="CA", work_state="BC")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.poe_snapshot == {"poe_result": "BC", "poe_reason": "PHYSICAL_SINGLE"}


def test_add_payslip_item_persists_poe_snapshot_for_ca(db, organization):
    from app.modules.payroll.schemas import PayslipItemCreate
    employee = _make_employee(db, organization.id, "EMP-CA-POE-3", country="CA", work_state=None)
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="NS"))
    db.commit()
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("5000"),
    ), organization.id)
    assert item.poe_snapshot == {"poe_result": "NS", "poe_reason": "PAYROLL_FALLBACK"}


def test_add_payslip_item_poe_snapshot_none_for_non_ca(db, organization):
    from app.modules.payroll.schemas import PayslipItemCreate
    employee = _make_employee(db, organization.id, "EMP-UK-POE-1", country="UK", work_state="England")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("5000"),
    ), organization.id)
    assert item.poe_snapshot is None


def test_ca_employee_with_no_province_falls_back_to_org_jurisdiction_state(db, organization):
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="QC"))
    db.commit()

    employee = _make_employee(db, organization.id, "EMP-CA-NOSTATE", country="CA", work_state=None)
    resolved, _reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "QC"


def test_ca_employee_with_invalid_province_code_does_not_pass_through(db, organization):
    # Unlike the generic fallback chain other countries use, CA validates
    # against the doc's actual province/territory list — bad data resolves
    # to no jurisdiction rather than being silently passed through to
    # state-scoped config lookup.
    employee = _make_employee(db, organization.id, "EMP-CA-BAD", country="CA", work_state="ZZ")
    resolved, _reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved is None
    assert service._resolve_ca_poe_with_source("ZZ", None) == (None, "UNRESOLVED")


# ── Canada remote-work "reasonable attachment" POE (ZP-TAX-CA-2026-001
# §5 step 4) ──────────────────────────────────────────────────────────

def test_ca_employee_with_remote_agreement_resolves_remote_attached(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-REMOTE", country="CA", work_state=None)
    employee.remote_work_agreement = True
    employee.remote_attachment_province = "BC"
    db.commit()

    resolved, _reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "BC"
    assert service._resolve_ca_poe_with_source(None, None, remote_work_agreement=True, remote_attachment_province="BC") == ("BC", "REMOTE_ATTACHED")


def test_ca_physical_work_state_wins_over_remote_agreement(db, organization):
    # An employee's own physical work_state must never be overridden by a
    # remote-attachment flag — §5's precedence is physical-single first.
    employee = _make_employee(db, organization.id, "EMP-CA-PHYS-OVER-REMOTE", country="CA", work_state="ON")
    employee.remote_work_agreement = True
    employee.remote_attachment_province = "BC"
    db.commit()

    resolved, _reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "ON"


def test_ca_remote_agreement_with_invalid_province_falls_through(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-REMOTE-BAD", country="CA", work_state=None)
    employee.remote_work_agreement = True
    employee.remote_attachment_province = "ZZ"
    db.commit()

    resolved, _reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved is None


# ── Canada true multi-establishment POE (ZP-TAX-CA-2026-001 §5 steps
# 2-3) — an employee who physically reports to 2+ establishments
# resolves to whichever they spend the most time at, tie-broken by
# whichever they most recently worked. An employee with fewer than two
# ACTIVE EmployeeEstablishment rows is completely unaffected (falls
# through to the pre-existing single-work_state/remote/fallback chain).

def test_ca_multi_establishment_resolves_to_most_time(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-1", country="CA", work_state="ON")
    db.add_all([
        EmployeeEstablishment(employee_id=employee.id, province="ON", time_allocation_pct=Decimal("40")),
        EmployeeEstablishment(employee_id=employee.id, province="QC", time_allocation_pct=Decimal("60")),
    ])
    db.commit()

    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "QC"
    assert reason == "PHYSICAL_MULTI"


def test_ca_multi_establishment_tie_broken_by_last_worked(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-2", country="CA", work_state="ON")
    db.add_all([
        EmployeeEstablishment(
            employee_id=employee.id, province="ON", time_allocation_pct=Decimal("50"),
            last_worked_date=date(2026, 1, 10),
        ),
        EmployeeEstablishment(
            employee_id=employee.id, province="AB", time_allocation_pct=Decimal("50"),
            last_worked_date=date(2026, 1, 20),
        ),
    ])
    db.commit()

    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "AB"
    assert reason == "PHYSICAL_MULTI"


def test_ca_multi_establishment_ignores_inactive_rows(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-3", country="CA", work_state="ON")
    db.add_all([
        EmployeeEstablishment(employee_id=employee.id, province="ON", time_allocation_pct=Decimal("40")),
        EmployeeEstablishment(employee_id=employee.id, province="QC", time_allocation_pct=Decimal("60"), is_active=False),
    ])
    db.commit()

    # Only one ACTIVE row remains — not a real "multi" case, so this
    # falls through to the ordinary single-work_state resolution.
    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "ON"
    assert reason == "PHYSICAL_SINGLE"


def test_ca_single_establishment_row_does_not_trigger_multi_resolution(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-4", country="CA", work_state="ON")
    db.add(EmployeeEstablishment(employee_id=employee.id, province="QC", time_allocation_pct=Decimal("100")))
    db.commit()

    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "ON"
    assert reason == "PHYSICAL_SINGLE"


def test_ca_multi_establishment_wins_over_org_jurisdiction_fallback(db, organization):
    # An employee with no literal work_state but 2+ active establishment
    # rows must resolve via PHYSICAL_MULTI, not fall all the way through
    # to the org's own configured jurisdiction state.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="NS"))
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-5", country="CA", work_state=None)
    db.add_all([
        EmployeeEstablishment(employee_id=employee.id, province="AB", time_allocation_pct=Decimal("30")),
        EmployeeEstablishment(employee_id=employee.id, province="MB", time_allocation_pct=Decimal("70")),
    ])
    db.commit()

    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "MB"
    assert reason == "PHYSICAL_MULTI"


def test_ca_beyond_limits_still_wins_over_multi_establishment(db, organization):
    # "XP" is a deliberate declaration and must outrank even a genuine
    # multi-establishment record — §5 step 7 wins first per the doc's
    # own precedence.
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-6", country="CA", work_state="XP")
    db.add_all([
        EmployeeEstablishment(employee_id=employee.id, province="ON", time_allocation_pct=Decimal("40")),
        EmployeeEstablishment(employee_id=employee.id, province="QC", time_allocation_pct=Decimal("60")),
    ])
    db.commit()

    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "XP"
    assert reason == "BEYOND_LIMITS"


def test_ca_multi_establishment_invalid_province_rows_excluded(db, organization):
    employee = _make_employee(db, organization.id, "EMP-CA-MULTI-7", country="CA", work_state="ON")
    db.add_all([
        EmployeeEstablishment(employee_id=employee.id, province="ZZ", time_allocation_pct=Decimal("90")),
        EmployeeEstablishment(employee_id=employee.id, province="QC", time_allocation_pct=Decimal("10")),
    ])
    db.commit()

    # Only one recognized-province active row remains after excluding
    # "ZZ" — not a real "multi" case, falls through to work_state.
    resolved, reason = service._resolve_country_aware_state("CA", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "ON"
    assert reason == "PHYSICAL_SINGLE"


def test_resolve_ca_multi_establishment_poe_unit_empty_and_single():
    assert service._resolve_ca_multi_establishment_poe(None) == (None, "UNRESOLVED")
    assert service._resolve_ca_multi_establishment_poe([]) == (None, "UNRESOLVED")
    assert service._resolve_ca_multi_establishment_poe(
        [{"province": "ON", "time_allocation_pct": Decimal("100"), "is_active": True}]
    ) == (None, "UNRESOLVED")


def test_resolve_ca_multi_establishment_poe_unit_accepts_plain_dicts():
    result = service._resolve_ca_multi_establishment_poe([
        {"province": "ON", "time_allocation_pct": Decimal("20"), "is_active": True},
        {"province": "BC", "time_allocation_pct": Decimal("80"), "is_active": True},
    ])
    assert result == ("BC", "PHYSICAL_MULTI")


# ── Canada H1/H2 effective-dated package selection (ZP-TAX-CA-2026-001
# §4 "VERSIONING TEST": "A pay date of June 30, 2026 must resolve
# CA-2026-H1. A pay date of July 1, 2026 must resolve CA-2026-H2.") ─────
#
# Uses the EXISTING generic effective_from/effective_to mechanism
# tax_resolver.py already provides for every country — no new versioning
# code is Canada-specific. Synthetic pack IDs/values only (no real 2026
# CRA figures — real statutory data entry is a separate, manual Super
# Admin task per Venu's own decision, not something this test fabricates).

def test_ca_h1_h2_versioning_boundary_jun30_resolves_h1(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    h1 = JurisdictionPack(
        pack_id="CA-2026-H1-TEST", jurisdiction_country="CA", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
    )
    h2 = JurisdictionPack(
        pack_id="CA-2026-H2-TEST", jurisdiction_country="CA", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31),
    )
    db.add_all([h1, h2])
    db.commit()

    _, _, pack = resolve_tax_configuration(db, "CA", state=None, payroll_date=date(2026, 6, 30))
    assert pack.pack_id == "CA-2026-H1-TEST"


def test_ca_h1_h2_versioning_boundary_jul1_resolves_h2(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    h1 = JurisdictionPack(
        pack_id="CA-2026-H1-TEST", jurisdiction_country="CA", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
    )
    h2 = JurisdictionPack(
        pack_id="CA-2026-H2-TEST", jurisdiction_country="CA", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31),
    )
    db.add_all([h1, h2])
    db.commit()

    _, _, pack = resolve_tax_configuration(db, "CA", state=None, payroll_date=date(2026, 7, 1))
    assert pack.pack_id == "CA-2026-H2-TEST"


def test_ca_historical_payroll_replays_from_h1_after_h2_is_published(db):
    # AC-32: re-running/replaying a payroll originally calculated under H1
    # must still resolve H1 after H2 has since become the "current" pack —
    # the resolver keys off the ORIGINAL pay date, never "today"/whichever
    # pack is newest. Mirrors the existing historical-reproducibility
    # tests for other countries in this file, applied to CA's H1/H2 split.
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    h1 = JurisdictionPack(
        pack_id="CA-2026-H1-REPLAY", jurisdiction_country="CA", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
    )
    db.add(h1)
    db.commit()

    # A March 2026 payroll resolves H1 (the only pack that exists yet).
    _, _, original_pack = resolve_tax_configuration(db, "CA", state=None, payroll_date=date(2026, 3, 15))
    assert original_pack.pack_id == "CA-2026-H1-REPLAY"

    # H2 is published later (simulating the mid-year statutory update).
    h2 = JurisdictionPack(
        pack_id="CA-2026-H2-REPLAY", jurisdiction_country="CA", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31),
    )
    db.add(h2)
    db.commit()

    # Replaying the SAME March 2026 pay date must still resolve H1, not H2.
    _, _, replayed_pack = resolve_tax_configuration(db, "CA", state=None, payroll_date=date(2026, 3, 15))
    assert replayed_pack.pack_id == "CA-2026-H1-REPLAY"


# ── Immutable calculation snapshot / historical replay (ZP-TAX-CA-2026-001
# AC-32: "historical replay after a statutory update returns the same
# result using the original snapshot") ──────────────────────────────────
#
# Distinct from test_ca_historical_payroll_replays_from_h1_after_h2_is_
# published above (which proves date-based PACK selection is already
# stable) and from test_editing_a_rate_after_generation_does_not_change_
# the_old_payslip above (which only proves an untouched payslip's stored
# figures don't spontaneously change). This covers the real, previously-
# open gap: explicitly RECALCULATING an existing payslip (e.g. after
# fixing an employee's bank details) via regenerate_employee_payslip must
# reproduce the ORIGINAL numbers even when the SAME canonical pack's own
# rate/slab ROWS have since been edited in place — not silently pick up
# today's live values.

def test_regenerate_replays_original_rate_after_canonical_rate_edited(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    pack = _make_active_tax_pack(db, "IN", pack_id="IN-REPLAY-PACK")
    rate = _make_rate("IN", "pf", organization_id=None, rate_pct=Decimal("12"))
    rate.employer_rate_pct = Decimal("12")
    rate.jurisdiction_pack_id = pack.id
    db.add(rate)
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", active_pack_id=pack.id))
    db.commit()

    employee = _make_employee(db, organization.id, "IN-REPLAY-1", ctc=Decimal("600000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    original_pf = item.pf
    assert original_pf > Decimal("0")
    assert item.tax_rule_snapshot is not None
    original_rate_entry = next(r for r in item.tax_rule_snapshot["contributionRates"] if r["componentKey"] == "pf")
    assert Decimal(original_rate_entry["employeeRatePct"]) == Decimal("12")

    # Super Admin edits the SAME canonical pack's rate row after
    # generation — simulating a statutory update, no new pack/version.
    rate.employee_rate_pct = Decimal("20")
    db.commit()

    service.regenerate_employee_payslip(db, run.id, employee.id, organization.id)
    db.refresh(item)

    # Recalculating must reproduce the ORIGINAL 12%-derived figure, not
    # silently pick up the now-live 20%.
    assert item.pf == original_pf
    # The frozen snapshot itself must also stay untouched — still showing
    # the rate that was ACTUALLY used, not the current live value.
    replayed_rate_entry = next(r for r in item.tax_rule_snapshot["contributionRates"] if r["componentKey"] == "pf")
    assert Decimal(replayed_rate_entry["employeeRatePct"]) == Decimal("12")


def test_regenerate_replays_original_wcb_rate_after_employer_profile_edited(db, organization, monkeypatch):
    # AC-32's previously-disclosed narrower gap (ZP-TAX-CA-2026-001):
    # state_rate_map/employer_tax_profiles/reciprocity/locality_rate were
    # NOT captured in the snapshot at all, so unlike the country-level
    # rate_map/slabs test above, a WCB rate change made after generation
    # WOULD have silently changed a "historical" replay's result. This
    # proves that gap is closed.
    _stub_business_code_generation(monkeypatch)
    profile = EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="CA-ON", component_code="WCB",
        employer_rate_pct=Decimal("2.00"), taxable_wage_base=Decimal("200000"), effective_from=date(2026, 1, 1),
    )
    db.add(profile)
    db.commit()

    employee = _make_employee(db, organization.id, "CA-WCB-REPLAY-1", country="CA", work_state="ON", ctc=Decimal("120000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    original_wcb = item.employer_sui
    assert original_wcb == Decimal("200.00")  # 120000 * 2% / 12
    assert item.tax_rule_snapshot is not None
    original_profile_entry = item.tax_rule_snapshot["employerTaxProfiles"]["WCB"]
    assert Decimal(original_profile_entry["employerRatePct"]) == Decimal("2.00")

    # Super Admin/Tax Ops edits the SAME employer's WCB rate after
    # generation — simulating a real-world rate-notice update.
    profile.employer_rate_pct = Decimal("5.00")
    db.commit()

    service.regenerate_employee_payslip(db, run.id, employee.id, organization.id)
    db.refresh(item)

    # Recalculating must reproduce the ORIGINAL 2%-derived figure, not
    # silently pick up the now-live 5%.
    assert item.employer_sui == original_wcb
    replayed_profile_entry = item.tax_rule_snapshot["employerTaxProfiles"]["WCB"]
    assert Decimal(replayed_profile_entry["employerRatePct"]) == Decimal("2.00")


# ── Per-rule evidence + payslip rule-ID traceability (ZP-TAX-UK-2026-27- ─
# 001 §4.2/§20/AC-29 gap-closure Part 1B, 2026-09-09) ────────────────────

def test_rate_source_document_id_is_captured_in_payslip_snapshot(db, organization, monkeypatch):
    # A payslip's tax_rule_snapshot must be able to answer "which specific
    # rate ROW" (not just which pack) produced this number, and "which
    # official source" backs that row — previously neither the row's own
    # id nor its source_document_id were captured anywhere.
    _stub_business_code_generation(monkeypatch)
    source = SourceArtifact(agency="EPFO", title="EPF Scheme 1952 — current rate notification")
    db.add(source)
    db.commit()
    db.refresh(source)

    pack = _make_active_tax_pack(db, "IN", pack_id="IN-EVIDENCE-PACK")
    rate = _make_rate("IN", "pf", organization_id=None, rate_pct=Decimal("12"))
    rate.employer_rate_pct = Decimal("12")
    rate.jurisdiction_pack_id = pack.id
    rate.source_document_id = source.id
    db.add(rate)
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", active_pack_id=pack.id))
    db.commit()
    db.refresh(rate)

    employee = _make_employee(db, organization.id, "IN-EVIDENCE-1", ctc=Decimal("600000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    pf_entry = next(r for r in item.tax_rule_snapshot["contributionRates"] if r["componentKey"] == "pf")
    assert pf_entry["id"] == rate.id
    assert pf_entry["sourceDocumentId"] == source.id


def test_rate_and_slab_source_document_id_default_to_none(db):
    # Every existing row (created before this column existed) must be
    # completely unaffected — the regression-safety case for Part 1B.
    rate = _make_rate("IN", "pt", organization_id=None, flat_amount=Decimal("200"))
    slab = _make_slab("IN", Decimal("0"), Decimal("400000"), Decimal("0"))
    db.add_all([rate, slab])
    db.commit()
    db.refresh(rate)
    db.refresh(slab)
    assert rate.source_document_id is None
    assert slab.source_document_id is None


def test_regenerate_still_falls_back_to_live_rates_without_a_snapshot(db, organization, monkeypatch):
    # An org never opted into canonical tax-pack tracking (the common
    # case) has no COUNTRY-LEVEL rate_map/slabs captured in its snapshot
    # to replay from at all — recalculation must fall back to live
    # resolution exactly as it did before this fix, not silently produce
    # a zeroed/broken payslip. tax_rule_snapshot itself is no longer None
    # (the state/employer/reciprocity/locality overlay, AC-32's own
    # replay-gap closure, is captured regardless of canonical-pack opt-in
    # — get_state_scoped_config/get_employer_tax_profiles are independent
    # of it), but it carries no contributionRates/taxSlabs keys.
    _stub_business_code_generation(monkeypatch)
    db.add(_make_rate("IN", "pf", organization_id=organization.id, rate_pct=Decimal("12")))
    db.commit()

    employee = _make_employee(db, organization.id, "NO-SNAPSHOT-1", ctc=Decimal("600000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert not item.tax_rule_snapshot.get("contributionRates")
    assert not item.tax_rule_snapshot.get("taxSlabs")
    original_pf = item.pf

    service.regenerate_employee_payslip(db, run.id, employee.id, organization.id)
    db.refresh(item)
    assert item.pf == original_pf  # unchanged — nothing else changed either


def test_reconstruct_rate_map_and_slabs_from_snapshot_unit():
    snapshot = {
        "packId": "TEST-PACK", "version": "1.0",
        "contributionRates": [{
            "componentKey": "pf", "label": "Provident Fund",
            "employeeShare": "12%", "employerShare": "12%", "total": "24%",
            "employeeRatePct": "12", "employerRatePct": "12", "flatAmount": None, "textValue": None,
            "jurisdictionCountry": "IN", "jurisdictionState": None, "jurisdictionLocality": None,
            "taxRegime": None, "filingStatus": None,
        }],
        "taxSlabs": [{
            "minAmount": "0", "maxAmount": "300000", "ratePct": "0",
            "rateLabel": "Nil", "taxFormula": "", "sortOrder": 0,
            "jurisdictionCountry": "IN", "jurisdictionState": None, "jurisdictionLocality": None,
            "taxRegime": "New", "filingStatus": None, "ruleType": "MARGINAL_RATE", "formulaExpression": None,
            "flatAmount": None, "adjustmentAmount": None, "niCategory": None, "employerRatePct": None,
        }],
    }
    rates, slabs = service._reconstruct_rate_map_and_slabs_from_snapshot(snapshot)
    assert len(rates) == 1 and len(slabs) == 1
    assert rates[0].component_key == "pf"
    assert rates[0].employee_rate_pct == Decimal("12")
    assert slabs[0].min_amount == Decimal("0")
    assert slabs[0].max_amount == Decimal("300000")
    assert slabs[0].tax_regime == "New"


def test_reconstruct_rate_map_and_slabs_from_snapshot_empty_input():
    assert service._reconstruct_rate_map_and_slabs_from_snapshot(None) == ([], [])
    assert service._reconstruct_rate_map_and_slabs_from_snapshot({}) == ([], [])


# ── Regime-aware resolution (Tax Parameters feature) ────────────────────

def test_two_employees_different_regimes_resolve_distinct_canonical_rows(db, organization, monkeypatch):
    # Before the regime-aware fix to get_contribution_rates/get_tax_slabs,
    # employee.tax_regime had ZERO effect on the fallback (non-canonical)
    # resolution path — both employees below would have silently resolved
    # the SAME rebate_87a_limit row regardless of their own regime. This is
    # the direct DB-level test of that fix: one org, two employees, two
    # regime-tagged canonical rows for the same component_key, and each
    # employee's generated payslip must reflect only its own regime's row.
    _stub_business_code_generation(monkeypatch)
    db.add(_make_rate("IN", "rebate_87a_limit", organization_id=organization.id, flat_amount=Decimal("1200000"), tax_regime="New"))
    db.add(_make_rate("IN", "rebate_87a_limit", organization_id=organization.id, flat_amount=Decimal("500000"), tax_regime="Old"))
    # A regime-agnostic row (no tax_regime set) — must apply to BOTH
    # employees regardless of their regime, same as PF/ESI/PT do today.
    db.add(_make_rate("IN", "pf", organization_id=organization.id, rate_pct=Decimal("12"), tax_regime=None))
    db.commit()

    # Taxable income landing between the two regimes' limits: fully
    # rebated (tax=0) under New Regime's 12L limit, but taxable under Old
    # Regime's 5L limit.
    emp_new = _make_employee(db, organization.id, "E-NEW", ctc=Decimal("900000"), tax_regime="New")
    emp_old = _make_employee(db, organization.id, "E-OLD", ctc=Decimal("900000"), tax_regime="Old")

    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    items = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert items[emp_new.id].tds == Decimal("0.00")     # New Regime: fully rebated under its own 12L limit
    assert items[emp_old.id].tds > Decimal("0.00")      # Old Regime: taxable under its own, lower 5L limit
    # The regime-agnostic PF row must still apply to both employees.
    assert items[emp_new.id].pf > Decimal("0")
    assert items[emp_old.id].pf > Decimal("0")


# ── UK: complianceFields -> dedicated-column mapping (the dead-plumbing fix) ─

def test_uk_compliance_fields_map_onto_dedicated_columns_on_create(db, organization):
    # Before FIELD_COLUMN_MAP existed, none of these ever reached
    # PayrollEmployee.tax_code/ni_category/study_loan_plan/study_loan_balance
    # — the columns engine/countries/uk.py actually reads — no matter what
    # was submitted through complianceFields.
    payload = EmployeeCreate(
        name="Jane UK", employee_code="UK-E1", country_code="UK",
        compliance_fields={
            "nino": "AB123456C", "paye_tax_code": "1257L", "sort_code": "123456",
            "ni_category": "A", "student_loan_plan": "Plan 2", "study_loan_balance": "15000",
        },
    )
    employee = service.create_employee(db, payload, organization.id)

    assert employee.tax_code == "1257L"
    assert employee.ni_category == "A"
    assert employee.study_loan_plan == "UK_PLAN2"
    assert employee.study_loan_balance == Decimal("15000")
    # The original compliance_fields values are untouched (still "Plan 2",
    # not translated) — only the dedicated-column copy is mapped.
    assert employee.compliance_fields["student_loan_plan"] == "Plan 2"


def test_uk_compliance_fields_map_onto_dedicated_columns_on_update(db, organization):
    from app.modules.payroll.schemas import EmployeeUpdate

    employee = _make_employee(db, organization.id, "UK-E2", country="UK")
    update = EmployeeUpdate(compliance_fields={
        "nino": "AB123456C", "paye_tax_code": "BR", "sort_code": "123456",
        "ni_category": "H", "student_loan_plan": "Postgraduate", "study_loan_balance": "8000",
    })
    updated = service.update_employee(db, employee.id, update, organization.id)

    assert updated.tax_code == "BR"
    assert updated.ni_category == "H"
    assert updated.study_loan_plan == "UK_POSTGRAD"
    assert updated.study_loan_balance == Decimal("8000")


def test_non_uk_country_compliance_fields_do_not_touch_uk_columns(db, organization):
    # INEmployeeValidation has no FIELD_COLUMN_MAP — sync_to_columns must
    # be a complete no-op for it, not accidentally write into UK's columns.
    payload = EmployeeCreate(
        name="Priya IN", employee_code="IN-E1", country_code="IN",
        compliance_fields={"esi_number": "1234567890"},
    )
    employee = service.create_employee(db, payload, organization.id)
    assert employee.tax_code is None
    assert employee.ni_category is None
    assert employee.study_loan_plan is None


def test_us_compliance_fields_map_onto_dedicated_columns_on_create(db, organization):
    # Before this FIELD_COLUMN_MAP fix, state_tax_jurisdiction/w4_filing_status
    # were already mapped (a prior fix), but residence_state and the
    # reciprocity certificate fields were NOT — meaning the fully-built
    # reciprocity engine (service.py:_resolve_us_reciprocity) had no way to
    # ever actually activate for a real employee, since no org admin had any
    # path to record a cross-state residence or a certificate.
    payload = EmployeeCreate(
        name="Sam US", employee_code="US-E1", country_code="US",
        compliance_fields={
            "ssn": "123-45-6789", "flsa_status": "Exempt", "state_tax_jurisdiction": "NJ",
            "w4_filing_status": "Married Filing Jointly",
            "residence_state": "PA",
            "reciprocity_certificate_on_file": "true",
            "reciprocity_certificate_expiry": "2026-12-31",
        },
    )
    employee = service.create_employee(db, payload, organization.id)

    assert employee.work_state == "NJ"
    assert employee.w4_filing_status == "MFJ"
    assert employee.residence_state == "PA"
    assert employee.reciprocity_certificate_on_file is True
    assert employee.reciprocity_certificate_expiry == date(2026, 12, 31)
    # Original compliance_fields values stay exactly as entered (human-readable/
    # string), only the dedicated-column copy is translated/typed — same
    # convention as UK's student_loan_plan.
    assert employee.compliance_fields["w4_filing_status"] == "Married Filing Jointly"
    assert employee.compliance_fields["reciprocity_certificate_on_file"] == "true"


def test_us_reciprocity_certificate_fields_optional_and_default_none(db, organization):
    # Every field added in this fix is optional — an employee with no
    # cross-state situation at all must be completely unaffected.
    payload = EmployeeCreate(
        name="Alex US", employee_code="US-E2", country_code="US",
        compliance_fields={"ssn": "987-65-4321", "flsa_status": "Non-Exempt", "state_tax_jurisdiction": "TX"},
    )
    employee = service.create_employee(db, payload, organization.id)
    assert employee.residence_state is None
    assert employee.reciprocity_certificate_on_file is False
    assert employee.reciprocity_certificate_expiry is None


# ── Section 9: preview / generation / manual payslip must never disagree ──

def test_uk_scotland_consistent_across_preview_generation_and_manual_payslip(db, organization, monkeypatch):
    from app.modules.payroll.schemas import PayslipItemCreate

    _stub_business_code_generation(monkeypatch)
    # Deliberately different flat rates so a wrong entry point is obvious
    # rather than accidentally passing by coincidence.
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="UK", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="UK", jurisdiction_state="Scotland",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("40"),
        rate_label="40%", tax_formula="",
    ))
    db.commit()

    emp = _make_employee(db, organization.id, "UK-SCOT-1", country="UK", work_state="Scotland", ctc=Decimal("600000"))
    # basic=25000, hra=10000, special=15000 -> gross=50000/month, matching
    # _make_employee's ctc/2/0.2 split exactly, so the manual entry below
    # (which takes these as explicit request fields) reconstructs the
    # identical gross the other two entry points derive from ctc.

    preview = service.preview_payroll_run(db, organization.id, [emp.id], country="UK")
    preview_tax = Decimal(str(preview["employees"][0]["monthlyTax"]))

    run1 = _make_run(db, organization.id, date(2026, 4, 6), date(2026, 5, 5), date(2026, 5, 6))
    service.generate_payslips_for_run(db, run1, organization.id)
    generated = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run1.id, PayslipItem.employee_id == emp.id,
    ).first()

    run2 = _make_run(db, organization.id, date(2026, 5, 6), date(2026, 6, 5), date(2026, 6, 6))
    manual = service.add_payslip_item(db, run2.id, PayslipItemCreate(
        employee_id=emp.id, basic_salary=Decimal("25000"), hra=Decimal("10000"), special_allowance=Decimal("15000"),
    ), organization.id)

    assert preview_tax == generated.tds
    assert generated.tds == manual.tds
    # Genuinely Scotland's 40% rate, not the national 20% one — proves the
    # fix changed real behavior, not just "all three happen to agree."
    # £600,000/yr taxable at £600,000-£12,570=£587,430 × 40% ÷ 12 = £19,581 —
    # no longer £20,000: since the Phase 1 PA-taper-removal fix (2026-09-07),
    # the full £12,570 allowance survives at this income instead of being
    # independently zeroed out by the (now-removed) taper computation.
    assert generated.tds == Decimal("19581.00")


# ── Section 10: canonical-pack immutability guard (US blueprint Phase 0) ──
# A pack that has reached Active must not have its rates edited in place —
# see service.py's _require_editable_pack. Before this guard existed,
# upsert_canonical_contribution_rate/upsert_canonical_tax_slab had no
# status check at all, so an "edit" to an Active pack's rate silently
# changed what the live resolver returns for any not-yet-generated or
# still-Draft payslip, even for a past pay period within the pack's own
# effective_from/effective_to window.

def test_editing_a_rate_on_an_active_pack_via_service_is_rejected(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    pack = _make_active_tax_pack(db, "US", pack_id="US-IMMUTABILITY-TEST")
    rate = _make_rate("US", "social-security", organization_id=None, rate_pct=Decimal("6.20"))
    rate.jurisdiction_pack_id = pack.id
    db.add(rate)
    db.commit()
    db.refresh(rate)

    with pytest.raises(BadRequestException):
        service.upsert_canonical_contribution_rate(
            db,
            CanonicalContributionRateUpsert(
                id=rate.id, jurisdictionPackId=pack.id, jurisdictionCountry="US",
                componentKey="social-security", label="Social Security", employeeSharePct=Decimal("7.00"),
            ),
        )
    db.refresh(rate)
    assert rate.employee_rate_pct == Decimal("6.20")  # unchanged


def test_editing_a_slab_on_a_draft_pack_via_service_is_allowed(db, organization):
    from app.modules.payroll.schemas import CanonicalTaxSlabUpsert

    pack = JurisdictionPack(
        pack_id="US-DRAFT-TEST", jurisdiction_country="US", pack_type="tax", version="1.0", status="Draft",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    slab = TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_pack_id=pack.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"), rate_label="10%", tax_formula="",
    )
    db.add(slab)
    db.commit()
    db.refresh(slab)

    updated = service.upsert_canonical_tax_slab(
        db,
        CanonicalTaxSlabUpsert(
            id=slab.id, jurisdictionPackId=pack.id, jurisdictionCountry="US",
            minAmount=Decimal("0"), maxAmount=None, ratePct=Decimal("12"), rateLabel="12%",
        ),
    )
    assert updated.rate_pct == Decimal("12")


def test_new_pack_version_clones_previous_versions_rates(db, organization):
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    v1 = _make_active_tax_pack(db, "US", pack_id="US-VERSION-CLONE-TEST", state="TestState")
    db.add(_make_rate("US", "social-security", organization_id=None, state="TestState", rate_pct=Decimal("6.20")))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state="TestState", jurisdiction_pack_id=v1.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"), rate_label="10%", tax_formula="",
    ))
    db.commit()
    # The rate above wasn't linked to v1 via jurisdiction_pack_id at
    # creation (matching _make_rate's own signature) — link it now so the
    # clone helper (which reads by jurisdiction_pack_id) has something to
    # find, exactly as a real canonical ContributionRate created through
    # the Super Admin UI would already be.
    rate = db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_state == "TestState", ContributionRate.component_key == "social-security",
    ).first()
    rate.jurisdiction_pack_id = v1.id
    db.commit()

    v2 = service.upsert_jurisdiction_pack(
        db,
        JurisdictionPackUpsert(
            packId="US-VERSION-CLONE-TEST", version="2.0", jurisdictionCountry="US", jurisdictionState="TestState",
            packType="tax", status="Draft",
        ),
    )
    assert v2.previous_version_id == v1.id

    cloned_rate = db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == v2.id, ContributionRate.component_key == "social-security",
    ).first()
    cloned_slab = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == v2.id).first()
    assert cloned_rate is not None and cloned_rate.id != rate.id and cloned_rate.employee_rate_pct == Decimal("6.20")
    assert cloned_slab is not None and cloned_slab.rate_pct == Decimal("10")


# ── Canada gap-closure Phase 4: maker-checker Publish Center integrity ──
# Found while auditing what "Formula Asset Registry / maker-checker
# Publish Center" (ZP-TAX-CA-2026-001's own Section 19.2, "author cannot
# self-approve a production statutory version") actually still needed:
# set_jurisdiction_pack_status already had a real distinct-approver gate,
# but three real bypasses of it existed. All three are fixed together —
# none of them change any already-calculated payslip's numbers, they only
# tighten the Super-Admin-side publish workflow.

def test_upsert_jurisdiction_pack_rejects_direct_active_on_create(db, organization):
    from app.modules.payroll.schemas import JurisdictionPackUpsert
    # Before this fix: creating a tax pack with status="Active" directly
    # through the plain upsert endpoint completely bypassed
    # set_jurisdiction_pack_status's overlap guard, inverted-date guard,
    # and distinct-approver gate — a pack could go live with zero review.
    with pytest.raises(BadRequestException):
        service.upsert_jurisdiction_pack(
            db,
            JurisdictionPackUpsert(
                packId="CA-BYPASS-CREATE-TEST", version="1.0", jurisdictionCountry="CA",
                packType="tax", status="Active",
            ),
        )
    assert db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "CA-BYPASS-CREATE-TEST").first() is None


def test_upsert_jurisdiction_pack_rejects_direct_active_on_edit(db, organization):
    from app.modules.payroll.schemas import JurisdictionPackUpsert
    pack = JurisdictionPack(pack_id="CA-BYPASS-EDIT-TEST", jurisdiction_country="CA", pack_type="tax", version="1.0", status="Draft")
    db.add(pack)
    db.commit()
    db.refresh(pack)

    with pytest.raises(BadRequestException):
        service.upsert_jurisdiction_pack(
            db,
            JurisdictionPackUpsert(
                id=pack.id, packId="CA-BYPASS-EDIT-TEST", version="1.0", jurisdictionCountry="CA",
                packType="tax", status="Active",
            ),
        )
    db.refresh(pack)
    assert pack.status == "Draft"  # unchanged


def test_upsert_jurisdiction_pack_allows_direct_active_for_policy_pack(db, organization):
    # The danger is specific to TAX packs (set_jurisdiction_pack_status's
    # overlap/date/approver machinery only ever runs for pack_type=="tax")
    # — a policy pack going Active directly via plain edit is unchanged
    # behavior, not a bypass of anything that exists.
    from app.modules.payroll.schemas import JurisdictionPackUpsert
    result = service.upsert_jurisdiction_pack(
        db,
        JurisdictionPackUpsert(
            packId="CA-POLICY-DIRECT-ACTIVE", version="1.0", jurisdictionCountry="CA",
            packType="policy", status="Active",
        ),
    )
    assert result.status == "Active"


def test_approved_by_id_not_settable_via_plain_upsert(db, organization):
    from app.modules.payroll.schemas import JurisdictionPackUpsert
    pack = JurisdictionPack(pack_id="CA-APPROVER-BYPASS-TEST", jurisdiction_country="CA", pack_type="tax", version="1.0", status="Draft")
    db.add(pack)
    db.commit()
    db.refresh(pack)

    # Attempting to smuggle an arbitrary approver id through the plain
    # edit endpoint (rather than the dedicated set_jurisdiction_pack_approver
    # action) must be silently ignored — approval can only ever be granted
    # by someone actually invoking the dedicated Approve action themselves.
    result = service.upsert_jurisdiction_pack(
        db,
        JurisdictionPackUpsert(
            id=pack.id, packId="CA-APPROVER-BYPASS-TEST", version="1.0", jurisdictionCountry="CA",
            packType="tax", status="Draft", approvedById=999,
        ),
    )
    assert result.approved_by_id is None


def test_editing_pack_metadata_after_approval_invalidates_it(db, organization):
    pack = JurisdictionPack(pack_id="CA-INVALIDATE-META-TEST", jurisdiction_country="CA", pack_type="tax", version="1.0", status="Draft")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=42)
    db.refresh(pack)
    assert pack.status == "Approved" and pack.approved_by_id == 42

    from app.modules.payroll.schemas import JurisdictionPackUpsert
    service.upsert_jurisdiction_pack(
        db,
        JurisdictionPackUpsert(
            id=pack.id, packId="CA-INVALIDATE-META-TEST", version="1.0", jurisdictionCountry="CA",
            packType="tax", status="Approved", changeSummary="A later correction to the effective window.",
        ),
        actor_id=7,
    )
    db.refresh(pack)
    assert pack.approved_by_id is None
    assert pack.status == "Draft"  # forced back — must be re-approved before Active


def test_editing_a_rate_after_approval_invalidates_pack_approval(db, organization):
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert
    pack = JurisdictionPack(pack_id="CA-INVALIDATE-RATE-TEST", jurisdiction_country="CA", pack_type="tax", version="1.0", status="Draft")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    rate = _make_rate("CA", "cpp", organization_id=None, rate_pct=Decimal("5.95"))
    rate.jurisdiction_pack_id = pack.id
    db.add(rate)
    db.commit()
    db.refresh(rate)

    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=42)
    db.refresh(pack)
    assert pack.status == "Approved"

    service.upsert_canonical_contribution_rate(
        db,
        CanonicalContributionRateUpsert(
            id=rate.id, jurisdictionPackId=pack.id, jurisdictionCountry="CA",
            componentKey="cpp", label="CPP", employeeSharePct=Decimal("6.00"),
        ),
    )
    db.refresh(pack)
    assert pack.approved_by_id is None
    assert pack.status == "Draft"


def test_deleting_a_rate_from_an_active_pack_is_rejected(db, organization):
    pack = _make_active_tax_pack(db, "CA", pack_id="CA-DELETE-GUARD-TEST")
    rate = _make_rate("CA", "cpp", organization_id=None, rate_pct=Decimal("5.95"))
    rate.jurisdiction_pack_id = pack.id
    db.add(rate)
    db.commit()
    db.refresh(rate)

    with pytest.raises(BadRequestException):
        service.delete_canonical_contribution_rate(db, rate.id)
    # Still there — an Active pack's rates must never disappear silently.
    assert db.query(ContributionRate).filter(ContributionRate.id == rate.id).first() is not None


def test_deleting_a_slab_from_a_draft_pack_is_allowed(db, organization):
    pack = JurisdictionPack(pack_id="CA-DELETE-DRAFT-TEST", jurisdiction_country="CA", pack_type="tax", version="1.0", status="Draft")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    slab = TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_pack_id=pack.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"), rate_label="10%", tax_formula="",
    )
    db.add(slab)
    db.commit()
    db.refresh(slab)

    service.delete_canonical_tax_slab(db, slab.id)
    assert db.query(TaxSlab).filter(TaxSlab.id == slab.id).first() is None


# ── Section 11: US filing-status-aware ContributionRate resolution ───────

def test_get_contribution_rates_prefers_filing_status_tagged_row(db, organization):
    db.add(_make_rate("US", "medicare_addl_thresh", organization_id=organization.id, flat_amount=Decimal("200000")))
    mfj_row = _make_rate("US", "medicare_addl_thresh", organization_id=organization.id, flat_amount=Decimal("250000"))
    mfj_row.filing_status = "MFJ"
    db.add(mfj_row)
    db.commit()

    mfj_rates = service.get_contribution_rates(db, organization.id, country="US", filing_status="MFJ")
    single_rates = service.get_contribution_rates(db, organization.id, country="US", filing_status="SINGLE")

    mfj_map = {r.component_key: r for r in mfj_rates}
    single_map = {r.component_key: r for r in single_rates}
    assert mfj_map["medicare_addl_thresh"].flat_amount == Decimal("250000")
    # No SINGLE-tagged row exists — falls back to the generic (filing_status
    # IS NULL) row, same value an org with no filing-status overrides at
    # all would already see.
    assert single_map["medicare_addl_thresh"].flat_amount == Decimal("200000")


# ── Section 12: US employer-specific tax profile (SUI) resolution ────────

def test_get_employer_tax_profiles_resolves_by_org_jurisdiction_and_date(db, organization):
    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="US-CA", component_code="SUI",
        taxable_wage_base=Decimal("7000"), employer_rate_pct=Decimal("3.4"),
        effective_from=date(2026, 1, 1), effective_to=None, rate_source="EMPLOYER_NOTICE",
    ))
    db.commit()

    profiles = service.get_employer_tax_profiles(db, organization.id, "US-CA", as_of=date(2026, 6, 1))
    assert profiles["SUI"].employer_rate_pct == Decimal("3.4")

    # Wrong jurisdiction and no jurisdiction_id at all both resolve empty —
    # never guessed, never falls back to a different state's profile.
    assert service.get_employer_tax_profiles(db, organization.id, "US-NY", as_of=date(2026, 6, 1)) == {}
    assert service.get_employer_tax_profiles(db, organization.id, None, as_of=date(2026, 6, 1)) == {}


def test_get_employer_tax_profiles_respects_effective_dates(db, organization):
    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="US-CA", component_code="SUI",
        taxable_wage_base=Decimal("7000"), employer_rate_pct=Decimal("2.0"),
        effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31),
    ))
    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="US-CA", component_code="SUI",
        taxable_wage_base=Decimal("7000"), employer_rate_pct=Decimal("3.4"),
        effective_from=date(2026, 1, 1), effective_to=None,
    ))
    db.commit()

    old_profile = service.get_employer_tax_profiles(db, organization.id, "US-CA", as_of=date(2025, 6, 1))
    new_profile = service.get_employer_tax_profiles(db, organization.id, "US-CA", as_of=date(2026, 6, 1))
    assert old_profile["SUI"].employer_rate_pct == Decimal("2.0")
    assert new_profile["SUI"].employer_rate_pct == Decimal("3.4")


def test_sui_and_futa_credit_flow_through_real_payslip_generation(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="US-CA", component_code="SUI",
        taxable_wage_base=Decimal("7000"), employer_rate_pct=Decimal("3.4"),
        effective_from=date(2026, 1, 1), effective_to=None,
    ))
    db.commit()

    emp = _make_employee_with_monthly_gross(db, organization.id, "US-SUI-1", Decimal("5000"), country="US", work_state="CA")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).first()
    assert item.employer_sui == pytest.approx(Decimal("19.83"), abs=Decimal("0.01"))
    # FUTA credited down to ~0.6% effective rate because a real SUI profile exists.
    assert item.employer_futa == pytest.approx(Decimal("3.50"), abs=Decimal("0.01"))


# ── Section 13: US cross-state reciprocity ────────────────────────────────

def test_resolve_reciprocity_matches_directional_pair_and_date(db, organization):
    from app.modules.payroll.models import ReciprocityRule

    db.add(ReciprocityRule(
        resident_jurisdiction="US-PA", work_jurisdiction="US-NJ",
        employee_certificate="NJ-165", certificate_required=True,
        effective_from=date(2026, 1, 1), effective_to=None,
    ))
    db.commit()

    assert service.resolve_reciprocity(db, "US-PA", "US-NJ", as_of=date(2026, 6, 1)) is not None
    # Reversed direction must NOT match — reciprocity is directional.
    assert service.resolve_reciprocity(db, "US-NJ", "US-PA", as_of=date(2026, 6, 1)) is None
    # Before effective_from must not match.
    assert service.resolve_reciprocity(db, "US-PA", "US-NJ", as_of=date(2025, 1, 1)) is None
    # Same jurisdiction on both sides is not a cross-state question at all.
    assert service.resolve_reciprocity(db, "US-PA", "US-PA", as_of=date(2026, 6, 1)) is None


def test_reciprocity_requires_certificate_on_file_and_unexpired(db, organization):
    from app.modules.payroll.models import ReciprocityRule

    rule = ReciprocityRule(
        resident_jurisdiction="US-PA", work_jurisdiction="US-NJ",
        employee_certificate="NJ-165", certificate_required=True,
        effective_from=date(2026, 1, 1), effective_to=None,
    )
    emp_no_cert = _make_employee(db, organization.id, "US-RECIP-NOCERT", country="US")
    emp_with_cert = _make_employee(db, organization.id, "US-RECIP-CERT", country="US")
    emp_with_cert.reciprocity_certificate_on_file = True
    emp_with_cert.reciprocity_certificate_expiry = date(2026, 12, 31)
    emp_expired = _make_employee(db, organization.id, "US-RECIP-EXPIRED", country="US")
    emp_expired.reciprocity_certificate_on_file = True
    emp_expired.reciprocity_certificate_expiry = date(2026, 1, 1)
    db.commit()

    as_of = date(2026, 6, 1)
    assert service._reciprocity_certificate_satisfied(emp_no_cert, rule, as_of) is False
    assert service._reciprocity_certificate_satisfied(emp_with_cert, rule, as_of) is True
    assert service._reciprocity_certificate_satisfied(emp_expired, rule, as_of) is False


def test_reciprocity_flows_through_real_payslip_generation(db, organization, monkeypatch):
    """A PA-resident employee who works in NJ, with a valid PA/NJ
    reciprocity agreement and certificate on file, must be taxed on PA's
    (resident) rates, not NJ's (work) rates."""
    from app.modules.payroll.models import ReciprocityRule

    _stub_business_code_generation(monkeypatch)
    db.add(ReciprocityRule(
        resident_jurisdiction="US-PA", work_jurisdiction="US-NJ",
        employee_certificate="NJ-165", certificate_required=True,
        effective_from=date(2026, 1, 1), effective_to=None,
    ))
    # NJ (work state): 8% flat. PA (resident state): 3% flat. Deliberately
    # different so a wrong entry point is obvious rather than passing by
    # coincidence.
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state="NJ",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("8"), rate_label="8%", tax_formula="",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state="PA",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("3"), rate_label="3%", tax_formula="",
    ))
    db.commit()

    emp = _make_employee_with_monthly_gross(db, organization.id, "US-RECIP-FLOW", Decimal("5000"), country="US", work_state="NJ")
    emp.residence_state = "PA"
    emp.reciprocity_certificate_on_file = True
    emp.reciprocity_certificate_expiry = date(2026, 12, 31)
    db.commit()

    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._US_STATE_TAX_ENABLED_STATES.update({"NJ", "PA"})
    try:
        run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
        service.generate_payslips_for_run(db, run, organization.id)
    finally:
        shared_module._US_STATE_TAX_ENABLED_STATES.discard("NJ")
        shared_module._US_STATE_TAX_ENABLED_STATES.discard("PA")

    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).first()
    # PA's 3% of $60,000/yr / 12 = $150.00 — NOT NJ's 8% ($400.00).
    assert item.state_income_tax == pytest.approx(Decimal("150.00"), abs=Decimal("0.01"))


# ── Section 14: US locality (county/municipal/school-district) rates ─────

def test_get_locality_rate_resolves_by_country_code_and_date(db, organization):
    dataset = LocalityDataset(
        jurisdiction_country="US", jurisdiction_state="PA", version="MANUAL-1", status="Active",
        effective_from=date(2026, 1, 1), effective_to=None,
    )
    db.add(dataset)
    db.commit()
    db.add(LocalityRate(
        locality_dataset_id=dataset.id, locality_code="PHILADELPHIA", locality_type="MUNICIPAL",
        resident_rate_pct=Decimal("3.75"),
    ))
    db.commit()

    rate = service.get_locality_rate(db, "US", "PHILADELPHIA", as_of=date(2026, 6, 1))
    assert rate.resident_rate_pct == Decimal("3.75")

    # No code, wrong code, and no configuration at all all resolve None —
    # never guessed, never falls back to a different locality.
    assert service.get_locality_rate(db, "US", None, as_of=date(2026, 6, 1)) is None
    assert service.get_locality_rate(db, "US", "PITTSBURGH", as_of=date(2026, 6, 1)) is None


def test_get_locality_rate_respects_dataset_effective_dates(db, organization):
    old_dataset = LocalityDataset(
        jurisdiction_country="US", jurisdiction_state="PA", version="MANUAL-1", status="Active",
        effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31),
    )
    db.add(old_dataset)
    db.commit()
    db.add(LocalityRate(locality_dataset_id=old_dataset.id, locality_code="PHILADELPHIA", locality_type="MUNICIPAL", resident_rate_pct=Decimal("3.00")))
    db.commit()

    assert service.get_locality_rate(db, "US", "PHILADELPHIA", as_of=date(2026, 6, 1)) is None
    assert service.get_locality_rate(db, "US", "PHILADELPHIA", as_of=date(2025, 6, 1)).resident_rate_pct == Decimal("3.00")


def test_locality_tax_flows_through_real_payslip_generation(db, organization, monkeypatch):
    """An employee whose work_locality matches a configured LocalityRate
    must have local_tax computed from it during a real payroll run — the
    same end-to-end wiring already proven for SUI and reciprocity above."""
    _stub_business_code_generation(monkeypatch)
    dataset = LocalityDataset(jurisdiction_country="US", jurisdiction_state="PA", version="MANUAL-1", status="Active")
    db.add(dataset)
    db.commit()
    db.add(LocalityRate(
        locality_dataset_id=dataset.id, locality_code="PHILADELPHIA", locality_type="MUNICIPAL",
        resident_rate_pct=Decimal("3.75"),
    ))
    db.commit()

    emp = _make_employee_with_monthly_gross(db, organization.id, "US-LOCALITY-1", Decimal("5000"), country="US", work_state="PA")
    emp.work_locality = "PHILADELPHIA"
    db.commit()

    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).first()
    # 3.75% of $5,000 monthly gross.
    assert item.local_tax == pytest.approx(Decimal("187.50"), abs=Decimal("0.01"))


def test_no_locality_configured_leaves_local_tax_zero_through_real_payslip_generation(db, organization, monkeypatch):
    """An employee with no work_locality set — every employee before this
    feature existed — must keep local_tax at exactly zero through a real
    run, never a guess."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee_with_monthly_gross(db, organization.id, "US-LOCALITY-NONE", Decimal("5000"), country="US", work_state="PA")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).first()
    assert item.local_tax == Decimal("0")


# ── Section 15: audit trail for SUI/Reciprocity/Locality/Source Evidence ──
# Before this, a Super Admin editing/deleting one of these left no history
# of who changed what — unlike every canonical ContributionRate/TaxSlab
# edit, which has always gone through record_tax_audit. These reuse the
# SAME TaxConfigurationAudit table (jurisdiction_pack_id left None — none
# of these four are pack-scoped).

def _last_audit(db, entity_type, entity_id):
    return (
        db.query(TaxConfigurationAudit)
        .filter(TaxConfigurationAudit.entity_type == entity_type, TaxConfigurationAudit.entity_id == entity_id)
        .order_by(TaxConfigurationAudit.created_at.desc(), TaxConfigurationAudit.id.desc())
        .first()
    )


def test_employer_tax_profile_upsert_and_delete_are_audited(db, organization):
    actor_id = 42
    profile = service.upsert_employer_tax_profile(
        db,
        EmployerTaxProfileUpsert(
            organizationId=organization.id, jurisdictionId="US-CA", componentCode="SUI",
            taxableWageBase=Decimal("7000"), employerRatePct=Decimal("3.4"),
            effectiveFrom=date(2026, 1, 1),
        ),
        actor_id=actor_id,
    )
    created = _last_audit(db, "employer_tax_profile", profile.id)
    assert created.action == "create"
    assert created.actor_id == actor_id
    assert Decimal(created.new_value["employer_rate_pct"]) == Decimal("3.4")

    service.upsert_employer_tax_profile(
        db,
        EmployerTaxProfileUpsert(
            id=profile.id, organizationId=organization.id, jurisdictionId="US-CA", componentCode="SUI",
            taxableWageBase=Decimal("7000"), employerRatePct=Decimal("4.0"),
            effectiveFrom=date(2026, 1, 1),
        ),
        actor_id=actor_id,
    )
    updated = _last_audit(db, "employer_tax_profile", profile.id)
    assert updated.action == "update"
    assert Decimal(updated.old_value["employer_rate_pct"]) == Decimal("3.4")
    assert Decimal(updated.new_value["employer_rate_pct"]) == Decimal("4.0")

    service.delete_employer_tax_profile(db, profile.id, actor_id=actor_id)
    deleted = _last_audit(db, "employer_tax_profile", profile.id)
    assert deleted.action == "delete"
    assert Decimal(deleted.old_value["employerRatePct"]) == Decimal("4.0")


def test_reciprocity_rule_upsert_and_delete_are_audited(db, organization):
    actor_id = 42
    rule = service.upsert_reciprocity_rule(
        db,
        ReciprocityRuleUpsert(
            residentJurisdiction="US-PA", workJurisdiction="US-NJ",
            employeeCertificate="NJ-165", certificateRequired=True,
            effectiveFrom=date(2026, 1, 1),
        ),
        actor_id=actor_id,
    )
    created = _last_audit(db, "reciprocity_rule", rule.id)
    assert created.action == "create"
    assert created.actor_id == actor_id
    assert created.new_value["resident_jurisdiction"] == "US-PA"

    service.delete_reciprocity_rule(db, rule.id, actor_id=actor_id)
    deleted = _last_audit(db, "reciprocity_rule", rule.id)
    assert deleted.action == "delete"
    assert deleted.old_value["workJurisdiction"] == "US-NJ"


def test_locality_rate_upsert_and_delete_are_audited(db, organization):
    actor_id = 42
    rate = service.upsert_locality_rate(
        db,
        LocalityRateUpsert(
            jurisdictionCountry="US", jurisdictionState="PA", localityCode="PHILADELPHIA",
            residentRatePct=Decimal("3.75"),
        ),
        actor_id=actor_id,
    )
    created = _last_audit(db, "locality_rate", rate.id)
    assert created.action == "create"
    assert created.actor_id == actor_id
    assert Decimal(created.new_value["resident_rate_pct"]) == Decimal("3.75")

    service.delete_locality_rate(db, rate.id, actor_id=actor_id)
    deleted = _last_audit(db, "locality_rate", rate.id)
    assert deleted.action == "delete"
    assert deleted.old_value["localityCode"] == "PHILADELPHIA"


def test_source_artifact_create_and_review_are_audited(db, organization):
    actor_id = 42
    artifact = service.create_source_artifact(
        db,
        SourceArtifactCreate(agency="IRS", title="2026 Publication 15-T"),
        actor_id=actor_id,
    )
    created = _last_audit(db, "source_artifact", artifact.id)
    assert created.action == "create"
    assert created.actor_id == actor_id
    assert created.new_value["title"] == "2026 Publication 15-T"

    service.mark_source_artifact_reviewed(db, artifact.id, reviewer_id=actor_id)
    reviewed = _last_audit(db, "source_artifact", artifact.id)
    assert reviewed.action == "review"
    assert reviewed.actor_id == actor_id
    assert reviewed.new_value["reviewerId"] == actor_id


# ── ZP-TAX-CA-2026-001 §18/AC-25: provincial TD1 / TP-1015.3-V ──────────
# collectible via the employee form (same compliance_fields ->
# sync_to_columns mechanism already used for td1_claim_amount), and every
# change to a TD1/TP-1015.3-V claim amount gets a declaration-history
# audit row (reusing record_tax_audit/TaxConfigurationAudit).

def test_ca_provincial_and_qc_td1_fields_sync_onto_dedicated_columns(db, organization):
    from app.modules.payroll.schemas import EmployeeUpdate

    employee = _make_employee(db, organization.id, "CA-DECL-1", country="CA", work_state="ON")
    update = EmployeeUpdate(compliance_fields={
        "sin": "123456789", "province": "ON",
        "provincial_td1_claim_amount": "15000", "qc_tp1015_claim_amount": "10000",
    })
    updated = service.update_employee(db, employee.id, update, organization.id)
    assert updated.provincial_td1_claim_amount == Decimal("15000")
    assert updated.qc_tp1015_claim_amount == Decimal("10000")


def test_ca_td1_claim_amount_change_is_audited(db, organization):
    from app.modules.payroll.schemas import EmployeeUpdate

    employee = _make_employee(db, organization.id, "CA-DECL-2", country="CA", work_state="ON")
    actor_id = 7
    service.update_employee(
        db, employee.id,
        EmployeeUpdate(compliance_fields={"sin": "123456789", "province": "ON", "td1_claim_amount": "16452"}),
        organization.id, actor_id=actor_id,
    )
    audit = _last_audit(db, "payroll_employee_declaration", employee.id)
    assert audit is not None
    assert audit.actor_id == actor_id
    assert audit.old_value == {"td1_claim_amount": None}
    assert audit.new_value == {"td1_claim_amount": "16452.00"}


def test_ca_declaration_unchanged_value_is_not_audited(db, organization):
    from app.modules.payroll.schemas import EmployeeUpdate

    employee = _make_employee(db, organization.id, "CA-DECL-3", country="CA", work_state="ON")
    fields = {"sin": "123456789", "province": "ON", "td1_claim_amount": "16452"}
    service.update_employee(db, employee.id, EmployeeUpdate(compliance_fields=fields), organization.id)
    before = _last_audit(db, "payroll_employee_declaration", employee.id)
    # Same value again — must NOT produce a second, redundant audit row.
    service.update_employee(db, employee.id, EmployeeUpdate(compliance_fields=fields), organization.id)
    after = _last_audit(db, "payroll_employee_declaration", employee.id)
    assert before.id == after.id


# ── Country-resolution: no more silent "IN" default (fallback-removal Phase 4) ──
# The `organization` fixture is exactly the "nothing configured anywhere"
# case: a bare Organization row with no `country` set and no
# CompanyComplianceDetails row at all — this never had test coverage before
# since every call site used to silently default to "IN" instead of
# reaching an actually-untested branch.

def test_resolve_org_country_none_when_nothing_configured(db, organization):
    assert service._resolve_org_country(db, organization.id) is None


def test_resolve_org_country_falls_back_to_organization_country(db, organization):
    # CompanyComplianceDetails intentionally left unset/absent — the
    # Organization's own `country` (set at registration) is a real value
    # and must win over guessing "IN".
    organization.country = "Germany"
    db.commit()
    assert service._resolve_org_country(db, organization.id) == "DE"


def test_resolve_org_country_required_raises_when_nothing_configured(db, organization):
    with pytest.raises(BadRequestException):
        service._resolve_org_country(db, organization.id, required=True)


def test_resolve_employee_country_raises_for_new_employee_with_no_jurisdiction(db, organization):
    # No explicit_country_code, no CompanyComplianceDetails, no
    # Organization.country — must raise rather than silently assigning
    # this employee to India.
    with pytest.raises(BadRequestException):
        service._resolve_employee_country(db, organization.id, None)


def test_resolve_employee_country_explicit_code_bypasses_org_lookup(db, organization):
    # An explicit per-employee country always wins, even with nothing
    # configured at the org level — no reason to touch org resolution at all.
    assert service._resolve_employee_country(db, organization.id, "US") == "US"


def test_filing_dates_empty_not_india_when_org_unconfigured(db, organization):
    # Previously this silently resolved to "IN" and could return India's
    # filing calendar for an org that hasn't configured its jurisdiction —
    # must now return an empty list instead.
    dates = service.get_upcoming_filing_dates_for_org(db, organization.id)
    assert dates == []


# ── ZP-TAX-CA-2026-001 §10: CPP/QPP age 18/70 mandatory window ──────────
# Service-layer confirmation that employee.date_of_birth and
# run.pay_date actually reach the engine through generate_payslips_for_run
# — pure calculation-level coverage (dormancy, boundary ages) already
# lives in test_engine_standard.py's test_age_gated_cpp_*/
# test_calc_age_gating_* tests.

def _seed_ca_cpp_rate(db):
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state=None,
        component_key="cpp", label="cpp", employee_share="—", employer_share="—", total="—",
        employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"),
    ))
    db.commit()


def test_generate_payslips_for_run_age_gating_dormant_by_default(db, organization, monkeypatch):
    import app.modules.payroll.engine.countries.shared as shared
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.discard("CA")  # simulate the switch OFF

    _stub_business_code_generation(monkeypatch)
    _seed_ca_cpp_rate(db)
    employee = _make_employee(db, organization.id, "CA-AGE-1", country="CA")
    employee.date_of_birth = date(2015, 1, 1)  # age 11 on the pay date below
    db.commit()
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 31))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    # Switch is OFF -> date_of_birth is never consumed, CPP computes normally.
    assert item.social_security > Decimal("0")
    assert item.employer_social_security > Decimal("0")


def test_generate_payslips_for_run_age_gating_stops_cpp_for_minor_when_enabled(db, organization, monkeypatch):
    import app.modules.payroll.engine.countries.shared as shared

    _stub_business_code_generation(monkeypatch)
    _seed_ca_cpp_rate(db)
    employee = _make_employee(db, organization.id, "CA-AGE-2", country="CA")
    employee.date_of_birth = date(2015, 1, 1)  # age 11 on the pay date below
    db.commit()
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 31))
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.add("CA")
    try:
        service.generate_payslips_for_run(db, run, organization.id)
    finally:
        shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.discard("CA")

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.social_security == Decimal("0")
    assert item.employer_social_security == Decimal("0")


# ── ZP-TAX-CA-2026-001 §11: EI reduced-rate authorization is FEDERAL ────
# (not provincial) — service-layer confirmation that an EmployerTaxProfile
# stored at jurisdiction_id="CA" (bare country, no province) applies to
# employees regardless of which province they work in, since Ontario and
# BC employees would otherwise need it entered twice under a state-scoped
# lookup. Pure rate-mechanics coverage lives in test_engine_standard.py's
# test_ei_employer_rate_*/test_qpip_employer_rate_* tests.

def _seed_ca_ei_rate(db, employer_rate_pct=Decimal("3.00")):
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state=None,
        component_key="ei", label="ei", employee_share="—", employer_share="—", total="—",
        employee_rate_pct=Decimal("1.63"), employer_rate_pct=employer_rate_pct,
    ))
    db.commit()


def test_generate_payslips_for_run_ei_reduced_rate_is_country_level_not_state_scoped(db, organization, monkeypatch):
    import app.modules.payroll.engine.countries.shared as shared

    _stub_business_code_generation(monkeypatch)
    # employer_rate_pct=3.00 is deliberately inconsistent with both the
    # 1.4x default (2.282%) and the reduced authorization (1.00%) below —
    # proving neither the row's own rate nor 1.4x wins once a reduced
    # authorization exists.
    _seed_ca_ei_rate(db, employer_rate_pct=Decimal("3.00"))
    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="CA", component_code="EI_REDUCED",
        taxable_wage_base=Decimal("68900"), employer_rate_pct=Decimal("1.00"),
        effective_from=date(2025, 1, 1),
    ))
    employee_on = _make_employee(db, organization.id, "CA-EI-ON", country="CA", work_state="ON", ctc=Decimal("60000"))
    employee_bc = _make_employee(db, organization.id, "CA-EI-BC", country="CA", work_state="BC", ctc=Decimal("60000"))
    db.commit()
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 31))
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.add("CA")
    try:
        service.generate_payslips_for_run(db, run, organization.id)
    finally:
        shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.discard("CA")

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == 2
    for item in items:
        assert item.employer_esi == Decimal("50.00")  # 5000/mo * 1.00% — same reduced rate, both provinces


# ── date_of_birth / lsvcc_investment_amount actually settable ───────────
# Both columns existed on PayrollEmployee (and were read by the engine)
# before EmployeeCreate/EmployeeUpdate/EmployeeResponse ever exposed
# them — the exact same class of gap the component_key VARCHAR(20) bug
# was, just at the schema layer instead of the DB layer: correct engine
# logic that nothing could ever actually feed real data into. Caught
# while wiring up Phase 8's LSVCC credit and fixed for both fields at
# once.

def test_create_employee_persists_date_of_birth_and_lsvcc_investment_amount(db, organization):
    from app.modules.payroll.schemas import EmployeeCreate

    employee = service.create_employee(db, EmployeeCreate(
        employee_code="CA-DOB-CREATE-1", name="DOB Test", country_code="CA",
        compliance_fields={"sin": "123456789", "province": "ON"},
        date_of_birth=date(1990, 5, 15), lsvcc_investment_amount=Decimal("2000"),
    ), organization.id)
    assert employee.date_of_birth == date(1990, 5, 15)
    assert employee.lsvcc_investment_amount == Decimal("2000")


def test_update_employee_persists_date_of_birth_and_lsvcc_investment_amount(db, organization):
    from app.modules.payroll.schemas import EmployeeUpdate

    employee = _make_employee(db, organization.id, "CA-DOB-1", country="CA")
    updated = service.update_employee(db, employee.id, EmployeeUpdate(
        date_of_birth=date(1985, 3, 20), lsvcc_investment_amount=Decimal("3000"),
    ), organization.id)
    assert updated.date_of_birth == date(1985, 3, 20)
    assert updated.lsvcc_investment_amount == Decimal("3000")


def test_lsvcc_investment_amount_change_is_audited(db, organization):
    from app.modules.payroll.schemas import EmployeeUpdate

    employee = _make_employee(db, organization.id, "CA-DOB-2", country="CA")
    actor_id = 9
    service.update_employee(
        db, employee.id, EmployeeUpdate(lsvcc_investment_amount=Decimal("1500")), organization.id, actor_id=actor_id,
    )
    audit = _last_audit(db, "payroll_employee_declaration", employee.id)
    assert audit is not None
    assert audit.actor_id == actor_id
    assert audit.old_value == {"lsvcc_investment_amount": None}
    assert audit.new_value == {"lsvcc_investment_amount": "1500.00"}


# ── UK NI category relief-eligibility facts (ZP-TAX-UK-2026-27-001 ──────
# §9.1/§9.3 gap-closure Part 2, 2026-09-09) ──────────────────────────────

def _make_uk_employee_with_dob(db, org_id, code, dob):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="UK", ctc=Decimal("60000"), date_of_birth=dob,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def test_create_uk_ni_relief_fact_persists_and_lists(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NIREL-1", date_cls(1990, 1, 1))
    fact = service.create_uk_ni_relief_fact(
        db, organization.id, emp.id, "FREEPORT", "Teesside Freeport Site A",
        date_cls(2026, 1, 1), None,
    )
    assert fact.id is not None
    facts = service.list_uk_ni_relief_facts(db, organization.id, emp.id)
    assert len(facts) == 1
    assert facts[0].relief_type == "FREEPORT"
    assert facts[0].reference == "Teesside Freeport Site A"


def test_create_uk_ni_relief_fact_rejects_unknown_type(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NIREL-2", date_cls(1990, 1, 1))
    with pytest.raises(BadRequestException):
        service.create_uk_ni_relief_fact(db, organization.id, emp.id, "NOT_REAL", None, date_cls(2026, 1, 1), None)


def test_create_uk_ni_relief_fact_rejects_unknown_employee(db, organization):
    from datetime import date as date_cls
    with pytest.raises(NotFoundException):
        service.create_uk_ni_relief_fact(db, organization.id, 999999, "VETERAN", None, date_cls(2026, 1, 1), None)


def test_delete_uk_ni_relief_fact_removes_it(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NIREL-3", date_cls(1990, 1, 1))
    fact = service.create_uk_ni_relief_fact(db, organization.id, emp.id, "APPRENTICE", None, date_cls(2026, 1, 1), None)
    service.delete_uk_ni_relief_fact(db, organization.id, emp.id, fact.id)
    assert service.list_uk_ni_relief_facts(db, organization.id, emp.id) == []


def test_delete_uk_ni_relief_fact_not_found_for_wrong_employee(db, organization):
    from datetime import date as date_cls
    emp1 = _make_uk_employee_with_dob(db, organization.id, "NIREL-4A", date_cls(1990, 1, 1))
    emp2 = _make_uk_employee_with_dob(db, organization.id, "NIREL-4B", date_cls(1990, 1, 1))
    fact = service.create_uk_ni_relief_fact(db, organization.id, emp1.id, "VETERAN", None, date_cls(2026, 1, 1), None)
    with pytest.raises(NotFoundException):
        service.delete_uk_ni_relief_fact(db, organization.id, emp2.id, fact.id)


def test_resolve_uk_ni_category_override_none_when_explicitly_disabled(db, organization):
    """UK — enabled by default since 2026-09-10 (see shared.py). An org/
    deployment that deliberately discards "UK" from this switch must still
    fall back to the manual ni_category, exactly as the old dormant-by-
    default behavior did — this replaces that prior test."""
    from datetime import date as date_cls
    import app.modules.payroll.engine.countries.shared as shared_module
    emp = _make_uk_employee_with_dob(db, organization.id, "NIREL-5", date_cls(1990, 1, 1))
    service.create_uk_ni_relief_fact(db, organization.id, emp.id, "FREEPORT", None, date_cls(2026, 1, 1), None)
    was_enabled = "UK" in shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES
    shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES.discard("UK")
    try:
        result = service._resolve_uk_ni_category_override(db, emp, date_cls(2026, 6, 1), {})
    finally:
        if was_enabled:
            shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES.add("UK")
    assert result is None


def test_resolve_uk_ni_category_override_derives_when_enabled(db, organization):
    from datetime import date as date_cls
    import app.modules.payroll.engine.countries.shared as shared_module
    emp = _make_uk_employee_with_dob(db, organization.id, "NIREL-6", date_cls(1990, 1, 1))
    service.create_uk_ni_relief_fact(db, organization.id, emp.id, "FREEPORT", None, date_cls(2026, 1, 1), None)
    was_enabled = "UK" in shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES
    shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES.add("UK")
    try:
        result = service._resolve_uk_ni_category_override(db, emp, date_cls(2026, 6, 1), {})
    finally:
        if not was_enabled:
            shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES.discard("UK")
    assert result == "F"


def test_resolve_uk_ni_category_override_none_without_any_facts(db, organization):
    from datetime import date as date_cls
    import app.modules.payroll.engine.countries.shared as shared_module
    emp = _make_uk_employee_with_dob(db, organization.id, "NIREL-7", date_cls(1990, 1, 1))
    was_enabled = "UK" in shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES
    shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES.add("UK")
    try:
        result = service._resolve_uk_ni_category_override(db, emp, date_cls(2026, 6, 1), {})
    finally:
        if not was_enabled:
            shared_module._UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES.discard("UK")
    assert result is None


# ── UK Mileage Allowance & Advisory Fuel Rate service-layer wiring ──────
# (ZP-TAX-UK-2026-27-001 §16 gap-closure Part 4, 2026-09-09) ────────────

def test_calculate_uk_mileage_reimbursement_via_service(db, organization):
    from datetime import date as date_cls
    emp = _make_employee(db, organization.id, "MILEAGE-1", country="UK")
    result = service.calculate_uk_mileage_reimbursement(
        db, organization.id, emp.id, "MOTORCYCLE", Decimal("100"), date_cls(2026, 6, 1),
    )
    assert result["eligible"] is True
    assert result["tax_free_amount"] == Decimal("24.00")


def test_calculate_uk_mileage_reimbursement_rejects_non_uk_employee(db, organization):
    from datetime import date as date_cls
    emp = _make_employee(db, organization.id, "MILEAGE-2", country="IN")
    with pytest.raises(BadRequestException):
        service.calculate_uk_mileage_reimbursement(
            db, organization.id, emp.id, "CAR", Decimal("100"), date_cls(2026, 6, 1),
        )


def test_calculate_uk_mileage_reimbursement_unknown_employee_raises(db, organization):
    from datetime import date as date_cls
    with pytest.raises(NotFoundException):
        service.calculate_uk_mileage_reimbursement(
            db, organization.id, 999999, "CAR", Decimal("100"), date_cls(2026, 6, 1),
        )


def test_resolve_uk_advisory_fuel_rate_via_service_auto_seeds_from_defaults(db, organization):
    # A fresh org's first-ever UK contribution-rate read auto-seeds from
    # _CONTRIBUTION_RATES_BY_COUNTRY["UK"] (get_contribution_rates' own
    # existing first-use behavior) — this org has never touched UK rates
    # before, so this call seeds (and then reads) the real default AFR
    # rows, not a fail-closed result.
    result = service.resolve_uk_advisory_fuel_rate(db, organization.id, "PETROL", "LE_1400")
    assert result["eligible"] is True
    assert result["rate_per_mile"] == Decimal("0.14")


def test_resolve_uk_advisory_fuel_rate_fails_closed_for_unknown_combination(db, organization):
    # Diesel's own band ("LE_1600"), requested with PETROL as the fuel
    # type — no such key exists even after auto-seeding.
    result = service.resolve_uk_advisory_fuel_rate(db, organization.id, "PETROL", "LE_1600")
    assert result["eligible"] is False


# ── UK National Minimum Wage compliance validation (ZP-TAX-UK-2026-27- ──
# 001 §15 gap-closure Part 5, 2026-09-09) ────────────────────────────────

def _make_attendance(db, org_id, emp_id, day, hours):
    rec = PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=day, hours=str(hours), status="present",
    )
    db.add(rec)
    return rec


def test_sum_uk_attendance_hours_within_period(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NMW-HOURS-1", date_cls(1990, 1, 1))
    _make_attendance(db, organization.id, emp.id, date_cls(2026, 6, 1), "8")
    _make_attendance(db, organization.id, emp.id, date_cls(2026, 6, 2), "7.5")
    # Outside the period — must not be counted.
    _make_attendance(db, organization.id, emp.id, date_cls(2026, 7, 1), "8")
    db.commit()

    total = service._sum_uk_attendance_hours(db, emp.id, date_cls(2026, 6, 1), date_cls(2026, 6, 30))
    assert total == Decimal("15.5")


def test_sum_uk_attendance_hours_skips_unparseable_values(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NMW-HOURS-2", date_cls(1990, 1, 1))
    _make_attendance(db, organization.id, emp.id, date_cls(2026, 6, 1), "8")
    rec = PayrollAttendanceRecord(organization_id=organization.id, employee_id=emp.id, date=date_cls(2026, 6, 2), hours=None, status="present")
    db.add(rec)
    db.commit()

    total = service._sum_uk_attendance_hours(db, emp.id, date_cls(2026, 6, 1), date_cls(2026, 6, 30))
    assert total == Decimal("8")


def test_validate_uk_nmw_compliance_compliant_end_to_end(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NMW-E2E-1", date_cls(1995, 1, 1))
    _make_attendance(db, organization.id, emp.id, date_cls(2026, 6, 1), "160")
    db.commit()
    # Fresh org auto-seeds real NMW defaults on first UK read (same
    # behavior confirmed for mileage/AFR in Part 4) — age 31 on 2026-06-30
    # -> 21+ rate £12.71/hour.
    result = service.validate_uk_nmw_compliance(
        db, organization.id, emp.id, date_cls(2026, 6, 1), date_cls(2026, 6, 30), Decimal("12.71") * 160,
    )
    assert result["eligible"] is True
    assert result["compliant"] is True


def test_validate_uk_nmw_compliance_uses_apprentice_relief_fact(db, organization):
    from datetime import date as date_cls
    emp = _make_uk_employee_with_dob(db, organization.id, "NMW-E2E-2", date_cls(2003, 1, 1))  # 23 on 2026-06-30
    service.create_uk_ni_relief_fact(db, organization.id, emp.id, "APPRENTICE", None, date_cls(2026, 1, 1), None)
    _make_attendance(db, organization.id, emp.id, date_cls(2026, 6, 1), "160")
    db.commit()
    # 23-year-old apprentice, apprenticeship started 2026-01-01 (within
    # 365 days of the period end) -> apprentice-19-plus-first-year rate
    # (£8.00), NOT the 21+ rate (£12.71) they'd otherwise get.
    result = service.validate_uk_nmw_compliance(
        db, organization.id, emp.id, date_cls(2026, 6, 1), date_cls(2026, 6, 30), Decimal("8.00") * 160,
    )
    assert result["eligible"] is True
    assert result["applicable_rate"] == Decimal("8.00")
    assert result["compliant"] is True


def test_validate_uk_nmw_compliance_rejects_non_uk_employee(db, organization):
    from datetime import date as date_cls
    emp = _make_employee(db, organization.id, "NMW-BAD-1", country="IN")
    with pytest.raises(BadRequestException):
        service.validate_uk_nmw_compliance(
            db, organization.id, emp.id, date_cls(2026, 6, 1), date_cls(2026, 6, 30), Decimal("1000"),
        )


def test_validate_uk_nmw_compliance_unknown_employee_raises(db, organization):
    from datetime import date as date_cls
    with pytest.raises(NotFoundException):
        service.validate_uk_nmw_compliance(
            db, organization.id, 999999, date_cls(2026, 6, 1), date_cls(2026, 6, 30), Decimal("1000"),
        )
