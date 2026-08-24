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

from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, TaxSlab, PayrollEmployee, PayrollRun, PayslipItem, JurisdictionPack,
    CompanyComplianceDetails,
)
from app.modules.payroll.schemas import EmployeeCreate


def _make_rate(country, component_key, organization_id=None, state=None, flat_amount=None, rate_pct=None, tax_regime=None):
    return ContributionRate(
        organization_id=organization_id,
        jurisdiction_country=country,
        jurisdiction_state=state,
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


def _make_pt_bracket(country, state, min_amount, max_amount, flat_amount):
    return TaxSlab(
        organization_id=None, jurisdiction_country=country, jurisdiction_state=state,
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

    rows = service.get_contribution_rates(db, organization.id, "IN")
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

    rows = service.get_contribution_rates(db, organization.id, "IN")
    pt = next(r for r in rows if r.component_key == "pt")
    assert pt.flat_amount == Decimal("300")
    assert pt.organization_id == organization.id  # seeded as the org's own row


def test_hardcoded_fallback_when_no_canonical_and_no_org_row(db, organization):
    # Nothing configured anywhere for this org+country — must fall back to
    # the hardcoded _CONTRIBUTION_RATES_BY_COUNTRY default (India "pt" = 200)
    # instead of returning empty or raising.
    rows = service.get_contribution_rates(db, organization.id, "IN")
    pt = next(r for r in rows if r.component_key == "pt")
    assert pt.flat_amount == Decimal("200")


def test_unknown_country_falls_back_cleanly_with_no_rows(db, organization):
    # A jurisdiction with zero canonical data AND no hardcoded defaults
    # must not crash — just return an empty list.
    rows = service.get_contribution_rates(db, organization.id, "ZZ")
    assert rows == []
    slabs = service.get_tax_slabs(db, organization.id, "ZZ")
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
    resolved = service._resolve_country_aware_state("IN", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "Telangana"


def test_employee_with_own_work_state_is_not_overridden_by_org_fallback(db, organization):
    # The org's jurisdiction state is a FALLBACK only — an employee's own
    # explicitly-set work_state must always win.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", jurisdiction_state="Telangana"))
    db.commit()

    employee = _make_employee(db, organization.id, "EMP-OWN-STATE", work_state="Karnataka")
    resolved = service._resolve_country_aware_state("IN", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved == "Karnataka"


def test_org_jurisdiction_state_fallback_ignored_for_a_different_country(db, organization):
    # An org configured for India shouldn't hand a random state to a US
    # employee just because the org has SOME jurisdiction_state on file.
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="IN", jurisdiction_state="Telangana"))
    db.commit()

    employee = _make_employee(db, organization.id, "EMP-US", country="US", work_state=None)
    resolved = service._resolve_country_aware_state("US", employee, employee.work_state, db=db, organization_id=organization.id)
    assert resolved is None


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
    assert generated.tds == Decimal("20000.00")
