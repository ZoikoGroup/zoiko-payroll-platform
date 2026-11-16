"""
tests/test_au_draft_run_delete_sg_liability.py
----------------------------------------------
Regression: deleting a Draft AU payroll run (or one of its payslips)
returned HTTP 500 in production. Every real AU payslip creates a
SuperGuaranteeLiability row whose payslip_item_id FK has no ON DELETE
rule, so Postgres refused the payslip delete with a foreign-key
violation. The default SQLite test DB does not enforce FKs, which is why
the suite never caught it — these tests switch enforcement on.

Expected behaviour:
  * PENDING liabilities (nothing filed yet) are removed together with the
    run / payslip, and the delete succeeds.
  * A liability already moved past PENDING (SUBMITTED / RECEIVED / ...)
    is a recorded statutory fact — the delete is refused with 409, never
    a 500, and nothing is removed.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, PayrollEmployee, PayrollRun, PayslipItem, SuperGuaranteeLiability,
)
from app.modules.payroll.schemas import PayslipItemCreate


@pytest.fixture
def fk_db(db):
    """Enforce foreign keys like Postgres does. PRAGMA foreign_keys is a
    no-op inside an open transaction, so end any implicit one first."""
    db.commit()
    db.execute(text("PRAGMA foreign_keys=ON"))
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    try:
        yield db
    finally:
        db.rollback()
        db.execute(text("PRAGMA foreign_keys=OFF"))


def _au_run_with_payslip(db, org_id, code="AU-DEL-1"):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="AU",
        component_key="super", label="Superannuation Guarantee",
        employee_share="0%", employer_share="12%", total="12%",
        employer_rate_pct=Decimal("12.00"),
    ))
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", ctc=Decimal("120000"),
    )
    db.add(emp)
    db.commit()
    run = PayrollRun(
        organization_id=org_id, period_label="AU Draft Delete Test",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 9, 1),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=emp.id, basic_salary=Decimal("10000"),
    ), org_id)
    db.commit()
    liability = db.query(SuperGuaranteeLiability).filter(
        SuperGuaranteeLiability.payslip_item_id == item.id).one()
    assert liability.status == "PENDING"
    return run, item, liability


def test_delete_draft_au_run_removes_pending_sg_liabilities(fk_db, organization):
    run, item, liability = _au_run_with_payslip(fk_db, organization.id)
    run_id, item_id = run.id, item.id

    service.delete_payroll_run(fk_db, run_id, organization.id)

    assert fk_db.query(PayrollRun).filter(PayrollRun.id == run_id).count() == 0
    assert fk_db.query(PayslipItem).filter(PayslipItem.id == item_id).count() == 0
    assert fk_db.query(SuperGuaranteeLiability).filter(
        SuperGuaranteeLiability.payslip_item_id == item_id).count() == 0


def test_delete_draft_au_run_refused_when_sg_liability_already_submitted(fk_db, organization):
    run, item, liability = _au_run_with_payslip(fk_db, organization.id, code="AU-DEL-2")
    liability.status = "SUBMITTED"
    fk_db.commit()

    with pytest.raises(HTTPException) as exc:
        service.delete_payroll_run(fk_db, run.id, organization.id)
    assert exc.value.status_code == 409
    assert "Super Guarantee" in exc.value.detail

    # Nothing removed.
    assert fk_db.query(PayrollRun).filter(PayrollRun.id == run.id).count() == 1
    assert fk_db.query(PayslipItem).filter(PayslipItem.id == item.id).count() == 1
    assert fk_db.query(SuperGuaranteeLiability).filter(
        SuperGuaranteeLiability.payslip_item_id == item.id).count() == 1


def test_delete_au_payslip_in_draft_run_removes_pending_sg_liability(fk_db, organization):
    run, item, liability = _au_run_with_payslip(fk_db, organization.id, code="AU-DEL-3")
    item_id = item.id

    service.delete_payslip(fk_db, item_id, organization.id)

    assert fk_db.query(PayslipItem).filter(PayslipItem.id == item_id).count() == 0
    assert fk_db.query(SuperGuaranteeLiability).filter(
        SuperGuaranteeLiability.payslip_item_id == item_id).count() == 0
    assert fk_db.query(PayrollRun).filter(PayrollRun.id == run.id).count() == 1


def test_delete_au_payslip_refused_when_sg_liability_already_submitted(fk_db, organization):
    run, item, liability = _au_run_with_payslip(fk_db, organization.id, code="AU-DEL-4")
    liability.status = "SUBMITTED"
    fk_db.commit()

    with pytest.raises(HTTPException) as exc:
        service.delete_payslip(fk_db, item.id, organization.id)
    assert exc.value.status_code == 409
    assert fk_db.query(PayslipItem).filter(PayslipItem.id == item.id).count() == 1
