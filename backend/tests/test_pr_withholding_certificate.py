"""
tests/test_pr_withholding_certificate.py
-------------------------------------------
Coverage for Puerto Rico's Form 499 R-4/R-4.1 withholding certificate
CRUD (PR-005) — same create-Draft -> submit -> approve-supersedes-prior
immutable-versioning contract as India's SalaryTdsDeclaration — and
service.get_pr_certificate_inputs, which is what actually feeds the
engine (see tests/test_puerto_rico.py for the engine-side math).
"""
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee


def _make_employee(db, organization_id, code="PRC1", name="Maria Rivera"):
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def test_create_certificate_starts_as_draft(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.create_pr_withholding_certificate(
        db, organization.id, employee.id, personal_exemption_amount=Decimal("3500"),
    )
    assert row.status == "Draft"
    assert row.personal_exemption_amount == Decimal("3500")


def test_get_certificate_inputs_empty_when_none_approved(db, organization):
    employee = _make_employee(db, organization.id)
    service.create_pr_withholding_certificate(db, organization.id, employee.id, personal_exemption_amount=Decimal("3500"))
    # Still Draft — must NOT be picked up.
    assert service.get_pr_certificate_inputs(db, organization.id, employee.id) == {}


def test_submit_then_approve_makes_it_visible_to_the_engine_reader(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.create_pr_withholding_certificate(
        db, organization.id, employee.id, personal_exemption_amount=Decimal("6000"),
        dependents_count=2, dependent_exemption_per_dependent=Decimal("1000"),
        msrra_election=False,
    )
    service.submit_pr_withholding_certificate(db, organization.id, row.id)
    approver = _make_employee(db, organization.id, code="APPROVER", name="Approver")  # placeholder actor id source
    service.approve_pr_withholding_certificate(db, organization.id, row.id, approver_id=1)

    inputs = service.get_pr_certificate_inputs(db, organization.id, employee.id)
    assert inputs["pr_certificate_personal_exemption"] == Decimal("6000")
    assert inputs["pr_certificate_dependents_count"] == 2
    assert inputs["pr_certificate_dependent_exemption_per_dependent"] == Decimal("1000")
    assert inputs["pr_certificate_msrra_election"] is False


def test_approving_a_new_certificate_supersedes_the_prior_approved_one(db, organization):
    employee = _make_employee(db, organization.id)
    first = service.create_pr_withholding_certificate(db, organization.id, employee.id, personal_exemption_amount=Decimal("3500"))
    service.submit_pr_withholding_certificate(db, organization.id, first.id)
    service.approve_pr_withholding_certificate(db, organization.id, first.id, approver_id=1)

    second = service.create_pr_withholding_certificate(db, organization.id, employee.id, personal_exemption_amount=Decimal("7000"))
    service.submit_pr_withholding_certificate(db, organization.id, second.id)
    service.approve_pr_withholding_certificate(db, organization.id, second.id, approver_id=1)

    db.refresh(first)
    assert first.status == "Superseded"
    inputs = service.get_pr_certificate_inputs(db, organization.id, employee.id)
    assert inputs["pr_certificate_personal_exemption"] == Decimal("7000")


def test_cannot_submit_a_non_draft_certificate(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.create_pr_withholding_certificate(db, organization.id, employee.id)
    service.submit_pr_withholding_certificate(db, organization.id, row.id)
    with pytest.raises(BadRequestException):
        service.submit_pr_withholding_certificate(db, organization.id, row.id)


def test_cannot_approve_a_draft_certificate(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.create_pr_withholding_certificate(db, organization.id, employee.id)
    with pytest.raises(BadRequestException):
        service.approve_pr_withholding_certificate(db, organization.id, row.id, approver_id=1)


def test_list_certificates_filters_by_employee(db, organization):
    emp1 = _make_employee(db, organization.id, code="PRC2A", name="Maria Rivera")
    emp2 = _make_employee(db, organization.id, code="PRC2B", name="Jose Ortiz")
    service.create_pr_withholding_certificate(db, organization.id, emp1.id)
    service.create_pr_withholding_certificate(db, organization.id, emp2.id)

    rows = service.list_pr_withholding_certificates(db, organization.id, employee_id=emp1.id)
    assert len(rows) == 1
    assert rows[0].employee_id == emp1.id


def test_certificate_not_found_raises(db, organization):
    with pytest.raises(NotFoundException):
        service.submit_pr_withholding_certificate(db, organization.id, 999999)
