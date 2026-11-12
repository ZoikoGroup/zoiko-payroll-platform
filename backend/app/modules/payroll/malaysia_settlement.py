"""Malaysia settlements and reconciliation (ZP-MY-ENG-001 Phase 9; MY-021;
decision D-5).

  liabilities  one row per legal employer, authority and pay-date month,
               rebuilt at PAID from the frozen PAID payslips of that month:
                 PCB      the PCB / MTD withheld (HASiL)
                 EPF      employee + employer EPF
                 PERKESO  employee + employer SOCSO and EIS (one PERKESO payment)
                 HRD      the HRD levy (employer cost)
               Due dates come from signed content only (the PCB remittance
               day); the EPF / PERKESO / HRD due rules are PENDING_G1, so their
               due date stays empty.
  payments     recorded by hand (no bank call, D-5), each with its own
               reference: the same reference with the same amount and date is
               the same payment (idempotent retry); with anything else it is
               refused. A filing's acceptance never marks a liability paid.
  reconcile    paid == due -> RECONCILED (no tolerance: the tolerance row is
               not signed). Otherwise a variance is raised; only a second
               person can resolve it, with a reason. A liability that changes
               after a payment raises CHANGED_AFTER_PAYMENT.
  holds        a tax-clearance hold (MY-020) keeps the employee's NET pay; it
               never changes a statutory liability.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import malaysia_filing as myf
from app.modules.payroll import malaysia_service as mys

ZERO = Decimal("0")
LIABILITIES = ("PCB", "EPF", "PERKESO", "HRD")


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Malaysia ({code}): {message}")


def _models():
    m = mys._models()
    return m.PayrollMySettlement, m.PayrollMyReconciliationVariance


def settlement_key(organization_id: int, legal_entity_id, liability: str, key: str) -> str:
    return f"MY:{organization_id}:{legal_entity_id or 0}:{liability}:{key}"


def _status(due: Decimal, paid: Decimal) -> str:
    if paid == ZERO:
        return "DUE" if due > ZERO else "PAID"
    if paid < due:
        return "PART_PAID"
    return "PAID" if paid == due else "OVERPAID"


def _amounts(items) -> dict:
    out = {name: {} for name in LIABILITIES}

    def add(liability, part, value):
        out[liability][part] = out[liability].get(part, ZERO) + value

    for _run, item, _employee in items:
        mm = myf.item_measures(item)
        add("PCB", "pcb", mm["pcb"])
        add("EPF", "epfEmployee", mm["epfEmployee"])
        add("EPF", "epfEmployer", mm["epfEmployer"])
        add("PERKESO", "socsoEmployee", mm["socsoEmployee"])
        add("PERKESO", "socsoEmployer", mm["socsoEmployer"])
        add("PERKESO", "eisEmployee", mm["eisEmployee"])
        add("PERKESO", "eisEmployer", mm["eisEmployer"])
        add("HRD", "hrdLevy", mm["hrd"])
    return out


def _variance(db: Session, settlement, kind: str, expected: Decimal, actual: Decimal, actor_id):
    _S, V = _models()
    difference = actual - expected
    same = (db.query(V).filter(V.settlement_id == settlement.id, V.status == "OPEN", V.variance_kind == kind,
                               V.difference == difference).first())
    if same is not None:
        return same
    row = V(organization_id=settlement.organization_id, legal_entity_id=settlement.legal_entity_id,
            settlement_id=settlement.id, variance_kind=kind, expected_amount=expected, actual_amount=actual,
            difference=difference, status="OPEN", raised_by_id=actor_id)
    db.add(row)
    db.flush()
    mys._audit(db, actor_id, "raised", "my_reconciliation_variance", row.id,
               new={"kind": kind, "difference": str(difference)})
    return row


def build_my_settlements(db: Session, run, actor_id) -> list:
    """At PAID: (re)compute every liability of the pay-date month for each
    legal employer in the run."""
    S, _V = _models()
    items = mys._run_items(db, run)
    if not items:
        return []
    key = myf.period_key(run.pay_date)
    start, end = myf._month_bounds(key)
    out = []
    for entity in myf._entities(db, items):
        run_ids, month_items = myf._paid_items(db, run.organization_id, start, end, entity, extra_run=run)
        for liability, parts in _amounts(month_items).items():
            amount = sum(parts.values(), ZERO).quantize(Decimal("0.01"))
            components = {k: myf._s(v) for k, v in sorted(parts.items())}
            skey = settlement_key(run.organization_id, entity, liability, key)
            row = db.query(S).filter(S.settlement_key == skey).first()
            if row is None:
                if amount == ZERO:
                    continue
                due = myf.pcb_due_on(db, run.organization_id, key) if liability == "PCB" else None
                row = S(organization_id=run.organization_id, legal_entity_id=entity, liability_type=liability,
                        period_key=key, settlement_key=skey, amount_due=amount, paid_amount=ZERO, payments=[],
                        run_ids=run_ids, components=components, status=_status(amount, ZERO), due_on=due,
                        created_by_id=actor_id)
                db.add(row)
                db.flush()
                mys._audit(db, actor_id, "created", "my_settlement", row.id,
                           new={"liability": liability, "period": key, "amount": str(amount)})
                out.append(row)
                continue
            old = Decimal(str(row.amount_due))
            if old == amount:
                out.append(row)                                           # nothing changed
                continue
            paid = Decimal(str(row.paid_amount or 0))
            row.amount_due, row.components, row.run_ids = amount, components, run_ids
            row.updated_at = datetime.utcnow()
            touched = paid > ZERO or row.status == "RECONCILED"
            row.status = _status(amount, paid)
            row.reconciled_by_id, row.reconciled_at = None, None
            db.flush()
            if touched:
                _variance(db, row, "CHANGED_AFTER_PAYMENT", amount, paid, actor_id)
            mys._audit(db, actor_id, "recomputed", "my_settlement", row.id, old={"amount": str(old)},
                       new={"amount": str(amount)})
            out.append(row)
    return out


def _settlement(db: Session, organization_id: int, settlement_id: int):
    S, _V = _models()
    row = db.query(S).filter(S.id == settlement_id, S.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Malaysia settlement")
    return row


def record_my_settlement_payment(db: Session, organization_id: int, settlement_id: int, payload: dict, actor_id):
    payload = dict(payload or {})
    ref = str(payload.get("paymentRef") or "").strip()[:100]
    if not ref:
        raise BadRequestException("paymentRef is required.")
    amount = mys._decimal(payload.get("amount"), "amount")
    if amount is None or amount <= ZERO:
        raise BadRequestException("amount must be greater than zero.")
    amount = amount.quantize(Decimal("0.01"))
    paid_on = mys._as_date(payload.get("paidOn"), "paidOn")
    row = _settlement(db, organization_id, settlement_id)
    for existing in row.payments or []:
        if existing.get("ref") == ref:
            if existing.get("amount") == myf._s(amount) and existing.get("paidOn") == paid_on.isoformat():
                return row                                                # idempotent retry
            _conflict("MY_PAYMENT_REF_REUSED", "this payment reference is already recorded with other details.")
    if row.status == "RECONCILED":
        _conflict("MY_SETTLEMENT_RECONCILED", "the liability is reconciled; record a variance instead.")
    payments = list(row.payments or [])
    payments.append({"ref": ref, "amount": myf._s(amount), "paidOn": paid_on.isoformat(), "recordedById": actor_id})
    row.payments = payments
    row.paid_amount = Decimal(str(row.paid_amount or 0)) + amount
    row.status = _status(Decimal(str(row.amount_due)), Decimal(str(row.paid_amount)))
    row.updated_at = datetime.utcnow()
    db.flush()
    mys._audit(db, actor_id, "paid", "my_settlement", row.id, new={"ref": ref, "amount": myf._s(amount)})
    return row


def reconcile_my_settlement(db: Session, organization_id: int, settlement_id: int, actor_id) -> dict:
    """paid == due -> RECONCILED; otherwise an OPEN variance for a second
    person to resolve."""
    _S, V = _models()
    row = _settlement(db, organization_id, settlement_id)
    if row.status == "RECONCILED":
        return {"settlement": settlement_view(row), "variance": None}
    if db.query(V.id).filter(V.settlement_id == row.id, V.status == "OPEN").first():
        _conflict("MY_VARIANCE_OPEN", "an open variance must be resolved first.")
    due, paid = Decimal(str(row.amount_due)), Decimal(str(row.paid_amount or 0))
    if due == paid:
        row.status, row.reconciled_by_id, row.reconciled_at = "RECONCILED", actor_id, datetime.utcnow()
        db.flush()
        mys._audit(db, actor_id, "reconciled", "my_settlement", row.id, new={"status": "RECONCILED"})
        return {"settlement": settlement_view(row), "variance": None}
    variance = _variance(db, row, "UNDERPAID" if paid < due else "OVERPAID", due, paid, actor_id)
    return {"settlement": settlement_view(row), "variance": variance_view(variance)}


def resolve_my_variance(db: Session, organization_id: int, variance_id: int, resolution, actor_id):
    from app.modules.payroll.service import require_four_eyes

    _S, V = _models()
    text = mys._reason(resolution)
    row = db.query(V).filter(V.id == variance_id, V.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Malaysia reconciliation variance")
    if row.status != "OPEN":
        raise BadRequestException("Only an OPEN variance can be resolved.")
    require_four_eyes(row.raised_by_id, actor_id, "Resolving a Malaysia reconciliation variance", db=db,
                      entity_type="my_reconciliation_variance", entity_id=row.id, current_status=row.status)
    row.status, row.resolution, row.resolved_by_id, row.resolved_at = "RESOLVED", text, actor_id, datetime.utcnow()
    settlement = db.get(_S, row.settlement_id)
    due, paid = Decimal(str(settlement.amount_due)), Decimal(str(settlement.paid_amount or 0))
    still_open = (db.query(V.id).filter(V.settlement_id == settlement.id, V.status == "OPEN", V.id != row.id)
                  .first())
    if not still_open and Decimal(str(row.difference)) == paid - due:
        settlement.status, settlement.reconciled_by_id = "RECONCILED", actor_id
        settlement.reconciled_at = datetime.utcnow()
    db.flush()
    mys._audit(db, actor_id, "resolved", "my_reconciliation_variance", row.id, new={"status": "RESOLVED"},
               reason=text)
    return row


def settlement_view(row) -> dict:
    return {"id": row.id, "legalEntityId": row.legal_entity_id, "liabilityType": row.liability_type,
            "periodKey": row.period_key, "dueOn": row.due_on.isoformat() if row.due_on else None,
            "amountDue": myf._s(Decimal(str(row.amount_due))),
            "paidAmount": myf._s(Decimal(str(row.paid_amount or 0))),
            "outstanding": myf._s(Decimal(str(row.amount_due)) - Decimal(str(row.paid_amount or 0))),
            "components": row.components, "payments": row.payments or [], "runIds": row.run_ids,
            "status": row.status, "reconciledById": row.reconciled_by_id}


def variance_view(row) -> dict:
    return {"id": row.id, "settlementId": row.settlement_id, "kind": row.variance_kind,
            "expected": myf._s(Decimal(str(row.expected_amount))), "actual": myf._s(Decimal(str(row.actual_amount))),
            "difference": myf._s(Decimal(str(row.difference))), "status": row.status, "resolution": row.resolution,
            "raisedById": row.raised_by_id, "resolvedById": row.resolved_by_id}


def list_my_settlements(db: Session, organization_id: int, period=None, liability=None, status=None) -> list:
    S, _V = _models()
    query = db.query(S).filter(S.organization_id == organization_id)
    if period:
        query = query.filter(S.period_key == str(period).strip())
    if liability:
        query = query.filter(S.liability_type == str(liability).strip().upper())
    if status:
        query = query.filter(S.status == str(status).strip().upper())
    return [settlement_view(r) for r in query.order_by(S.period_key.desc(), S.liability_type, S.id)]


def list_my_variances(db: Session, organization_id: int, status=None) -> list:
    _S, V = _models()
    query = db.query(V).filter(V.organization_id == organization_id)
    if status:
        query = query.filter(V.status == str(status).strip().upper())
    return [variance_view(r) for r in query.order_by(V.id.desc())]
