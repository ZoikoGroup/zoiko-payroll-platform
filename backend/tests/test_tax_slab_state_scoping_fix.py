"""
tests/test_tax_slab_state_scoping_fix.py
--------------------------------------------
Regression coverage for a real bug found 2026-09-11 while building the
CA special-payment calculator (see this session's own memory entry
ca_special_payment_phase_and_resolver_bug_found): get_tax_slabs/
get_contribution_rates (the legacy, non-canonical org-scoped rate
resolver) filtered ONLY on jurisdiction_country, with no jurisdiction_
state exclusion at all. For get_contribution_rates this was harmless
(rate_map is a component_key-keyed dict, so a stray provincial key never
collides with a federal lookup key), but for get_tax_slabs it was NOT:
`slabs` is a flat LIST fed straight into _calculate_annual_tax, which
sums every row as its own marginal bracket — so an org on this legacy
path with BOTH a country-level (jurisdiction_state IS NULL) and a
province-level (e.g. "ON") TaxSlab row for the same country got the
provincial bracket silently summed into "federal" tax too.

Fixed by filtering both functions to jurisdiction_state IS NULL/"" —
their own architectural counterpart, get_state_scoped_config, is the
correct, SEPARATE lookup for province/state-scoped rows.
"""

from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import TaxSlab, ContributionRate, PayrollEmployee, LocalityDataset, LocalityRate


def test_get_tax_slabs_excludes_state_scoped_rows(db, organization):
    db.add(TaxSlab(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="flat",
    ))
    db.add(TaxSlab(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"),
        rate_label="10%", tax_formula="flat",
    ))
    db.commit()

    rows = service.get_tax_slabs(db, organization.id, country="CA")
    assert len(rows) == 1
    assert rows[0].rate_pct == Decimal("20")
    assert rows[0].jurisdiction_state is None


def test_get_tax_slabs_does_not_contaminate_federal_bracket_calculation(db, organization):
    # The exact reproduction of the real bug: federal (20%) + a province
    # (10%) row for the same org previously made _calculate_annual_tax
    # sum BOTH as marginal brackets, taxing at 30% instead of 20%.
    from app.modules.payroll.engine.countries.shared import _calculate_annual_tax

    db.add(TaxSlab(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"),
        rate_label="20%", tax_formula="flat",
    ))
    db.add(TaxSlab(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"),
        rate_label="10%", tax_formula="flat",
    ))
    db.commit()

    slabs = service.get_tax_slabs(db, organization.id, country="CA")
    tax = _calculate_annual_tax(Decimal("60000"), slabs)
    assert tax == Decimal("12000.00")  # 60000 * 20%, NOT 30%


# ── Full-name vs. code state mismatch (found 2026-09-24) ────────────────
# CompanyComplianceDetails.jurisdiction_state can hold the FULL region name
# captured at registration (registrationRegions.js's dropdown lists
# "Saskatchewan", "California", ...), while canonical state-scoped TaxSlab
# rows (seeded via Super Admin) are keyed by the 2-letter code (confirmed
# live: a real CA-SK-2026-V1 pack's brackets are stored with
# jurisdiction_state="SK"). get_state_scoped_config/get_state_tax_slabs did
# an exact string match between the two, so a real, Active, populated
# canonical pack silently resolved to nothing on the org's own Compliance >
# Tax Configuration page. _normalize_jurisdiction_state fixes this for the
# two countries where it's real (US/CA); UK/India already use full names as
# their genuine canonical convention, so those must NOT be touched.

def test_normalize_jurisdiction_state_ca_full_name_to_code():
    assert service._normalize_jurisdiction_state("CA", "Saskatchewan") == "SK"
    assert service._normalize_jurisdiction_state("CA", "  saskatchewan  ") == "SK"
    assert service._normalize_jurisdiction_state("CA", "SK") == "SK"  # already-correct code: no-op


def test_normalize_jurisdiction_state_us_full_name_to_code():
    assert service._normalize_jurisdiction_state("US", "California") == "CA"
    assert service._normalize_jurisdiction_state("US", "CA") == "CA"


def test_normalize_jurisdiction_state_leaves_full_name_countries_untouched():
    # UK/India's own canonical convention IS the full name — normalizing
    # these would break an already-correct match, not fix one.
    assert service._normalize_jurisdiction_state("UK", "Scotland") == "Scotland"
    assert service._normalize_jurisdiction_state("IN", "Telangana") == "Telangana"
    assert service._normalize_jurisdiction_state("CA", None) is None
    assert service._normalize_jurisdiction_state(None, "Saskatchewan") == "Saskatchewan"


def test_get_state_tax_slabs_resolves_canonical_pack_from_full_province_name(db, organization):
    # Exact reproduction of the live bug: a canonical (organization_id=None)
    # Saskatchewan pack exists, real and Active, but the org's own
    # jurisdiction_state is the full name from registration.
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="SK",
        min_amount=Decimal("0"), max_amount=Decimal("54532"), rate_pct=Decimal("10.5"),
        rate_label="10.50%", tax_formula="marginal", rule_type="MARGINAL_RATE", sort_order=1,
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="SK",
        min_amount=Decimal("54532"), max_amount=Decimal("155805"), rate_pct=Decimal("12.5"),
        rate_label="12.50%", tax_formula="marginal", rule_type="MARGINAL_RATE", sort_order=2,
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="SK",
        min_amount=Decimal("155805"), max_amount=None, rate_pct=Decimal("14.5"),
        rate_label="14.50%", tax_formula="marginal", rule_type="MARGINAL_RATE", sort_order=3,
    ))
    db.commit()

    # Before the fix this returned [] — the exact "No provincial /
    # territorial income tax slabs configured" symptom reported live.
    rows = service.get_state_tax_slabs(db, "CA", "Saskatchewan")
    assert len(rows) == 3
    assert {r.rate_pct for r in rows} == {Decimal("10.5"), Decimal("12.5"), Decimal("14.5")}

    # And the already-correct 2-letter code still works exactly as before.
    rows_by_code = service.get_state_tax_slabs(db, "CA", "SK")
    assert len(rows_by_code) == 3


def test_get_contribution_rates_excludes_state_scoped_rows(db, organization):
    db.add(ContributionRate(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state=None,
        component_key="cpp", label="cpp", employee_share="—", employer_share="—", total="—",
        employee_rate_pct=Decimal("5.95"),
    ))
    db.add(ContributionRate(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="ON",
        component_key="on_eht_exemption", label="on_eht_exemption", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("1000000"),
    ))
    db.commit()

    rows = service.get_contribution_rates(db, organization.id, country="CA")
    keys = {r.component_key for r in rows}
    assert keys == {"cpp"}


def test_get_tax_slabs_still_returns_rows_with_empty_string_state(db, organization):
    # Some existing conventions in this schema use "" rather than NULL
    # for "no state" — the fix must not exclude those either.
    db.add(TaxSlab(
        organization_id=organization.id, jurisdiction_country="CA", jurisdiction_state="",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("15"),
        rate_label="15%", tax_formula="flat",
    ))
    db.commit()

    rows = service.get_tax_slabs(db, organization.id, country="CA")
    assert len(rows) == 1
    assert rows[0].rate_pct == Decimal("15")


# ── get_state_tax_slabs (2026-09-15 Org Admin visibility audit) ───────────
# get_tax_slabs above deliberately EXCLUDES state-scoped rows — TaxConfig-
# urationTab.jsx's State/Provincial Taxes item needs its own, genuinely
# separate fetch of exactly those excluded rows. get_state_tax_slabs is a
# thin wrapper around get_state_scoped_config's slab half, canonical
# (organization_id IS NULL) rows only, MARGINAL_RATE only.

def test_get_state_tax_slabs_returns_only_that_state_marginal_rate_rows(db):
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state="CA",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("9.3"),
        rate_label="9.3%", tax_formula="marginal", rule_type="MARGINAL_RATE",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state="NY",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("6.85"),
        rate_label="6.85%", tax_formula="marginal", rule_type="MARGINAL_RATE",
    ))
    # A federal (country-level) row must never leak into a state's own list.
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state=None,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("22"),
        rate_label="22%", tax_formula="marginal", rule_type="MARGINAL_RATE",
    ))
    db.commit()

    rows = service.get_state_tax_slabs(db, country="US", state="CA")
    assert len(rows) == 1
    assert rows[0].jurisdiction_state == "CA"
    assert rows[0].rate_pct == Decimal("9.3000")


def test_get_state_tax_slabs_excludes_non_marginal_rule_types(db):
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="US", jurisdiction_state="CA",
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("1"),
        rate_label="1%", tax_formula="sdi", rule_type="SDI",
    ))
    db.commit()

    rows = service.get_state_tax_slabs(db, country="US", state="CA")
    assert rows == []


def test_get_state_tax_slabs_returns_empty_for_falsy_state(db):
    assert service.get_state_tax_slabs(db, country="US", state=None) == []
    assert service.get_state_tax_slabs(db, country="US", state="") == []


# ── get_org_locality_rates (2026-09-15 Org Admin visibility audit) ───────
# Local Taxes (City/County/Local Payroll Tax) had NO fetch pulling
# org-specific data at all — get_org_locality_rates resolves this org's own
# employees' distinct work_locality codes through get_locality_rate, the
# same Active-dataset resolver payroll calculation itself uses.

def test_get_org_locality_rates_resolves_employee_work_localities(db, organization):
    dataset = LocalityDataset(
        jurisdiction_country="US", jurisdiction_state="PA", version="MANUAL-1", status="Active",
    )
    db.add(dataset)
    db.commit()
    db.add(LocalityRate(
        locality_dataset_id=dataset.id, locality_code="PHILADELPHIA", locality_type="MUNICIPAL",
        resident_rate_pct=Decimal("3.75"),
    ))
    db.commit()

    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="US-LOC-1", name="Employee US-LOC-1",
        country_code="US", ctc=Decimal("60000"), work_state="PA", work_locality="PHILADELPHIA",
    )
    db.add(emp)
    db.commit()

    rows = service.get_org_locality_rates(db, organization.id, country="US")
    assert len(rows) == 1
    assert rows[0].locality_code == "PHILADELPHIA"
    assert rows[0].resident_rate_pct == Decimal("3.7500")


def test_get_org_locality_rates_skips_employees_with_no_matching_dataset(db, organization):
    # work_locality set, but no Active LocalityDataset/Rate exists for it —
    # contributes nothing, silently (not an error).
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="US-LOC-2", name="Employee US-LOC-2",
        country_code="US", ctc=Decimal("60000"), work_state="OH", work_locality="UNKNOWN_CITY",
    )
    db.add(emp)
    db.commit()

    assert service.get_org_locality_rates(db, organization.id, country="US") == []


def test_get_org_locality_rates_empty_for_org_with_no_localities(db, organization):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="US-LOC-3", name="Employee US-LOC-3",
        country_code="US", ctc=Decimal("60000"),
    )
    db.add(emp)
    db.commit()

    assert service.get_org_locality_rates(db, organization.id, country="US") == []
