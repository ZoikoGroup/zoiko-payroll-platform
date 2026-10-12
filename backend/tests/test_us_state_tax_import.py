"""
tests/test_us_state_tax_import.py
-----------------------------------
Coverage for service.bulk_import_state_tax_pack — the "New State Import"
bulk tooling (Production-Readiness Plan Phase 3, 2026-09-15). Today the
only way to add a brand-new state's full bracket table is hand-writing a
Python dict into hardcoded_defaults.py and running a seed script; this
gives Tax Ops a single-submit path through the exact same Draft->Approved
->Active JurisdictionPack lifecycle and publish gates every other US pack
already goes through.
"""

from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import TaxSlab, ContributionRate, JurisdictionPack


def _bracket_rows():
    return [
        {"filingStatus": "SINGLE", "minAmount": Decimal("0"), "maxAmount": Decimal("10000"), "ratePct": Decimal("2.0")},
        {"filingStatus": "SINGLE", "minAmount": Decimal("10000"), "maxAmount": None, "ratePct": Decimal("4.0")},
        {"filingStatus": "MFJ", "minAmount": Decimal("0"), "maxAmount": Decimal("20000"), "ratePct": Decimal("2.0")},
        {"filingStatus": "MFJ", "minAmount": Decimal("20000"), "maxAmount": None, "ratePct": Decimal("4.0")},
    ]


def _standard_deduction_rows():
    return [
        {"filingStatus": "SINGLE", "label": "Standard Deduction (Single)", "flatAmount": Decimal("3000")},
        {"filingStatus": "MFJ", "label": "Standard Deduction (MFJ)", "flatAmount": Decimal("6000")},
    ]


def test_bulk_import_creates_new_draft_pack_with_bracket_and_deduction_rows(db):
    pack = service.bulk_import_state_tax_pack(
        db, jurisdiction_state="ks", version="2026.1",
        bracket_rows=_bracket_rows(), standard_deduction_rows=_standard_deduction_rows(),
    )
    assert pack.status == "Draft"
    assert pack.jurisdiction_country == "US"
    assert pack.jurisdiction_state == "KS"
    assert pack.pack_id == "US-KS-STATE-TAX"

    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).order_by(TaxSlab.sort_order).all()
    assert len(slabs) == 4
    assert {s.filing_status for s in slabs} == {"SINGLE", "MFJ"}
    assert all(s.rule_type == "MARGINAL_RATE" for s in slabs)
    assert all(s.jurisdiction_state == "KS" for s in slabs)

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert len(rates) == 2
    assert {r.filing_status for r in rates} == {"SINGLE", "MFJ"}
    assert all(r.component_key == "state_standard_deduction" for r in rates)
    assert {r.flat_amount for r in rates} == {Decimal("3000.00"), Decimal("6000.00")}


def test_bulk_import_requires_at_least_one_bracket_row(db):
    with pytest.raises(BadRequestException):
        service.bulk_import_state_tax_pack(db, jurisdiction_state="KS", version="2026.1", bracket_rows=[])


def test_bulk_import_requires_a_state(db):
    with pytest.raises(BadRequestException):
        service.bulk_import_state_tax_pack(db, jurisdiction_state="", version="2026.1", bracket_rows=_bracket_rows())


def test_bulk_import_standard_deduction_rows_are_optional(db):
    pack = service.bulk_import_state_tax_pack(
        db, jurisdiction_state="LA", version="2026.1", bracket_rows=_bracket_rows(),
    )
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert rates == []


def test_bulk_import_accepts_custom_pack_id_and_effective_from(db):
    from datetime import date

    pack = service.bulk_import_state_tax_pack(
        db, jurisdiction_state="OR", version="2026.1", pack_id="US-OR-CUSTOM",
        effective_from=date(2026, 1, 1), bracket_rows=_bracket_rows(),
    )
    assert pack.pack_id == "US-OR-CUSTOM"
    assert pack.effective_from == date(2026, 1, 1)


def test_bulk_imported_pack_still_goes_through_existing_publish_gates(db):
    # No source artifact / no effective date on this pack — the SAME gate
    # every other US pack hits in set_jurisdiction_pack_status. Confirms
    # the bulk import doesn't bypass anything the lifecycle already
    # enforces; it's a data-entry shortcut, not a new activation path.
    pack = service.bulk_import_state_tax_pack(
        db, jurisdiction_state="ME", version="2026.1", bracket_rows=_bracket_rows(),
    )
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=1)
    with pytest.raises(BadRequestException, match="Source Evidence"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=2)


def test_bulk_import_creates_only_one_pack_per_call(db):
    service.bulk_import_state_tax_pack(db, jurisdiction_state="MD", version="2026.1", bracket_rows=_bracket_rows())
    count = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_state == "MD").count()
    assert count == 1
