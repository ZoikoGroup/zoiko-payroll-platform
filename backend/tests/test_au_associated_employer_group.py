"""
tests/test_au_associated_employer_group.py
-----------------------------------------------
Coverage for Australia's cross-employer group/interstate wage aggregation
(ZP-TAX-AU-2026-27-001 §AU-D07, closed 2026-09-17) — state payroll-tax
rate/threshold entitlement may depend on Australian-wide wages and group
status, not only wages this org itself paid in the state. Reuses the
EXACT SAME Organization.connected_group_code + _connected_group_member_
ids/_sum_org_ytd_component_across_orgs mechanism CA's EHT/HE Levy/HAPSET
and UK's Apprenticeship Levy sharing already established and test (see
test_ca_associated_employer_group.py), gated behind the SAME
_CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES switch now widened to include "AU".
"""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_au_group_switches():
    original_org_levy = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    original_group = set(shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original_org_levy)
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.clear()
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.update(original_group)


def _make_connected_org(db, code, org_code="AUGRP2"):
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="AU Group Org", organization_code=org_code, connected_group_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_au_payroll_tax_ungrouped_org_unaffected(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("AU")
    service._upsert_ca_org_levy_ytd(
        db, organization.id, date(2026, 8, 1), {"au_payroll_tax_nsw": Decimal("500000")},
        tax_year=service._au_ytd_tax_year(date(2026, 8, 1)),
    )
    db.commit()
    inputs = service._au_org_payroll_tax_read_inputs(db, organization.id, date(2026, 9, 1), "NSW")
    assert inputs["au_state_payroll_tax_ytd_remuneration_before"] == Decimal("500000")


def test_au_payroll_tax_summed_across_connected_group_when_switch_on(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("AU")
    other = _make_connected_org(db, "AU-GROUP-A")
    organization.connected_group_code = "AU-GROUP-A"
    db.commit()

    tax_year = service._au_ytd_tax_year(date(2026, 8, 1))
    service._upsert_ca_org_levy_ytd(
        db, organization.id, date(2026, 8, 1), {"au_payroll_tax_nsw": Decimal("600000")}, tax_year=tax_year,
    )
    service._upsert_ca_org_levy_ytd(
        db, other.id, date(2026, 8, 1), {"au_payroll_tax_nsw": Decimal("700000")}, tax_year=tax_year,
    )
    db.commit()

    # Both members must see the SAME combined group total, not just their
    # own contribution — mirrors CA's identical test for Ontario EHT.
    inputs_a = service._au_org_payroll_tax_read_inputs(db, organization.id, date(2026, 9, 1), "NSW")
    inputs_b = service._au_org_payroll_tax_read_inputs(db, other.id, date(2026, 9, 1), "NSW")
    assert inputs_a["au_state_payroll_tax_ytd_remuneration_before"] == Decimal("1300000")
    assert inputs_b["au_state_payroll_tax_ytd_remuneration_before"] == Decimal("1300000")


def test_au_payroll_tax_group_summation_dormant_when_switch_off(db, organization):
    # _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES on, but _CA_ASSOCIATED_
    # GROUP_ENABLED_COUNTRIES off — group summation must NOT kick in even
    # though the org has a connected_group_code set.
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.discard("AU")
    other = _make_connected_org(db, "AU-GROUP-B", org_code="AUGRP3")
    organization.connected_group_code = "AU-GROUP-B"
    db.commit()

    tax_year = service._au_ytd_tax_year(date(2026, 8, 1))
    service._upsert_ca_org_levy_ytd(
        db, organization.id, date(2026, 8, 1), {"au_payroll_tax_nsw": Decimal("600000")}, tax_year=tax_year,
    )
    service._upsert_ca_org_levy_ytd(
        db, other.id, date(2026, 8, 1), {"au_payroll_tax_nsw": Decimal("700000")}, tax_year=tax_year,
    )
    db.commit()

    inputs = service._au_org_payroll_tax_read_inputs(db, organization.id, date(2026, 9, 1), "NSW")
    assert inputs["au_state_payroll_tax_ytd_remuneration_before"] == Decimal("600000")


def test_au_payroll_tax_group_summation_dormant_when_no_connected_group_code(db, organization):
    """Every real org today (no connected_group_code set) sums across a
    'group of one' — identical to reading its own total alone, even with
    the switch on."""
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("AU")
    tax_year = service._au_ytd_tax_year(date(2026, 8, 1))
    service._upsert_ca_org_levy_ytd(
        db, organization.id, date(2026, 8, 1), {"au_payroll_tax_nsw": Decimal("450000")}, tax_year=tax_year,
    )
    db.commit()

    inputs = service._au_org_payroll_tax_read_inputs(db, organization.id, date(2026, 9, 1), "NSW")
    assert inputs["au_state_payroll_tax_ytd_remuneration_before"] == Decimal("450000")
