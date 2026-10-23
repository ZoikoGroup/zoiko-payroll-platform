"""
modules/payroll/mexico_termination_service.py
---------------------------------------------
Mexico Phase 9c (docs/mexico/MEXICO_PHASE_9_PLAN.md B6, D5 / D6):

  * the termination record — the last day employed, a reason from the
    transcribed catalog (S26; empty → MX_TERMINATION_RULE_MISSING) and an
    evidence reference, recorded by one person and approved by another
    (MX_FOUR_EYES_REQUIRED). An operator never chooses a component or a tax
    treatment (MX-057): the reason decides.
  * approval sets the employee's date of leaving and generates the IMSS BAJA
    — an approved termination is the ONLY BAJA source (D6, Phase 8).
  * the FINIQUITO run — one special run for the termination: proportional
    aguinaldo (9b rule), the vacation still owed paid out with its premium
    (FiniquitoRule), the separation components the reason triggers; withheld
    by the finiquito rule (never the ordinary tariff, MX-009). Commit writes the
    PAID_OUT vacation records and marks the termination COMMITTED; a reset
    reverses both.
  * cancelling (with a reason) is possible only before a FINIQUITO run exists;
    an APPROVED termination's PENDING, never-exported BAJA is withdrawn and the
    previous date of leaving restored.
  * the ordinary run: the final period pays salary to the termination date
    (calendar-day convention; a fixed-days convention blocks — no transcribed
    proration); later periods exclude the employee.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
LIVE = ("DRAFT", "APPROVED", "COMMITTED")
SETTLING = ("APPROVED", "COMMITTED")          # the employment has ended


def _m():
    from app.modules.payroll import models as m

    return m


def _dec(value) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _audit(db, **kw):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, **kw)


def _guard(db: Session, org_id: int) -> None:
    from app.modules.payroll import mexico_filing_service

    mexico_filing_service.guard(db, org_id)


def _employee(db: Session, org_id: int, employee_id: int):
    emp = db.get(_m().PayrollEmployee, employee_id)
    if emp is None or emp.organization_id != org_id:
        raise NotFoundException(f"Employee {employee_id} not found")
    return emp


def _termination(db: Session, org_id: int, termination_id: int):
    row = db.get(_m().PayrollMxTermination, termination_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Termination {termination_id} not found")
    return row


def reasons(db: Session, org_id: int) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import termination

    _guard(db, org_id)
    rows = termination.catalog()
    return {"reasons": rows, "transcribed": bool(rows),
            "block": None if rows else {"code": "MX_TERMINATION_RULE_MISSING",
                                        "message": "the termination-reason catalog (S26) is not transcribed — no "
                                                   "termination can be recorded"}}


# ── the record ──────────────────────────────────────────────────────────────

def record_termination(db: Session, org_id: int, employee_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import termination

    _guard(db, org_id)
    m = _m()
    emp = _employee(db, org_id, employee_id)
    when = data.get("termination_date")
    if not isinstance(when, date):
        raise BadRequestException("terminationDate (the last day employed) is required")
    if emp.date_of_joining is not None and when < emp.date_of_joining:
        raise BadRequestException("the termination date is before the employee's date of joining")
    code = str(data.get("reason_code") or "").strip()
    rule = termination.reason(code)                     # BLOCKS while the catalog is empty / the code unknown
    evidence = str(data.get("evidence_ref") or "").strip()
    if not evidence:
        raise BadRequestException("A termination needs an evidence reference (the signed letter, resignation, "
                                  "award, ...)")
    T = m.PayrollMxTermination
    live = db.query(T).filter(T.employee_id == emp.id, T.status.in_(LIVE)).first()
    if live is not None:
        raise BadRequestException(f"the employee already has a {live.status} termination (#{live.id}) — cancel it "
                                  f"first")
    row = T(organization_id=org_id, employee_id=emp.id, termination_date=when, reason_code=code,
            reason_source=f"{rule.source} {rule.source_ref}"[:200], evidence_ref=evidence[:300],
            note=(data.get("note") or "").strip()[:300] or None, status="DRAFT", recorded_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="record_termination", entity_type="mx_termination", entity_id=row.id,
           new={"employeeId": emp.id, "terminationDate": when.isoformat(), "reasonCode": code})
    db.commit()
    return termination_view(db, row)


def approve_termination(db: Session, org_id: int, termination_id: int, actor_id: Optional[int]) -> dict:
    """Four-eyes; sets the date of leaving and generates the BAJA (D6)."""
    from app.modules.payroll import mexico_imss_service
    from app.modules.payroll.engine.jurisdictions.mexico import termination

    _guard(db, org_id)
    row = _termination(db, org_id, termination_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT termination can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.recorded_by_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", "a termination must be approved by someone other than its recorder",
                      org_id)
    termination.reason(row.reason_code)                 # still in the catalog
    emp = _employee(db, org_id, row.employee_id)
    row.previous_date_of_leaving = emp.date_of_leaving
    emp.date_of_leaving = row.termination_date
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.now(timezone.utc)
    db.flush()
    baja = mexico_imss_service.baja_for_termination(db, org_id, row, actor_id)
    row.baja_movement_ids = [mv.id for mv in baja["created"]]
    _audit(db, actor_id=actor_id, action="approve_termination", entity_type="mx_termination", entity_id=row.id,
           new={"status": "APPROVED", "bajaMovements": row.baja_movement_ids})
    db.commit()
    return {**termination_view(db, row), "baja": {"created": row.baja_movement_ids, "skipped": baja["skipped"]},
            "committedPeriodsAfter": committed_periods_after(db, row)}


def cancel_termination(db: Session, org_id: int, termination_id: int, reason: str, actor_id: Optional[int]) -> dict:
    """Only before a FINIQUITO run exists. An APPROVED one also withdraws its
    PENDING, never-exported BAJA and restores the previous date of leaving —
    all or nothing."""
    from app.modules.payroll import mexico_imss_service

    _guard(db, org_id)
    m = _m()
    row = _termination(db, org_id, termination_id)
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Cancelling a termination needs a reason")
    if row.status not in ("DRAFT", "APPROVED"):
        raise BadRequestException(f"A {row.status} termination cannot be cancelled"
                                  + (" — its finiquito is committed" if row.status == "COMMITTED" else ""))
    run = db.get(m.PayrollRun, row.finiquito_run_id) if row.finiquito_run_id else None
    if run is not None:
        raise BadRequestException(f"the termination has a finiquito run ({run.id}, {run.status}) — delete it first")
    moves = [db.get(m.PayrollMxImssMovement, i) for i in (row.baja_movement_ids or [])]
    live = [mv for mv in moves if mv is not None and mv.status not in ("WITHDRAWN", "VOIDED", "REJECTED")]
    sent = [mv for mv in live if mv.status != "PENDING" or mv.payload_hash is not None]
    if sent:
        raise MXBlock("MX_BAJA_ALREADY_EXPORTED",
                      f"the BAJA movement(s) {', '.join(str(mv.id) for mv in sent)} already left Zoiko — record their "
                      f"outcome in IDSE first; the termination stands", org_id)
    for mv in live:
        mexico_imss_service.withdraw_movement(db, org_id, mv, f"termination {row.id} cancelled: {text}"[:300], actor_id)
    if row.status == "APPROVED":
        emp = _employee(db, org_id, row.employee_id)
        emp.date_of_leaving = row.previous_date_of_leaving
    row.status, row.cancelled_reason, row.cancelled_by_id = "CANCELLED", text[:300], actor_id
    _audit(db, actor_id=actor_id, action="cancel_termination", entity_type="mx_termination", entity_id=row.id,
           reason=text[:300], new={"bajaWithdrawn": [mv.id for mv in live]})
    db.commit()
    return termination_view(db, row)


def committed_periods_after(db: Session, row) -> list:
    """Committed ordinary runs whose period runs past the termination date —
    paid as if employed; a correction run (9a) is the way to fix them."""
    m = _m()
    out = []
    items = (db.query(m.PayslipItem, m.PayrollRun).join(m.PayrollRun, m.PayslipItem.payroll_run_id == m.PayrollRun.id)
             .filter(m.PayslipItem.employee_id == row.employee_id, m.PayrollRun.period_end > row.termination_date))
    for item, run in items.order_by(m.PayrollRun.period_start):
        if (run.mx_run_type or "ORDINARY") == "ORDINARY" and (run.mx_approval_fingerprint or {}).get("committedAt"):
            out.append({"runId": run.id, "periodStart": run.period_start.isoformat(),
                        "periodEnd": run.period_end.isoformat()})
    return out


def termination_view(db: Session, row) -> dict:
    m = _m()
    run = db.get(m.PayrollRun, row.finiquito_run_id) if row.finiquito_run_id else None
    return {"id": row.id, "employeeId": row.employee_id, "terminationDate": row.termination_date.isoformat(),
            "reasonCode": row.reason_code, "reasonSource": row.reason_source, "evidenceRef": row.evidence_ref,
            "note": row.note, "status": row.status, "recordedById": row.recorded_by_id,
            "approvedById": row.approved_by_id, "bajaMovementIds": row.baja_movement_ids or [],
            "finiquitoRun": None if run is None else {
                "id": run.id, "status": run.status, "payDate": run.pay_date.isoformat() if run.pay_date else None,
                "committed": bool((run.mx_approval_fingerprint or {}).get("committedAt"))},
            "cancelledReason": row.cancelled_reason}


def list_terminations(db: Session, org_id: int, employee_id: int) -> list:
    _guard(db, org_id)
    emp = _employee(db, org_id, employee_id)
    T = _m().PayrollMxTermination
    return [termination_view(db, r) for r in db.query(T).filter(T.employee_id == emp.id).order_by(T.id)]


# ── effect on runs ──────────────────────────────────────────────────────────

def settling(db: Session, employee_id: int):
    """The employee's APPROVED / COMMITTED termination, or None."""
    T = _m().PayrollMxTermination
    return db.query(T).filter(T.employee_id == employee_id, T.status.in_(SETTLING)).first()


def select_for_run(db: Session, org_id: int, run, employees: list, employee_ids) -> list:
    """The shared run selection, Mexico terminations applied: a FINIQUITO run
    pays exactly its termination's employee (whatever the shared filters say);
    any other run drops an employee whose employment ended before its period.
    Returns the list unchanged when the organisation has no termination."""
    m = _m()
    T = m.PayrollMxTermination
    if getattr(run, "mx_run_type", None) == "FINIQUITO":
        row = db.query(T).filter(T.finiquito_run_id == run.id).first()
        if row is None:
            return []
        emp = db.get(m.PayrollEmployee, row.employee_id)
        return [emp] if emp is not None and (not employee_ids or emp.id in set(employee_ids)) else []
    ended = {r.employee_id for r in db.query(T).filter(T.organization_id == org_id, T.status.in_(SETTLING),
                                                       T.termination_date < run.period_start)}
    return [e for e in employees if e.id not in ended] if ended else employees


def for_run(db: Session, run):
    T = _m().PayrollMxTermination
    row = db.query(T).filter(T.finiquito_run_id == run.id).first()
    if row is None:
        raise MXBlock("MX_FINIQUITO_TERMINATION_MISSING", f"run {run.id} is not linked to a termination",
                      run.organization_id)
    return row


def create_finiquito_run(db: Session, org_id: int, termination_id: int, pay_date: date,
                         actor_id: Optional[int]) -> dict:
    """The FINIQUITO run of an APPROVED termination (period = the termination
    date), paid on `pay_date`. Atomic: if the calculation fails, nothing is
    left behind."""
    from app.modules.payroll import service

    _guard(db, org_id)
    m = _m()
    row = _termination(db, org_id, termination_id)
    if row.status != "APPROVED":
        raise BadRequestException(f"Only an APPROVED termination gets a finiquito run (this one is {row.status})")
    if row.finiquito_run_id and db.get(m.PayrollRun, row.finiquito_run_id) is not None:
        raise BadRequestException(f"the termination already has finiquito run {row.finiquito_run_id}")
    if not isinstance(pay_date, date):
        raise BadRequestException("payDate is required")
    if pay_date < row.termination_date:
        raise BadRequestException("the finiquito is paid on or after the termination date")
    run = m.PayrollRun(organization_id=org_id, period_label=f"Finiquito (termination {row.id})",
                       period_start=row.termination_date, period_end=row.termination_date, pay_date=pay_date,
                       status="Draft", created_by=actor_id, mx_run_type="FINIQUITO")
    db.add(run)
    db.flush()
    row.finiquito_run_id = run.id
    db.commit()
    run_id = run.id
    try:
        service.generate_payslips_for_run(db, run, org_id, [row.employee_id])
    except Exception:
        db.rollback()
        row = db.get(m.PayrollMxTermination, termination_id)
        row.finiquito_run_id = None
        leftover = db.get(m.PayrollRun, run_id)
        if leftover is not None:
            db.delete(leftover)
        db.commit()
        raise
    _audit(db, actor_id=actor_id, action="open_finiquito_run", entity_type="mx_termination", entity_id=row.id,
           new={"runId": run_id, "payDate": pay_date.isoformat()})
    db.commit()
    return {"runId": run_id, "terminationId": row.id, "payDate": pay_date.isoformat()}


# ── the finiquito's inputs ──────────────────────────────────────────────────

def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:                                  # 29 February → 28 February
        return d.replace(year=d.year + years, day=28)


def ledger_years(db: Session, employee_id: int, seniority: date, termination_date: date, policy: dict) -> list:
    """Every service year up to the one the termination falls in: its dates,
    the employer policy days and the live vacation records."""
    from app.modules.payroll import mexico_benefits_service as benefits
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    current = sbc.service_year(seniority, termination_date)
    rows = [r for r in benefits._rows(db, employee_id) if r.status not in ("DRAFT", "WITHDRAWN")]
    out = []
    for year in range(1, current + 1):
        mine = [r for r in rows if r.service_year == year]
        start = _add_years(seniority, year - 1)
        out.append({"service_year": year, "start": start, "end": min(_add_years(seniority, year), termination_date),
                    "complete": year < current,
                    "policy_days": sbc.policy_vacation_days(policy, year),
                    "opening": sum((_dec(r.days) for r in mine if r.kind == "OPENING"), _ZERO),
                    "taken": sum((_dec(r.days) for r in mine if r.kind == "TAKEN"), _ZERO),
                    "paid_out": sum((_dec(r.days) for r in mine if r.kind == "PAID_OUT"), _ZERO)})
    return out


def _aguinaldo_paid(db: Session, employee_id: int, year: int):
    """A committed AGUINALDO payslip of `year` for the employee, or None."""
    m = _m()
    rows = (db.query(m.PayslipItem, m.PayrollRun).join(m.PayrollRun, m.PayslipItem.payroll_run_id == m.PayrollRun.id)
            .filter(m.PayslipItem.employee_id == employee_id, m.PayrollRun.mx_run_type == "AGUINALDO",
                    m.PayrollRun.period_start == date(year, 1, 1)))
    for item, run in rows:
        if (run.mx_approval_fingerprint or {}).get("committedAt"):
            return run
    return None


def finiquito_lines(db: Session, row, employee, prof, policy: dict, content, rounder, facts: dict) -> tuple:
    """(earning lines, detail) — every rule problem reported at once."""
    from app.modules.payroll.engine.jurisdictions.mexico import special_pay, termination

    problems, lines = [], []
    daily = _dec(prof.mx_daily_salary)
    term_date = row.termination_date
    detail = {"concept": "FINIQUITO", "terminationId": row.id, "terminationDate": term_date,
              "reasonCode": row.reason_code, "reasonSource": row.reason_source, "dailySalary": daily}

    def attempt(fn):
        try:
            return fn()
        except MXBlock as exc:
            problems.extend(exc.reasons)
            return None

    # Proportional aguinaldo of the termination year (unless already paid).
    paid = _aguinaldo_paid(db, employee.id, term_date.year)
    if paid is not None:
        detail["aguinaldo"] = {"alreadyPaidByRun": paid.id}
    else:
        days = _dec(policy.get("aguinaldo_days"))
        statutory = attempt(lambda: content.amount("mx_aguinaldo_min_days"))
        if statutory is not None and days < statutory:
            problems.append(("MX_LABOR_POLICY_BELOW_FLOOR",
                             "the labour policy's aguinaldo days are below the statutory minimum"))
        ag = attempt(lambda: special_pay.aguinaldo_amount(days, daily, term_date.year, employee.date_of_joining,
                                                          term_date))
        if ag is not None:
            amount = rounder(ag["amount"])
            detail["aguinaldo"] = {"days": days, "fraction": ag["fraction"], "unrounded": ag["amount"],
                                   "amount": amount, "ruleSource": ag["rule_source"]}
            if amount:
                lines.append({"code": "MX_AGUINALDO", "kind": "AGUINALDO", "amount": amount})
    # Vacation still owed, paid out with its premium.
    years = attempt(lambda: ledger_years(db, employee.id, prof.mx_seniority_date, term_date, policy))
    owed = attempt(lambda: termination.vacation_owed(years, term_date)) if years is not None else None
    if owed is not None:
        total = sum(owed.values(), _ZERO)
        pct = _dec(policy.get("vacation_premium_pct"))
        pay = rounder(total * daily)
        premium = rounder(total * daily * pct / Decimal("100"))
        detail["vacation"] = {"owedByServiceYear": {str(k): v for k, v in sorted(owed.items())}, "days": total,
                              "payout": pay, "premiumPct": pct, "premium": premium}
        if pay:
            lines.append({"code": "MX_VACATION_PAYOUT", "kind": "VACATION_PAYOUT", "amount": pay})
        if premium:
            lines.append({"code": "MX_FINIQUITO_VACATION_PREMIUM", "kind": "VACATION_PREMIUM", "amount": premium})
    # Separation components the reason triggers.
    sep = attempt(lambda: termination.separation_lines(row.reason_code, facts))
    if sep is not None:
        detail["separation"] = [{"code": l["code"], "label": l["label"], "kind": l["kind"],
                                 "amount": rounder(l["amount"])} for l in sep]
        lines += [{"code": l["code"], "kind": l["kind"], "amount": rounder(l["amount"])} for l in sep]
    finiquito = attempt(termination.rule_source)
    detail["ruleSource"] = finiquito
    if problems:
        seen, unique = set(), []
        for p in problems:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        raise MXBlock(unique[0][0], "; ".join(f"{k}: {d}" for k, d in unique), reasons=unique)
    return lines, detail


# ── commit / reset ──────────────────────────────────────────────────────────

def on_commit(db: Session, run) -> int:
    """Inside the APPROVED transition of a FINIQUITO run: the vacation paid out
    becomes PAID_OUT records (per service year, linked to the run and payslip)
    and the termination is COMMITTED."""
    from app.modules.payroll import mexico_run_service

    if (run.mx_run_type or "ORDINARY") != "FINIQUITO":
        return 0
    m = _m()
    row = for_run(db, run)
    n = 0
    for item in mexico_run_service._mx_items(db, run):
        detail = (((item.mx_calculation_snapshot or {}).get("result") or {}).get("special") or {}).get("detail") or {}
        for year, days in ((detail.get("vacation") or {}).get("owedByServiceYear") or {}).items():
            if _dec(days) > 0:
                db.add(m.PayrollMxVacationRecord(
                    organization_id=run.organization_id, employee_id=item.employee_id, service_year=int(year),
                    kind="PAID_OUT", days=_dec(days), status="PAID", note=f"finiquito of termination {row.id}",
                    recorded_by_id=None, premium_run_id=run.id, premium_item_id=item.id))
                n += 1
    row.status = "COMMITTED"
    return n


def on_reset(db: Session, run) -> int:
    """A FINIQUITO run reset: its PAID_OUT records go, the termination is
    APPROVED again."""
    if (run.mx_run_type or "ORDINARY") != "FINIQUITO":
        return 0
    m = _m()
    V = m.PayrollMxVacationRecord
    n = 0
    for rec in db.query(V).filter(V.premium_run_id == run.id, V.kind == "PAID_OUT").all():
        db.delete(rec)
        n += 1
    row = for_run(db, run)
    row.status = "APPROVED"
    db.flush()
    return n
