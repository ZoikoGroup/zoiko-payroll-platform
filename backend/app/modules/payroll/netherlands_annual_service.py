"""
payroll/netherlands_annual_service.py
--------------------------------------
Jaaropgaaf (annual wage/tax statement) generation for NL.

Generated from committed year-to-date totals only — never from the current
employee record (NL-048). The statement includes:
  - Fiscal wage
  - Wage tax withheld
  - Applied employment credit (arbeidskorting)
  - Tax credit applied (heffingskorting)
  - ZVW wage and contribution
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollNlAnnualStatement,
    PayrollNlIncomeRelationship,
    PayrollNlVcrSnapshot,
    PayrollNlVcrSnapshot,
    PayrollRun,
    PayslipItem,
)
from app.modules.payroll.netherlands_service import committed_vcr_state, VcrFamily
from app.core.exceptions import BadRequestException, NotFoundException


NL = "NL"


class AnnualStatementError(BadRequestException):
    pass


def _sum_decimal(values: List[Decimal]) -> Decimal:
    return sum(values, Decimal("0"))


def _get_vcr_annual_totals(db: Session, organization_id: int, employee_id: int, tax_year: int) -> Dict[str, Decimal]:
    """Get year-to-date VCR totals for EI and ZVW families."""
    vcr = committed_vcr_state(db, organization_id, employee_id, tax_year)

    totals = {
        "ei_cumulative_wage": Decimal("0"),
        "ei_cumulative_base": Decimal("0"),
        "zvw_cumulative_wage": Decimal("0"),
        "zvw_cumulative_base": Decimal("0"),
    }

    for family in (VcrFamily.EI, VcrFamily.ZVW_LEVY, VcrFamily.ZVW_CONTRIB):
        snap = vcr.get(family)
        if snap:
            wage = Decimal(str(snap.get("cumulative_wage", "0")))
            base = Decimal(str(snap.get("cumulative_base", "0")))
            if family == VcrFamily.EI:
                totals["ei_cumulative_wage"] = wage
                totals["ei_cumulative_base"] = base
            else:
                totals["zvw_cumulative_wage"] += wage
                totals["zvw_cumulative_base"] += base

    return totals


def _aggregate_payslip_totals(db: Session, organization_id: int, employee_id: int, tax_year: int) -> Dict[str, Decimal]:
    """Aggregate totals from committed payslips in the tax year."""
    items = (
        db.query(PayslipItem)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollRun.organization_id == organization_id,
            PayslipItem.employee_id == employee_id,
            PayslipItem.country_code == NL,
            PayrollRun.pay_date >= date(tax_year, 1, 1),
            PayrollRun.pay_date <= date(tax_year, 12, 31),
            PayrollRun.status.in_(["Approved", "Authorized", "Paid", "Closed"]),
        )
        .all()
    )

    totals = {
        "fiscal_wage": Decimal("0"),
        "wage_tax_withheld": Decimal("0"),
        "applied_employment_credit": Decimal("0"),
        "tax_credit_applied": Decimal("0"),
        "zvw_wage": Decimal("0"),
        "zvw_contribution": Decimal("0"),
    }

    for item in items:
        snap = item.nl_calculation_snapshot or {}
        pos = snap.get("totals", {})
        totals["fiscal_wage"] += Decimal(pos.get("gross", "0"))
        totals["wage_tax_withheld"] += Decimal(pos.get("wageTax", "0"))
        totals["zvw_wage"] += Decimal(pos.get("zvwEmployee", "0")) + Decimal(pos.get("zvwEmployer", "0"))
        totals["zvw_contribution"] += Decimal(pos.get("zvwEmployee", "0"))

        # Employment credit (arbeidskorting) - from trace
        trace = snap.get("trace", [])
        for t in trace:
            if t.get("code") == "EMPLOYMENT_CREDIT":
                totals["applied_employment_credit"] += Decimal(str(t.get("amount", "0")))
            if t.get("code") == "TAX_CREDIT":
                totals["tax_credit_applied"] += Decimal(str(t.get("amount", "0")))

    return totals


def _compute_source_ledger_sha256(db: Session, organization_id: int, employee_id: int, tax_year: int) -> str:
    """Hash the committed ledger state for integrity verification."""
    vcr = committed_vcr_state(db, organization_id, employee_id, tax_year)

    # Also include payslip snapshots
    items = (
        db.query(PayslipItem)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollRun.organization_id == organization_id,
            PayslipItem.employee_id == employee_id,
            PayslipItem.country_code == NL,
            PayrollRun.pay_date >= date(tax_year, 1, 1),
            PayrollRun.pay_date <= date(tax_year, 12, 31),
            PayrollRun.status.in_(["Approved", "Authorized", "Paid", "Closed"]),
        )
        .all()
    )

    data = {
        "vcr": {k: v for k, v in vcr.items()},
        "payslips": [
            {
                "id": item.id,
                "run_id": item.payroll_run_id,
                "snapshot_hash": (item.nl_calculation_snapshot or {}).get("inputHash"),
            }
            for item in items
        ],
    }
    json_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def generate_annual_statement(
    db: Session,
    organization_id: int,
    employee_id: int,
    tax_year: int,
    actor_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> PayrollNlAnnualStatement:
    """Generate or retrieve the jaaropgaaf for an employee/year.

    The statement is built from committed year-to-date totals only.
    Returns existing DRAFT if idempotency key matches.
    """
    if idempotency_key is None:
        # One original statement per employee and year: a repeated "generate"
        # returns it instead of creating a second jaaropgaaf.
        idempotency_key = hashlib.sha256(f"jaaropgaaf-{organization_id}-{employee_id}-{tax_year}".encode()).hexdigest()[:100]

    existing = db.query(PayrollNlAnnualStatement).filter(
        PayrollNlAnnualStatement.idempotency_key == idempotency_key
    ).first()
    if existing:
        return existing

    emp = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).one_or_none()
    if not emp:
        raise NotFoundException("PayrollEmployee", employee_id)

    ikv = db.query(PayrollNlIncomeRelationship).filter(
        PayrollNlIncomeRelationship.employee_id == employee_id,
        PayrollNlIncomeRelationship.organization_id == organization_id,
    ).first()

    # Get totals from committed data only
    vcr_totals = _get_vcr_annual_totals(db, organization_id, employee_id, tax_year)
    payslip_totals = _aggregate_payslip_totals(db, organization_id, employee_id, tax_year)
    source_hash = _compute_source_ledger_sha256(db, organization_id, employee_id, tax_year)

    # Determine version
    max_version = db.query(func.max(PayrollNlAnnualStatement.version)).filter(
        PayrollNlAnnualStatement.organization_id == organization_id,
        PayrollNlAnnualStatement.employee_id == employee_id,
        PayrollNlAnnualStatement.tax_year == tax_year,
    ).scalar() or 0
    version = max_version + 1
    supersedes_id = None
    if max_version > 0:
        supersedes = db.query(PayrollNlAnnualStatement).filter(
            PayrollNlAnnualStatement.organization_id == organization_id,
            PayrollNlAnnualStatement.employee_id == employee_id,
            PayrollNlAnnualStatement.tax_year == tax_year,
            PayrollNlAnnualStatement.version == max_version,
        ).first()
        if supersedes:
            supersedes_id = supersedes.id

    statement = PayrollNlAnnualStatement(
        organization_id=organization_id,
        employee_id=employee_id,
        income_relationship_id=ikv.id if ikv else None,
        tax_year=tax_year,
        version=version,
        supersedes_id=supersedes_id,
        fiscal_wage=vcr_totals["ei_cumulative_wage"] + payslip_totals.get("fiscal_wage", Decimal("0")),
        wage_tax_withheld=payslip_totals["wage_tax_withheld"],
        applied_employment_credit=payslip_totals["applied_employment_credit"],
        tax_credit_applied=payslip_totals["tax_credit_applied"],
        zvw_wage=vcr_totals["zvw_cumulative_wage"],
        zvw_contribution=payslip_totals["zvw_contribution"],
        source_ledger_sha256=source_hash,
        status="DRAFT",
        idempotency_key=idempotency_key,
    )
    db.add(statement)
    db.flush()
    return statement


def issue_annual_statement(
    db: Session,
    statement_id: int,
    actor_id: int,
    delivery_channel: str = "PORTAL",
    document_ref: Optional[str] = None,
) -> PayrollNlAnnualStatement:
    """Issue a DRAFT annual statement to the employee."""
    stmt = db.query(PayrollNlAnnualStatement).filter(
        PayrollNlAnnualStatement.id == statement_id
    ).one_or_none()
    if not stmt:
        raise NotFoundException("PayrollNlAnnualStatement", statement_id)
    if stmt.status != "DRAFT":
        raise AnnualStatementError(f"Cannot issue statement with status {stmt.status}")

    stmt.status = "ISSUED"
    stmt.delivered_at = datetime.utcnow()
    stmt.delivery_channel = delivery_channel
    stmt.document_ref = document_ref
    db.flush()
    return stmt


def amend_annual_statement(
    db: Session,
    statement_id: int,
    actor_id: int,
    reason: str,
    delivery_channel: str = "PORTAL",
) -> PayrollNlAnnualStatement:
    """Create an amended version of an issued statement."""
    original = db.query(PayrollNlAnnualStatement).filter(
        PayrollNlAnnualStatement.id == statement_id
    ).one_or_none()
    if not original:
        raise NotFoundException("PayrollNlAnnualStatement", statement_id)
    if original.status != "ISSUED":
        raise AnnualStatementError(f"Can only amend ISSUED statements (status={original.status})")

    # Create new version
    import hashlib
    from datetime import datetime
    idempotency_key = f"jaaropgaaf-amend-{original.organization_id}-{original.employee_id}-{original.tax_year}-{original.version + 1}-{actor_id}-{datetime.utcnow().isoformat()}"
    idempotency_key = hashlib.sha256(idempotency_key.encode()).hexdigest()[:100]

    new_stmt = PayrollNlAnnualStatement(
        organization_id=original.organization_id,
        employee_id=original.employee_id,
        income_relationship_id=original.income_relationship_id,
        tax_year=original.tax_year,
        version=original.version + 1,
        supersedes_id=original.id,
        fiscal_wage=original.fiscal_wage,
        wage_tax_withheld=original.wage_tax_withheld,
        applied_employment_credit=original.applied_employment_credit,
        tax_credit_applied=original.tax_credit_applied,
        zvw_wage=original.zvw_wage,
        zvw_contribution=original.zvw_contribution,
        source_ledger_sha256=original.source_ledger_sha256,
        status="DRAFT",
        idempotency_key=idempotency_key,
    )
    db.add(new_stmt)
    db.flush()
    return new_stmt


def list_annual_statements(
    db: Session,
    organization_id: int,
    tax_year: Optional[int] = None,
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
) -> List[PayrollNlAnnualStatement]:
    q = db.query(PayrollNlAnnualStatement).filter(
        PayrollNlAnnualStatement.organization_id == organization_id
    )
    if tax_year:
        q = q.filter(PayrollNlAnnualStatement.tax_year == tax_year)
    if employee_id:
        q = q.filter(PayrollNlAnnualStatement.employee_id == employee_id)
    if status:
        q = q.filter(PayrollNlAnnualStatement.status == status)
    return q.order_by(PayrollNlAnnualStatement.tax_year.desc(), PayrollNlAnnualStatement.employee_id).all()


def get_annual_statement(
    db: Session,
    statement_id: int,
) -> PayrollNlAnnualStatement:
    stmt = db.query(PayrollNlAnnualStatement).filter(
        PayrollNlAnnualStatement.id == statement_id
    ).one_or_none()
    if not stmt:
        raise NotFoundException("PayrollNlAnnualStatement", statement_id)
    return stmt