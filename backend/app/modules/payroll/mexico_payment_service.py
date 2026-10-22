"""
modules/payroll/mexico_payment_service.py
-----------------------------------------
Mexico Phase 10a (docs/mexico/MEXICO_PHASE_10_PLAN.md D2–D5): salary payments.

  * a BATCH per committed Mexican run: one item per payslip with net pay, the
    worker's CLABE checked (18 digits; the check digit is S33, not saved) — a
    worker without a usable CLABE refuses the whole batch (fail closed). Only
    the CLABE's last 4 digits are stored (MX-061).
  * RELEASE by someone other than the maker (four-eyes). A RELEASED batch
    refuses the run's reset (Phase 6 rule); a DRAFT one is cancelled by it.
  * WORKLIST mode (D2): no bank layout is saved, so the file is a Zoiko
    worklist keyed into online banking — labelled "not a bank file", built on
    request with the full CLABE read only then, never stored; each export is
    audited without the CLABE, and its hash kept.
  * OUTCOMES per item, recorded by the operator with a reference: SETTLED,
    FAILED, RETURNED (with a reason) or UNKNOWN (D4 — never retried
    automatically; resolve it to SETTLED / FAILED first). A batch is CLOSED
    when no item is PENDING or UNKNOWN.
  * RE-ISSUE (D5): FAILED / RETURNED items go into a new DRAFT batch, each
    linked to the item it replaces; the payslip is never edited.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
WORKLIST_BANNER = ("ZOIKO PAYMENT WORKLIST - NOT A BANK FILE - key these payments into your online banking (SPEI) "
                   "and then record each outcome in Zoiko")
_CLABE = re.compile(r"^\d{18}$")
FINAL = ("SETTLED", "FAILED", "RETURNED")
OUTCOMES = ("SETTLED", "FAILED", "RETURNED", "UNKNOWN")


def _payment_models():
    from app.modules.payroll import models as m

    return m


def _amount(value) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _payment_audit(db, **kw):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, **kw)


def _payment_guard(db: Session, org_id: int) -> None:
    from app.modules.payroll import mexico_filing_service

    mexico_filing_service.guard(db, org_id)


def _clabe_of(employee) -> Optional[str]:
    raw = ((getattr(employee, "compliance_fields", None) or {}).get("clabe") or "")
    clabe = re.sub(r"[\s-]", "", str(raw))
    return clabe if _CLABE.match(clabe) else None


def _committed(run) -> bool:
    return bool((run.mx_approval_fingerprint or {}).get("committedAt"))


def _payment_batch(db: Session, org_id: int, batch_id: int):
    row = db.get(_payment_models().PayrollMxPaymentBatch, batch_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Payment batch {batch_id} not found")
    return row


def _payment_item(db: Session, org_id: int, item_id: int):
    row = db.get(_payment_models().PayrollMxPaymentItem, item_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Payment item {item_id} not found")
    return row


def _batch_items(db: Session, batch_id: int) -> list:
    I = _payment_models().PayrollMxPaymentItem
    return db.query(I).filter(I.batch_id == batch_id).order_by(I.id).all()


def _next_key(db: Session, org_id: int, run_id: int) -> str:
    B = _payment_models().PayrollMxPaymentBatch
    n = db.query(B).filter(B.organization_id == org_id, B.payroll_run_id == run_id).count()
    return f"mxpay:{org_id}:{run_id}:{n + 1}"


# ── batches ─────────────────────────────────────────────────────────────────

def create_batch(db: Session, org_id: int, run_id: int, actor_id: Optional[int]) -> dict:
    """The salary batch of a committed run: every payslip with net pay > 0."""
    from app.modules.payroll import mexico_run_service

    _payment_guard(db, org_id)
    m = _payment_models()
    run = db.get(m.PayrollRun, run_id)
    if run is None or run.organization_id != org_id:
        raise NotFoundException(f"Payroll run {run_id} not found")
    if not _committed(run):
        raise BadRequestException("Only a committed (approved) run can be paid")
    B = m.PayrollMxPaymentBatch
    live = (db.query(B).filter(B.payroll_run_id == run.id, B.reissue_of_batch_id.is_(None),
                               B.status.in_(("DRAFT", "RELEASED", "CLOSED"))).first())
    if live is not None:
        raise BadRequestException(f"the run already has payment batch {live.id} ({live.status})")
    lines, missing = [], []
    for item in mexico_run_service._mx_items(db, run):
        amount = _amount(item.net_pay)
        if amount <= 0:
            continue
        emp = db.get(m.PayrollEmployee, item.employee_id)
        clabe = _clabe_of(emp)
        if clabe is None:
            missing.append(item.employee_id)
            continue
        lines.append((item, emp, clabe, amount))
    if missing:
        raise MXBlock("MX_CLABE_MISSING",
                      f"employee(s) {missing} have no 18-digit CLABE — record it before paying the run", org_id)
    if not lines:
        raise BadRequestException("the run has no payslip with net pay to pay")
    batch = B(organization_id=org_id, payroll_run_id=run.id, file_mode="WORKLIST", status="DRAFT",
              item_count=len(lines), total_amount=sum((a for *_, a in lines), _ZERO), maker_id=actor_id,
              exports=0, idempotency_key=_next_key(db, org_id, run.id))
    db.add(batch)
    db.flush()
    for item, emp, clabe, amount in lines:
        db.add(m.PayrollMxPaymentItem(organization_id=org_id, batch_id=batch.id, employee_id=emp.id,
                                      payslip_item_id=item.id, clabe_last4=clabe[-4:], amount=amount,
                                      status="PENDING"))
    _payment_audit(db, actor_id=actor_id, action="create_payment_batch", entity_type="mx_payment_batch",
                   entity_id=batch.id, new={"runId": run.id, "items": len(lines), "total": str(batch.total_amount)})
    db.commit()
    return batch_view(db, batch)


def release_batch(db: Session, org_id: int, batch_id: int, actor_id: Optional[int]) -> dict:
    _payment_guard(db, org_id)
    batch = _payment_batch(db, org_id, batch_id)
    if batch.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT batch can be released (this one is {batch.status})")
    if actor_id is not None and actor_id == batch.maker_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", "a payment batch must be released by someone other than its maker",
                      org_id)
    batch.status, batch.checker_id, batch.released_at = "RELEASED", actor_id, datetime.now(timezone.utc)
    _payment_audit(db, actor_id=actor_id, action="release_payment_batch", entity_type="mx_payment_batch",
                   entity_id=batch.id, new={"status": "RELEASED"})
    db.commit()
    return batch_view(db, batch)


def cancel_batch(db: Session, org_id: int, batch_id: int, reason: str, actor_id: Optional[int]) -> dict:
    _payment_guard(db, org_id)
    batch = _payment_batch(db, org_id, batch_id)
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Cancelling a batch needs a reason")
    if batch.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT batch can be cancelled (this one is {batch.status} — record each "
                                  f"payment's outcome instead)")
    batch.status, batch.cancelled_reason = "CANCELLED", text[:300]
    _unlink_reissues(db, batch)
    _payment_audit(db, actor_id=actor_id, action="cancel_payment_batch", entity_type="mx_payment_batch",
                   entity_id=batch.id, reason=text[:300])
    db.commit()
    return batch_view(db, batch)


def _unlink_reissues(db: Session, batch) -> None:
    """A cancelled re-issue batch frees the items it was re-issuing."""
    m = _payment_models()
    for it in _batch_items(db, batch.id):
        if it.reissue_of_item_id:
            original = db.get(m.PayrollMxPaymentItem, it.reissue_of_item_id)
            if original is not None and original.reissued_by_item_id == it.id:
                original.reissued_by_item_id = None


def export_worklist(db: Session, org_id: int, batch_id: int, actor_id: Optional[int]) -> dict:
    """The worklist of a RELEASED batch (D2), built on request: the full CLABE
    is read only now and never stored; the export is audited without it."""
    _payment_guard(db, org_id)
    m = _payment_models()
    batch = _payment_batch(db, org_id, batch_id)
    if batch.status not in ("RELEASED", "CLOSED"):
        raise BadRequestException("Only a released batch can be exported")
    run = db.get(m.PayrollRun, batch.payroll_run_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([WORKLIST_BANNER])
    w.writerow(["item_id", "reference", "employee_code", "employee_name", "clabe", "amount", "currency", "pay_date",
                "status"])
    changed = []
    for it in _batch_items(db, batch.id):
        emp = db.get(m.PayrollEmployee, it.employee_id)
        clabe = _clabe_of(emp)
        if clabe is None or clabe[-4:] != it.clabe_last4:
            changed.append(it.employee_id)
            continue
        w.writerow([it.id, f"ZP-{batch.id}-{it.id}", emp.employee_code, emp.name, clabe, str(it.amount), "MXN",
                    run.pay_date.isoformat() if run and run.pay_date else "", it.status])
    if changed:
        raise MXBlock("MX_CLABE_CHANGED",
                      f"the CLABE of employee(s) {changed} changed or was removed after the batch was built — cancel "
                      f"and rebuild, or re-issue", org_id)
    content = buf.getvalue()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    batch.last_export_sha256, batch.exports = digest, (batch.exports or 0) + 1
    _payment_audit(db, actor_id=actor_id, action="export_payment_worklist", entity_type="mx_payment_batch",
                   entity_id=batch.id, new={"sha256": digest, "items": batch.item_count})
    db.commit()
    return {"filename": f"zoiko-mx-payment-worklist-batch-{batch.id}.csv", "content": content, "sha256": digest,
            "banner": WORKLIST_BANNER}


# ── outcomes and re-issue ───────────────────────────────────────────────────

def record_item_outcome(db: Session, org_id: int, item_id: int, data: dict, actor_id: Optional[int]) -> dict:
    _payment_guard(db, org_id)
    m = _payment_models()
    it = _payment_item(db, org_id, item_id)
    batch = db.get(m.PayrollMxPaymentBatch, it.batch_id)
    if batch.status not in ("RELEASED", "CLOSED"):
        raise BadRequestException("Outcomes are recorded for a released batch")
    outcome = str(data.get("outcome") or "").upper()
    if outcome not in OUTCOMES:
        raise BadRequestException(f"outcome must be one of {', '.join(OUTCOMES)}")
    if it.status in FINAL:
        raise BadRequestException(f"the payment is already {it.status}")
    reference = (data.get("reference") or "").strip()
    if outcome in ("SETTLED", "RETURNED", "FAILED") and not reference:
        raise BadRequestException("Recording an outcome needs the bank reference (e.g. the SPEI tracking key)")
    reason = (data.get("reason") or "").strip()
    if outcome in ("RETURNED", "FAILED") and not reason:
        raise BadRequestException(f"A {outcome.lower()} payment needs the reason")
    it.status = outcome
    it.outcome_reference = reference[:120] or it.outcome_reference
    it.return_reason = reason[:300] or None
    if not any(x.status in ("PENDING", "UNKNOWN") for x in _batch_items(db, batch.id)):
        batch.status = "CLOSED"
    _payment_audit(db, actor_id=actor_id, action="record_payment_outcome", entity_type="mx_payment_item",
                   entity_id=it.id, new={"outcome": outcome})
    db.commit()
    return item_view(it)


def reissue(db: Session, org_id: int, batch_id: int, actor_id: Optional[int]) -> dict:
    """A new DRAFT batch for the FAILED / RETURNED items not re-issued yet,
    with the worker's CURRENT CLABE (the reason to re-issue is often a wrong one)."""
    _payment_guard(db, org_id)
    m = _payment_models()
    batch = _payment_batch(db, org_id, batch_id)
    todo = [it for it in _batch_items(db, batch.id) if it.status in ("FAILED", "RETURNED") and not it.reissued_by_item_id]
    if not todo:
        raise BadRequestException("No failed or returned payment to re-issue")
    lines, missing = [], []
    for it in todo:
        emp = db.get(m.PayrollEmployee, it.employee_id)
        clabe = _clabe_of(emp)
        if clabe is None:
            missing.append(it.employee_id)
        lines.append((it, clabe))
    if missing:
        raise MXBlock("MX_CLABE_MISSING", f"employee(s) {missing} have no 18-digit CLABE", org_id)
    B = m.PayrollMxPaymentBatch
    new = B(organization_id=org_id, payroll_run_id=batch.payroll_run_id, reissue_of_batch_id=batch.id,
            file_mode="WORKLIST", status="DRAFT", item_count=len(lines),
            total_amount=sum((_amount(it.amount) for it, _ in lines), _ZERO), maker_id=actor_id, exports=0,
            idempotency_key=_next_key(db, org_id, batch.payroll_run_id))
    db.add(new)
    db.flush()
    for it, clabe in lines:
        copy = m.PayrollMxPaymentItem(organization_id=org_id, batch_id=new.id, employee_id=it.employee_id,
                                      payslip_item_id=it.payslip_item_id, clabe_last4=clabe[-4:], amount=it.amount,
                                      status="PENDING", reissue_of_item_id=it.id)
        db.add(copy)
        db.flush()
        it.reissued_by_item_id = copy.id
    _payment_audit(db, actor_id=actor_id, action="reissue_payments", entity_type="mx_payment_batch",
                   entity_id=new.id, new={"reissueOf": batch.id, "items": len(lines)})
    db.commit()
    return batch_view(db, new)


# ── the run's reset (Phase 6 rule) ──────────────────────────────────────────

def downstream_reasons(db: Session, run) -> list:
    """A RELEASED (or CLOSED) batch refuses the run's reset."""
    B = _payment_models().PayrollMxPaymentBatch
    return [f"payment batch {b.id} is {b.status}" for b in
            db.query(B).filter(B.payroll_run_id == run.id, B.status.in_(("RELEASED", "CLOSED"))).order_by(B.id)]


def withdraw_on_reset(db: Session, run) -> int:
    B = _payment_models().PayrollMxPaymentBatch
    n = 0
    for b in db.query(B).filter(B.payroll_run_id == run.id, B.status == "DRAFT"):
        b.status, b.cancelled_reason = "CANCELLED", "the run was reset"
        _unlink_reissues(db, b)
        n += 1
    return n


# ── views ───────────────────────────────────────────────────────────────────

def item_view(it) -> dict:
    return {"id": it.id, "batchId": it.batch_id, "employeeId": it.employee_id, "payslipItemId": it.payslip_item_id,
            "clabeLast4": it.clabe_last4, "amount": str(it.amount), "status": it.status,
            "reference": it.outcome_reference, "returnReason": it.return_reason,
            "reissueOfItemId": it.reissue_of_item_id, "reissuedByItemId": it.reissued_by_item_id}


def batch_view(db: Session, batch) -> dict:
    return {"id": batch.id, "runId": batch.payroll_run_id, "reissueOfBatchId": batch.reissue_of_batch_id,
            "fileMode": batch.file_mode, "status": batch.status, "itemCount": batch.item_count,
            "totalAmount": str(batch.total_amount), "makerId": batch.maker_id, "checkerId": batch.checker_id,
            "releasedAt": batch.released_at.isoformat() if batch.released_at else None, "exports": batch.exports,
            "lastExportSha256": batch.last_export_sha256, "cancelledReason": batch.cancelled_reason,
            "items": [item_view(it) for it in _batch_items(db, batch.id)]}


def list_batches(db: Session, org_id: int, run_id: Optional[int] = None) -> list:
    _payment_guard(db, org_id)
    B = _payment_models().PayrollMxPaymentBatch
    q = db.query(B).filter(B.organization_id == org_id)
    if run_id:
        q = q.filter(B.payroll_run_id == run_id)
    return [batch_view(db, b) for b in q.order_by(B.id.desc())]


def get_batch(db: Session, org_id: int, batch_id: int) -> dict:
    _payment_guard(db, org_id)
    return batch_view(db, _payment_batch(db, org_id, batch_id))
