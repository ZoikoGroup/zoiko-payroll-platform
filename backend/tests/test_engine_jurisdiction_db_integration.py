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
)


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
