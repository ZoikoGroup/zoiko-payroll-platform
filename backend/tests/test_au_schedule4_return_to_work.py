"""
tests/test_au_schedule4_return_to_work.py
--------------------------------------------
Coverage for service.py's calculate_au_employee_schedule4_withholding
(ZP-TAX-AU-2026-27-001 §9, production-readiness fix plan Tier 3.1,
2026-09-18) — the standalone/on-demand caller that makes engine/
countries/australia.py's calculate_au_schedule4_return_to_work_withholding
reachable from a real employee record. No calc-inputs resolution is
needed at all here (unlike Schedule 5) since this is a flat rate on the
payment amount alone, driven purely by the employee's own au_tfn_status/
au_residency_status declarations.
"""

from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee


def _make_au_employee(db, org_id, code="A1", tfn_status="PROVIDED", residency_status="RESIDENT"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", ctc=Decimal("80000"),
        au_tfn_status=tfn_status, au_residency_status=residency_status,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_uk_employee(db, org_id, code="U1"):
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="UK", ctc=Decimal("60000"))
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def test_au_schedule4_rejects_non_australia_employee(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_au_employee_schedule4_withholding(db, organization.id, emp.id, Decimal("5000"))


def test_au_schedule4_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_au_employee_schedule4_withholding(db, organization.id, 999999, Decimal("5000"))


def test_au_schedule4_rejects_negative_amount(db, organization):
    emp = _make_au_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_au_employee_schedule4_withholding(db, organization.id, emp.id, Decimal("-1"))


def test_au_schedule4_flat_32_percent_with_tfn(db, organization):
    emp = _make_au_employee(db, organization.id, tfn_status="PROVIDED", residency_status="RESIDENT")
    result = service.calculate_au_employee_schedule4_withholding(db, organization.id, emp.id, Decimal("5000"))
    assert result["withholding"] == Decimal("1600")
    assert result["tfn_status"] == "PROVIDED"


def test_au_schedule4_no_tfn_falls_back_to_scale4_rate(db, organization):
    emp = _make_au_employee(db, organization.id, tfn_status="NOT_PROVIDED", residency_status="RESIDENT")
    result = service.calculate_au_employee_schedule4_withholding(db, organization.id, emp.id, Decimal("5000"))
    assert result["withholding"] == Decimal("2350")
