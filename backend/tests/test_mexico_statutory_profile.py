"""Mexico Phase 4b — the employee statutory profile through the SHARED
statutory-profile save path and the Mexico hooks: versioning and
carry-forward, tokens not identifiers, establishment / registration
ownership and ACTIVE checks, work state vs establishment (MX-038),
professional minimum only from Active content, identifier findings
recorded and never rewritten (MX-036), rehire as a new version.
SYNTHETIC data."""

from datetime import date
from decimal import Decimal

import pytest

from tests._mx_employer_helpers import (
    MX_IDS, employer_payload, enable_mx_onboarding, make_org, mx_workplace, new_mx_employee, new_registration,
    save_mx_profile, to_service,
)


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    enable_mx_onboarding(monkeypatch)


def _setup(db):
    t = make_org(db)
    return t, new_mx_employee(db, t.org.id), mx_workplace(db, t.org.id)


def test_profile_holds_tokens_and_last4_never_identifiers(db):
    t, emp, w = _setup(db)
    row = save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"],
                          mx_imss_registration_id=w.registration["id"], mx_salary_type="fixed",
                          mx_daily_salary=Decimal("500"))
    assert row.mx_curp_token.startswith("v1:") and row.mx_rfc_token.startswith("v1:")
    assert row.mx_rfc_last4 == MX_IDS["rfc"][-4:] and row.mx_identifier_validation_status == "FORMAT_ONLY"
    columns = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    assert not any(isinstance(v, str) and v in MX_IDS.values() for v in columns.values())
    assert (row.mx_work_state, row.mx_work_municipality, row.mx_salary_type) == ("CDMX", "Cuauhtémoc", "FIXED")


def test_findings_say_not_checked_until_sources_exist(db):
    t, emp, _w = _setup(db)
    row = save_mx_profile(db, emp, t.org.id)
    checks = {f["check"]: f["result"] for f in row.mx_identifier_findings}
    assert set(checks.values()) == {"NOT_CHECKED"} and any("RFC ↔ CURP" in k for k in checks)


def test_versions_carry_forward_unsent_fields(db):
    t, emp, w = _setup(db)
    save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"], mx_daily_salary=Decimal("500"),
                    mx_contract_type_code="01")
    v2 = save_mx_profile(db, emp, t.org.id, effective_from=date(2026, 7, 1), mx_daily_salary=Decimal("600"))
    assert (v2.mx_daily_salary, v2.mx_contract_type_code, v2.mx_establishment_id) == (
        Decimal("600"), "01", w.establishment["id"])


@pytest.mark.parametrize("field,value,msg", [
    ("mx_work_state", "XX", "32 federal-entity codes"),
    ("mx_salary_type", "HOURLY", "FIXED, VARIABLE, MIXED"),
    ("mx_daily_salary", Decimal("-1"), "cannot be negative"),
    ("mx_fiscal_postal_code", "123", "5-digit"),
    ("mx_annual_adjustment_exclusion", "OTHER_EMPLOYER", "attach its evidence reference"),
])
def test_shape_errors(db, field, value, msg):
    from app.core.exceptions import BadRequestException

    t, emp, _w = _setup(db)
    with pytest.raises(BadRequestException, match=msg):
        save_mx_profile(db, emp, t.org.id, **{field: value})


def test_registration_must_be_active_on_the_effective_date_and_same_employer(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_employer_service as svc

    t, emp, w = _setup(db)
    late = new_registration(db, t.org.id, w.employer["id"], rp="Z7654321109", eff="2026-06-01")
    with pytest.raises(BadRequestException, match="ACTIVE on the profile's effective date"):
        save_mx_profile(db, emp, t.org.id, mx_imss_registration_id=late["id"])
    other = svc.create_employer(db, t.org.id, to_service(employer_payload(rfc="XYZ010101AB1")), 701)
    reg_other = new_registration(db, t.org.id, other["id"], rp="Q1111111111")
    with pytest.raises(BadRequestException, match="different legal employers"):
        save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"],
                        mx_imss_registration_id=reg_other["id"])


def test_other_tenants_establishment_is_refused(db):
    from app.core.exceptions import BadRequestException

    t, emp, _w = _setup(db)
    other = make_org(db, name="Other", code="OTHER")
    w2 = mx_workplace(db, other.org.id)
    with pytest.raises(BadRequestException, match="active establishment of this organisation"):
        save_mx_profile(db, emp, t.org.id, mx_establishment_id=w2.establishment["id"])


def test_work_state_differing_from_establishment_needs_an_exception_ref(db):
    from app.core.exceptions import BadRequestException

    t, emp, w = _setup(db)
    with pytest.raises(BadRequestException, match="remote / multi-state exception reference"):
        save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"], mx_work_state="JAL")
    row = save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"], mx_work_state="JAL",
                          mx_work_municipality="Guadalajara", mx_remote_state_exception_ref="REMOTE-SYN-1")
    assert row.mx_work_state == "JAL"


def test_professional_minimum_only_from_active_content(db):
    from app.core.exceptions import BadRequestException

    t, emp, _w = _setup(db)
    with pytest.raises(BadRequestException, match="no professional minimum with that code is in Active content"):
        save_mx_profile(db, emp, t.org.id, mx_professional_min_code="P01")


def test_rehire_is_a_new_version_on_the_same_employee(db):
    """The duplicate-CURP rule refuses a second employee record; the rehire is
    the same employee reactivated with a new effective-dated profile version."""
    from fastapi import HTTPException

    from app.modules.payroll.models import EmployeeStatutoryProfile

    t, emp, w = _setup(db)
    save_mx_profile(db, emp, t.org.id, mx_seniority_date=date(2026, 1, 1))
    with pytest.raises(HTTPException) as exc:
        new_mx_employee(db, t.org.id, code="MX-REHIRE", email="again@example.com", rfc="WXYZ010101AB1",
                        nss="10987654321")
    assert exc.value.status_code == 409
    save_mx_profile(db, emp, t.org.id, effective_from=date(2027, 3, 1), mx_seniority_date=date(2027, 3, 1))
    versions = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.employee_id == emp.id) \
        .order_by(EmployeeStatutoryProfile.effective_from).all()
    assert [v.mx_seniority_date for v in versions] == [date(2026, 1, 1), date(2027, 3, 1)]
    assert versions[0].effective_to == date(2027, 2, 28)


def test_flag_off_the_shared_profile_route_refuses_mexico(db, monkeypatch):
    from app.config import settings
    from app.core.exceptions import BadRequestException

    t, emp, _w = _setup(db)
    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", False)
    with pytest.raises(BadRequestException, match="Unsupported jurisdiction country_code: 'MX'"):
        save_mx_profile(db, emp, t.org.id)
