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
    assert "UK" not in shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES
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
