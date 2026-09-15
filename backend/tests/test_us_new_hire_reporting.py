"""
tests/test_us_new_hire_reporting.py
-------------------------------------
Coverage for US New Hire Reporting (Production-Readiness Plan Phase 5,
2026-09-15) — the one genuinely new concept in that phase: compliance
TRACKING (a due-date + mark-filed workflow), not report generation
against already-run payroll. Covers create_employee's own auto-trigger,
the manual create/list/mark-filed service functions, and the "due_date is
a suggestion, editable, never authoritative" contract.
"""

from datetime import date, timedelta

import pytest

from app.core.exceptions import NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, NewHireReport
from app.modules.payroll.schemas import EmployeeCreate


def _make_us_employee(db, organization_id, code="ENHR1", work_state="CA", date_of_joining=None):
    employee = PayrollEmployee(
        organization_id=organization_id, employee_code=code, name="New Hire Employee",
        country_code="US", ctc=60000, work_state=work_state,
        date_of_joining=date_of_joining or date(2026, 3, 1),
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def test_create_employee_auto_creates_pending_new_hire_report_for_us(db, organization):
    payload = EmployeeCreate(
        employee_code="AUTOHIRE1", name="Auto Hire", email="auto.hire@test.com", designation="Engineer",
        dateOfJoining="2026-05-01", ctc=70000, countryCode="US",
        complianceFields={
            "ssn": "123-45-6789", "flsa_status": "Exempt", "state_tax_jurisdiction": "TX",
        },
    )
    employee = service.create_employee(db, payload, organization.id)

    reports = db.query(NewHireReport).filter(NewHireReport.employee_id == employee.id).all()
    assert len(reports) == 1
    report = reports[0]
    assert report.status == "Pending"
    assert report.hire_date == date(2026, 5, 1)
    assert report.due_date == date(2026, 5, 1) + timedelta(days=20)
    assert report.work_state == "TX"


def test_create_employee_does_not_create_new_hire_report_for_non_us(db, organization):
    payload = EmployeeCreate(
        employee_code="AUTOHIRE2", name="India Hire", email="india.hire@test.com", designation="Engineer",
        dateOfJoining="2026-05-01", ctc=700000, countryCode="IN",
    )
    employee = service.create_employee(db, payload, organization.id)
    reports = db.query(NewHireReport).filter(NewHireReport.employee_id == employee.id).all()
    assert reports == []


def test_create_new_hire_report_manual_defaults_to_employee_hire_date_and_work_state(db, organization):
    employee = _make_us_employee(db, organization.id, date_of_joining=date(2026, 2, 10))
    report = service.create_new_hire_report(db, organization.id, employee.id)
    assert report.hire_date == date(2026, 2, 10)
    assert report.due_date == date(2026, 2, 10) + timedelta(days=20)
    assert report.work_state == "CA"
    assert report.status == "Pending"
    assert report.employee_name == "New Hire Employee"


def test_create_new_hire_report_accepts_explicit_overrides(db, organization):
    employee = _make_us_employee(db, organization.id, code="ENHR2")
    report = service.create_new_hire_report(
        db, organization.id, employee.id,
        hire_date=date(2026, 6, 1), work_state="NY", due_date_days=15,
    )
    assert report.hire_date == date(2026, 6, 1)
    assert report.work_state == "NY"
    assert report.due_date == date(2026, 6, 16)


def test_create_new_hire_report_raises_for_unknown_employee(db, organization):
    with pytest.raises(NotFoundException):
        service.create_new_hire_report(db, organization.id, 999999)


def _make_second_organization(db):
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="Second Test Org", organization_code="TESTORG2")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_list_new_hire_reports_filters_by_status_and_org(db, organization):
    second_organization = _make_second_organization(db)
    emp1 = _make_us_employee(db, organization.id, code="ENHR3")
    emp2 = _make_us_employee(db, organization.id, code="ENHR4")
    other_org_emp = _make_us_employee(db, second_organization.id, code="ENHR5")

    r1 = service.create_new_hire_report(db, organization.id, emp1.id)
    r2 = service.create_new_hire_report(db, organization.id, emp2.id)
    service.create_new_hire_report(db, second_organization.id, other_org_emp.id)
    service.mark_new_hire_report_filed(db, organization.id, r2.id, actor_id=1)

    all_reports = service.list_new_hire_reports(db, organization.id)
    assert {r.id for r in all_reports} == {r1.id, r2.id}
    assert all(r.employee_name for r in all_reports)

    pending_only = service.list_new_hire_reports(db, organization.id, status="Pending")
    assert {r.id for r in pending_only} == {r1.id}

    filed_only = service.list_new_hire_reports(db, organization.id, status="Filed")
    assert {r.id for r in filed_only} == {r2.id}


def test_mark_new_hire_report_filed_sets_status_date_and_actor(db, organization):
    employee = _make_us_employee(db, organization.id, code="ENHR6")
    report = service.create_new_hire_report(db, organization.id, employee.id)
    assert report.status == "Pending"

    filed = service.mark_new_hire_report_filed(
        db, organization.id, report.id, filed_date=date(2026, 3, 5), notes="Filed via state portal.", actor_id=42,
    )
    assert filed.status == "Filed"
    assert filed.filed_date == date(2026, 3, 5)
    assert filed.filed_by_id == 42
    assert filed.notes == "Filed via state portal."


def test_mark_new_hire_report_filed_defaults_filed_date_to_today(db, organization):
    employee = _make_us_employee(db, organization.id, code="ENHR7")
    report = service.create_new_hire_report(db, organization.id, employee.id)
    filed = service.mark_new_hire_report_filed(db, organization.id, report.id, actor_id=1)
    assert filed.filed_date == date.today()


def test_mark_new_hire_report_filed_raises_for_wrong_org(db, organization):
    second_organization = _make_second_organization(db)
    employee = _make_us_employee(db, organization.id, code="ENHR8")
    report = service.create_new_hire_report(db, organization.id, employee.id)
    with pytest.raises(NotFoundException):
        service.mark_new_hire_report_filed(db, second_organization.id, report.id, actor_id=1)
