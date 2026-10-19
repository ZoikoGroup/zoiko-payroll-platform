"""
modules/payroll/mexico_benefits_service.py
------------------------------------------
Mexico Phase 9b (docs/mexico/MEXICO_PHASE_9_PLAN.md B4 / B5, D3 / D4):

  * vacation records — TAKEN (with dates) and OPENING balances per service
    year (anniversary-exact from the seniority date, MX-053), recorded by one
    person and approved by another; PAID_OUT is written only by the
    termination workflow (9c). The ledger per service year: the employer
    policy days and the statutory days (content), opening, taken, paid out,
    balance. An approved TAKEN record pays its VACATION PREMIUM in the
    ordinary run whose period reaches its start date (mexico_run_service adds
    the line; this module marks it PAID at commit and reopens it on reset).
  * the AGUINALDO run — one special run per year and pay date; each payslip is
    days (labour policy, never below the statutory floor) × daily salary ×
    the transcribed proportion for part of a year, withheld by the transcribed
    special-pay rule (engine special_pay; both empty → BLOCK).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
PREMIUM_CODE = "MX_VACATION_PREMIUM"
AGUINALDO_CODE = "MX_AGUINALDO"


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


def service_year(db: Session, employee_id: int, on: date) -> Optional[int]:
    """1 = the first year from the seniority date (anniversary-exact)."""
    from app.modules.payroll import mexico_employee_service
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    prof = mexico_employee_service._profile_on(db, employee_id, on)
    if prof is None or prof.mx_seniority_date is None:
        return None
    return sbc.service_year(prof.mx_seniority_date, on)


# ── vacation records ────────────────────────────────────────────────────────

def _policy_for(db: Session, employee_id: int, on: date):
    from app.modules.payroll import mexico_employee_service, mexico_run_service

    prof = mexico_employee_service._profile_on(db, employee_id, on)
    if prof is None:
        return None
    reg = mexico_run_service._registration(db, prof, on)
    return mexico_run_service._labor_policy(db, reg, on) if reg is not None else None


def _rows(db: Session, employee_id: int, year: Optional[int] = None):
    m = _m()
    V = m.PayrollMxVacationRecord
    q = db.query(V).filter(V.employee_id == employee_id)
    if year is not None:
        q = q.filter(V.service_year == year)
    return q.order_by(V.service_year, V.id).all()


def _balance(db: Session, employee_id: int, year: int, on: date, exclude_id: Optional[int] = None) -> Optional[Decimal]:
    """Policy days for `year` + approved openings − taken − paid out (live records)."""
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    policy = _policy_for(db, employee_id, on)
    if policy is None:
        return None
    entitled = sbc.policy_vacation_days({"vacation_policy": policy.vacation_policy}, year)
    used = _ZERO
    for r in _rows(db, employee_id, year):
        if r.id == exclude_id or r.status in ("DRAFT", "WITHDRAWN"):
            continue
        used += _dec(r.days) * (-1 if r.kind == "OPENING" else 1)
    return _dec(entitled) - used


def record_vacation(db: Session, org_id: int, employee_id: int, data: dict, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    m = _m()
    emp = _employee(db, org_id, employee_id)
    kind = str(data.get("kind") or "").upper()
    if kind == "PAID_OUT":
        raise BadRequestException("Paid-out vacation days are recorded by the termination workflow (Phase 9c)")
    if kind not in ("TAKEN", "OPENING"):
        raise BadRequestException("kind must be TAKEN or OPENING")
    try:
        days = Decimal(str(data.get("days")))
    except Exception:                                  # noqa: BLE001
        raise BadRequestException("days must be a number")
    if days <= 0:
        raise BadRequestException("days must be more than zero")
    start = data.get("start_date")
    end = data.get("end_date")
    on = start if isinstance(start, date) else date.today()
    current = service_year(db, emp.id, on)
    if current is None:
        raise MXBlock("MX_SENIORITY_DATE_MISSING", "the employee has no Mexican profile with a seniority date", org_id)
    year = int(data.get("service_year") or current)
    if kind == "TAKEN":
        if not isinstance(start, date) or not isinstance(end, date) or end < start:
            raise BadRequestException("Vacation taken needs a start and an end date (end on or after start)")
        if year > current:
            raise BadRequestException(f"service year {year} has not started on {start.isoformat()} "
                                      f"(the employee is in service year {current})")
    elif not (data.get("note") or "").strip():
        raise BadRequestException("An opening balance needs a note (where the figure comes from)")
    row = m.PayrollMxVacationRecord(
        organization_id=org_id, employee_id=emp.id, service_year=year, kind=kind, days=days,
        start_date=start if kind == "TAKEN" else None, end_date=end if kind == "TAKEN" else None, status="DRAFT",
        note=(data.get("note") or "").strip()[:300] or None, recorded_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="record_vacation", entity_type="mx_vacation_record", entity_id=row.id,
           new={"employeeId": emp.id, "kind": kind, "days": str(days), "serviceYear": year})
    db.commit()
    return vacation_view(row)


def _record(db: Session, org_id: int, record_id: int):
    row = db.get(_m().PayrollMxVacationRecord, record_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Vacation record {record_id} not found")
    return row


def approve_vacation(db: Session, org_id: int, record_id: int, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    row = _record(db, org_id, record_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT record can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.recorded_by_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", "a vacation record must be approved by someone other than its recorder",
                      org_id)
    if row.kind == "TAKEN":
        balance = _balance(db, row.employee_id, row.service_year, row.start_date or date.today(), exclude_id=row.id)
        if balance is None:
            raise MXBlock("MX_LABOR_POLICY_MISSING", "no employer labour policy is in force for the vacation dates",
                          org_id)
        if _dec(row.days) > balance:
            raise MXBlock("MX_VACATION_BALANCE_EXCEEDED",
                          f"{row.days} day(s) exceed the service-year {row.service_year} balance of {balance}", org_id)
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.now(timezone.utc)
    _audit(db, actor_id=actor_id, action="approve_vacation", entity_type="mx_vacation_record", entity_id=row.id,
           new={"status": "APPROVED"})
    db.commit()
    return vacation_view(row)


def withdraw_vacation(db: Session, org_id: int, record_id: int, reason: str, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    row = _record(db, org_id, record_id)
    if row.status not in ("DRAFT", "APPROVED"):
        raise BadRequestException(f"A {row.status} record cannot be withdrawn (its premium was paid — reset that run)")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Withdrawing a vacation record needs a reason")
    row.status, row.withdrawn_reason = "WITHDRAWN", text[:300]
    _audit(db, actor_id=actor_id, action="withdraw_vacation", entity_type="mx_vacation_record", entity_id=row.id,
           reason=text[:300])
    db.commit()
    return vacation_view(row)


def vacation_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "serviceYear": row.service_year, "kind": row.kind,
            "days": str(row.days), "startDate": row.start_date.isoformat() if row.start_date else None,
            "endDate": row.end_date.isoformat() if row.end_date else None, "status": row.status, "note": row.note,
            "recordedById": row.recorded_by_id, "approvedById": row.approved_by_id,
            "premiumRunId": row.premium_run_id, "premiumItemId": row.premium_item_id,
            "withdrawnReason": row.withdrawn_reason}


def ledger(db: Session, org_id: int, employee_id: int, on: Optional[date] = None) -> dict:
    """Per service year: policy and statutory entitlement, opening, taken,
    paid out, balance — and every record."""
    from app.modules.payroll import mexico_employer_service, service
    from app.modules.payroll.engine.jurisdictions.mexico import sbc
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content

    _guard(db, org_id)
    emp = _employee(db, org_id, employee_id)
    on = on or date.today()
    current = service_year(db, emp.id, on)
    policy = _policy_for(db, emp.id, on)
    pack = mexico_employer_service._active_national_pack(db, on)
    content = Content(*service.pack_rows_for_golden(db, pack, on)) if pack is not None else None
    rows = _rows(db, emp.id)
    years = sorted({r.service_year for r in rows} | ({current} if current else set()))
    out = []
    for year in years:
        live = [r for r in rows if r.service_year == year and r.status not in ("DRAFT", "WITHDRAWN")]
        opening = sum((_dec(r.days) for r in live if r.kind == "OPENING"), _ZERO)
        taken = sum((_dec(r.days) for r in live if r.kind == "TAKEN"), _ZERO)
        paid_out = sum((_dec(r.days) for r in live if r.kind == "PAID_OUT"), _ZERO)
        policy_days = (_dec(sbc.policy_vacation_days({"vacation_policy": policy.vacation_policy}, year))
                       if policy is not None else None)
        try:
            statutory = str(content.vacation_days(year)) if content is not None else None
        except MXBlock:
            statutory = None                            # the statutory table is not transcribed
        out.append({"serviceYear": year, "policyDays": None if policy_days is None else str(policy_days),
                    "statutoryDays": statutory, "opening": str(opening), "taken": str(taken),
                    "paidOut": str(paid_out),
                    "balance": None if policy_days is None else str(policy_days + opening - taken - paid_out)})
    return {"employeeId": emp.id, "on": on.isoformat(), "currentServiceYear": current, "years": out,
            "records": [vacation_view(r) for r in rows]}


# ── vacation premium in the ordinary run ────────────────────────────────────

def pending_premiums(db: Session, employee_id: int, period_end: date) -> list:
    """Approved TAKEN records whose premium is still unpaid and whose vacation
    starts on or before the period end — paid in this run."""
    m = _m()
    V = m.PayrollMxVacationRecord
    return (db.query(V).filter(V.employee_id == employee_id, V.kind == "TAKEN", V.status == "APPROVED",
                               V.start_date <= period_end).order_by(V.id).all())


def premium_records(db: Session, run, employee_id: int, period_end: date) -> list:
    """Which vacation records this calculation pays the premium of:
    a preview or an uncommitted ordinary run — the pending ones; a committed
    ordinary run — the ones it paid (so approving a later record never changes
    a committed run); a correction run — the ones its replaced payslips paid;
    any other run type — none."""
    m = _m()
    V = m.PayrollMxVacationRecord
    run_type = (getattr(run, "mx_run_type", None) or "ORDINARY") if run is not None else "ORDINARY"
    if run_type == "CORRECTION":
        from app.modules.payroll import mexico_correction_service

        replaced = mexico_correction_service.replaced_chain(db, run)
        return (db.query(V).filter(V.employee_id == employee_id, V.premium_item_id.in_(replaced or {-1}))
                .order_by(V.id).all())
    if run_type != "ORDINARY":
        return []
    if run is not None and (run.mx_approval_fingerprint or {}).get("committedAt"):
        return db.query(V).filter(V.premium_run_id == run.id, V.employee_id == employee_id).order_by(V.id).all()
    return pending_premiums(db, employee_id, period_end)


def premium_lines(db: Session, run, employee_id: int, period_end: date, daily_salary: Decimal, policy) -> list:
    """One VACATION_PREMIUM line per record: days × daily salary × the
    employer policy premium % (never below the statutory floor — the policy's
    floor check, MX-051). Its exemption and withholding are the special-pay
    rule's (engine special_pay)."""
    if policy is None:
        return []
    pct = _dec((policy or {}).get("vacation_premium_pct"))
    return [{"code": f"{PREMIUM_CODE}:{r.id}", "kind": "VACATION_PREMIUM",
             "amount": _dec(r.days) * daily_salary * pct / Decimal("100")}
            for r in premium_records(db, run, employee_id, period_end)]


def on_commit(db: Session, run) -> int:
    """Inside the APPROVED transition of an ORDINARY run: every premium line
    paid marks its record PAID (linked to the run and payslip)."""
    from app.modules.payroll import mexico_run_service

    if (run.mx_run_type or "ORDINARY") != "ORDINARY":
        return 0
    m = _m()
    n = 0
    for item in mexico_run_service._mx_items(db, run):
        res = (item.mx_calculation_snapshot or {}).get("result") or {}
        for concept in res.get("concepts") or []:
            code = str(concept.get("code") or "")
            if concept.get("kind") == "VACATION_PREMIUM" and code.startswith(PREMIUM_CODE + ":"):
                row = db.get(m.PayrollMxVacationRecord, int(code.split(":", 1)[1]))
                if row is not None and row.status == "APPROVED":
                    row.status, row.premium_run_id, row.premium_item_id = "PAID", run.id, item.id
                    n += 1
    return n


def on_reset(db: Session, run) -> int:
    m = _m()
    n = 0
    for row in db.query(m.PayrollMxVacationRecord).filter(m.PayrollMxVacationRecord.premium_run_id == run.id):
        row.status, row.premium_run_id, row.premium_item_id = "APPROVED", None, None
        n += 1
    return n


# ── the aguinaldo run ───────────────────────────────────────────────────────

def year_joiners(db: Session, org_id: int, run, employee_ids, already: set) -> list:
    """Active Mexican employees who joined within the aguinaldo year (after its
    first day) — the shared selection keeps only those employed by the period
    start; a mid-year joiner is owed the proportion for the part of the year."""
    from app.modules.payroll.models import EmployeeStatus

    m = _m()
    E = m.PayrollEmployee
    q = db.query(E).filter(E.organization_id == org_id, E.status == EmployeeStatus.ACTIVE, E.country_code == "MX",
                           E.date_of_joining > run.period_start, E.date_of_joining <= run.period_end)
    if employee_ids:
        q = q.filter(E.id.in_(employee_ids))
    return [e for e in q.order_by(E.id).all() if e.id not in already]


def create_aguinaldo_run(db: Session, org_id: int, year: int, pay_date: date, employee_ids: Optional[list],
                         actor_id: Optional[int]) -> dict:
    """An AGUINALDO run for `year` (period 1 Jan – 31 Dec), paid on `pay_date`.
    Atomic: if the calculation fails, nothing is left behind."""
    from app.modules.payroll import service

    _guard(db, org_id)
    m = _m()
    if not isinstance(pay_date, date):
        raise BadRequestException("payDate is required")
    if pay_date.year != year:
        raise BadRequestException("the aguinaldo of a year is paid within that year")
    existing = (db.query(m.PayrollRun).filter(m.PayrollRun.organization_id == org_id,
                                              m.PayrollRun.mx_run_type == "AGUINALDO",
                                              m.PayrollRun.period_start == date(year, 1, 1)).first())
    if existing is not None:
        raise BadRequestException(f"an aguinaldo run for {year} already exists (run {existing.id})")
    q = db.query(m.PayrollEmployee).filter(m.PayrollEmployee.organization_id == org_id,
                                           m.PayrollEmployee.country_code == "MX")
    employees = [e for e in q if (not employee_ids or e.id in {int(i) for i in employee_ids})
                 and (e.date_of_joining is None or e.date_of_joining <= date(year, 12, 31))
                 and (e.date_of_leaving is None or e.date_of_leaving >= date(year, 1, 1))]
    if not employees:
        raise BadRequestException(f"no Mexican employee was employed in {year}")
    run = m.PayrollRun(organization_id=org_id, period_label=f"Aguinaldo {year}", period_start=date(year, 1, 1),
                       period_end=date(year, 12, 31), pay_date=pay_date, status="Draft", created_by=actor_id,
                       mx_run_type="AGUINALDO")
    db.add(run)
    db.commit()
    run_id = run.id
    try:
        service.generate_payslips_for_run(db, run, org_id, [e.id for e in employees])
    except Exception:
        db.rollback()
        leftover = db.get(m.PayrollRun, run_id)
        if leftover is not None:
            db.delete(leftover)
        db.commit()
        raise
    _audit(db, actor_id=actor_id, action="open_aguinaldo_run", entity_type="mx_aguinaldo_run", entity_id=run_id,
           new={"year": year, "payDate": pay_date.isoformat(), "employees": [e.id for e in employees]})
    db.commit()
    return {"runId": run_id, "year": year, "payDate": pay_date.isoformat(), "employees": [e.id for e in employees]}
