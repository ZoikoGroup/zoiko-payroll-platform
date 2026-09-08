"""
tests/test_ca_org_levy_accumulator.py
----------------------------------------
DB-level coverage for the Canada org-level employer-levy YTD accumulator
(service.py's _load_ca_org_levy_ytd/_upsert_ca_org_levy_ytd,
OrganizationYtdAccumulator) — the foundational piece for Ontario/BC EHT,
Manitoba HE Levy, NL HAPSET, and Quebec HSF (ZP-TAX-CA-2026-001 §13/§15).
No levy calculation exists yet to call these, so these tests exercise the
plumbing directly, the same way test_ca_ytd_accumulator.py proved the
per-employee accumulator's read/write contract before canada.py's
CPP/CPP2/EI math was changed to consume it.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import OrganizationYtdAccumulator
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    """Same leak-prevention pattern already used for
    _YTD_ACCUMULATOR_ENABLED_COUNTRIES/_VALIDATION_ENABLED_COUNTRIES
    elsewhere in this suite."""
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_ca_org_levy_ytd_empty_when_switch_off(db, organization):
    assert "CA" not in shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES
    result = service._load_ca_org_levy_ytd(db, organization.id, date(2026, 6, 1), ("on_eht",))
    assert result == {}


def test_load_ca_org_levy_ytd_defaults_to_zero_for_fresh_org(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    result = service._load_ca_org_levy_ytd(db, organization.id, date(2026, 6, 1), ("on_eht", "mb_he_levy"))
    assert result == {"on_eht": Decimal("0"), "mb_he_levy": Decimal("0")}


def test_upsert_ca_org_levy_ytd_increments_not_overwrites(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"on_eht": Decimal("8000")})
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 2, 1), {"on_eht": Decimal("8000")})
    db.commit()
    loaded = service._load_ca_org_levy_ytd(db, organization.id, date(2026, 3, 1), ("on_eht",))
    assert loaded["on_eht"] == Decimal("16000")


def test_upsert_ca_org_levy_ytd_updates_existing_row_not_duplicate(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"on_eht": Decimal("5000")})
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 2, 1), {"on_eht": Decimal("5000")})
    db.commit()
    rows = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).all()
    assert len(rows) == 1
    assert rows[0].ytd_taxable_wages == Decimal("10000")


def test_upsert_ca_org_levy_ytd_skips_zero_increment(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"on_eht": Decimal("0")})
    db.commit()
    count = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
    ).count()
    assert count == 0


def test_upsert_ca_org_levy_ytd_noop_when_increments_empty(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {})
    db.commit()
    count = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
    ).count()
    assert count == 0


def test_multiple_levy_components_tracked_independently(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(
        db, organization.id, date(2026, 1, 1), {"on_eht": Decimal("8000"), "mb_he_levy": Decimal("3000")},
    )
    db.commit()
    loaded = service._load_ca_org_levy_ytd(db, organization.id, date(2026, 2, 1), ("on_eht", "mb_he_levy"))
    assert loaded == {"on_eht": Decimal("8000"), "mb_he_levy": Decimal("3000")}


def test_last_updated_payslip_id_tracked(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"on_eht": Decimal("8000")}, payslip_id=42)
    db.commit()
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id, OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    assert row.last_updated_payslip_id == 42
