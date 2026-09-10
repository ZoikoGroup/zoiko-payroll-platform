"""
tests/test_uk_rti_config_fields.py
--------------------------------------------
Coverage for the UK RTI data-gap config fields added in ZP-TAX-UK-2026-27-
001 §18 gap-closure Part 9 (2026-09-09): PayrollEmployee address/starter-
declaration fields flow through create_employee/update_employee, and
CompanyComplianceDetails paye_reference/accounts_office_reference flow
through update_company_details — both real, persisted columns, not just
schema-only additions.
"""
from app.modules.payroll import service
from app.modules.payroll.schemas import EmployeeCreate, EmployeeUpdate, CompanyDetailsUpdate


_UK_COMPLIANCE_FIELDS = {"nino": "AB123456C", "paye_tax_code": "1257L", "sort_code": "12-34-56"}


def test_create_employee_persists_uk_rti_fields(db, organization):
    # employee_code supplied explicitly — generate_employee_code() calls a
    # Postgres-only pg_advisory_xact_lock() the SQLite test DB can't run
    # (the same pre-existing test-infrastructure gap noted for leave
    # requests in test_uk_statutory_leave_wiring.py).
    data = EmployeeCreate(
        employee_code="RTICFG1", name="Ada Lovelace", countryCode="UK",
        addressLine1="1 Test Street", addressTown="London", addressPostcode="SW1A 1AA",
        starterDeclaration="A", complianceFields=_UK_COMPLIANCE_FIELDS,
    )
    employee = service.create_employee(db, data, organization.id)
    assert employee.address_line1 == "1 Test Street"
    assert employee.address_town == "London"
    assert employee.address_postcode == "SW1A 1AA"
    assert employee.starter_declaration == "A"


def test_update_employee_persists_uk_rti_fields(db, organization):
    created = service.create_employee(
        db, EmployeeCreate(employee_code="RTICFG2", name="Grace Hopper", countryCode="UK", complianceFields=_UK_COMPLIANCE_FIELDS), organization.id,
    )
    assert created.address_line1 is None

    updated = service.update_employee(
        db, created.id,
        EmployeeUpdate(addressLine1="2 Test Avenue", addressCounty="Greater London", starterDeclaration="B"),
        organization.id,
    )
    assert updated.address_line1 == "2 Test Avenue"
    assert updated.address_county == "Greater London"
    assert updated.starter_declaration == "B"


def test_update_company_details_persists_paye_and_accounts_office_reference(db, organization):
    service.get_company_details(db, organization.id)  # ensures a row exists
    updated = service.update_company_details(
        db, organization.id,
        CompanyDetailsUpdate(payeReference="123/AB45678", accountsOfficeReference="123PX00012345"),
    )
    assert updated.paye_reference == "123/AB45678"
    assert updated.accounts_office_reference == "123PX00012345"
