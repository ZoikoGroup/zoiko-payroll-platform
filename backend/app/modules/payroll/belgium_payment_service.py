"""Belgium salary payment batches (ZP-BE-ENG-001 D13; Block B3).

Mirrors netherlands_payment_service: a SEPA pain.001.001.09 salary batch built
by bank_export/sepa_pain001.py — used UNCHANGED — for the Belgian payslips of a
COMMITTED (approved) run, then status tracking and bank reconciliation. On top
of the Dutch flow, a Belgian batch needs a SECOND person's approval before it
can be submitted (four-eyes; the database refuses a non-DRAFT batch whose
approver is its creator).

* Debtor: the organisation's settlement account (company compliance details)
  and the legal name of the employer registration in force.
* Creditor: each employee's IBAN from their compliance fields (validated
  check digits); an employee who cannot be paid blocks the build unless
  excluded with a reason.
* A retried request returns the same batch (idempotency key); a second live
  batch for the run is refused; the run's payment channel is claimed so the
  generic bank file can never pay it too (payment_treatment hook).
* Net pay is the frozen be_net of the payslip — never recalculated or edited.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.bank_export.sepa_pain001 import (Pain001Builder, SepaBatch, SepaParty, SepaPaymentItem,
                                                          SepaValidationError, mask_iban, normalise_iban,
                                                          validate_bic, validate_iban)

BE = "BE"
CHANNEL_SEPA = "BE_SEPA_BATCH"
_LIVE_STATUSES = ("DRAFT", "APPROVED", "SUBMITTED", "ACCEPTED", "UNKNOWN", "SETTLED")
_TRANSITIONS = {
    "submit": ({"APPROVED"}, "SUBMITTED"),
    "ACCEPTED": ({"SUBMITTED", "UNKNOWN"}, "ACCEPTED"),
    "REJECTED": ({"SUBMITTED", "UNKNOWN"}, "REJECTED"),
    "UNKNOWN": ({"SUBMITTED"}, "UNKNOWN"),
    "settle": ({"ACCEPTED"}, "SETTLED"),
}


class PaymentServiceError(BadRequestException):
    pass


def _models():
    from app.modules.payroll import models as m

    return m


def _run(db: Session, organization_id: int, run_id: int):
    m = _models()
    run = db.query(m.PayrollRun).filter(m.PayrollRun.id == run_id, m.PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("PayrollRun", run_id)
    return run


def _committed(run) -> bool:
    return str(getattr(run.status, "value", run.status)) in ("Approved", "Authorized", "Paid", "Closed")


def claim_payment_channel(run, channel: str) -> None:
    current = getattr(run, "payment_channel", None)
    if current and current != channel:
        raise PaymentServiceError(f"Run {run.id} is already being paid through {current}; paying it through {channel} "
                                  "as well would pay the employees twice.")
    run.payment_channel = channel


def _employer_party(db: Session, organization_id: int, on: date) -> SepaParty:
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import CompanyComplianceDetails

    details = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    iban = normalise_iban(getattr(details, "settlement_acc", None))
    registration = be._be_registration_for(db, organization_id, None, on)
    name = getattr(registration, "legal_name", None) or getattr(details, "name", None) or ""
    if not iban or not validate_iban(iban):
        raise PaymentServiceError("The employer settlement account (IBAN) is missing or fails the check digits.")
    return SepaParty(name=name, iban=iban, country=BE, organisation_id=getattr(registration, "enterprise_number", None))


def _employee_account(emp) -> Tuple[str, Optional[str]]:
    fields = dict(getattr(emp, "compliance_fields", None) or {})
    return normalise_iban(fields.get("iban")), (fields.get("bic") or None)


def _end_to_end_id(run_id: int, employee_id: int) -> str:
    return f"BEPAY-{run_id}-{employee_id}"


def salary_payment_preview(db: Session, organization_id: int, run_id: int) -> Dict[str, Any]:
    """Payable items and exceptions of the run's Belgian salary batch (nothing built)."""
    m = _models()
    run = _run(db, organization_id, run_id)
    payslips = (db.query(m.PayslipItem).filter(m.PayslipItem.payroll_run_id == run.id, m.PayslipItem.country_code == BE)
                .order_by(m.PayslipItem.employee_id).all())
    payable, exceptions = [], []
    for slip in payslips:
        emp = db.get(m.PayrollEmployee, slip.employee_id)
        name = (emp.name if emp else None) or slip.employee_name or f"Employee {slip.employee_id}"
        net = Decimal(str((slip.be_calculation_snapshot or {}).get("be_net") or "0"))
        iban, bic = _employee_account(emp)
        if net <= 0:
            exceptions.append({"employeeId": slip.employee_id, "name": name, "reason": f"no positive net pay ({net})"})
        elif not iban:
            exceptions.append({"employeeId": slip.employee_id, "name": name, "reason": "no IBAN on file"})
        elif not validate_iban(iban):
            exceptions.append({"employeeId": slip.employee_id, "name": name,
                               "reason": f"IBAN {mask_iban(iban)} fails the check digits"})
        elif bic and not validate_bic(bic):
            exceptions.append({"employeeId": slip.employee_id, "name": name, "reason": "BIC is not 8 or 11 characters"})
        else:
            payable.append({"employeeId": slip.employee_id, "payslipItemId": slip.id, "name": name, "iban": iban,
                            "bic": bic, "employeeCode": getattr(emp, "employee_code", None), "amount": net})
    return {"payable": payable, "exceptions": exceptions}


def create_salary_payment_batch(db: Session, organization_id: int, run_id: int, actor_id: int,
                                requested_execution_date: Optional[date] = None,
                                idempotency_key: Optional[str] = None, exclusions: Optional[Dict[int, str]] = None,
                                today: Optional[date] = None):
    m = _models()
    run = _run(db, organization_id, run_id)
    if not _committed(run):
        raise PaymentServiceError(f"The run must be approved (committed) first (status={run.status}).")
    Batch, Item = m.PayrollBePaymentBatch, m.PayrollBePaymentItem
    previous = db.query(Batch).filter(Batch.payroll_run_id == run.id).order_by(Batch.id).all()
    live = [b for b in previous if b.status in _LIVE_STATUSES]
    if idempotency_key is None:
        sequence = len(previous) + (0 if live else 1)
        idempotency_key = hashlib.sha256(f"be-salary-batch-run-{run.id}-{max(sequence, 1)}".encode()).hexdigest()[:100]
    existing = db.query(Batch).filter(Batch.idempotency_key == idempotency_key).first()
    if existing:
        return existing
    if live:
        raise PaymentServiceError(f"Run {run.id} already has payment batch {live[-1].id} ({live[-1].status}).")
    employer = _employer_party(db, organization_id, run.pay_date)
    preview = salary_payment_preview(db, organization_id, run.id)
    excluded = {int(k): str(v).strip() for k, v in (exclusions or {}).items() if str(v or "").strip()}
    blocking = [e for e in preview["exceptions"] if e["employeeId"] not in excluded]
    if blocking:
        raise PaymentServiceError("Employees who cannot be paid — fix or exclude each with a reason: "
                                  + "; ".join(f"{e['name']} ({e['employeeId']}): {e['reason']}" for e in blocking))
    payable = [p for p in preview["payable"] if p["employeeId"] not in excluded]
    if not payable:
        raise PaymentServiceError("No employee to pay in this run.")
    execution = requested_execution_date or run.pay_date
    if execution < (today or date.today()):
        raise PaymentServiceError(f"The execution date {execution} is in the past — pass a current date.")
    claim_payment_channel(run, CHANNEL_SEPA)
    row = Batch(organization_id=organization_id, payroll_run_id=run.id, batch_kind="SALARY",
                message_id=f"BESAL-R{run.id}-{len(previous) + 1}", status="DRAFT", idempotency_key=idempotency_key,
                created_at_utc=datetime.now(timezone.utc).replace(microsecond=0), pain001_sha256="pending",
                created_by_id=actor_id)
    sepa = SepaBatch(message_id=row.message_id, initiating_party=employer, debtor=employer,
                     debtor_account_iban=employer.iban, requested_execution_date=execution, category_purpose="SALA",
                     items=[SepaPaymentItem(end_to_end_id=_end_to_end_id(run.id, p["employeeId"]), amount=p["amount"],
                                            creditor=SepaParty(name=p["name"], iban=p["iban"], bic=p["bic"]),
                                            creditor_account_iban=p["iban"], creditor_agent_bic=p["bic"],
                                            purpose_code="SALA",
                                            remittance_info=f"Salaris {run.period_label} {p['employeeCode'] or ''}".strip())
                            for p in payable])
    try:
        xml = Pain001Builder(created_at=row.created_at_utc).add_batch(sepa).build()
    except SepaValidationError as exc:
        raise PaymentServiceError(str(exc))
    row.pain001_xml = xml
    row.pain001_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    db.add(row)
    db.flush()
    for p in payable:
        db.add(Item(organization_id=organization_id, batch_id=row.id, employee_id=p["employeeId"],
                    payslip_item_id=p["payslipItemId"], iban_token=p["iban"], amount=p["amount"],
                    end_to_end_id=_end_to_end_id(run.id, p["employeeId"]), status="PENDING"))
    db.flush()
    return row


def _batch(db: Session, organization_id: int, batch_id: int):
    Batch = _models().PayrollBePaymentBatch
    row = db.query(Batch).filter(Batch.id == batch_id, Batch.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgium payment batch")
    return row


def approve_payment_batch(db: Session, organization_id: int, batch_id: int, actor_id: int):
    """Four-eyes: the approver is not the creator (the database also refuses it)."""
    row = _batch(db, organization_id, batch_id)
    if row.status != "DRAFT":
        raise PaymentServiceError("Only a DRAFT payment batch can be approved.")
    if actor_id is None or actor_id == row.created_by_id:
        raise PaymentServiceError("The payment batch must be approved by a user other than its creator (four-eyes).")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    return row


def _move(row, action: str) -> None:
    allowed, target = _TRANSITIONS[action]
    if row.status not in allowed:
        raise PaymentServiceError(f"Cannot {action.lower()} a {row.status} batch.")
    row.status = target


def submit_payment_batch(db: Session, organization_id: int, batch_id: int, actor_id: int):
    row = _batch(db, organization_id, batch_id)
    _move(row, "submit")
    row.submitted_at = datetime.utcnow()
    Item = _models().PayrollBePaymentItem
    for item in db.query(Item).filter(Item.batch_id == row.id):
        item.status = "SENT"
    db.flush()
    return row


def record_bank_result(db: Session, organization_id: int, batch_id: int, outcome: str):
    outcome = str(outcome or "").strip().upper()
    if outcome not in ("ACCEPTED", "REJECTED", "UNKNOWN"):
        raise PaymentServiceError("outcome must be ACCEPTED, REJECTED or UNKNOWN.")
    row = _batch(db, organization_id, batch_id)
    _move(row, outcome)
    db.flush()
    return row


def reconcile_payment_batch(db: Session, organization_id: int, batch_id: int):
    row = _batch(db, organization_id, batch_id)
    _move(row, "settle")
    row.reconciled_at = datetime.utcnow()
    Item = _models().PayrollBePaymentItem
    for item in db.query(Item).filter(Item.batch_id == row.id, Item.status == "SENT"):
        item.status = "SETTLED"
    db.flush()
    return row


def handle_payment_return(db: Session, organization_id: int, batch_id: int, end_to_end_id: str, return_reason: str):
    row = _batch(db, organization_id, batch_id)
    Item = _models().PayrollBePaymentItem
    item = db.query(Item).filter(Item.batch_id == row.id, Item.end_to_end_id == end_to_end_id).first()
    if item is None:
        raise NotFoundException("Payment item")
    if not str(return_reason or "").strip():
        raise PaymentServiceError("A return needs its reason.")
    item.status, item.return_reason = "RETURNED", str(return_reason).strip()[:200]
    db.flush()
    return item


def batch_view(db: Session, organization_id: int, batch_id: int) -> dict:
    """The batch and its items — IBANs masked (the file itself is the only
    place the account numbers appear)."""
    row = _batch(db, organization_id, batch_id)
    Item = _models().PayrollBePaymentItem
    items = db.query(Item).filter(Item.batch_id == row.id).order_by(Item.id).all()
    return {"id": row.id, "runId": row.payroll_run_id, "status": row.status, "messageId": row.message_id,
            "sha256": row.pain001_sha256, "createdById": row.created_by_id, "approvedById": row.approved_by_id,
            "items": [{"employeeId": i.employee_id, "payslipItemId": i.payslip_item_id, "amount": str(i.amount),
                       "iban": mask_iban(i.iban_token), "endToEndId": i.end_to_end_id, "status": i.status,
                       "returnReason": i.return_reason} for i in items]}


def list_payment_batches(db: Session, organization_id: int, run_id: Optional[int] = None) -> List[dict]:
    Batch = _models().PayrollBePaymentBatch
    q = db.query(Batch).filter(Batch.organization_id == organization_id)
    if run_id is not None:
        q = q.filter(Batch.payroll_run_id == run_id)
    return [{"id": b.id, "runId": b.payroll_run_id, "status": b.status, "messageId": b.message_id,
             "createdById": b.created_by_id, "approvedById": b.approved_by_id} for b in q.order_by(Batch.id)]


def batch_file(db: Session, organization_id: int, batch_id: int) -> Tuple[str, str]:
    row = _batch(db, organization_id, batch_id)
    if row.status in ("DRAFT",):
        raise PaymentServiceError("The pain.001 file is released only after a second person approves the batch.")
    return f"{row.message_id}.xml", row.pain001_xml
