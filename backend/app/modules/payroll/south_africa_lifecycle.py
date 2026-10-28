"""
south_africa_lifecycle.py — South Africa payroll lifecycle controls
(ZP-ZA-ENG-001 §5, §8; ZA-012, ZA-013, ZA-016, ZA-017; Phase 9). "ZA" is South
Africa ("SA" in this repo is Saudi Arabia).

  * calculation inputs   approved hours (attendance), ZA deduction orders
                         (payroll_court_ordered_deductions, jurisdiction 'ZA'),
                         APPROVED overrides for the run;
  * four-eyes exceptions za_run_exceptions / approve_za_run_exception — every
                         ZA-016 exception needs a second person before APPROVED;
  * approval / commit    fingerprint stored at APPROVED, drift refused; at PAID
                         the ETI ledger, directive 'applied' marking and override
                         APPLIED are written once (idempotent);
  * overrides            propose / approve / withdraw (ZA-017): a result changes,
                         the rule pack never does;
  * corrections          a linked delta payslip replayed from the frozen context;
                         the original is never edited; ETI reversed + re-recorded;
  * public holidays      Public Holidays Act 36 of 1994 schedule.

A threshold the spec does not state (large variable pay, bank-change window)
fails closed: with no configured value every case is an exception.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

ZA = "ZA"
ZA_CORRECTION_MARKER = "[ZA-CORRECTION]"
# Inputs a correction may restate (frozen-context keys).
ZA_CORRECTABLE_INPUTS = frozenset({"gross", "basic", "overtime", "za_components", "za_retirement_fund_contribution",
                                   "za_eti_paid_hours", "za_hours", "za_deduction_orders", "za_variable_items"})
# Delta payslip column <- za_result key.
_ZA_DELTA_COLUMNS = (("tds", "za_paye"), ("esi", "za_uif_employee"), ("employer_esi", "za_uif_employer"),
                     ("employer_payroll_tax", "za_sdl"), ("employee_pension", "za_retirement_contribution"))
_OPEN_RUN_STATUSES = ("Draft", "Review")
_COMMITTED_RUN_STATUSES = ("Paid", "Closed")


def _svc():
    from app.modules.payroll import south_africa_service

    return south_africa_service


def _content():
    from app.modules.payroll.engine.countries import south_africa_content

    return south_africa_content


def _status(run) -> str:
    return str(getattr(run.status, "value", run.status))


def _conflict(detail: str):
    from fastapi import HTTPException, status as http_status

    return HTTPException(http_status.HTTP_409_CONFLICT, detail=detail)


def _scalar(key: str):
    """(employee_pct, flat, text) of a ZA content scalar row; Nones when empty."""
    for row in _content().ZA_SCALAR_CONTENT:
        if row[0] == key:
            return row[2], row[4], row[5]
    return None, None, None


def _dec_or_none(value) -> Optional[Decimal]:
    return None if value in (None, "") else Decimal(str(value))


def _money2(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _opt_date(data, *names) -> Optional[date]:
    svc = _svc()
    value = next((svc._field(data, n) for n in names if svc._field(data, n) not in (None, "")), None)
    return None if value is None else svc._as_date(value, names[0])


# ══════════════════════════════════════════════════════════════════════════
# Public holidays (Public Holidays Act 36 of 1994)
# ══════════════════════════════════════════════════════════════════════════

def easter_sunday(year: int) -> date:
    """Anonymous Gregorian computus (Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def za_public_holidays(year: int) -> list:
    """Schedule 1 fixed dates, Good Friday / Family Day from Easter, and the s2(1)
    rule that a holiday falling on a Sunday makes the next Monday a holiday.
    Ad-hoc s2A declarations are not derivable and are added to the org calendar
    by hand."""
    content = _content()
    easter = easter_sunday(year)
    days = [(date(year, month, day), name) for month, day, name in content.ZA_PUBLIC_HOLIDAYS_FIXED]
    days += [(easter + timedelta(days=offset), name) for offset, name in content.ZA_PUBLIC_HOLIDAYS_EASTER]
    taken = {d for d, _n in days}
    for day, name in sorted(days):
        if day.weekday() == 6:
            monday = day + timedelta(days=1)
            if monday not in taken and monday.year == year:
                days.append((monday, f"{name} (observed)"))
                taken.add(monday)
    return [{"date": d.isoformat(), "name": n} for d, n in sorted(days)]


# ══════════════════════════════════════════════════════════════════════════
# Calculation inputs (plain JSON-safe values for PayrollContext)
# ══════════════════════════════════════════════════════════════════════════

def za_hours(db: Session, employee, period_start: date, period_end: date) -> Optional[dict]:
    """Time for the period from attendance (PayrollAttendanceRecord.hours, a
    string) on 'present' days: Sunday and ZA public-holiday hours split out,
    the rest ordinary. The platform has no approved-overtime-hours source, so
    no `overtime` is reported. No attendance rows -> None (NMW not verifiable)."""
    from app.modules.payroll.models import PayrollAttendanceRecord, PayrollHoliday

    if period_start is None or period_end is None:
        return None
    rows = (db.query(PayrollAttendanceRecord)
            .filter(PayrollAttendanceRecord.organization_id == employee.organization_id,
                    PayrollAttendanceRecord.employee_id == employee.id,
                    PayrollAttendanceRecord.date >= period_start, PayrollAttendanceRecord.date <= period_end,
                    PayrollAttendanceRecord.status == "present")
            .all())
    if not rows:
        return None
    holidays = {h.date for h in db.query(PayrollHoliday)
                .filter(PayrollHoliday.organization_id == employee.organization_id, PayrollHoliday.country == ZA,
                        PayrollHoliday.date >= period_start, PayrollHoliday.date <= period_end)}
    out = {"ordinary": Decimal("0"), "sunday": Decimal("0"), "public_holiday": Decimal("0")}
    for row in rows:
        try:
            hours = Decimal(str(row.hours).strip()) if row.hours not in (None, "") else Decimal("0")
        except InvalidOperation:
            raise BadRequestException(f"Attendance record #{row.id} has unreadable hours {row.hours!r}.")
        bucket = ("public_holiday" if row.date in holidays
                  else "sunday" if row.date.weekday() == 6 else "ordinary")
        out[bucket] += hours
    return {k: str(v) for k, v in out.items()}


def za_deduction_orders(db: Session, employee, on: date) -> Optional[list]:
    """Active ZA non-statutory deductions in force on `on`, as the plain dicts
    labour.evaluate_za_deductions reads. A rate-only order is passed without an
    amount so the engine BLOCKS it rather than guessing a base."""
    from app.modules.payroll.models import CourtOrderedDeduction as D

    rows = (db.query(D)
            .filter(D.organization_id == employee.organization_id, D.employee_id == employee.id,
                    D.jurisdiction == ZA, D.status == "active", D.start_date <= on,
                    or_(D.end_date.is_(None), D.end_date >= on))
            .order_by(D.priority.is_(None), D.priority, D.id)
            .all())
    return [{"id": r.id, "order_type": r.order_type, "authority_type": r.za_authority_type,
             "amount": None if r.fixed_deduction_amount is None else _money2(r.fixed_deduction_amount),
             "evidence_ref": r.za_evidence_ref} for r in rows] or None


def za_overrides_for(db: Session, employee, run, on: date) -> Optional[list]:
    """APPROVED, unexpired overrides for the employee in THIS run (a preview has
    no run and applies none)."""
    from app.modules.payroll.models import PayrollZaPayrollOverride as O

    if run is None or getattr(run, "id", None) is None:
        return None
    rows = (db.query(O).filter(O.organization_id == employee.organization_id, O.employee_id == employee.id,
                               O.payroll_run_id == run.id, O.status == "APPROVED", O.expires_on >= on)
            .order_by(O.id).all())
    return [{"id": r.id, "field": r.field, "before": _money2(r.before_value), "after": _money2(r.after_value),
             "reason_code": r.reason_code} for r in rows] or None


# ══════════════════════════════════════════════════════════════════════════
# Four-eyes exceptions and the approval fingerprint (ZA-016)
# ══════════════════════════════════════════════════════════════════════════

def _run_items(db: Session, run) -> list:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == ZA)
            .order_by(PayslipItem.id).all())


def _run_or_404(db: Session, organization_id: int, run_id: int, lock: bool = False):
    from app.modules.payroll.models import PayrollRun

    query = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id)
    run = (query.with_for_update() if lock else query).first()
    if run is None:
        raise NotFoundException("PayrollRun", run_id)
    return run


def za_approval_fingerprint(db: Session, run) -> dict:
    """What a ZA approval is bound to: per payslip its money columns, frozen
    context (inputs + the exact pack rows used) and per-obligation totals."""
    svc = _svc()
    payslips = []
    for item in _run_items(db, run):
        snap = item.za_calculation_snapshot or {}
        payslips.append([item.id, item.employee_id, str(item.gross_pay), str(item.net_pay),
                         str(item.total_deductions), snap.get("frozenContext"),
                         snap.get("totalsAll") or svc.za_totals_all(snap)])
    return {"fingerprint": svc._content_hash(svc._json_safe(payslips)), "payslipCount": len(payslips)}


def _tax_year_end(on: date) -> date:
    from app.modules.payroll.engine.countries import south_africa as engine

    return engine.tax_year_end(on)


def za_run_exceptions(db: Session, run) -> list:
    """The ZA-016 exceptions for a run: [{code, employeeId, key, detail, approved}]."""
    from app.modules.payroll.engine.countries import south_africa as engine
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    variable_pct = _dec_or_none(_scalar("za_four_eyes_variable_pay_pct")[0])
    found = []

    def add(code, employee_id, detail):
        found.append({"code": code, "employeeId": employee_id, "detail": detail})

    items = _run_items(db, run)
    pay_year_end = _tax_year_end(run.pay_date) if run.pay_date else None
    for item in items:
        snap = item.za_calculation_snapshot or {}
        ctx = (snap.get("frozenContext") or {}).get("ctx") or {}
        trace = snap.get("trace") or {}
        if Decimal(str(item.net_pay or 0)) < 0:
            add("NEGATIVE_NET", item.employee_id, f"net pay R{item.net_pay} is negative")
        if (trace.get("directive") or {}).get("applied"):
            add("MANUAL_DIRECTIVE", item.employee_id, "a captured SARS tax directive replaced the computed PAYE")
        for vi in ctx.get("za_variable_items") or []:
            raw = vi.get("earned_to") or vi.get("earnedTo")
            earned = date.fromisoformat(str(raw)[:10]) if raw else None
            if earned is not None and pay_year_end is not None and _tax_year_end(earned) != pay_year_end:
                add("RETRO_ACROSS_TAX_YEARS", item.employee_id,
                    f"{vi.get('component')} earned {earned.isoformat()} belongs to an earlier tax year")
                break
        basic = Decimal(str(ctx.get("basic") or 0))
        variable = Decimal(str(ctx.get("overtime") or 0)) + sum(
            (Decimal(str(v or 0)) for k, v in (ctx.get("za_components") or {}).items()
             if str(k).upper() in engine.VARIABLE_COMPONENTS and str(k).upper() != "OVERTIME"), Decimal("0"))
        if variable > 0:
            if variable_pct is None:
                add("LARGE_VARIABLE_PAY", item.employee_id,
                    f"variable pay R{variable}: no 'unusually large' threshold is configured, so every variable "
                    "payment needs a second approval")
            elif basic <= 0 or variable * 100 / basic > variable_pct:
                add("LARGE_VARIABLE_PAY", item.employee_id,
                    f"variable pay R{variable} exceeds {variable_pct}% of basic R{basic}")
        earlier = (db.query(PayslipItem.id).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
                   .filter(PayslipItem.employee_id == item.employee_id, PayslipItem.country_code == ZA,
                           PayslipItem.payroll_run_id != run.id, PayrollRun.status.in_(_COMMITTED_RUN_STATUSES),
                           PayrollRun.pay_date < run.pay_date)
                   .first())
        leaving = getattr(db.get(PayrollEmployee, item.employee_id), "date_of_leaving", None)
        if earlier is None:
            add("FIRST_OR_LAST_PAYROLL", item.employee_id, "first committed South African payroll for the employee")
        elif leaving is not None and run.period_start and run.period_end and \
                run.period_start <= leaving <= run.period_end:
            add("FIRST_OR_LAST_PAYROLL", item.employee_id, f"last payroll (leaving {leaving.isoformat()})")
        if snap.get("za_overrides_applied"):
            add("OVERRIDE_PRESENT", item.employee_id,
                f"{snap['za_overrides_applied']} manual override(s) applied to the result")

    if items:
        add("BANK_CHANGE_HISTORY_UNAVAILABLE", None,
            "the platform records no bank-detail change history, so a bank change near pay day cannot be ruled "
            "out: confirm the bank details independently")
        if run.pay_date is not None:
            from app.modules.payroll import south_africa_filing as filing

            period = f"{_tax_year_end(run.pay_date).year}-ANNUAL"
            try:
                recon = filing.build_za_reconciliation(db, run.organization_id, period)
            except (BadRequestException, LookupError, ValueError) as exc:
                recon = {"status": "IMBALANCED", "issues": [str(exc)]}
            if recon.get("status") != "READY":
                add("RECONCILIATION_IMBALANCE", None,
                    f"EMP501 {period} is {recon.get('status')} ({len(recon.get('issues') or [])} issue(s))")

    stored = (run.za_approval_fingerprint or {}).get("fingerprint")
    if stored and items:
        current = za_approval_fingerprint(db, run)["fingerprint"]
        if current != stored:
            # Keyed to the NEW payload, so approving it never covers a later change.
            add("PAYLOAD_CHANGED_AFTER_APPROVAL", None,
                f"the payslips or their frozen inputs changed since the approval of {stored[:12]} "
                f"(now {current[:12]})")
            found[-1]["key"] = f"PAYLOAD_CHANGED_AFTER_APPROVAL:{current[:16]}"

    approvals = (run.za_approval_fingerprint or {}).get("exceptions") or {}
    codes = set(_content().ZA_RUN_EXCEPTION_CODES)
    for e in found:
        assert e["code"] in codes, e["code"]
        e.setdefault("key", f"{e['code']}:{e['employeeId'] or 'RUN'}")
        e["approved"] = approvals.get(e["key"])
    return found


def list_za_run_exceptions(db: Session, organization_id: int, run_id: int) -> list:
    return za_run_exceptions(db, _run_or_404(db, organization_id, run_id))


def approve_za_run_exception(db: Session, organization_id: int, run_id: int, *, key: str, approver_id: int,
                             note: Optional[str] = None) -> dict:
    """A second person's approval of one exception. The run's preparer can never
    approve its own run's exceptions (four-eyes)."""
    run = _run_or_404(db, organization_id, run_id, lock=True)
    if _status(run) not in _OPEN_RUN_STATUSES:
        raise BadRequestException("Exceptions are approved before the run is approved.")
    if approver_id is None or approver_id == run.created_by:
        raise BadRequestException("The run's preparer cannot approve its exceptions; a second person must (ZA-016).")
    match = next((e for e in za_run_exceptions(db, run) if e["key"] == key), None)
    if match is None:
        raise NotFoundException("ZA run exception", key)
    stored = dict(run.za_approval_fingerprint or {})
    exceptions = dict(stored.get("exceptions") or {})
    exceptions[key] = {"approvedBy": approver_id, "approvedAt": datetime.utcnow().isoformat(),
                       "detail": match["detail"], "note": (note or "").strip() or None}
    stored["exceptions"] = exceptions
    run.za_approval_fingerprint = stored
    db.flush()
    return {**match, "approved": exceptions[key]}


def before_approval(db: Session, run, actor_id) -> None:
    """APPROVED gate (after the snapshot check): every exception — including a
    payload changed since a previous approval — needs its second approval; the
    new fingerprint is then stored."""
    stored = dict(run.za_approval_fingerprint or {})
    current = za_approval_fingerprint(db, run)
    open_items = [e for e in za_run_exceptions(db, run) if not e["approved"]]
    if open_items:
        listing = "; ".join(f"{e['code']} ({'employee #' + str(e['employeeId']) if e['employeeId'] else 'run'})"
                            for e in open_items)
        raise _conflict(f"South Africa: {len(open_items)} exception(s) need a second person's approval before the "
                        f"run is approved (ZA-016): {listing}")
    run.za_approval_fingerprint = {**stored, **current, "approvedBy": actor_id,
                                   "approvedAt": datetime.utcnow().isoformat()}
    db.flush()


def commit_run(db: Session, run, actor_id) -> None:
    """PAID (the commit): ETI ledger rows, directive 'applied' marking and
    override APPLIED. Idempotent: a retried commit writes nothing twice."""
    from types import SimpleNamespace

    from app.modules.payroll.models import PayrollZaEtiLedgerEntry as E, PayrollZaPayrollOverride as O

    svc = _svc()
    stored = dict(run.za_approval_fingerprint or {})
    if stored.get("fingerprint") and stored["fingerprint"] != za_approval_fingerprint(db, run)["fingerprint"]:
        raise _conflict("South Africa: the payslips changed after approval - re-approve the run before it is paid.")
    for item in _run_items(db, run):
        snap = item.za_calculation_snapshot or {}
        eti = snap.get("za_eti") or {}
        if (eti.get("status") or "").upper() == "ELIGIBLE":
            claim_month = date(run.pay_date.year, run.pay_date.month, 1)
            live = (db.query(E).filter(E.employee_id == item.employee_id, E.claim_month == claim_month,
                                       E.status != "REVERSED").first())
            if live is None:
                svc.record_za_eti_entry(db, organization_id=run.organization_id, employee_id=item.employee_id,
                                        claim_month=claim_month, eti_result=eti, payroll_run_id=run.id,
                                        payslip_item_id=item.id, actor_id=actor_id)
            elif live.payslip_item_id != item.id:
                raise _conflict(f"South Africa: ETI for employee #{item.employee_id} in {claim_month:%Y-%m} is "
                                f"already claimed by payslip #{live.payslip_item_id}.")
        svc.mark_za_directive_applied(db, item, SimpleNamespace(za_result=snap))
    (db.query(O).filter(O.payroll_run_id == run.id, O.status == "APPROVED")
     .update({O.status: "APPLIED"}, synchronize_session=False))
    stored["committedAt"] = stored.get("committedAt") or datetime.utcnow().isoformat()
    stored["committedBy"] = stored.get("committedBy") or actor_id
    run.za_approval_fingerprint = stored
    db.flush()


# ══════════════════════════════════════════════════════════════════════════
# Overrides (ZA-017)
# ══════════════════════════════════════════════════════════════════════════

def propose_za_override(db: Session, organization_id: int, run_id: int, data: dict, actor_id: Optional[int]):
    """Record a manual override of one result field. `before` is the figure on
    the run's current payslip snapshot. It counts once a second person approves
    it and lands on the run's next recalculation; if the engine then computes a
    different `before`, the calculation BLOCKS as stale."""
    from app.modules.payroll.models import PayrollZaPayrollOverride as O, PayslipItem

    svc = _svc()
    run = _run_or_404(db, organization_id, run_id)
    if _status(run) not in _OPEN_RUN_STATUSES:
        raise BadRequestException("Overrides are recorded on a run that is not yet approved.")
    employee_id = svc._field(data, "employeeId") or svc._field(data, "employee_id")
    field = svc._field(data, "field")
    if field not in _content().OVERRIDE_FIELDS:
        raise BadRequestException(f"field must be one of {', '.join(_content().OVERRIDE_FIELDS)}.")
    item = (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == ZA,
                                         PayslipItem.employee_id == employee_id).first())
    if item is None or not item.za_calculation_snapshot:
        raise BadRequestException("The employee has no calculated South African payslip in this run.")
    before = svc._money(item.za_calculation_snapshot.get(field) or "0", "before")
    after = svc._money(svc._field(data, "after"), "after")
    if after is None or after < 0:
        raise BadRequestException("after must be a non-negative amount.")
    if after == before:
        raise BadRequestException("The override does not change the computed figure.")
    reason_code = (svc._field(data, "reasonCode") or svc._field(data, "reason_code") or "").strip()
    reason = (svc._field(data, "reason") or "").strip()
    if not reason_code or not reason:
        raise BadRequestException("An override needs a reason code and a reason (ZA-017).")
    expires_on = _opt_date(data, "expiresOn", "expires_on")
    if expires_on is None:
        raise BadRequestException("An override needs an expiry date (ZA-017).")
    if expires_on < date.today():
        raise BadRequestException("The expiry date is in the past.")
    live = (db.query(O).filter(O.payroll_run_id == run.id, O.employee_id == employee_id, O.field == field,
                               O.status.in_(("PROPOSED", "APPROVED"))).first())
    if live is not None:
        raise BadRequestException(f"Override #{live.id} for {field} is already {live.status}; withdraw it first.")
    evidence = (svc._field(data, "evidenceRef") or svc._field(data, "evidence_ref") or "").strip()
    row = O(organization_id=organization_id, employee_id=employee_id, payroll_run_id=run.id,
            payslip_item_id=item.id, field=field, before_value=before, after_value=after,
            reason_code=reason_code[:40], reason=reason[:500], evidence_ref=evidence[:300] or None,
            status="PROPOSED", expires_on=expires_on, created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def _override_or_404(db: Session, organization_id: int, override_id: int):
    from app.modules.payroll.models import PayrollZaPayrollOverride as O

    row = db.query(O).filter(O.id == override_id, O.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("PayrollZaPayrollOverride", override_id)
    return row


def approve_za_override(db: Session, organization_id: int, override_id: int, approver_id: int):
    row = _override_or_404(db, organization_id, override_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Override #{row.id} is {row.status}, not PROPOSED.")
    if approver_id is None or approver_id == row.created_by_id:
        raise BadRequestException("An override must be approved by someone other than its maker (ZA-017).")
    if row.expires_on < date.today():
        row.status = "EXPIRED"
        db.flush()
        raise BadRequestException(f"Override #{row.id} expired on {row.expires_on.isoformat()}.")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", approver_id, datetime.utcnow()
    db.flush()
    return row


def withdraw_za_override(db: Session, organization_id: int, override_id: int, actor_id: Optional[int] = None):
    row = _override_or_404(db, organization_id, override_id)
    if row.status not in ("PROPOSED", "APPROVED"):
        raise BadRequestException(f"Override #{row.id} is {row.status} and can no longer be withdrawn.")
    row.status = "WITHDRAWN"
    db.flush()
    return row


def list_za_overrides(db: Session, organization_id: int, run_id: int) -> list:
    from app.modules.payroll.models import PayrollZaPayrollOverride as O

    _run_or_404(db, organization_id, run_id)
    return (db.query(O).filter(O.organization_id == organization_id, O.payroll_run_id == run_id)
            .order_by(O.id).all())


# ══════════════════════════════════════════════════════════════════════════
# Deduction orders (ZA-013)
# ══════════════════════════════════════════════════════════════════════════

def list_za_deduction_orders(db: Session, organization_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import CourtOrderedDeduction as D

    _svc()._za_employee(db, employee_id, organization_id)
    return (db.query(D).filter(D.organization_id == organization_id, D.employee_id == employee_id,
                               D.jurisdiction == ZA)
            .order_by(D.start_date.desc(), D.id.desc()).all())


def record_za_deduction_order(db: Session, organization_id: int, employee_id: int, data: dict,
                              actor_id: Optional[int] = None):
    """A ZA non-statutory deduction: a fixed amount per period, a recognised
    authority (content row za_deduction_authority_types) and its evidence."""
    from app.modules.payroll.models import CourtOrderedDeduction

    svc = _svc()
    svc._za_employee(db, employee_id, organization_id)
    authority = (svc._field(data, "authorityType") or svc._field(data, "authority_type") or "").strip().upper()
    allowed = [a.strip() for a in (_scalar("za_deduction_authority_types")[2] or "").split(",") if a.strip()]
    if authority not in allowed:
        raise BadRequestException(f"authorityType must be one of {', '.join(allowed) or '(none configured)'} "
                                  "(ZA-013).")
    evidence = (svc._field(data, "evidenceRef") or svc._field(data, "evidence_ref") or "").strip()
    if not evidence:
        raise BadRequestException("A deduction needs evidence of its authority (ZA-013).")
    order_type = (svc._field(data, "orderType") or svc._field(data, "order_type") or "").strip().upper()
    if not order_type:
        raise BadRequestException("orderType is required.")
    amount = svc._money(svc._field(data, "amount"), "amount")
    if amount is None or amount <= 0:
        raise BadRequestException("A ZA deduction needs a positive fixed amount per period.")
    start = _opt_date(data, "startDate", "start_date")
    if start is None:
        raise BadRequestException("startDate is required.")
    end = _opt_date(data, "endDate", "end_date")
    if end is not None and end < start:
        raise BadRequestException("endDate is before startDate.")
    row = CourtOrderedDeduction(
        organization_id=organization_id, employee_id=employee_id, jurisdiction=ZA, order_type=order_type[:40],
        court_reference=(svc._field(data, "reference") or None), start_date=start, end_date=end,
        priority=svc._field(data, "priority"), fixed_deduction_amount=amount,
        za_authority_type=authority, za_evidence_ref=evidence[:300], status="active", created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


# ══════════════════════════════════════════════════════════════════════════
# Corrections (spec §8)
# ══════════════════════════════════════════════════════════════════════════

def za_replay(frozen: dict):
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(_svc().za_thaw_context(frozen), frozen.get("calculationMode") or "standard")


def _correction_chain(db: Session, original) -> list:
    from app.modules.payroll.models import PayslipItem

    return [i for i in db.query(PayslipItem).filter(PayslipItem.employee_id == original.employee_id,
                                                    PayslipItem.country_code == ZA).order_by(PayslipItem.id).all()
            if ((i.za_calculation_snapshot or {}).get("correction") or {}).get("originalPayslipId") == original.id]


def create_za_correction(db: Session, organization_id: int, original_payslip_id: int, reason: str,
                         changes: dict, actor_id: Optional[int]) -> dict:
    """Append-only correction of a committed ZA payslip: replay its frozen
    context with the declared input changes and book the difference as a delta
    payslip in a linked correction run (status Paid, so EMP201 / EMP501 sums pick
    it up); the original is never edited. ETI: when the result changes, the
    month's live ledger row is REVERSED and the new ELIGIBLE result recorded
    against it. Commits on success."""
    from app.modules.payroll.models import (PayrollRun, PayrollStatus, PayrollZaEtiLedgerEntry as E,
                                            PayslipItem, PayslipStatus)

    svc = _svc()
    try:
        if not (reason or "").strip():
            raise BadRequestException("A correction needs a reason.")
        changes = dict(changes or {})
        if not changes:
            raise BadRequestException("Declare at least one corrected input.")
        undeclared = sorted(set(changes) - ZA_CORRECTABLE_INPUTS)
        if undeclared:
            raise BadRequestException(f"not correctable: {undeclared} (allowed: {sorted(ZA_CORRECTABLE_INPUTS)})")
        item = db.query(PayslipItem).filter(PayslipItem.id == original_payslip_id,
                                            PayslipItem.organization_id == organization_id).first()
        if item is None or (item.country_code or "").upper() != ZA:
            raise NotFoundException("Payslip", original_payslip_id)
        snapshot = item.za_calculation_snapshot or {}
        if snapshot.get("correction"):
            raise BadRequestException("Correct the original payslip, not a correction delta.")
        run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).with_for_update().one()
        if _status(run) not in _COMMITTED_RUN_STATUSES:
            raise BadRequestException("Only a committed (Paid) payslip is corrected; recalculate an open run instead.")
        frozen = snapshot.get("frozenContext")
        if not frozen:
            raise BadRequestException("This payslip has no frozen calculation context, so it cannot be replayed.")
        original_totals = snapshot.get("totalsAll") or svc.za_totals_all(snapshot)
        if svc.za_totals_all(za_replay(frozen)) != original_totals:
            raise BadRequestException("Replaying the frozen context does not reproduce the original payslip; "
                                      "refusing to correct on a drifted basis.")

        chain = _correction_chain(db, item)
        last = (chain[-1].za_calculation_snapshot or {}) if chain else snapshot
        basis = last.get("frozenContext") or frozen
        new_frozen = json.loads(json.dumps(basis))
        new_frozen["ctx"]["za_overrides"] = None            # overrides were approved for the original run only
        for key, value in changes.items():
            new_frozen["ctx"][key] = svc._json_safe(value)
        result = za_replay(new_frozen)
        za_result = result.za_result or {}
        new_totals = svc.za_totals_all(result)
        effective = (last.get("correction") or {}).get("totalsAll") if chain else original_totals
        deltas = {k: Decimal(new_totals[k]) - Decimal(str(effective.get(k) or 0)) for k in svc.ZA_TOTAL_KEYS}
        gross_delta = Decimal(str(new_frozen["ctx"].get("gross") or 0)) - Decimal(str(basis["ctx"].get("gross") or 0))
        other_delta = (Decimal(str(za_result.get("za_other_deductions") or 0))
                       - Decimal(str(last.get("za_other_deductions") or 0)))
        if not any(deltas.values()) and gross_delta == 0 and other_delta == 0:
            raise BadRequestException("The corrected inputs produce no change; nothing to correct.")
        employee_delta = (deltas["za_paye"] + deltas["za_uif_employee"] + deltas["za_retirement_contribution"]
                          + other_delta)

        corr_run = PayrollRun(
            organization_id=organization_id, period_label=run.period_label, period_start=run.period_start,
            period_end=run.period_end, pay_date=run.pay_date, status=PayrollStatus.PAID,
            notes=f"{ZA_CORRECTION_MARKER} corrects run {run.id} payslip {item.id}: {reason.strip()}"[:2000],
            created_by=actor_id, calculation_mode=run.calculation_mode or "standard")
        db.add(corr_run)
        db.flush()
        new_item = PayslipItem(
            organization_id=organization_id, payroll_run_id=corr_run.id, employee_id=item.employee_id,
            employee_name=item.employee_name, department=item.department, designation=item.designation,
            date_of_joining=item.date_of_joining, country_code=ZA,
            gross_pay=gross_delta, total_deductions=employee_delta, net_pay=gross_delta - employee_delta,
            **{column: deltas[key] for column, key in _ZA_DELTA_COLUMNS},
            status=PayslipStatus.PAID, notes=f"Correction delta of payslip {item.id}",
            za_calculation_snapshot=svc._json_safe({
                **za_result, "totalsAll": new_totals,
                "correction": {"originalPayslipId": item.id, "originalRunId": run.id, "correctionRunId": corr_run.id,
                               "sequence": len(chain) + 1, "reason": reason.strip(), "changes": changes,
                               "deltas": {k: str(v) for k, v in deltas.items()}, "grossDelta": str(gross_delta),
                               "totalsAll": new_totals, "actorId": actor_id},
                "frozenContext": new_frozen,
            }))
        db.add(new_item)
        db.flush()

        eti_action = None
        old_eti = last.get("za_eti") or {}
        new_eti = za_result.get("za_eti") or {}
        if deltas["za_eti_amount"] != 0 or old_eti.get("status") != new_eti.get("status"):
            claim_month = date(run.pay_date.year, run.pay_date.month, 1)
            live = (db.query(E).filter(E.employee_id == item.employee_id, E.claim_month == claim_month,
                                       E.status != "REVERSED").first())
            if live is not None:
                svc.reverse_za_eti_entry(db, live.id, actor_id=actor_id, organization_id=organization_id)
            replacement = None
            if (new_eti.get("status") or "").upper() == "ELIGIBLE":
                replacement = svc.record_za_eti_entry(
                    db, organization_id=organization_id, employee_id=item.employee_id, claim_month=claim_month,
                    eti_result=new_eti, payroll_run_id=corr_run.id, payslip_item_id=new_item.id,
                    actor_id=actor_id, reverses_id=getattr(live, "id", None))
            eti_action = {"reversedEntryId": getattr(live, "id", None),
                          "recordedEntryId": getattr(replacement, "id", None)}
        db.commit()
        return {"correctionRunId": corr_run.id, "payslipId": new_item.id, "originalPayslipId": item.id,
                "sequence": len(chain) + 1, "deltas": {k: str(v) for k, v in deltas.items()},
                "grossDelta": str(gross_delta), "totalsAll": new_totals, "eti": eti_action}
    except Exception:
        db.rollback()
        raise


def is_za_correction_run(run) -> bool:
    return bool(run is not None and (run.notes or "").startswith(ZA_CORRECTION_MARKER))
