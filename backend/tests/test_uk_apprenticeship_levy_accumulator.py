"""
tests/test_uk_apprenticeship_levy_accumulator.py
----------------------------------------------------
DB-level coverage for the UK Apprenticeship Levy org-level accumulator
(service.py's _load_uk_org_levy_ytd/_upsert_uk_org_levy_ytd,
OrganizationYtdAccumulator) — mirrors test_ca_org_levy_accumulator.py's
own structure. Calculation correctness itself (the annual-telescoping
math) is covered engine-side in test_engine_standard.py's
test_apprenticeship_levy_* tests — these tests are about the DB
read/write plumbing, the shared rollout-switch dormancy contract, and
the UK-tax-year keying (distinct from Canada's calendar-year key).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import OrganizationYtdAccumulator
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    """Same shared module-level set Canada's own org-levy switch uses —
    must not leak between tests."""
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_uk_org_levy_ytd_empty_when_switch_off(db, organization):
    # Phase 3 (2026-09-09) flipped the default to {"UK"} — the OLD,
    # superseded off-state remains reachable only by explicitly
    # discarding "UK", same pattern as every other UK rollout switch's
    # "_if_explicitly_reverted" test.
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.discard("UK")
    result = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1))
    assert result == {}


def test_load_uk_org_levy_ytd_defaults_to_zero_for_fresh_org(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    result = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1))
    assert result == {
        "appr_levy_ytd_pay_bill_before": Decimal("0"),
        "employer_ni_ytd_before": Decimal("0"),
    }


def test_upsert_uk_org_levy_ytd_increments_not_overwrites(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), Decimal("2000000"))
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1), Decimal("2000000"))
    db.commit()
    loaded = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 7, 1))
    assert loaded["appr_levy_ytd_pay_bill_before"] == Decimal("4000000")


def test_upsert_uk_org_levy_ytd_updates_existing_row_not_duplicate(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), Decimal("2000000"))
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1), Decimal("2000000"))
    db.commit()
    rows = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "uk_appr_levy",
    ).all()
    assert len(rows) == 1
    assert rows[0].ytd_taxable_wages == Decimal("4000000")


def test_upsert_uk_org_levy_ytd_skips_zero_increment(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), Decimal("0"))
    db.commit()
    count = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
    ).count()
    assert count == 0


def test_uk_org_levy_tax_year_boundary_before_and_after_6_april(db, organization):
    # A March payslip belongs to the OLD UK tax year — a fresh April
    # payslip in the NEW tax year must not see March's contribution
    # (the allowance resets at the tax-year boundary).
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 3, 15), Decimal("3000000"))
    db.commit()
    old_year = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 3, 20))
    new_year = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 4, 10))
    assert old_year["appr_levy_ytd_pay_bill_before"] == Decimal("3000000")
    assert new_year["appr_levy_ytd_pay_bill_before"] == Decimal("0")


def test_last_updated_payslip_id_tracked(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), Decimal("2000000"), payslip_id=42)
    db.commit()
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "uk_appr_levy",
    ).first()
    assert row.last_updated_payslip_id == 42


# ── Employment Allowance's own accumulator (employer_ni cumulative total) ─
# Shares the same _load_uk_org_levy_ytd/_upsert_uk_org_levy_ytd pair as the
# Levy's pay-bill tracking above — both UK org-level components an
# employee always needs read/written together at the same call sites.

def test_employer_ni_accumulator_tracked_independently_of_levy_pay_bill(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(
        db, organization.id, date(2026, 5, 1),
        gross_increment=Decimal("2000000"), employer_ni_increment=Decimal("5000"),
    )
    db.commit()
    loaded = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1))
    assert loaded["appr_levy_ytd_pay_bill_before"] == Decimal("2000000")
    assert loaded["employer_ni_ytd_before"] == Decimal("5000")


def test_employer_ni_accumulator_increments_across_periods(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), gross_increment=None, employer_ni_increment=Decimal("3000"))
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1), gross_increment=None, employer_ni_increment=Decimal("2000"))
    db.commit()
    loaded = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 7, 1))
    assert loaded["employer_ni_ytd_before"] == Decimal("5000")
    # The levy pay-bill component was never touched — stays at 0.
    assert loaded["appr_levy_ytd_pay_bill_before"] == Decimal("0")


# ── Connected-employer Apprenticeship Levy pay-bill sharing ──────────────
# (ZP-TAX-UK-2026-27-001 §14/AC-24 — "Apprenticeship Levy annual
# allowance... Connected employers share one allowance under connection
# rules", found on a fresh document re-read 2026-09-10; a real gap this
# session's earlier Part 7B only closed for Employment Allowance, not
# the Levy specifically).

def _make_connected_org(db, code, org_code="LEVYGRP2"):
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="Levy Group Org", organization_code=org_code, connected_group_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_levy_pay_bill_ungrouped_org_unaffected(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), gross_increment=Decimal("500000"))
    db.commit()
    loaded = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1))
    assert loaded["appr_levy_ytd_pay_bill_before"] == Decimal("500000")


def test_levy_pay_bill_summed_across_connected_group(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    other = _make_connected_org(db, "LEVY-GROUP-A")
    organization.connected_group_code = "LEVY-GROUP-A"
    db.commit()

    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), gross_increment=Decimal("2000000"))
    service._upsert_uk_org_levy_ytd(db, other.id, date(2026, 5, 1), gross_increment=Decimal("1500000"))
    db.commit()

    # Both members must see the SAME combined group total, not just
    # their own contribution.
    loaded_a = service._load_uk_org_levy_ytd(db, organization.id, date(2026, 6, 1))
    loaded_b = service._load_uk_org_levy_ytd(db, other.id, date(2026, 6, 1))
    assert loaded_a["appr_levy_ytd_pay_bill_before"] == Decimal("3500000")
    assert loaded_b["appr_levy_ytd_pay_bill_before"] == Decimal("3500000")


def test_levy_pay_bill_group_sharing_produces_correct_shared_allowance_exhaustion(db, organization):
    """The real-world bug §14/AC-24 exists to prevent: two connected
    £2M-pay-bill employers, each checked only against their OWN £15,000
    allowance, would each show a levy well below the group's true
    combined liability. With group-aware pay-bill tracking, the SECOND
    org's payslip correctly sees the group already close to/past the
    shared allowance."""
    from app.modules.payroll.engine.countries import uk as uk_country

    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    other = _make_connected_org(db, "LEVY-GROUP-B", org_code="LEVYGRP3")
    organization.connected_group_code = "LEVY-GROUP-B"
    db.commit()

    rate_map = {
        "appr_levy_rate": type("R", (), {"employer_rate_pct": Decimal("0.5"), "flat_amount": None})(),
        "appr_levy_allowance": type("R", (), {"employer_rate_pct": None, "flat_amount": Decimal("15000")})(),
    }

    # Org A's own payroll already pushed the GROUP pay bill to £3,000,000
    # (exactly the allowance-exhaustion point: 0.5% x 3,000,000 = 15,000).
    service._upsert_uk_org_levy_ytd(db, organization.id, date(2026, 5, 1), gross_increment=Decimal("3000000"))
    db.commit()

    # Org B's own accumulator has never had a single payslip — under the
    # OLD (pre-fix) per-org-only logic it would see org_ytd_pay_bill_before=0
    # and compute levy as if starting completely fresh, wrongly getting a
    # full new allowance. With group-aware tracking, it correctly sees
    # the group is already at the exhaustion point.
    group_before = service._load_uk_org_levy_ytd(db, other.id, date(2026, 6, 1))["appr_levy_ytd_pay_bill_before"]
    assert group_before == Decimal("3000000")

    levy_on_next_payslip = uk_country.calculate_apprenticeship_levy_period_amount(Decimal("100000"), group_before, rate_map)
    # Group total after this payslip: 3,100,000. Levy already fully due
    # (allowance already exhausted at 3,000,000) -> the whole further
    # 100,000 x 0.5% = 500 is now payable, not zero.
    assert levy_on_next_payslip == Decimal("500.00")
