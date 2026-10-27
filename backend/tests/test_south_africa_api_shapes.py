"""South Africa API shapes (ZP-ZA-ENG-001 Phase 7) — the request / response
contracts the frontend depends on, exercised through the same entry points the
routes use. Regression tests for two Phase 5 gaps:

  * EmployeeStatutoryProfileCreate / Response had no za_* fields and ignore
    unknown keys, so every South Africa profile fact sent by the UI was
    silently dropped and none was returned;
  * _serialize_payslip / PayslipItemResponse never carried
    zaCalculationSnapshot, so the ZA payslip breakdown could not render.

"ZA" is South Africa; "SA" is Saudi Arabia.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.models import PayrollEmployee
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate,
    EmployeeStatutoryProfileResponse,
    PayslipItemResponse,
)

# Exactly the camelCase keys SouthAfricaStatutoryProfilePanel.jsx sends.
UI_PAYLOAD = {
    "countryCode": "ZA", "effectiveFrom": "2026-03-01",
    "zaEmploymentType": "standard", "zaTaxResidency": "RESIDENT", "zaIsDirector": True,
    "zaMedicalSchemeMember": True, "zaMedicalDependants": 2, "zaTravelBusinessUse80": False,
    "zaUifExcluded": False, "zaUifExclusionReason": None, "zaEtiEligible": True,
    "zaEtiFirstQualifyingMonth": "2026-03-01", "zaSezEmployee": False,
    "zaVoluntaryAdditionalPaye": "150.00", "zaEvidenceRef": "HR-FILE-001",
}


@pytest.fixture()
def za_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ZA_TENANT_ONBOARDING_ENABLED", True)


def _employee(db, organization):
    employee = PayrollEmployee(
        organization_id=organization.id, employee_code="ZA-P7-1", name="Employee ZA-P7-1",
        date_of_joining=date(2020, 1, 1), basic=Decimal("10000"), country_code="ZA",
        compliance_fields={"national_id": "8001015009087", "tax_number": "0123456789"},
    )
    db.add(employee)
    db.flush()
    return employee


def test_create_schema_accepts_every_za_fact_the_ui_sends():
    data = EmployeeStatutoryProfileCreate(**UI_PAYLOAD)
    assert set(svc.ZA_PROFILE_COLUMNS) <= data.model_fields_set
    values = svc._za_profile_values(None, None, data, None)
    assert values["za_employment_type"] == "STANDARD"           # normalised
    assert values["za_medical_dependants"] == 2
    assert values["za_voluntary_additional_paye"] == Decimal("150.00")
    assert values["za_eti_first_qualifying_month"] == date(2026, 3, 1)
    assert set(values) == set(svc.ZA_PROFILE_COLUMNS)


def test_profile_errors_run_on_the_parsed_request():
    data = EmployeeStatutoryProfileCreate(**{**UI_PAYLOAD, "zaMedicalDependants": None})
    errors = svc._za_statutory_profile_errors(data)
    assert any("za_medical_dependants" in e for e in errors)


def test_profile_round_trips_through_the_service_and_response(db, organization, za_on):
    from app.modules.payroll import service

    employee = _employee(db, organization)
    row = service.create_employee_statutory_profile_version(
        db, employee.id, organization.id, EmployeeStatutoryProfileCreate(**UI_PAYLOAD), actor_id=1)
    assert (row.za_employment_type, row.za_medical_dependants, row.za_is_director) == ("STANDARD", 2, True)
    dumped = EmployeeStatutoryProfileResponse.model_validate(row).model_dump(by_alias=True)
    assert dumped["zaEmploymentType"] == "STANDARD"
    assert dumped["zaMedicalSchemeMember"] is True and dumped["zaMedicalDependants"] == 2
    assert dumped["zaVoluntaryAdditionalPaye"] == Decimal("150.00")
    assert dumped["zaEvidenceRef"] == "HR-FILE-001"


def test_an_unchanged_fact_carries_forward_to_the_next_version(db, organization, za_on):
    from app.modules.payroll import service

    employee = _employee(db, organization)
    service.create_employee_statutory_profile_version(
        db, employee.id, organization.id, EmployeeStatutoryProfileCreate(**UI_PAYLOAD), actor_id=1)
    second = service.create_employee_statutory_profile_version(
        db, employee.id, organization.id,
        EmployeeStatutoryProfileCreate(countryCode="ZA", effectiveFrom="2026-06-01", zaMedicalDependants=3),
        actor_id=1)
    assert second.za_medical_dependants == 3
    assert second.za_employment_type == "STANDARD" and second.za_evidence_ref == "HR-FILE-001"


def test_payslip_response_declares_the_za_snapshot():
    assert "zaCalculationSnapshot" in PayslipItemResponse.model_fields
    snap = {"za_paye": "11075.58", "za_eti_amount": "0.00"}
    assert PayslipItemResponse.model_construct(zaCalculationSnapshot=snap).model_dump()["zaCalculationSnapshot"] == snap


@pytest.mark.parametrize("country, expected", [("ZA", {"za_paye": "11075.58"}), ("SA", None)])
def test_serialized_payslip_carries_the_za_snapshot_for_za_only(db, organization, country, expected):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayslipItem

    employee = _employee(db, organization)
    run = PayrollRun(organization_id=organization.id, period_label="2026-09", period_start=date(2026, 9, 1),
                     period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code=country, gross_pay=Decimal("50000"),
                       net_pay=Decimal("38747.30"), za_calculation_snapshot={"za_paye": "11075.58"})
    db.add(item)
    db.flush()
    assert service._serialize_payslip(item, run, country=country)["zaCalculationSnapshot"] == expected
