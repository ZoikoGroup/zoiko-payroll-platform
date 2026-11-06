"""Poland settlements and reconciliation (ZP-PL-ENG-001 Phase 8; spec §10
Settlement / reconciliation, PL-020; decision D5).

  liabilities  one row per legal employer, liability and pay-date month,
               rebuilt at PAID from the frozen PAID payslips of that month:
                 ZUS  employee + employer social insurance, health
                      contribution and the employer funds (one ZUS transfer)
                 PIT  the PIT advances withheld
                 PPK  employee + employer PPK contributions
               Due dates come from signed content only (ZUS day of the
               employer's verified class; PPK transfer day); the PIT remittance
               rule is PENDING_G1 so its due date stays empty.
  payments     recorded by hand (no bank call, PL-021), each with its own
               reference: the same reference with the same amount and date is
               the same payment (idempotent retry); with anything else it is
               refused. A filing's acceptance never marks a liability paid.
  reconcile    paid == due -> RECONCILED (no tolerance: the tolerance row is
               not signed). Otherwise a variance is raised; only a second person
               can resolve it, with a reason. A liability that changes after a
               payment raises CHANGED_AFTER_PAYMENT.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import poland_filing as plf
from app.modules.payroll import poland_service as pls

ZERO = Decimal("0")
LIABILITIES = ("ZUS", "PIT", "PPK")


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Poland ({code}): {message}")


def _models():
    m = pls._models()
    return m.PayrollPlSettlement, m.PayrollPlReconciliationVariance


def settlement_key(organization_id: int, legal_entity_id, liability: str, key: str) -> str:
    return f"PL:{organization_id}:{legal_entity_id or 0}:{liability}:{key}"


def _status(due: Decimal, paid: Decimal) -> str:
    if paid == ZERO:
        return "DUE" if due > ZERO else "PAID"
    if paid < due:
        return "PART_PAID"
    return "PAID" if paid == due else "OVERPAID"


def _amounts(items) -> dict:
    out = {name: {} for name in LIABILITIES}
    for _run, item, _employee in items:
        mm = plf.item_measures(item)
        z = out["ZUS"]
        z["zusEmployee"] = z.get("zusEmployee", ZERO) + sum(mm["zusEmployee"].values(), ZERO)
        z["zusEmployer"] = z.get("zusEmployer", ZERO) + sum(mm["zusEmployer"].values(), ZERO)
        z["health"] = z.get("health", ZERO) + mm["health"]
        z["funds"] = z.get("funds", ZERO) + sum(mm["funds"].values(), ZERO)
        out["PIT"]["pitAdvance"] = out["PIT"].get("pitAdvance", ZERO) + mm["pit"]
        p = out["PPK"]
        p["ppkEmployee"] = p.get("ppkEmployee", ZERO) + mm["ppkEmployee"]
        p["ppkEmployer"] = p.get("ppkEmployer", ZERO) + mm["ppkEmployer"]
    return out


def _due_on(db: Session, organization_id: int, liability: str, key: str, registration) -> Optional[date]:
    if liability == "ZUS":
        return plf.zus_due_on(db, organization_id, key, registration)
    if liability == "PPK":
        start, _end = plf._month_bounds(key)
        year, month = plf._next_month(start)
        pack = plf.signed_pack(db, organization_id, date(year, month, 1))
        day = plf.signed_amount(pack, "pl_ppk_transfer_day")
        if day is None:
            return None
        try:
            return date(year, month, int(day))
        except ValueError:
            return None
    return None                                   # PIT: pl_pit_remittance_due_rule is PENDING_G1


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
    pls._audit(db, actor_id, "raised", "pl_reconciliation_variance", row.id,
               new={"kind": kind, "difference": str(difference)})
    return row


def build_pl_settlements(db: Session, run, actor_id) -> list:
    """At PAID: (re)compute every liability of the pay-date month for each
    legal employer in the run."""
    from app.modules.payroll.models import PayrollEmployee

    S, _V = _models()
    items = pls._run_items(db, run)
    if not items:
        return []
    key = plf.period_key(run.pay_date)
    start, end = plf._month_bounds(key)
    entities = sorted({getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items},
                      key=lambda x: (x is not None, x or 0))
    out = []
    for entity in entities:
        run_ids, month_items = plf._paid_items(db, run.organization_id, start, end, entity, extra_run=run)
        registration = plf._registration(db, run.organization_id, entity, end)
        for liability, parts in _amounts(month_items).items():
            amount = sum(parts.values(), ZERO).quantize(Decimal("0.01"))
            components = {k: plf._s(v) for k, v in sorted(parts.items())}
            skey = settlement_key(run.organization_id, entity, liability, key)
            row = db.query(S).filter(S.settlement_key == skey).first()
            if row is None:
                if amount == ZERO:
                    continue
                row = S(organization_id=run.organization_id, legal_entity_id=entity, liability_type=liability,
                        period_key=key, settlement_key=skey, amount_due=amount, paid_amount=ZERO, payments=[],
                        run_ids=run_ids, components=components, status=_status(amount, ZERO),
                        due_on=_due_on(db, run.organization_id, liability, key, registration),
                        created_by_id=actor_id)
                db.add(row)
                db.flush()
                pls._audit(db, actor_id, "created", "pl_settlement", row.id,
                           new={"liability": liability, "period": key, "amount": str(amount)})
                out.append(row)
                continue
            old = Decimal(str(row.amount_due))
            if old == amount:
                out.append(row)                                           # PL-020: nothing changed
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
            pls._audit(db, actor_id, "recomputed", "pl_settlement", row.id, old={"amount": str(old)},
                       new={"amount": str(amount)})
            out.append(row)
    return out


def _settlement(db: Session, organization_id: int, settlement_id: int):
    S, _V = _models()
    row = db.query(S).filter(S.id == settlement_id, S.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Poland settlement")
    return row


def record_pl_settlement_payment(db: Session, organization_id: int, settlement_id: int, payload: dict, actor_id):
    payload = dict(payload or {})
    ref = str(payload.get("paymentRef") or "").strip()[:100]
    if not ref:
        raise BadRequestException("paymentRef is required.")
    amount = pls._decimal(payload.get("amount"), "amount")
    if amount is None or amount <= ZERO:
        raise BadRequestException("amount must be greater than zero.")
    amount = amount.quantize(Decimal("0.01"))
    paid_on = pls._as_date(payload.get("paidOn"), "paidOn")
    row = _settlement(db, organization_id, settlement_id)
    for existing in row.payments or []:
        if existing.get("ref") == ref:
            if existing.get("amount") == plf._s(amount) and existing.get("paidOn") == paid_on.isoformat():
                return row                                                # idempotent retry (PL-020)
            _conflict("PL_PAYMENT_REF_REUSED", "this payment reference is already recorded with other details.")
    if row.status == "RECONCILED":
        _conflict("PL_SETTLEMENT_RECONCILED", "the liability is reconciled; record a variance instead.")
    payments = list(row.payments or [])
    payments.append({"ref": ref, "amount": plf._s(amount), "paidOn": paid_on.isoformat(), "recordedById": actor_id})
    row.payments = payments
    row.paid_amount = Decimal(str(row.paid_amount or 0)) + amount
    row.status = _status(Decimal(str(row.amount_due)), Decimal(str(row.paid_amount)))
    row.updated_at = datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "paid", "pl_settlement", row.id, new={"ref": ref, "amount": plf._s(amount)})
    return row


def reconcile_pl_settlement(db: Session, organization_id: int, settlement_id: int, actor_id) -> dict:
    """paid == due -> RECONCILED; otherwise an OPEN variance for a second
    person to resolve."""
    _S, V = _models()
    row = _settlement(db, organization_id, settlement_id)
    if row.status == "RECONCILED":
        return {"settlement": settlement_view(row), "variance": None}
    if db.query(V.id).filter(V.settlement_id == row.id, V.status == "OPEN").first():
        _conflict("PL_VARIANCE_OPEN", "an open variance must be resolved first.")
    due, paid = Decimal(str(row.amount_due)), Decimal(str(row.paid_amount or 0))
    if due == paid:
        row.status, row.reconciled_by_id, row.reconciled_at = "RECONCILED", actor_id, datetime.utcnow()
        db.flush()
        pls._audit(db, actor_id, "reconciled", "pl_settlement", row.id, new={"status": "RECONCILED"})
        return {"settlement": settlement_view(row), "variance": None}
    variance = _variance(db, row, "UNDERPAID" if paid < due else "OVERPAID", due, paid, actor_id)
    return {"settlement": settlement_view(row), "variance": variance_view(variance)}


def resolve_pl_variance(db: Session, organization_id: int, variance_id: int, resolution, actor_id):
    from app.modules.payroll.service import require_four_eyes

    _S, V = _models()
    text = pls._reason(resolution)
    row = db.query(V).filter(V.id == variance_id, V.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Poland reconciliation variance")
    if row.status != "OPEN":
        raise BadRequestException("Only an OPEN variance can be resolved.")
    require_four_eyes(row.raised_by_id, actor_id, "Resolving a Poland reconciliation variance", db=db,
                      entity_type="pl_reconciliation_variance", entity_id=row.id, current_status=row.status)
    row.status, row.resolution, row.resolved_by_id, row.resolved_at = "RESOLVED", text, actor_id, datetime.utcnow()
    settlement = db.get(_S, row.settlement_id)
    due, paid = Decimal(str(settlement.amount_due)), Decimal(str(settlement.paid_amount or 0))
    still_open = (db.query(V.id).filter(V.settlement_id == settlement.id, V.status == "OPEN", V.id != row.id)
                  .first())
    if not still_open and Decimal(str(row.difference)) == paid - due:
        settlement.status, settlement.reconciled_by_id = "RECONCILED", actor_id
        settlement.reconciled_at = datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "resolved", "pl_reconciliation_variance", row.id, new={"status": "RESOLVED"},
               reason=text)
    return row


def settlement_view(row) -> dict:
    return {"id": row.id, "legalEntityId": row.legal_entity_id, "liabilityType": row.liability_type,
            "periodKey": row.period_key, "dueOn": row.due_on.isoformat() if row.due_on else None,
            "amountDue": plf._s(Decimal(str(row.amount_due))),
            "paidAmount": plf._s(Decimal(str(row.paid_amount or 0))),
            "outstanding": plf._s(Decimal(str(row.amount_due)) - Decimal(str(row.paid_amount or 0))),
            "components": row.components, "payments": row.payments or [], "runIds": row.run_ids,
            "status": row.status, "reconciledById": row.reconciled_by_id}


def variance_view(row) -> dict:
    return {"id": row.id, "settlementId": row.settlement_id, "kind": row.variance_kind,
            "expected": plf._s(Decimal(str(row.expected_amount))), "actual": plf._s(Decimal(str(row.actual_amount))),
            "difference": plf._s(Decimal(str(row.difference))), "status": row.status, "resolution": row.resolution,
            "raisedById": row.raised_by_id, "resolvedById": row.resolved_by_id}


def list_pl_settlements(db: Session, organization_id: int, period=None, liability=None, status=None) -> list:
    S, _V = _models()
    query = db.query(S).filter(S.organization_id == organization_id)
    if period:
        query = query.filter(S.period_key == str(period).strip())
    if liability:
        query = query.filter(S.liability_type == str(liability).strip().upper())
    if status:
        query = query.filter(S.status == str(status).strip().upper())
    return [settlement_view(r) for r in query.order_by(S.period_key.desc(), S.liability_type, S.id)]


def list_pl_variances(db: Session, organization_id: int, status=None) -> list:
    _S, V = _models()
    query = db.query(V).filter(V.organization_id == organization_id)
    if status:
        query = query.filter(V.status == str(status).strip().upper())
    return [variance_view(r) for r in query.order_by(V.id.desc())]
