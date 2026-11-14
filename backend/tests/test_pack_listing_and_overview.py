"""
tests/test_pack_listing_and_overview.py
---------------------------------------
Super Admin Active Pack fixes (Overview / Active Pack audit, P3b):

1. The cross-jurisdiction pack list returned only the newest-created version
   of each pack, hiding the Active version once a Draft version was started.
2. Editing a pack overwrote every column from the payload, so an Overview
   edit (which sends a subset) wiped source_document_id and other fields.
3. A new version cloned rates from the newest row (possibly a Draft) and
   started with blank metadata.
4. The org-facing version list sorted the version string as text.
5. New read-only Overview summary for every country.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
from app.modules.payroll.schemas import JurisdictionPackUpsert


def _pack(db, version, status, *, pack_id="XX-TAX", created_offset=0, **kw):
    from datetime import datetime

    row = JurisdictionPack(
        pack_id=pack_id, version=version, jurisdiction_country=kw.pop("country", "IN"), pack_type="tax",
        status=status, created_at=datetime(2026, 1, 1) + timedelta(days=created_offset), **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _rate(db, pack, key, **kw):
    fields = {"employee_share": "0%", "employer_share": "0%", "total": "0%", **kw}
    db.add(ContributionRate(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="IN",
                            component_key=key, label=fields.pop("label", key), **fields))
    db.commit()


# 1 ── listing ────────────────────────────────────────────────────────────────

def test_list_shows_the_active_version_not_a_newer_draft(db):
    active = _pack(db, "1.0", "Active", effective_from=date.today() - timedelta(days=30))
    _pack(db, "1.1", "Draft", created_offset=5)
    (row,) = service.list_all_jurisdiction_packs(db, country="IN")
    assert row.id == active.id


def test_list_prefers_the_active_version_in_force_today(db):
    _pack(db, "1.0", "Active", effective_from=date.today() - timedelta(days=400),
          effective_to=date.today() - timedelta(days=1))
    current = _pack(db, "2.0", "Active", effective_from=date.today() - timedelta(days=10), created_offset=3)
    _pack(db, "3.0", "Draft", created_offset=6)
    (row,) = service.list_all_jurisdiction_packs(db, country="IN")
    assert row.id == current.id


def test_list_falls_back_to_latest_when_nothing_is_active(db):
    _pack(db, "1.0", "Draft")
    latest = _pack(db, "1.1", "Draft", created_offset=2)
    (row,) = service.list_all_jurisdiction_packs(db, country="IN")
    assert row.id == latest.id


# 2 ── edit keeps fields it did not send ──────────────────────────────────────

def test_editing_overview_keeps_unsent_fields(db):
    pack = _pack(db, "1.0", "Draft", source_document_id=77, default_tax_regime="new",
                 policy_defaults={"x": 1}, regulatory_authority="Old authority")
    service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        id=pack.id, packId="XX-TAX", jurisdictionCountry="IN", packType="tax", version="1.0", status="Draft",
        regulatoryAuthority="New authority",
    ))
    db.refresh(pack)
    assert pack.regulatory_authority == "New authority"
    assert (pack.source_document_id, pack.default_tax_regime, pack.policy_defaults) == (77, "new", {"x": 1})


def test_a_field_sent_as_null_is_still_cleared(db):
    pack = _pack(db, "1.0", "Draft", compliance_owner="Someone")
    service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        id=pack.id, packId="XX-TAX", jurisdictionCountry="IN", packType="tax", complianceOwner=None,
    ))
    db.refresh(pack)
    assert pack.compliance_owner is None


def test_inverted_dates_are_checked_against_the_stored_date(db):
    import pytest
    from app.core.exceptions import BadRequestException

    pack = _pack(db, "1.0", "Draft", effective_from=date(2026, 4, 1))
    with pytest.raises(BadRequestException):
        service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
            id=pack.id, packId="XX-TAX", jurisdictionCountry="IN", packType="tax", effectiveTo=date(2026, 1, 1),
        ))


# 3 ── new version is based on the Active version ─────────────────────────────

def test_new_version_inherits_metadata_and_clones_the_active_versions_rates(db):
    active = _pack(db, "1.0", "Active", effective_from=date.today() - timedelta(days=30),
                   regulatory_authority="CBDT", currency="INR", source_document_id=12, compliance_owner="Tax team")
    _rate(db, active, "pf", employee_share="12%")
    draft = _pack(db, "1.1", "Draft", created_offset=4)
    _rate(db, draft, "draft_only_row", employee_share="1%")

    new = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId="XX-TAX", jurisdictionCountry="IN", packType="tax", version="2.0", status="Draft",
    ))
    assert (new.regulatory_authority, new.currency, new.source_document_id, new.compliance_owner) == (
        "CBDT", "INR", 12, "Tax team")
    keys = {r.component_key for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == new.id)}
    assert keys == {"pf"}


# 4 ── version ordering ───────────────────────────────────────────────────────

def test_version_list_is_newest_first_not_text_sorted(db):
    _pack(db, "2.0", "Draft")
    newest = _pack(db, "10.0", "Draft", created_offset=9)
    rows = service.list_jurisdiction_packs(db, "IN")
    assert rows[0].id == newest.id


# 5 ── overview summary ───────────────────────────────────────────────────────

def test_overview_counts_configuration_and_names_missing_metadata(db):
    pack = _pack(db, "1.0", "Active", effective_from=date.today() - timedelta(days=5), currency="INR",
                 approved_by_id=None)
    _rate(db, pack, "pf", employee_share="12%", employer_share="12%")
    _rate(db, pack, "esi", employer_share="3.25%")
    _rate(db, pack, "std_deduction", flat_amount=Decimal("75000"))
    _rate(db, pack, "lwf", label="LWF [PENDING G1]")
    db.add_all([
        TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="IN", min_amount=0,
                rate_pct=5, rate_label="5%", tax_formula="5%", rule_type="MARGINAL_RATE", tax_regime="new"),
        TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="IN", min_amount=0,
                rate_pct=0, rate_label="Nil", tax_formula="Nil", rule_type="PT_FLAT", jurisdiction_state="Karnataka"),
    ])
    db.commit()

    ov = service.get_jurisdiction_pack_overview(db, pack.id)
    assert ov["lifecycle"]["isActive"] and ov["lifecycle"]["inForceToday"]
    assert ov["lifecycle"]["approved"] is False and ov["lifecycle"]["sourceDocumentAttached"] is False
    assert ov["contributions"] == {"total": 4, "employeeSide": 1, "employerSide": 2, "parameters": 2,
                                   "pendingSignOff": 1}
    assert [(g["ruleType"], g["count"]) for g in ov["taxSlabs"]["byRuleType"]] == [("MARGINAL_RATE", 1), ("PT_FLAT", 1)]
    assert ov["regions"] == ["Karnataka"]
    assert "Regulatory authority" in ov["missingMetadata"] and "Currency" not in ov["missingMetadata"]
