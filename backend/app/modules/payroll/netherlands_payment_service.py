"""
payroll/netherlands_payment_service.py
----------------------------------------
SEPA (pain.001.001.09) payment batches for NL payroll.

  - Salary batch: net pay of a COMMITTED run, one credit transfer per employee.
  - Authority batch: tax / social-security payments (still LOCKED at the API
    until gate G3 — the service is ready, the route is not open).

Phase 4.2 (2026-10-23):
  - the exact file bytes are stored (pain001_xml) and downloadable; a rebuild
    of the same batch repeats them (stored CreDtTm, deterministic ids);
  - every employee who cannot be paid (no / invalid IBAN, no positive net) is
    an explicit exception that blocks the build — never silently skipped —
    unless the caller excludes them with a reason;
  - items are linked to employees by id (EndToEndId PAY-<run>-<employee>),
    never by name;
  - lifecycle DRAFT -> SUBMITTED -> ACCEPTED | REJECTED | UNKNOWN -> SETTLED;
    an UNKNOWN batch must be resolved before any new batch for the run (NL-052);
  - one run is paid through ONE channel (payroll_runs.payment_channel): a run
    whose bank transfer file was generated cannot get a SEPA batch, and the
    reverse is refused in service.generate_bank_transfer_file.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import netherlands_service as nl
from app.modules.payroll.bank_export.sepa_pain001 import (
    Pain001Builder,
    SepaBatch,
    SepaParty,
    SepaPaymentItem,
    SepaValidationError,
    mask_iban,
    normalise_iban,
    validate_bic,
    validate_iban,
)
from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollNlAuthorityPayment,
    PayrollNlEmployerProfile,
    PayrollNlPaymentBatch,
    PayrollNlPaymentItem,
    PayrollRun,
    PayslipItem,
)

NL = "NL"
CHANNEL_SEPA = "SEPA"
CHANNEL_GENERIC = "GENERIC_FILE"
_LIVE_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "UNKNOWN", "SETTLED")
_TRANSITIONS = {
    "submit": ({"DRAFT"}, "SUBMITTED"),
    "ACCEPTED": ({"SUBMITTED", "UNKNOWN"}, "ACCEPTED"),
    "REJECTED": ({"SUBMITTED", "UNKNOWN"}, "REJECTED"),
    "UNKNOWN": ({"SUBMITTED"}, "UNKNOWN"),
    "settle": ({"ACCEPTED"}, "SETTLED"),
}


class PaymentServiceError(BadRequestException):
    pass


# ── payment channel (no double payment) ─────────────────────────────────

def claim_payment_channel(run: PayrollRun, channel: str) -> None:
    """Record the run's payment channel; refuse a second, different channel."""
    current = getattr(run, "payment_channel", None)
    if current and current != channel:
        raise PaymentServiceError(
            f"Run {run.id} is already being paid through {current}; paying it through {channel} as well "
            "would pay the employees twice.")
    run.payment_channel = channel


# ── parties and items ────────────────────────────────────────────────────

def _get_employer_party(db: Session, organization_id: int) -> Tuple[SepaParty, Optional[PayrollNlEmployerProfile]]:
    profile = (db.query(PayrollNlEmployerProfile)
               .filter(PayrollNlEmployerProfile.organization_id == organization_id)
               .order_by(PayrollNlEmployerProfile.effective_from.desc()).first())
    if not profile:
        raise PaymentServiceError("No NL employer profile found")
    address = profile.address or {}
    party = SepaParty(
        name=profile.legal_name,
        iban=normalise_iban(profile.bank_iban_token),
        bic=profile.bank_bic,
        address_line1=" ".join(x for x in (address.get("street"), address.get("house_number")) if x) or None,
        city=address.get("city"),
        postal_code=address.get("postal_code"),
        country=address.get("country") or "NL",
        organisation_id=profile.loonheffingennummer,
    )
    return party, profile


def _employee_account(emp: Optional[PayrollEmployee]) -> Tuple[str, Optional[str]]:
    fields = dict(getattr(emp, "compliance_fields", None) or {})
    return normalise_iban(fields.get("iban")), (fields.get("bic") or None)


def _end_to_end_id(run_id: int, employee_id: int) -> str:
    return f"PAY-{run_id}-{employee_id}"


def salary_payment_preview(db: Session, run: PayrollRun) -> Dict[str, Any]:
    """The payable items and the exceptions of a run's salary batch, without
    building anything. exceptions: [{employeeId, name, reason}]."""
    payslips = (db.query(PayslipItem)
                .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == NL)
                .order_by(PayslipItem.employee_id).all())
    payable, exceptions = [], []
    for slip in payslips:
        emp = db.get(PayrollEmployee, slip.employee_id)
        name = (emp.name if emp else None) or slip.employee_name or f"Employee {slip.employee_id}"
        net = Decimal(str(((slip.nl_calculation_snapshot or {}).get("totals") or {}).get("netPay", "0")))
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
            payable.append({"employeeId": slip.employee_id, "name": name, "iban": iban, "bic": bic,
                            "employeeCode": getattr(emp, "employee_code", None), "amount": net})
    return {"payable": payable, "exceptions": exceptions}


def _execution_date(run: PayrollRun, profile, requested: Optional[date], today: date) -> date:
    if requested is not None:
        execution = requested
    else:
        lead = int(getattr(profile, "bank_lead_days", None) or 0)
        execution = run.pay_date - timedelta(days=lead)
    if execution < today:
        raise PaymentServiceError(f"Requested execution date {execution} is in the past — pass a current date.")
    return execution


def _build_file(batch_row: PayrollNlPaymentBatch, sepa: SepaBatch) -> str:
    return Pain001Builder(created_at=batch_row.created_at_utc).add_batch(sepa).build()


# ── salary batch ─────────────────────────────────────────────────────────

def create_salary_payment_batch(
    db: Session,
    run_id: int,
    actor_id: int,
    requested_execution_date: Optional[date] = None,
    idempotency_key: Optional[str] = None,
    exclusions: Optional[Dict[int, str]] = None,
    today: Optional[date] = None,
) -> PayrollNlPaymentBatch:
    """DRAFT SEPA salary batch of a committed run. Every employee who cannot
    be paid blocks the build unless excluded with a reason (exclusions =
    {employee_id: reason}). A retried request returns the same batch."""
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).one_or_none()
    if not run:
        raise NotFoundException("PayrollRun", run_id)
    if str(getattr(run.status, "value", run.status)) not in ("Approved", "Authorized", "Paid", "Closed"):
        raise PaymentServiceError(f"Run must be approved/committed (status={run.status})")
    if not nl.run_committed(db, run):
        raise PaymentServiceError("Run must be committed before payment batch creation")

    previous = (db.query(PayrollNlPaymentBatch)
                .filter(PayrollNlPaymentBatch.payroll_run_id == run.id,
                        or_(PayrollNlPaymentBatch.batch_kind == "SALARY", PayrollNlPaymentBatch.batch_kind.is_(None)))
                .order_by(PayrollNlPaymentBatch.id).all())
    live = [b for b in previous if b.status in _LIVE_STATUSES]
    if idempotency_key is None:
        sequence = len(previous) + (0 if live else 1)
        idempotency_key = hashlib.sha256(f"nl-salary-batch-run-{run_id}-{max(sequence, 1)}".encode()).hexdigest()[:100]
    existing = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.idempotency_key == idempotency_key).first()
    if existing:
        return existing
    if live:
        state = live[-1].status
        raise PaymentServiceError(
            f"Run {run.id} already has salary batch {live[-1].id} ({state})"
            + (" — resolve the UNKNOWN bank outcome first (NL-052)." if state == "UNKNOWN" else "."))

    employer, profile = _get_employer_party(db, run.organization_id)
    if not employer.iban:
        raise PaymentServiceError("Employer IBAN not configured")

    preview = salary_payment_preview(db, run)
    excluded = {int(k): str(v).strip() for k, v in (exclusions or {}).items() if str(v or "").strip()}
    blocking = [e for e in preview["exceptions"] if e["employeeId"] not in excluded]
    if blocking:
        raise PaymentServiceError("Employees who cannot be paid — fix or exclude each with a reason: "
                                  + "; ".join(f"{e['name']} ({e['employeeId']}): {e['reason']}" for e in blocking))
    payable = [p for p in preview["payable"] if p["employeeId"] not in excluded]
    if not payable:
        raise PaymentServiceError("No employee to pay in this run.")

    claim_payment_channel(run, CHANNEL_SEPA)
    execution = _execution_date(run, profile, requested_execution_date, today or date.today())
    row = PayrollNlPaymentBatch(
        organization_id=run.organization_id, payroll_run_id=run.id, batch_kind="SALARY",
        message_id=f"SAL-R{run.id}-{len(previous) + 1}", status="DRAFT", idempotency_key=idempotency_key,
        created_at_utc=datetime.now(timezone.utc).replace(microsecond=0), pain001_sha256="pending")
    sepa = SepaBatch(
        message_id=row.message_id, initiating_party=employer, debtor=employer,
        debtor_account_iban=employer.iban, debtor_agent_bic=employer.bic,
        requested_execution_date=execution, category_purpose="SALA",
        items=[SepaPaymentItem(
            end_to_end_id=_end_to_end_id(run.id, p["employeeId"]), amount=p["amount"],
            creditor=SepaParty(name=p["name"], iban=p["iban"], bic=p["bic"]),
            creditor_account_iban=p["iban"], creditor_agent_bic=p["bic"], purpose_code="SALA",
            remittance_info=f"Loon {run.period_label} {p['employeeCode'] or ''}".strip())
            for p in payable])
    try:
        xml = _build_file(row, sepa)
    except SepaValidationError as exc:
        raise PaymentServiceError(str(exc))
    row.pain001_xml = xml
    row.pain001_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    db.add(row)
    db.flush()
    for p in payable:
        db.add(PayrollNlPaymentItem(batch_id=row.id, employee_id=p["employeeId"], iban_token=p["iban"],
                                    amount=p["amount"], end_to_end_id=_end_to_end_id(run.id, p["employeeId"]),
                                    status="PENDING"))
    db.flush()
    return row


# ── authority batch (route LOCKED until G3) ──────────────────────────────

def create_authority_payment_batch(
    db: Session,
    organization_id: int,
    authority_payments: List[Dict[str, Any]],
    actor_id: int,
    requested_execution_date: Optional[date] = None,
    idempotency_key: Optional[str] = None,
    authority_payment_id: Optional[int] = None,
) -> PayrollNlPaymentBatch:
    """DRAFT batch of payments to authorities (e.g. Belastingdienst). Each
    payment: payment_reference, amount, creditor_name, creditor_iban,
    creditor_bic?, structured_reference? (the betalingskenmerk) and
    end_to_end_id?. The authority IBAN is the caller's (never a constant)."""
    if not authority_payments:
        raise PaymentServiceError("No authority payments provided")
    if authority_payment_id is not None and db.get(PayrollNlAuthorityPayment, authority_payment_id) is None:
        raise NotFoundException("PayrollNlAuthorityPayment", authority_payment_id)
    canonical = json.dumps(sorted(authority_payments, key=lambda p: json.dumps(p, sort_keys=True, default=str)),
                           sort_keys=True, default=str)
    digest = hashlib.sha256(f"nl-authority-batch-{organization_id}-{canonical}".encode()).hexdigest()
    if idempotency_key is None:
        idempotency_key = digest[:100]
    existing = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.idempotency_key == idempotency_key).first()
    if existing:
        return existing

    employer, _profile = _get_employer_party(db, organization_id)
    items = []
    for index, p in enumerate(authority_payments, start=1):
        items.append(SepaPaymentItem(
            end_to_end_id=(p.get("end_to_end_id") or f"AUTH-{digest[:12].upper()}-{index}")[:35],
            amount=Decimal(str(p["amount"])),
            creditor=SepaParty(name=p["creditor_name"], iban=p["creditor_iban"], bic=p.get("creditor_bic")),
            creditor_account_iban=p["creditor_iban"], creditor_agent_bic=p.get("creditor_bic"),
            structured_reference=p.get("structured_reference"),
            remittance_info=p.get("remittance_info") or p["payment_reference"], purpose_code="TAXS"))
    row = PayrollNlPaymentBatch(
        organization_id=organization_id, batch_kind="AUTHORITY", authority_payment_id=authority_payment_id,
        message_id=f"AUTH-{digest[:24].upper()}", status="DRAFT", idempotency_key=idempotency_key,
        created_at_utc=datetime.now(timezone.utc).replace(microsecond=0), pain001_sha256="pending")
    sepa = SepaBatch(message_id=row.message_id, initiating_party=employer, debtor=employer,
                     debtor_account_iban=employer.iban, debtor_agent_bic=employer.bic,
                     requested_execution_date=requested_execution_date or date.today(),
                     category_purpose="TAXS", items=items)
    try:
        xml = _build_file(row, sepa)
    except SepaValidationError as exc:
        raise PaymentServiceError(str(exc))
    row.pain001_xml = xml
    row.pain001_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    db.add(row)
    db.flush()
    for item in items:
        db.add(PayrollNlPaymentItem(batch_id=row.id, employee_id=None, iban_token=normalise_iban(item.creditor_account_iban),
                                    amount=item.amount, end_to_end_id=item.end_to_end_id, status="PENDING"))
    db.flush()
    return row


# ── lifecycle ────────────────────────────────────────────────────────────

def _batch(db: Session, batch_id: int) -> PayrollNlPaymentBatch:
    batch = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.id == batch_id).one_or_none()
    if not batch:
        raise NotFoundException("PayrollNlPaymentBatch", batch_id)
    return batch


def _move(batch: PayrollNlPaymentBatch, action: str) -> None:
    allowed, target = _TRANSITIONS[action]
    if batch.status not in allowed:
        raise PaymentServiceError(f"Batch {batch.id} is {batch.status}; {action} needs one of {sorted(allowed)}.")
    batch.status = target


def submit_payment_batch(db: Session, batch_id: int, actor_id: int) -> PayrollNlPaymentBatch:
    """The file was handed to the bank: DRAFT -> SUBMITTED."""
    batch = _batch(db, batch_id)
    _move(batch, "submit")
    batch.submitted_at = datetime.now(timezone.utc)
    db.query(PayrollNlPaymentItem).filter(PayrollNlPaymentItem.batch_id == batch.id,
                                          PayrollNlPaymentItem.status == "PENDING").update({"status": "SENT"})
    db.flush()
    return batch


def record_bank_result(db: Session, batch_id: int, outcome: str) -> PayrollNlPaymentBatch:
    """The bank's answer (pain.002 or portal): ACCEPTED, REJECTED or UNKNOWN
    (no answer / timeout). UNKNOWN must later become ACCEPTED or REJECTED —
    never a blind resend (NL-052)."""
    outcome = (outcome or "").upper()
    if outcome not in ("ACCEPTED", "REJECTED", "UNKNOWN"):
        raise PaymentServiceError("outcome must be ACCEPTED, REJECTED or UNKNOWN.")
    batch = _batch(db, batch_id)
    _move(batch, outcome)
    if outcome == "REJECTED":
        db.query(PayrollNlPaymentItem).filter(PayrollNlPaymentItem.batch_id == batch.id).update({"status": "REJECTED"})
    db.flush()
    return batch


def reconcile_payment_batch(db: Session, batch_id: int, bank_reference: Optional[str] = None) -> PayrollNlPaymentBatch:
    """Settlement evidenced by the bank statement (camt.054 / MT940):
    ACCEPTED -> SETTLED. A bank reference is required."""
    if not (bank_reference or "").strip():
        raise PaymentServiceError("A settlement needs the bank statement reference.")
    batch = _batch(db, batch_id)
    _move(batch, "settle")
    batch.reconciled_at = datetime.now(timezone.utc)
    db.query(PayrollNlPaymentItem).filter(PayrollNlPaymentItem.batch_id == batch.id,
                                          PayrollNlPaymentItem.status == "SENT").update({"status": "SETTLED"})
    db.flush()
    return batch


def handle_payment_return(db: Session, batch_id: int, end_to_end_id: str, return_reason: str) -> PayrollNlPaymentItem:
    """A returned payment (R-transaction) for one item."""
    item = (db.query(PayrollNlPaymentItem)
            .filter(PayrollNlPaymentItem.batch_id == batch_id, PayrollNlPaymentItem.end_to_end_id == end_to_end_id)
            .one_or_none())
    if not item:
        raise NotFoundException("PayrollNlPaymentItem", f"{batch_id}/{end_to_end_id}")
    item.status = "RETURNED"
    item.return_reason = return_reason
    db.flush()
    return item


def get_batch_file(db: Session, batch_id: int) -> Tuple[str, str]:
    """(filename, xml) — exactly the stored bytes."""
    batch = _batch(db, batch_id)
    if not batch.pain001_xml:
        raise PaymentServiceError(f"Batch {batch.id} predates file storage — rebuild it as a new batch.")
    return f"pain001_{batch.message_id}.xml", batch.pain001_xml


def get_batch_with_items(db: Session, batch_id: int) -> tuple[PayrollNlPaymentBatch, List[PayrollNlPaymentItem]]:
    batch = _batch(db, batch_id)
    items = db.query(PayrollNlPaymentItem).filter(PayrollNlPaymentItem.batch_id == batch_id).all()
    return batch, items


def list_payment_batches(db: Session, organization_id: int, status: Optional[str] = None) -> List[PayrollNlPaymentBatch]:
    q = db.query(PayrollNlPaymentBatch).filter(PayrollNlPaymentBatch.organization_id == organization_id)
    if status:
        q = q.filter(PayrollNlPaymentBatch.status == status)
    return q.order_by(PayrollNlPaymentBatch.created_at.desc()).all()
