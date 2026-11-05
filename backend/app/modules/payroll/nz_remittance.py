"""New Zealand remittance (ZP-NZ-ENG-001 Phase 8; spec §9, NZ-019; D-P8-3).

  periods     MONTHLY: the calendar month; TWICE_MONTHLY: 1–15 and 16–end.
  due dates   from signed content rows only: monthly -> the signed day of the
              next month; 1–15 -> the signed day of the same month; 16–end ->
              the signed day of the next month, except 16–31 December -> the
              signed MM-DD of January. An unsigned rule leaves due_on empty.
  lines       written once per payslip and obligation when a run is PAID
              (append-only); a correction's delta lands in the ORIGINAL
              payday's period and is flagged late if that period was already
              due (D-P8-3).
  settlements recorded by one person, matched by a second; only matched
              settlements make a remittance PART_PAID / PAID. A filing's
              acceptance never pays anything (NZ-019).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs

ZERO = Decimal("0")
MARK = "[PENDING G1]"
# obligation -> nz_result.obligations key (PAYE already includes the ACC earner levy)
OBLIGATION_FIELDS = (("PAYE", "payeTotal"), ("STUDENT_LOAN", "studentLoan"), ("KS_EMPLOYEE", "ksEmployee"),
                     ("KS_EMPLOYER_NET", "ksEmployerNet"), ("ESCT", "esct"), ("CHILD_SUPPORT", "childSupport"))
KIWISAVER_OBLIGATIONS = ("KS_EMPLOYEE", "KS_EMPLOYER_NET")


def _conflict(message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"New Zealand: {message}")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def signed_row(rate_map: Optional[dict], key: str):
    """A content row only when it exists and is signed (no PENDING marker)."""
    row = (rate_map or {}).get(key)
    if row is None or MARK in (getattr(row, "label", None) or ""):
        return None
    return row


def signed_amount(rate_map, key) -> Optional[Decimal]:
    row = signed_row(rate_map, key)
    return None if row is None or row.flat_amount is None else Decimal(str(row.flat_amount))


def signed_text(rate_map, key) -> Optional[str]:
    row = signed_row(rate_map, key)
    value = (getattr(row, "text_value", None) or "").strip().upper() if row is not None else ""
    return value or None


# ── periods and due dates ───────────────────────────────────────────────────
def period_for(pay_date: date, remittance_class: str) -> tuple:
    last = calendar.monthrange(pay_date.year, pay_date.month)[1]
    if remittance_class == "TWICE_MONTHLY":
        if pay_date.day <= 15:
            return date(pay_date.year, pay_date.month, 1), date(pay_date.year, pay_date.month, 15)
        return date(pay_date.year, pay_date.month, 16), date(pay_date.year, pay_date.month, last)
    return date(pay_date.year, pay_date.month, 1), date(pay_date.year, pay_date.month, last)


def _day_in(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _next_month(d: date) -> tuple:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def remittance_due_on(rate_map, period_start: date, period_end: date, remittance_class: str) -> Optional[date]:
    if remittance_class == "MONTHLY":
        day = signed_amount(rate_map, "nz_remit_monthly_due_day")
        return None if day is None else _day_in(*_next_month(period_end), int(day))
    if period_start.day == 1:
        day = signed_amount(rate_map, "nz_remit_first_half_due_day")
        return None if day is None else _day_in(period_end.year, period_end.month, int(day))
    if period_end.month == 12:
        text = signed_text(rate_map, "nz_remit_december_second_half_due")
        if not text or len(text) != 5:
            return None
        month, day = int(text[:2]), int(text[3:])
        return _day_in(period_end.year + 1, month, day)
    day = signed_amount(rate_map, "nz_remit_second_half_due_day")
    return None if day is None else _day_in(*_next_month(period_end), int(day))


def class_mismatch(db: Session, profile, on: date) -> Optional[str]:
    """The profile's remittance class against the signed large-employer
    threshold, with a connected-business group's annual PAYE/ESCT summed.
    None when it agrees or cannot be checked (no amount / unsigned rule)."""
    rate_map, _slabs, _pack = nzs._nz_pack_in_force(db, on)
    threshold = signed_amount(rate_map, "nz_large_employer_threshold")
    if threshold is None or profile.annual_paye_esct_amount is None:
        return None
    m = nzs._nz_models()
    P = m.PayrollNzEmployerProfile
    total = _dec(profile.annual_paye_esct_amount)
    if profile.connected_business_group_ref:
        others = (db.query(P).filter(P.organization_id == profile.organization_id, P.status == "ACTIVE",
                                     P.id != profile.id,
                                     P.connected_business_group_ref == profile.connected_business_group_ref).all())
        total += sum((_dec(o.annual_paye_esct_amount) for o in others), ZERO)
    expected = "TWICE_MONTHLY" if total >= threshold else "MONTHLY"
    if expected != profile.remittance_class:
        return f"annual PAYE/ESCT {total} makes this a {expected} remitter, but the profile says {profile.remittance_class}"
    return None


# ── posting at PAID ─────────────────────────────────────────────────────────
def _profile(db: Session, organization_id: int, legal_entity_id, on: date):
    m = nzs._nz_models()
    profile = nzs._nz_one_active(db, m.PayrollNzEmployerProfile, organization_id, None, on, "employer profile",
                                 legal_entity_id=legal_entity_id, entity_scoped=True)
    if profile is None:
        _conflict("no ACTIVE employer profile covers the payday; remittances cannot be posted.")
    return profile


def _recompute(row) -> None:
    amount, settled = _dec(row.amount), _dec(row.settled)
    if amount > ZERO and settled >= amount:
        row.status = "PAID"
    elif settled > ZERO:
        row.status = "PART_PAID"
    else:
        row.status = "OPEN"


def _remittance(db: Session, organization_id: int, legal_entity_id, profile, pay_date: date, obligation: str,
                destination: str, fund_ref: str, actor_id):
    m = nzs._nz_models()
    R = m.PayrollNzRemittance
    start, end = period_for(pay_date, profile.remittance_class)
    query = db.query(R).filter(R.organization_id == organization_id, R.period_start == start,
                               R.obligation == obligation, R.destination == destination, R.fund_ref == fund_ref)
    query = query.filter(R.legal_entity_id.is_(None) if legal_entity_id is None else R.legal_entity_id == legal_entity_id)
    row = query.first()
    if row is None:
        rate_map, _slabs, _pack = nzs._nz_pack_in_force(db, end)
        row = R(organization_id=organization_id, legal_entity_id=legal_entity_id, period_start=start, period_end=end,
                remittance_class=profile.remittance_class, obligation=obligation, destination=destination,
                fund_ref=fund_ref, amount=ZERO, settled=ZERO,
                due_on=remittance_due_on(rate_map, start, end, profile.remittance_class), status="OPEN",
                created_by_id=actor_id)
        db.add(row)
        db.flush()
    return row


def post_run(db: Session, run, actor_id) -> int:
    """One line per payslip and obligation of a PAID New Zealand run.
    Idempotent (unique per payslip and remittance)."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    m = nzs._nz_models()
    L = m.PayrollNzRemittanceLine
    posted = 0
    for item in nzs._nz_run_items(db, run):
        snapshot = item.nz_calculation_snapshot or {}
        obligations = snapshot.get("obligations") or {}
        if not obligations:
            continue
        employee = db.get(PayrollEmployee, item.employee_id)
        entity = getattr(employee, "legal_entity_id", None)
        source, correction_id, pay_date, kiwisaver = "RUN", None, run.pay_date, snapshot.get("kiwisaver") or {}
        if snapshot.get("correctionOf"):
            original = db.get(PayslipItem, snapshot["correctionOf"])
            original_run = db.get(PayrollRun, original.payroll_run_id)
            source, correction_id, pay_date = "CORRECTION", snapshot.get("correctionId"), original_run.pay_date
            kiwisaver = (original.nz_calculation_snapshot or {}).get("kiwisaver") or {}
        profile = _profile(db, run.organization_id, entity, pay_date)
        for obligation, key in OBLIGATION_FIELDS:
            amount = _dec(obligations.get(key))
            if amount == ZERO:
                continue
            destination, fund_ref = "INLAND_REVENUE", ""
            if obligation in KIWISAVER_OBLIGATIONS and kiwisaver.get("destination") == "COMPLYING_FUND":
                destination, fund_ref = "COMPLYING_FUND", kiwisaver.get("complyingFundRef") or ""
            row = _remittance(db, run.organization_id, entity, profile, pay_date, obligation, destination, fund_ref,
                              actor_id)
            if db.query(L.id).filter(L.payslip_item_id == item.id, L.remittance_id == row.id).first():
                continue
            db.add(L(organization_id=run.organization_id, legal_entity_id=entity, remittance_id=row.id, run_id=run.id,
                     payslip_item_id=item.id, amount=amount, source=source, correction_id=correction_id,
                     created_by_id=actor_id))
            row.amount = _dec(row.amount) + amount
            if source == "CORRECTION" and row.due_on is not None and run.pay_date > row.due_on:
                row.late = True
            _recompute(row)
            posted += 1
    db.flush()
    return posted


# ── settlements ─────────────────────────────────────────────────────────────
def _row(db: Session, model, organization_id: int, row_id: int, what: str):
    row = db.query(model).filter(model.id == row_id, model.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException(f"New Zealand {what}")
    return row


def record_settlement(db: Session, organization_id: int, remittance_id: int, payload: dict, actor_id):
    m = nzs._nz_models()
    remittance = _row(db, m.PayrollNzRemittance, organization_id, remittance_id, "remittance")
    payload = dict(payload or {})
    reason = nzs._nz_reason(payload.get("reason"))
    reference = (payload.get("payment_reference") or "").strip()
    if not reference:
        raise BadRequestException("A settlement needs its payment reference.")
    amount = nzs._money(payload.get("amount"), "amount")
    if amount is None or amount <= ZERO:
        raise BadRequestException("amount must be above zero.")
    paid_on = nzs._as_date(payload.get("paid_on"), "paid_on")
    row = m.PayrollNzSettlement(organization_id=organization_id, legal_entity_id=remittance.legal_entity_id,
                                remittance_id=remittance.id, paid_on=paid_on, amount=amount,
                                payment_reference=reference[:100], status="RECORDED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "recorded", "nz_settlement", row.id, new={"amount": str(amount)},
                  reason=reason)
    return row


def match_settlement(db: Session, organization_id: int, settlement_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    m = nzs._nz_models()
    row = _row(db, m.PayrollNzSettlement, organization_id, settlement_id, "settlement")
    if row.status != "RECORDED":
        raise BadRequestException("Only a RECORDED settlement can be matched.")
    require_four_eyes(row.created_by_id, actor_id, "Matching a New Zealand settlement", db=db,
                      entity_type="nz_settlement", entity_id=row.id, current_status=row.status)
    remittance = db.get(m.PayrollNzRemittance, row.remittance_id)
    row.status, row.matched_by_id, row.matched_at = "MATCHED", actor_id, datetime.utcnow()
    remittance.settled = _dec(remittance.settled) + _dec(row.amount)
    _recompute(remittance)
    db.flush()
    nzs._nz_audit(db, actor_id, "matched", "nz_settlement", row.id, new={"remittance": remittance.status})
    return row


def reverse_settlement(db: Session, organization_id: int, settlement_id: int, actor_id, reason=None):
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    row = _row(db, m.PayrollNzSettlement, organization_id, settlement_id, "settlement")
    if row.status == "REVERSED":
        raise BadRequestException("The settlement is already reversed.")
    if row.status == "MATCHED":
        remittance = db.get(m.PayrollNzRemittance, row.remittance_id)
        remittance.settled = _dec(remittance.settled) - _dec(row.amount)
        _recompute(remittance)
    row.status = "REVERSED"
    db.flush()
    nzs._nz_audit(db, actor_id, "reversed", "nz_settlement", row.id, new={"status": "REVERSED"}, reason=reason)
    return row


# ── views ───────────────────────────────────────────────────────────────────
def remittance_view(row, lines=None, settlements=None) -> dict:
    out = {"id": row.id, "legalEntityId": row.legal_entity_id, "periodStart": row.period_start.isoformat(),
           "periodEnd": row.period_end.isoformat(), "remittanceClass": row.remittance_class,
           "obligation": row.obligation, "destination": row.destination, "fundRef": row.fund_ref or None,
           "amount": str(row.amount), "settled": str(row.settled),
           "dueOn": row.due_on.isoformat() if row.due_on else None, "status": row.status, "late": row.late}
    if lines is not None:
        out["lines"] = [{"id": l.id, "runId": l.run_id, "payslipItemId": l.payslip_item_id, "amount": str(l.amount),
                         "source": l.source, "correctionId": l.correction_id} for l in lines]
    if settlements is not None:
        out["settlements"] = [settlement_view(s) for s in settlements]
    return out


def settlement_view(row) -> dict:
    return {"id": row.id, "remittanceId": row.remittance_id, "paidOn": row.paid_on.isoformat(),
            "amount": str(row.amount), "paymentReference": row.payment_reference, "status": row.status,
            "createdById": row.created_by_id, "matchedById": row.matched_by_id}


def list_remittances(db: Session, organization_id: int, period_start=None) -> list:
    m = nzs._nz_models()
    R = m.PayrollNzRemittance
    query = db.query(R).filter(R.organization_id == organization_id)
    if period_start:
        query = query.filter(R.period_start == nzs._as_date(period_start, "periodStart"))
    return [remittance_view(r) for r in query.order_by(R.period_start.desc(), R.obligation)]


def get_remittance(db: Session, organization_id: int, remittance_id: int) -> dict:
    m = nzs._nz_models()
    row = _row(db, m.PayrollNzRemittance, organization_id, remittance_id, "remittance")
    lines = (db.query(m.PayrollNzRemittanceLine).filter(m.PayrollNzRemittanceLine.remittance_id == row.id)
             .order_by(m.PayrollNzRemittanceLine.id).all())
    settlements = (db.query(m.PayrollNzSettlement).filter(m.PayrollNzSettlement.remittance_id == row.id)
                   .order_by(m.PayrollNzSettlement.id).all())
    return remittance_view(row, lines, settlements)
