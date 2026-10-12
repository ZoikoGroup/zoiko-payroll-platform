"""
tests/test_statutory_filings.py
---------------------------------
Coverage for the statutory-filing status write path behind the Super Admin
Filings & Remittances dashboard (payroll.service.upsert_statutory_filing /
delete_statutory_filing / list_statutory_filings) and its read merge in
command_center_router._load_org_filing_coverage.
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import StatutoryFiling
from app.modules.payroll.schemas import StatutoryFilingUpsert


_org_counter = 0


def _make_org(db):
    from app.modules.organizations.models import Organization
    global _org_counter
    _org_counter += 1
    org = Organization(organization_name=f"Acme Filing Test {_org_counter}", organization_code=f"ACMFILE{_org_counter}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _set_compliance(db, organization_id, country="IN"):
    from app.modules.payroll.models import CompanyComplianceDetails
    row = CompanyComplianceDetails(
        organization_id=organization_id, name="Acme", tax_no="AA",
        jurisdiction_country=country,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _upsert(db, org_id, **kw):
    defaults = dict(filingType="TDS", periodLabel="Q1 FY2026-27", status="FILED")
    defaults.update(kw)
    return service.upsert_statutory_filing(db, org_id, StatutoryFilingUpsert(**defaults), actor_id=None)


def test_upsert_creates_with_derived_jurisdiction(db):
    org = _make_org(db)
    _set_compliance(db, org.id, country="India")
    row = _upsert(db, org.id, periodStart=date(2026, 4, 1), periodEnd=date(2026, 6, 30))
    assert row.organization_id == org.id
    assert row.jurisdiction == "IN"
    assert row.filing_type == "TDS"
    assert row.status == "FILED"
    assert db.query(StatutoryFiling).count() == 1


def test_upsert_same_period_updates_not_duplicates(db):
    org = _make_org(db)
    _set_compliance(db, org.id)
    _upsert(db, org.id, status="NOT_STARTED")
    row = _upsert(db, org.id, status="IN_PROGRESS", blockedReason=None)
    assert row.status == "IN_PROGRESS"
    assert db.query(StatutoryFiling).count() == 1
    same_period_different_type = _upsert(db, org.id, filingType="GST", status="FILED")
    assert db.query(StatutoryFiling).count() == 2
    assert same_period_different_type.filing_type == "GST"


def test_upsert_rejects_unknown_status(db):
    org = _make_org(db)
    _set_compliance(db, org.id)
    with pytest.raises(BadRequestException):
        _upsert(db, org.id, status="EMITTED")


def test_upsert_rejects_reversed_period(db):
    org = _make_org(db)
    _set_compliance(db, org.id)
    with pytest.raises(BadRequestException):
        _upsert(db, org.id, periodStart=date(2026, 7, 1), periodEnd=date(2026, 6, 30))


def test_upsert_rejects_org_without_jurisdiction(db):
    org = _make_org(db)
    with pytest.raises(BadRequestException):
        _upsert(db, org.id)


def test_upsert_rejects_blank_filing_type_and_period(db):
    org = _make_org(db)
    _set_compliance(db, org.id)
    with pytest.raises(BadRequestException):
        _upsert(db, org.id, filingType="  ")
    with pytest.raises(BadRequestException):
        _upsert(db, org.id, periodLabel="")


def test_list_scoped_to_org(db):
    org_a = _make_org(db)
    org_b = _make_org(db)
    _set_compliance(db, org_a.id)
    _set_compliance(db, org_b.id)
    _upsert(db, org_a.id)
    _upsert(db, org_b.id)
    rows_a = service.list_statutory_filings(db, org_a.id)
    rows_b = service.list_statutory_filings(db, org_b.id)
    assert [r.organization_id for r in rows_a] == [org_a.id]
    assert [r.organization_id for r in rows_b] == [org_b.id]


def test_delete_removes_and_rejects_missing(db):
    org = _make_org(db)
    _set_compliance(db, org.id)
    row = _upsert(db, org.id)
    service.delete_statutory_filing(db, row.id, actor_id=None)
    assert db.query(StatutoryFiling).count() == 0
    with pytest.raises(NotFoundException):
        service.delete_statutory_filing(db, row.id, actor_id=None)


def test_delete_org_scoped_rejects_foreign_org(db):
    org_a = _make_org(db)
    org_b = _make_org(db)
    _set_compliance(db, org_a.id)
    _set_compliance(db, org_b.id)
    row_a = _upsert(db, org_a.id)
    # org B cannot delete org A's row
    with pytest.raises(NotFoundException):
        service.delete_statutory_filing(db, row_a.id, actor_id=None, organization_id=org_b.id)
    assert db.query(StatutoryFiling).count() == 1


def test_filing_coverage_merge(db):
    """command_center_router._load_org_filing_coverage buckets the org under
    its jurisdiction with its recorded filings."""
    from app.modules.super_admin import command_center_router as ccr

    org = _make_org(db)
    _set_compliance(db, org.id, country="IN")
    _upsert(db, org.id, filingType="TDS", periodLabel="Q1", status="FILED")
    _upsert(db, org.id, filingType="GST", periodLabel="Aug 2026", status="OVERDUE")

    jurisdictions, unconfigured = ccr._load_org_filing_coverage(db)
    assert unconfigured == []
    section = jurisdictions["IN"]
    assert section["total"] == 2
    assert section["blocked_count"] == 0
    org_section = section["organizations"][0]
    assert org_section["org_id"] == org.id
    statuses = {f["status"] for f in org_section["filings"]}
    assert statuses == {"FILED", "OVERDUE"}