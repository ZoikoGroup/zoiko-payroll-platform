"""South Africa service integration (ZP-ZA-ENG-001 Phase 5).

Covers the employer-registration lifecycle, profile validation, calculation
inputs, frozen snapshots and the read-only Super Admin summary. "ZA" is South
Africa; "SA" is Saudi Arabia.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.employee_validation import ZAEmployeeValidation
from app.modules.payroll.models import (
    EmployeeStatutoryProfile,
    PayrollEmployee,
)


def _employee(db, organization, *, code="ZA-P5-1"):
    employee = PayrollEmployee(
        organization_id=organization.id, employee_code=code,
        name=f"Employee {code}", date_of_joining=date(2020, 1, 1),
        basic=Decimal("10000"), country_code="ZA",
        compliance_fields={},
    )
    db.add(employee)
    db.flush()
    return employee


def _profile(db, organization, employee, **overrides):
    values = dict(
        employee_id=employee.id, organization_id=organization.id,
        country_code="ZA", effective_from=date(2026, 3, 1),
        za_employment_type="STANDARD", za_tax_residency="RESIDENT",
        za_is_director=False, za_medical_scheme_member=False,
        za_medical_dependants=0, za_travel_business_use_80=False,
        za_uif_excluded=False, za_eti_eligible=True,
        za_eti_first_qualifying_month=date(2026, 3, 1),
        za_sez_employee=False,
    )
    values.update(overrides)
    row = EmployeeStatutoryProfile(**values)
    db.add(row)
    db.flush()
    return row


def _registration(db, organization, **overrides):
    values = dict(
        organization_id=organization.id, effective_from=date(2026, 3, 1),
        paye_reference="7123456789", uif_reference="U123456789",
        sdl_reference="L123456789", coida_reference="1234567/ABC",
        sdl_liable=True, eti_registered=True, created_by_id=1,
    )
    values.update(overrides)
    return svc.create_za_employer_registration(db, organization.id, values, actor_id=1)


def test_registration_starts_draft_and_records_references(db, organization):
    row = _registration(db, organization)
    assert row.status == "DRAFT" and row.organization_id == organization.id
    assert row.paye_reference == "7123456789"
    assert row.sdl_liable is True and row.eti_registered is True


@pytest.mark.parametrize("overrides", [
    {"paye_reference": "8123456789"},
    {"paye_reference": "712345678"},
    {"uif_reference": "123456789"},
    {"sdl_reference": "X123456789"},
    {"coida_reference": "!!!"},
    {"sdl_liable": None},
    {"sdl_liable": False},
    {"sdl_liable": True, "sdl_exemption_reason": "not needed"},
    {"effective_from": "2026-03-01", "effective_to": "2026-02-01"},
])
def test_registration_refuses_invalid_payloads(db, organization, overrides):
    with pytest.raises(Exception):
        _registration(db, organization, **overrides)


def test_registration_four_eyes_and_supersede(db, organization):
    first = _registration(db, organization)
    with pytest.raises(Exception) as exc:
        svc.approve_za_employer_registration(db, first.id, approver_id=1,
                                             organization_id=organization.id)
    assert "four-eyes" in str(exc.value)

    active = svc.approve_za_employer_registration(
        db, first.id, approver_id=2, organization_id=organization.id)
    assert active.status == "ACTIVE"

    second = _registration(db, organization, effective_from=date(2027, 3, 1),
                           paye_reference="7987654321")
    superseded = svc.approve_za_employer_registration(
        db, second.id, approver_id=2, organization_id=organization.id)
    assert superseded.status == "ACTIVE"
    assert superseded.previous_version_id == active.id
    assert active.status == "SUPERSEDED"
    assert active.effective_to == date(2027, 2, 28)


def test_registration_scope_is_enforced(db, organization):
    row = _registration(db, organization)
    with pytest.raises(Exception):
        svc.approve_za_employer_registration(db, row.id, approver_id=2,
                                             organization_id=999999)


def test_profile_validation_uses_the_engine_vocabularies():
    class Data:
        za_employment_type = "CONTRACTOR"
        za_tax_residency = "FOREIGN"
        za_medical_scheme_member = True
        za_medical_dependants = None
        za_uif_excluded = True
        za_uif_exclusion_reason = None
        za_voluntary_additional_paye = Decimal("-1")
        za_sez_employee = True

    errors = svc._za_statutory_profile_errors(Data())
    text = " ".join(errors)
    assert "za_employment_type" in text
    assert "za_tax_residency" in text
    assert "za_medical_dependants" in text
    assert "za_uif_exclusion_reason" in text
    assert "za_voluntary_additional_paye" in text
    assert "SEZ" in text


def test_calc_inputs_resolve_profile_registration_directive_and_variables(db, organization):
    employee = _employee(db, organization)
    _profile(db, organization, employee)
    registration = _registration(db, organization)
    svc.approve_za_employer_registration(db, registration.id, approver_id=2,
                                          organization_id=organization.id)
    directive = svc.capture_za_directive(
        db, organization_id=organization.id, employee_id=employee.id,
        directive_number="ZA-D1", directive_type="FIXED_AMOUNT", amount="500",
        tax_year="2027", issue_date=date(2026, 8, 1),
        effective_from=date(2026, 3, 1), effective_to=date(2027, 2, 28),
        evidence_sha256="b" * 64, actor_id=1)
    svc.approve_za_directive(db, directive.id, approver_id=2,
                             organization_id=organization.id)
    employee.compliance_fields = {
        "tax_number": "1234567890",
        "za_components": {"bonus": "250"},
        "za_variable_items": [{"key": "commission", "amount": "100"}],
        "za_eti_paid_hours": "160",
    }
    db.flush()

    inputs = svc.resolve_za_calc_inputs(db, organization.id, employee,
                                        as_of=date(2026, 9, 30))
    assert inputs["za_statutory_profile"].id is not None
    assert inputs["za_employer_registration"].id == registration.id
    assert inputs["za_has_tax_number"] is True
    assert inputs["za_components"] == {"bonus": "250"}
    assert inputs["za_variable_items"][0]["key"] == "commission"
    assert inputs["za_eti_paid_hours"] == "160"
    assert [d["directive_number"] for d in inputs["za_directives"]] == ["ZA-D1"]
    assert inputs["za_eti_qualifying_month_no"] == 7


def test_calc_inputs_ignore_a_profile_for_another_country(db, organization):
    employee = _employee(db, organization)
    _profile(db, organization, employee, country_code="KE")
    inputs = svc.resolve_za_calc_inputs(db, organization.id, employee,
                                        as_of=date(2026, 9, 30))
    assert inputs["za_statutory_profile"] is None


def test_freeze_and_thaw_round_trip_the_za_context():
    from app.modules.payroll.engine.base import PayrollContext

    profile = SimpleNamespace(**{name: None for name in svc.ZA_PROFILE_COLUMNS})
    profile.za_employment_type = "STANDARD"
    profile.za_tax_residency = "RESIDENT"
    registration = SimpleNamespace(id=7, sdl_liable=True,
                                   sdl_exemption_reason=None, eti_registered=True,
                                   effective_from=date(2026, 3, 1), effective_to=None)
    ctx = PayrollContext(
        gross=Decimal("20000"), basic=Decimal("18000"), country="ZA",
        pay_date=date(2026, 9, 30),         period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30), za_statutory_profile=profile,
        za_organization_id=4, za_employee_id=9, za_has_tax_number=True,
        za_components={"bonus": "100"},
        za_retirement_fund_contribution=Decimal("1000"),
        za_directives=[], za_variable_items=[], za_eti_paid_hours=160,
        za_eti_qualifying_month_no=2,
    )
    ctx.za_employer_registration = registration

    frozen = svc.za_freeze_context(ctx)
    thawed = svc.za_thaw_context(frozen)
    assert thawed.country == "ZA"
    assert thawed.gross == Decimal("20000")
    assert thawed.za_employee_id == 9
    assert thawed.za_statutory_profile.za_employment_type == "STANDARD"
    assert thawed.za_employer_registration.id == 7
    assert thawed.za_eti_paid_hours == 160


def test_payslip_snapshot_carries_totals_and_frozen_context():
    profile = SimpleNamespace(**{name: None for name in svc.ZA_PROFILE_COLUMNS})
    ctx = SimpleNamespace(
        gross=Decimal("1000"), basic=Decimal("1000"), hra=Decimal("0"),
        special_allowance=Decimal("0"), overtime=Decimal("0"),
        additional_compensation=Decimal("0"), pay_frequency="Monthly",
        za_organization_id=1, za_employee_id=1, za_has_tax_number=True,
        za_components=None, za_retirement_fund_contribution=None,
        za_directives=[], za_variable_items=None, za_eti_paid_hours=None,
        za_eti_qualifying_month_no=None, unpaid_leave_days=0,
        date_of_joining=None, pay_date=date(2026, 9, 30),
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
        za_statutory_profile=profile, za_employer_registration=None,
        rate_map={}, slabs=[],
    )
    frozen = svc.za_freeze_context(ctx)
    result = SimpleNamespace(za_result={"za_paye": Decimal("100"), "za_employee_total": Decimal("200")})
    snapshot = svc.za_payslip_snapshot(result, frozen=frozen)
    assert snapshot["za_paye"] == "100"
    assert snapshot["totalsAll"]["za_paye"] == "100"
    assert snapshot["totalsAll"]["za_uif_employee"] == "0"
    assert snapshot["frozenContext"] == frozen


def test_statutory_summary_stays_planned_and_counts_workflows(db, organization):
    employee = _employee(db, organization)
    _profile(db, organization, employee)
    _registration(db, organization)
    summary = svc.statutory_summary(db)
    assert summary["jurisdiction"] == "ZA"
    assert summary["available"] is False
    assert "PLANNED" in summary["note"]
    assert summary["activeEmployerRegistrations"] == 0
    assert summary["decisions"]


def test_za_validation_accepts_a_real_id_and_exactly_one_identity():
    cleaned = ZAEmployeeValidation.validate({
        "national_id": "8001015009087",
        "tax_number": "1234567890",
        "branch_code": "123456",
        "account_number": "123456789",
    })
    assert cleaned["national_id"] == "8001015009087"
    with pytest.raises(Exception):
        ZAEmployeeValidation.validate({"passport_number": "AB123456",
                                       "national_id": "8001015009087"})
    with pytest.raises(Exception):
        ZAEmployeeValidation.validate({})
    with pytest.raises(Exception):
        ZAEmployeeValidation.validate({"national_id": "8001015009088"})
    with pytest.raises(Exception):
        ZAEmployeeValidation.validate({"national_id": "9913325009087"})
    with pytest.raises(Exception):
        ZAEmployeeValidation.validate({"passport_number": "AB123456",
                                       "tax_number": "12345"})

def test_za_tenant_routes_are_registered_with_the_tenant_guard():
    from app.modules.payroll.tenant_statutory_router import router

    expected = {
        ("GET", "/south-africa/employer-registrations"),
        ("POST", "/south-africa/employer-registrations"),
        ("POST", "/south-africa/employer-registrations/{registration_id}/approve"),
        ("GET", "/south-africa/employees/{employee_id}/directives"),
        ("POST", "/south-africa/employees/{employee_id}/directives"),
        ("POST", "/south-africa/directives/{directive_id}/approve"),
        ("POST", "/south-africa/directives/{directive_id}/revoke"),
        ("GET", "/south-africa/eti-ledger"),
    }
    routes = {}
    for route in router.routes:
        for method in getattr(route, "methods", set()):
            routes[(method, route.path)] = route
    assert expected <= set(routes)
    for key in expected:
        route = routes[key]
        deps = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "_za_org" in deps, key
        if key[0] == "POST":
            assert "get_current_payroll_operator" in deps, key


def test_za_tenant_guard_refuses_while_onboarding_is_closed(monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import south_africa_dormancy
    from app.modules.payroll.tenant_statutory_router import _za_org

    monkeypatch.setattr(south_africa_dormancy, "onboarding_enabled", lambda: False)
    with pytest.raises(BadRequestException, match="not open for onboarding"):
        _za_org(organization_id=1)

    monkeypatch.setattr(south_africa_dormancy, "onboarding_enabled", lambda: True)
    assert _za_org(organization_id=7) == 7
