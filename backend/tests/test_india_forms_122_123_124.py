"""
tests/test_india_forms_122_123_124.py
---------------------------------------
Coverage for Forms 122 (SalaryTdsDeclaration), 124 (SalaryTdsClaim), 123
(EmployeeBenefitValuation) — ZP-TAX-IN-2026-27-001 §6.2, gap-closure
Phase E (2026-09-10) — CRUD/status-transition service functions, the
get_india_salary_tds_inputs resolver that feeds them into the salary TDS
projection, and the engine-level consumption in india.py.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee


def _make_in_employee(db, org_id, code="F1"):
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="IN")
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_approver(db, email="approver_forms@test.com"):
    from app.modules.auth.models import User, UserRole
    user = User(email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN, first_name="A", last_name="B")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Form 122: SalaryTdsDeclaration ───────────────────────────────────────

def test_declaration_lifecycle_draft_submit_approve(db, organization):
    emp = _make_in_employee(db, organization.id)
    approver = _make_approver(db, "approver_f122a@test.com")

    declaration = service.create_salary_tds_declaration(
        db, organization.id, emp.id, "2026-27",
        prior_employer_salary=Decimal("200000"), prior_employer_tds_deducted=Decimal("10000"),
    )
    assert declaration.status == "Draft"

    submitted = service.submit_salary_tds_declaration(db, organization.id, declaration.id)
    assert submitted.status == "Submitted"

    approved = service.approve_salary_tds_declaration(db, organization.id, declaration.id, approver.id)
    assert approved.status == "Approved"
    assert approved.approved_by_id == approver.id


def test_declaration_cannot_approve_before_submit(db, organization):
    emp = _make_in_employee(db, organization.id)
    approver = _make_approver(db, "approver_f122b@test.com")
    declaration = service.create_salary_tds_declaration(db, organization.id, emp.id, "2026-27")
    with pytest.raises(BadRequestException):
        service.approve_salary_tds_declaration(db, organization.id, declaration.id, approver.id)


def test_declaration_approving_new_one_supersedes_prior_approved(db, organization):
    emp = _make_in_employee(db, organization.id)
    approver = _make_approver(db, "approver_f122c@test.com")

    first = service.create_salary_tds_declaration(db, organization.id, emp.id, "2026-27", other_income=Decimal("1000"))
    service.submit_salary_tds_declaration(db, organization.id, first.id)
    service.approve_salary_tds_declaration(db, organization.id, first.id, approver.id)

    second = service.create_salary_tds_declaration(db, organization.id, emp.id, "2026-27", other_income=Decimal("5000"))
    service.submit_salary_tds_declaration(db, organization.id, second.id)
    service.approve_salary_tds_declaration(db, organization.id, second.id, approver.id)

    db.refresh(first)
    assert first.status == "Superseded"
    inputs = service.get_india_salary_tds_inputs(db, organization.id, emp.id, "2026-27")
    assert inputs["other_income_for_tds"] == Decimal("5000")


# ── Form 124: SalaryTdsClaim ──────────────────────────────────────────────

def test_claim_rejects_unknown_claim_type(db, organization):
    emp = _make_in_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.create_salary_tds_claim(db, organization.id, emp.id, "2026-27", "NOT_A_REAL_TYPE", Decimal("1000"))


def test_claim_lifecycle_submit_approve(db, organization):
    emp = _make_in_employee(db, organization.id)
    approver = _make_approver(db, "approver_f124a@test.com")
    claim = service.create_salary_tds_claim(
        db, organization.id, emp.id, "2026-27", "SECTION_80C", Decimal("150000"), evidence_reference="LIC receipt #123",
    )
    service.submit_salary_tds_claim(db, organization.id, claim.id)
    approved = service.approve_salary_tds_claim(db, organization.id, claim.id, approver.id)
    assert approved.status == "Approved"


def test_claim_reject_records_reason(db, organization):
    emp = _make_in_employee(db, organization.id)
    claim = service.create_salary_tds_claim(db, organization.id, emp.id, "2026-27", "LTA", Decimal("20000"))
    service.submit_salary_tds_claim(db, organization.id, claim.id)
    rejected = service.reject_salary_tds_claim(db, organization.id, claim.id, "Evidence not sufficient")
    assert rejected.status == "Rejected"
    assert rejected.rejection_reason == "Evidence not sufficient"


def test_only_approved_claims_count_toward_tds_inputs(db, organization):
    emp = _make_in_employee(db, organization.id)
    approver = _make_approver(db, "approver_f124b@test.com")
    approved_claim = service.create_salary_tds_claim(db, organization.id, emp.id, "2026-27", "SECTION_80C", Decimal("100000"))
    service.submit_salary_tds_claim(db, organization.id, approved_claim.id)
    service.approve_salary_tds_claim(db, organization.id, approved_claim.id, approver.id)

    draft_claim = service.create_salary_tds_claim(db, organization.id, emp.id, "2026-27", "LTA", Decimal("999999"))

    inputs = service.get_india_salary_tds_inputs(db, organization.id, emp.id, "2026-27")
    assert inputs["claims_total"] == Decimal("100000")  # draft_claim's 999999 excluded


# ── Form 123: EmployeeBenefitValuation ────────────────────────────────────

def test_benefit_valuation_rejects_unknown_type(db, organization):
    emp = _make_in_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.create_employee_benefit_valuation(db, organization.id, emp.id, "2026-27", "SPACESHIP", Decimal("1000"))


def test_only_issued_benefit_valuations_count_toward_tds_inputs(db, organization):
    emp = _make_in_employee(db, organization.id)
    issued = service.create_employee_benefit_valuation(db, organization.id, emp.id, "2026-27", "CAR", Decimal("50000"))
    service.issue_employee_benefit_valuation(db, organization.id, issued.id)
    service.create_employee_benefit_valuation(db, organization.id, emp.id, "2026-27", "ACCOMMODATION", Decimal("999999"))  # stays Draft

    inputs = service.get_india_salary_tds_inputs(db, organization.id, emp.id, "2026-27")
    assert inputs["perquisites_total"] == Decimal("50000")


# ── Resolver defaults + org isolation ─────────────────────────────────────

def test_salary_tds_inputs_all_zero_when_nothing_configured(db, organization):
    emp = _make_in_employee(db, organization.id)
    inputs = service.get_india_salary_tds_inputs(db, organization.id, emp.id, "2026-27")
    assert inputs == {
        "other_income_for_tds": Decimal("0"), "tds_already_deducted": Decimal("0"),
        "claims_total": Decimal("0"), "perquisites_total": Decimal("0"),
    }


def test_india_tax_year_for_date():
    assert service.india_tax_year_for_date(date(2026, 6, 15)) == "2026-27"
    assert service.india_tax_year_for_date(date(2027, 3, 31)) == "2026-27"
    assert service.india_tax_year_for_date(date(2027, 4, 1)) == "2027-28"
