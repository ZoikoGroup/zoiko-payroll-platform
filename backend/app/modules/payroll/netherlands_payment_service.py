"""
payroll/netherlands_payment_service.py
----------------------------------------
SEPA payment batch (pain.001) creation for NL payroll.

Builds credit-transfer batches from committed payslips. Supports:
  - Net pay payments to employees
  - Authority payments (tax, social security) via separate batches
  - Reconciliation with bank statements
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.payroll import netherlands_service as nl
from app.modules.payroll.bank_export.sepa_pain001 import (
    Pain001Builder,
    SepaBatch,
    SepaParty,
    SepaPaymentItem,
    validate_batch,
    SepaValidationError,
)
from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollNlAuthorityPayment,
    PayrollNlPaymentBatch,
    PayrollNlPaymentItem,
    PayrollNlEmployerProfile,
    PayrollRun,
    PayslipItem,
)
from app.core.exceptions import BadRequestException, NotFoundException


NL = "NL"


class PaymentServiceError(BadRequestException):
    pass


def _get_employee_iban_token(db: Session, employee_id: int) -> Optional[str]:
    """Get the employee's IBAN token (tokenized, not raw IBAN)."""
    emp = db.query(PayrollEmployee).filter(PayrollEmployee.id == employee_id).one_or_none()
    if emp and emp.compliance_fields:
        return emp.compliance_fields.get("iban_token") or emp.compliance_fields.get("iban")
    return None


def _get_employer_party(db: Session, organization_id: int) -> SepaParty:
    """Get employer as SEPA party."""
    profile = db.query(PayrollNlEmployerProfile).filter(
        PayrollNlEmployerProfile.organization_id == organization_id,
    ).order_by(PayrollNlEmployerProfile.effective_from.desc()).first()

    if not profile:
        raise PaymentServiceError("No employer profile found")

    return SepaParty(
        name=profile.legal_name,
        iban=profile.bank_iban_token or "",
        bic=profile.bank_bic,
        address_line1=profile.address.get("street") if profile.address else None,
        address_line2=profile.address.get("house_number") if profile.address else None,
        city=profile.address.get("city") if profile.address else None,
        postal_code=profile.address.get("postal_code") if profile.address else None,
        country=profile.address.get("country") if profile.address else "NL",
        organisation_id=profile.loonheffingennummer,
    )


def _build_net_pay_items(db: Session, run: PayrollRun) -> List[SepaPaymentItem]:
    """Build SEPA payment items for net pay from committed payslips."""
    items = (
        db.query(PayslipItem)
        .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == NL)
        .all()
    )

    sepa_items = []
    for item in items:
        iban_token = _get_employee_iban_token(db, item.employee_id)
        if not iban_token:
            continue  # Skip employees without IBAN

        snap = item.nl_calculation_snapshot or {}
        pos = snap.get("totals", {})
        net_pay = Decimal(pos.get("netPay", "0"))
        if net_pay <= 0:
            continue

        emp = db.query(PayrollEmployee).filter(PayrollEmployee.id == item.employee_id).one()
        end_to_end_id = f"PAY-{run.id}-{item.employee_id}-{uuid.uuid4().hex[:8]}"

        sepa_items.append(SepaPaymentItem(
            end_to_end_id=end_to_end_id,
            amount=net_pay,
            currency="EUR",
            creditor=SepaParty(
                name=emp.name,
                iban=iban_token,
            ),
            creditor_account_iban=iban_token,
            remittance_info=f"Loon {run.period_label} {emp.employee_code}",
            purpose_code="SALA",
            category_purpose="SALA",
        ))

    return sepa_items


def create_salary_payment_batch(
    db: Session,
    run_id: int,
    actor_id: int,
    requested_execution_date: Optional[date] = None,
    idempotency_key: Optional[str] = None,
) -> PayrollNlPaymentBatch:
    """Create a SEPA salary payment batch from an APPROVED/COMMITTED payroll run."""
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).one_or_none()
    if not run:
        raise NotFoundException("PayrollRun", run_id)

    if str(run.status) not in ("Approved", "Authorized", "Paid", "Closed"):
        raise PaymentServiceError(f"Run must be approved/committed (status={run.status})")

    if not nl.run_committed(db, run):
        raise PaymentServiceError("Run must be committed before payment batch creation")

    if idempotency_key is None:
        # One salary batch per run unless the caller deliberately supplies a new
        # key: a retried request must return the same batch, never pay twice
        # (spec T8 duplicate payment). The key never depends on time or actor.
        idempotency_key = hashlib.sha256(f"nl-salary-batch-run-{run_id}".encode()).hexdigest()[:100]

    existing = db.query(PayrollNlPaymentBatch).filter(
        PayrollNlPaymentBatch.idempotency_key == idempotency_key
    ).first()
    if existing:
        return existing

    employer = _get_employer_party(db, run.organization_id)
    if not employer.iban:
        raise PaymentServiceError("Employer IBAN not configured")

    items = _build_net_pay_items(db, run)
    if not items:
        raise PaymentServiceError("No valid payment items (employees with IBAN and positive net pay)")

    batch = SepaBatch(
        message_id=f"SALARY-{run.id}-{uuid.uuid4().hex[:12].upper()}",
        initiating_party=employer,
        debtor=employer,
        debtor_account_iban=employer.iban,
        debtor_agent_bic=employer.bic,
        requested_execution_date=requested_execution_date or run.pay_date,
        items=items,
    )

    errors = validate_batch(batch)
    if errors:
        raise SepaValidationError(f"SEPA validation failed: {errors}")

    xml = Pain001Builder().add_batch(batch).build()
    xml_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()

    payment_batch = PayrollNlPaymentBatch(
        organization_id=run.organization_id,
        payroll_run_id=run.id,
        pain001_sha256=xml_sha256,
        message_id=batch.message_id,
        status="SUBMITTED",
        idempotency_key=idempotency_key,
    )
    db.add(payment_batch)
    db.flush()

    for item in items:
        emp = db.query(PayrollEmployee).filter(
            PayrollEmployee.employee_code == item.creditor.name
        ).first()
        if not emp:
            # Fallback: find by matching amount/remittance
            pass
        # Find the employee by name match
        emp = db.query(PayrollEmployee).filter(
            PayrollEmployee.organization_id == run.organization_id,
            PayrollEmployee.name == item.creditor.name,
        ).first()
        if emp:
            payment_item = PayrollNlPaymentItem(
                batch_id=payment_batch.id,
                employee_id=emp.id,
                iban_token=item.creditor_account_iban or "",
                amount=item.amount,
                end_to_end_id=item.end_to_end_id,
                status="PENDING",
            )
            db.add(payment_item)

    db.flush()
    return payment_batch


def create_authority_payment_batch(
    db: Session,
    organization_id: int,
    authority_payments: List[Dict[str, Any]],
    actor_id: int,
    requested_execution_date: Optional[date] = None,
    idempotency_key: Optional[str] = None,
) -> PayrollNlPaymentBatch:
    """Create a SEPA batch for authority payments (tax, social security).

    authority_payments: list of dicts with keys:
      - payment_reference (e.g. "LOONHEFFING-202603")
      - amount (Decimal)
      - creditor_name (e.g. "Belastingdienst")
      - creditor_iban
      - creditor_bic (optional)
      - end_to_end_id (optional)
      - remittance_info (optional)
    """
    if not authority_payments:
        raise PaymentServiceError("No authority payments provided")

    employer = _get_employer_party(db, organization_id)

    items = []
    for p in authority_payments:
        end_to_end_id = p.get("end_to_end_id") or f"AUTH-{uuid.uuid4().hex[:12].upper()}"
        items.append(SepaPaymentItem(
            end_to_end_id=end_to_end_id,
            amount=Decimal(str(p["amount"])),
            currency="EUR",
            creditor=SepaParty(
                name=p["creditor_name"],
                iban=p["creditor_iban"],
                bic=p.get("creditor_bic"),
            ),
            creditor_account_iban=p["creditor_iban"],
            creditor_agent_bic=p.get("creditor_bic"),
            remittance_info=p.get("remittance_info", p["payment_reference"]),
            purpose_code="TAXS",
            category_purpose="TAXS",
        ))

    batch = SepaBatch(
        message_id=f"AUTH-{organization_id}-{uuid.uuid4().hex[:12].upper()}",
        initiating_party=employer,
        debtor=employer,
        debtor_account_iban=employer.iban,
        debtor_agent_bic=employer.bic,
        requested_execution_date=requested_execution_date or date.today(),
        items=items,
    )

    errors = validate_batch(batch)
    if errors:
        raise SepaValidationError(f"SEPA validation failed: {errors}")

    xml = Pain001Builder().add_batch(batch).build()
    xml_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()

    if idempotency_key is None:
        # Same payments to the same authorities = the same batch (never paid twice).
        canonical = json.dumps(sorted(authority_payments, key=lambda p: json.dumps(p, sort_keys=True, default=str)),
                               sort_keys=True, default=str)
        idempotency_key = hashlib.sha256(f"nl-authority-batch-{organization_id}-{canonical}".encode()).hexdigest()[:100]

    existing = db.query(PayrollNlPaymentBatch).filter(
        PayrollNlPaymentBatch.idempotency_key == idempotency_key
    ).first()
    if existing:
        return existing

    payment_batch = PayrollNlPaymentBatch(
        organization_id=organization_id,
        pain001_sha256=xml_sha256,
        message_id=batch.message_id,
        status="SUBMITTED",
        idempotency_key=idempotency_key,
    )
    db.add(payment_batch)
    db.flush()

    for item in items:
        # Authority payments don't link to employees directly
        payment_item = PayrollNlPaymentItem(
            batch_id=payment_batch.id,
            employee_id=0,  # 0 = authority
            iban_token=item.creditor_account_iban,
            amount=item.amount,
            end_to_end_id=item.end_to_end_id,
            status="PENDING",
        )
        db.add(payment_item)

    db.flush()
    return payment_batch


def submit_payment_batch(db: Session, batch_id: int, actor_id: int) -> PayrollNlPaymentBatch:
    """Mark batch as submitted to bank (after XML delivery)."""
    batch = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.id == batch_id).one_or_none()
    if not batch:
        raise NotFoundException("PayrollNlPaymentBatch", batch_id)
    if batch.status != "SUBMITTED":
        raise PaymentServiceError(f"Batch must be SUBMITTED (status={batch.status})")

    batch.submitted_at = datetime.utcnow()
    db.flush()
    return batch


def reconcile_payment_batch(
    db: Session,
    batch_id: int,
    bank_reference: Optional[str] = None,
) -> PayrollNlPaymentBatch:
    """Reconcile batch after bank settlement (CAMT.054/MT940)."""
    batch = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.id == batch_id).one_or_none()
    if not batch:
        raise NotFoundException("PayrollNlPaymentBatch", batch_id)
    if batch.status not in ("SUBMITTED", "ACCEPTED"):
        raise PaymentServiceError(f"Cannot reconcile batch with status {batch.status}")

    batch.status = "SETTLED"
    batch.reconciled_at = datetime.utcnow()
    db.flush()
    return batch


def handle_payment_return(
    db: Session,
    batch_id: int,
    end_to_end_id: str,
    return_reason: str,
) -> PayrollNlPaymentItem:
    """Handle a returned payment (R-transaction from bank)."""
    item = db.query(PayrollNlPaymentItem).filter(
        PayrollNlPaymentItem.batch_id == batch_id,
        PayrollNlPaymentItem.end_to_end_id == end_to_end_id,
    ).one_or_none()
    if not item:
        raise NotFoundException("PayrollNlPaymentItem", f"{batch_id}/{end_to_end_id}")

    item.status = "RETURNED"
    item.return_reason = return_reason
    db.flush()
    return item


def get_batch_with_items(db: Session, batch_id: int) -> tuple[PayrollNlPaymentBatch, List[PayrollNlPaymentItem]]:
    batch = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.id == batch_id).one_or_none()
    if not batch:
        raise NotFoundException("PayrollNlPaymentBatch", batch_id)
    items = db.query(PayrollNlPaymentItem).filter(PayrollNlPaymentItem.batch_id == batch_id).all()
    return batch, items


def list_payment_batches(
    db: Session,
    organization_id: int,
    status: Optional[str] = None,
) -> List[PayrollNlPaymentBatch]:
    q = db.query(PayrollNlPaymentBatch).filter(
        PayrollNlPaymentBatch.organization_id == organization_id
    )
    if status:
        q = q.filter(PayrollNlPaymentBatch.status == status)
    return q.order_by(PayrollNlPaymentBatch.created_at.desc()).all()