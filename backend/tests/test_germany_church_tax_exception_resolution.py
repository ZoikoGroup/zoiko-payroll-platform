"""
tests/test_germany_church_tax_exception_resolution.py
--------------------------------------------------------
Master audit — genuine gap closure. `resolve_germany_church_tax_exception`
(service.py) has always required THREE inputs: land_code, denomination,
and municipality_postal_code. The first has existed on
`EmployeeStatutoryProfile`/its schemas/its form since the church-tax
mechanism was built; the latter two (`de_church_tax_denomination`,
`de_church_tax_municipality_postal_code`) existed as real model columns,
genuinely read by `_resolve_germany_calc_inputs`, but were never exposed
on `EmployeeStatutoryProfileCreate`/`Response` — meaning no API caller,
UI or otherwise, could ever set them, so a published exception (e.g. the
documented Bad Wimpfen Roman Catholic case, PLZ 74206) could never
actually resolve for any real employee. This test proves the closed gap:
setting all three fields via the public schema now lets a PUBLISHED
exception resolve; leaving any one unset still correctly falls back to
the ordinary Land rate (fail-closed-to-the-general-rate, not an error).
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, SourceArtifact
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyChurchTaxExceptionCreate,
)


def _make_employee(db, org_id, code="DE-CTE-001"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=72000, basic=6000, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Church-tax exception test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_church_tax_exception(
    db, land_code="DE-BW", denomination="ROMAN_CATHOLIC", postal_code="74206",
    rate=Decimal("9.00"), maker=1, checker=2,
):
    source = _make_source(db)
    row = service.create_germany_church_tax_exception_record(
        db, GermanyChurchTaxExceptionCreate(
            land_code=land_code, denomination=denomination, municipality_postal_code=postal_code,
            exception_rate_pct=rate, effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_germany_church_tax_exception_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_germany_church_tax_exception_approver(db, row.id, actor_id=checker)
    return service.set_germany_church_tax_exception_status(db, row.id, "PUBLISHED", actor_id=checker)


def test_schema_round_trips_denomination_and_postal_code(db, organization):
    emp = _make_employee(db, organization.id)
    profile = service.create_employee_statutory_profile_version(
        db, emp.id, organization.id,
        EmployeeStatutoryProfileCreate(
            effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=True,
            de_church_tax_land="DE-BW", de_church_tax_denomination="ROMAN_CATHOLIC",
            de_church_tax_municipality_postal_code="74206",
        ), actor_id=None,
    )
    assert profile.de_church_tax_denomination == "ROMAN_CATHOLIC"
    assert profile.de_church_tax_municipality_postal_code == "74206"


def test_published_exception_resolves_once_all_three_fields_are_set(db, organization):
    _publish_church_tax_exception(db)
    emp = _make_employee(db, organization.id, code="DE-CTE-002")
    profile = service.create_employee_statutory_profile_version(
        db, emp.id, organization.id,
        EmployeeStatutoryProfileCreate(
            effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=True,
            de_church_tax_land="DE-BW", de_church_tax_denomination="ROMAN_CATHOLIC",
            de_church_tax_municipality_postal_code="74206",
        ), actor_id=None,
    )
    exception = service.resolve_germany_church_tax_exception(
        db, profile.de_church_tax_land, profile.de_church_tax_denomination,
        profile.de_church_tax_municipality_postal_code, as_of=date(2026, 6, 1),
    )
    assert exception is not None
    assert exception.exception_rate_pct == Decimal("9.00")


def test_missing_postal_code_falls_back_to_ordinary_land_rate_not_error(db, organization):
    _publish_church_tax_exception(db)
    emp = _make_employee(db, organization.id, code="DE-CTE-003")
    # Denomination recorded, but no postal code — the exception is genuinely
    # inapplicable (unknown residence), so this must resolve to None (use
    # the ordinary Land rate), never raise and never guess a match.
    profile = service.create_employee_statutory_profile_version(
        db, emp.id, organization.id,
        EmployeeStatutoryProfileCreate(
            effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=True,
            de_church_tax_land="DE-BW", de_church_tax_denomination="ROMAN_CATHOLIC",
        ), actor_id=None,
    )
    assert profile.de_church_tax_municipality_postal_code is None
    exception = service.resolve_germany_church_tax_exception(
        db, profile.de_church_tax_land, profile.de_church_tax_denomination,
        profile.de_church_tax_municipality_postal_code, as_of=date(2026, 6, 1),
    )
    assert exception is None


def test_non_matching_postal_code_does_not_resolve(db, organization):
    _publish_church_tax_exception(db)  # PLZ 74206
    emp = _make_employee(db, organization.id, code="DE-CTE-004")
    profile = service.create_employee_statutory_profile_version(
        db, emp.id, organization.id,
        EmployeeStatutoryProfileCreate(
            effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=True,
            de_church_tax_land="DE-BW", de_church_tax_denomination="ROMAN_CATHOLIC",
            de_church_tax_municipality_postal_code="70173",  # Stuttgart, not Bad Wimpfen
        ), actor_id=None,
    )
    exception = service.resolve_germany_church_tax_exception(
        db, profile.de_church_tax_land, profile.de_church_tax_denomination,
        profile.de_church_tax_municipality_postal_code, as_of=date(2026, 6, 1),
    )
    assert exception is None
