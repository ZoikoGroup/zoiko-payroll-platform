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
from app.modules.payroll.models import TaxSlab, ContributionRate


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
