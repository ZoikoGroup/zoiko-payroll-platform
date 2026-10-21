"""
modules/payroll/mexico_ptu_service.py
-------------------------------------
Mexico Phase 9d (docs/mexico/MEXICO_PHASE_9D_PLAN.md, D1–D10): PTU.

  * the CYCLE — one per legal employer and fiscal year (D1): the distributable
    amount the employer enters with an evidence reference (never derived from
    payroll, MX-054), approved by a second person (D2). Status:
    DRAFT → AMOUNT_APPROVED → ALLOCATED → APPROVED → DISTRIBUTED / CANCELLED.
  * operator EXCLUSIONS — only a reason from the transcribed catalog, with
    evidence, approved by a second person (D6).
  * the ALLOCATION — the qualifying facts of every worker the employer paid in
    the fiscal year, from COMMITTED runs only (a payslip superseded by a
    committed correction is replaced by the correction, 9a; a finiquito's lines
    are kept apart), allocated by the transcribed rule (engine ptu.py, D4 /
    D5). Inputs are frozen by fingerprint; approval (a second person) re-checks
    it and blocks if a committed change has made it stale (D3).
  * the PTU RUN — one special run per cycle paying each eligible worker's final
    amount, leavers included (D7); never in ordinary pay or accumulators
    (MX-056). Commit links each allocation to its payslip and marks the cycle
    DISTRIBUTED; a reset reverses it.
  * the payment DEADLINE — from the rule (S21); none → unsourced (D8).
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
LIVE = ("DRAFT", "AMOUNT_APPROVED", "ALLOCATED", "APPROVED", "DISTRIBUTED")
PTU_CODE = "MX_PTU"


def _today() -> date:
    return date.today()


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


def _four_eyes(actor_id, other_id, what: str, org_id: int) -> None:
    if actor_id is not None and actor_id == other_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", f"{what} must be approved by someone other than its recorder", org_id)


def _cycle(db: Session, org_id: int, cycle_id: int):
    row = db.get(_m().PayrollMxPtuCycle, cycle_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"PTU cycle {cycle_id} not found")
    return row


def exclusion_reasons(db: Session, org_id: int) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import ptu

    _guard(db, org_id)
    rows = ptu.exclusion_catalog()
    return {"reasons": rows, "transcribed": bool(rows),
            "block": None if rows else {"code": "MX_PTU_EXCLUSION_RULE_MISSING",
                                        "message": "the PTU exclusion catalog (S26) is not transcribed — no operator "
                                                   "exclusion can be recorded"}}


# ── the cycle ───────────────────────────────────────────────────────────────

def create_cycle(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    m = _m()
    try:
        employer_id = int(data.get("employer_profile_id"))
        year = int(data.get("fiscal_year"))
    except (TypeError, ValueError):
        raise BadRequestException("employerId and fiscalYear are required")
    employer = db.get(m.PayrollMxEmployerProfile, employer_id)
    if employer is None or employer.organization_id != org_id or employer.previous_version_id is not None:
        raise NotFoundException(f"Legal employer {employer_id} not found")
    if year >= _today().year:
        raise BadRequestException("PTU is shared for a fiscal year that has ended")
    try:
        amount = Decimal(str(data.get("distributable_amount")))
    except Exception:                                   # noqa: BLE001
        raise BadRequestException("distributableAmount must be a number")
    if amount <= 0:
        raise BadRequestException("the distributable amount must be more than zero")
    evidence = str(data.get("evidence_ref") or "").strip()
    if not evidence:
        raise BadRequestException("The distributable amount needs an evidence reference (the employer's annual "
                                  "declaration)")
    C = m.PayrollMxPtuCycle
    live = db.query(C).filter(C.employer_profile_id == employer_id, C.fiscal_year == year, C.status.in_(LIVE)).first()
    if live is not None:
        raise BadRequestException(f"a {live.status} PTU cycle (#{live.id}) already exists for this employer and year")
    row = C(organization_id=org_id, employer_profile_id=employer_id, fiscal_year=year, distributable_amount=amount,
            evidence_ref=evidence[:300], note=(data.get("note") or "").strip()[:300] or None, status="DRAFT",
            recorded_by_id=actor_id, operator_exclusions=[])
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create_ptu_cycle", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"employerId": employer_id, "fiscalYear": year, "amount": str(amount)})
    db.commit()
    return cycle_view(db, row)


def approve_amount(db: Session, org_id: int, cycle_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import ptu

    _guard(db, org_id)
    row = _cycle(db, org_id, cycle_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT cycle's amount can be approved (this one is {row.status})")
    _four_eyes(actor_id, row.recorded_by_id, "the distributable amount", org_id)
    try:
        row.payment_deadline = ptu.payment_deadline(row.fiscal_year, {"id": row.employer_profile_id})
        row.deadline_rule_ref = ptu.rule_source()
    except MXBlock:
        row.payment_deadline, row.deadline_rule_ref = None, "unsourced — the PTU payment window (S21) is not transcribed"
    row.status, row.approved_by_id, row.amount_approved_at = "AMOUNT_APPROVED", actor_id, datetime.now(timezone.utc)
    _audit(db, actor_id=actor_id, action="approve_ptu_amount", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"status": row.status})
    db.commit()
    return cycle_view(db, row)


def cancel_cycle(db: Session, org_id: int, cycle_id: int, reason: str, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    m = _m()
    row = _cycle(db, org_id, cycle_id)
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Cancelling a PTU cycle needs a reason")
    if row.status in ("DISTRIBUTED", "CANCELLED"):
        raise BadRequestException(f"A {row.status} PTU cycle cannot be cancelled")
    run = db.get(m.PayrollRun, row.ptu_run_id) if row.ptu_run_id else None
    if run is not None:
        raise BadRequestException(f"the cycle has a PTU run ({run.id}, {run.status}) — delete it first")
    row.status, row.cancelled_reason = "CANCELLED", text[:300]
    _audit(db, actor_id=actor_id, action="cancel_ptu_cycle", entity_type="mx_ptu_cycle", entity_id=row.id,
           reason=text[:300])
    db.commit()
    return cycle_view(db, row)


# ── operator exclusions ─────────────────────────────────────────────────────

def record_exclusion(db: Session, org_id: int, cycle_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import ptu

    _guard(db, org_id)
    row = _cycle(db, org_id, cycle_id)
    if row.status != "AMOUNT_APPROVED":
        raise BadRequestException("Exclusions are recorded after the amount is approved and before allocation "
                                  f"(this cycle is {row.status})")
    code = str(data.get("reason_code") or "").strip()
    ptu.exclusion_reason(code)                          # BLOCKS while the catalog is empty / the code unknown
    evidence = str(data.get("evidence_ref") or "").strip()
    if not evidence:
        raise BadRequestException("An exclusion needs an evidence reference")
    try:
        employee_id = int(data.get("employee_id"))
    except (TypeError, ValueError):
        raise BadRequestException("employeeId is required")
    emp = db.get(_m().PayrollEmployee, employee_id)
    if emp is None or emp.organization_id != org_id:
        raise NotFoundException(f"Employee {employee_id} not found")
    current = copy.deepcopy(row.operator_exclusions or [])
    if any(e["employeeId"] == employee_id for e in current):
        raise BadRequestException("the worker already has an exclusion in this cycle")
    current.append({"employeeId": employee_id, "reason": code, "evidenceRef": evidence[:300],
                    "recordedById": actor_id, "approvedById": None})
    row.operator_exclusions = current
    _audit(db, actor_id=actor_id, action="record_ptu_exclusion", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"employeeId": employee_id, "reason": code})
    db.commit()
    return cycle_view(db, row)


def approve_exclusion(db: Session, org_id: int, cycle_id: int, employee_id: int, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    row = _cycle(db, org_id, cycle_id)
    if row.status != "AMOUNT_APPROVED":
        raise BadRequestException(f"Exclusions are approved before allocation (this cycle is {row.status})")
    current = copy.deepcopy(row.operator_exclusions or [])
    entry = next((e for e in current if e["employeeId"] == employee_id), None)
    if entry is None:
        raise NotFoundException(f"No exclusion for employee {employee_id} in this cycle")
    _four_eyes(actor_id, entry["recordedById"], "a PTU exclusion", org_id)
    entry["approvedById"] = actor_id
    row.operator_exclusions = current
    _audit(db, actor_id=actor_id, action="approve_ptu_exclusion", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"employeeId": employee_id})
    db.commit()
    return cycle_view(db, row)


# ── qualifying facts (committed runs only) ──────────────────────────────────

def _committed(run) -> bool:
    return bool((run.mx_approval_fingerprint or {}).get("committedAt"))


def qualifying_facts(db: Session, row) -> list:
    """Per worker the employer paid in the fiscal year: days and salary by
    concept kind from committed ORDINARY / CORRECTION payslips (a payslip a
    committed correction supersedes is left out — its correction counts), and
    the finiquito's lines apart. Sorted by employee."""
    from app.modules.payroll import mexico_filing_service

    m = _m()
    year = row.fiscal_year
    superseded = {c.original_item_id for c in db.query(m.PayrollMxRunCorrection)
                  .filter(m.PayrollMxRunCorrection.status == "COMMITTED")}
    items = (db.query(m.PayslipItem, m.PayrollRun).join(m.PayrollRun, m.PayslipItem.payroll_run_id == m.PayrollRun.id)
             .filter(m.PayslipItem.organization_id == row.organization_id, m.PayslipItem.country_code == "MX",
                     m.PayrollRun.period_start >= date(year, 1, 1), m.PayrollRun.period_start <= date(year, 12, 31))
             .order_by(m.PayslipItem.employee_id, m.PayrollRun.period_start, m.PayslipItem.id).all())
    workers = {}
    for item, run in items:
        kind = run.mx_run_type or "ORDINARY"
        if kind not in ("ORDINARY", "CORRECTION", "FINIQUITO") or not _committed(run) or item.id in superseded:
            continue
        reg = mexico_filing_service.registration_for(db, item.employee_id, run.period_end)
        if reg is None or reg.employer_profile_id != row.employer_profile_id:
            continue
        res = (item.mx_calculation_snapshot or {}).get("result") or {}
        w = workers.setdefault(item.employee_id, {"employee_id": item.employee_id, "days": _ZERO,
                                                  "salary_by_kind": {}, "finiquito_by_kind": {}})
        bucket = w["finiquito_by_kind"] if kind == "FINIQUITO" else w["salary_by_kind"]
        if kind != "FINIQUITO":
            w["days"] += _dec(res.get("days_paid"))
        for c in res.get("concepts") or []:
            key = str(c.get("kind") or "OTHER")
            bucket[key] = bucket.get(key, _ZERO) + _dec(c.get("gross"))
            if c.get("ptu") is True:
                bucket["PTU_WAGE_BASE"] = bucket.get("PTU_WAGE_BASE", _ZERO) + _dec(c.get("gross"))
    out = []
    excluded = {e["employeeId"]: e["reason"] for e in (row.operator_exclusions or []) if e.get("approvedById")}
    for employee_id in sorted(workers):
        emp = db.get(m.PayrollEmployee, employee_id)
        out.append({**workers[employee_id], "date_of_joining": emp.date_of_joining if emp else None,
                    "date_of_leaving": emp.date_of_leaving if emp else None,
                    "operator_exclusion": excluded.get(employee_id)})
    return out


def _fingerprint(row, facts: list) -> str:
    from app.modules.payroll import mexico_run_service

    return mexico_run_service._hash({"pool": row.distributable_amount, "year": row.fiscal_year,
                                     "employer": row.employer_profile_id, "workers": facts})


# ── the allocation ──────────────────────────────────────────────────────────

def allocate(db: Session, org_id: int, cycle_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import ptu

    _guard(db, org_id)
    m = _m()
    row = _cycle(db, org_id, cycle_id)
    if row.status not in ("AMOUNT_APPROVED", "ALLOCATED"):
        raise BadRequestException(f"A {row.status} cycle cannot be allocated")
    pending = [e["employeeId"] for e in (row.operator_exclusions or []) if not e.get("approvedById")]
    if pending:
        raise MXBlock("MX_PTU_EXCLUSION_PENDING",
                      f"exclusion(s) for employee(s) {pending} are not approved yet — approve or remove them first", org_id)
    facts = qualifying_facts(db, row)
    if not facts:
        raise BadRequestException(f"the employer has no committed Mexican payslip in {row.fiscal_year}")
    result = ptu.allocate(_dec(row.distributable_amount), facts, row.fiscal_year)
    A = m.PayrollMxPtuAllocation
    db.query(A).filter(A.cycle_id == row.id).delete(synchronize_session=False)
    by_id = {f["employee_id"]: f for f in facts}
    excl = {e["employeeId"]: e for e in (row.operator_exclusions or [])}
    for r in result["workers"]:
        f, e = by_id[r["employee_id"]], excl.get(r["employee_id"]) or {}
        db.add(A(organization_id=org_id, cycle_id=row.id, employee_id=r["employee_id"], eligible=r["eligible"],
                 exclusion_reason=r["exclusion_reason"], exclusion_evidence_ref=e.get("evidenceRef"),
                 exclusion_approved_by_id=e.get("approvedById"), qualifying_days=f["days"],
                 qualifying_salary=f["salary_by_kind"].get("PTU_WAGE_BASE", _ZERO),
                 salary_by_kind=_plain(f["salary_by_kind"]), days_share=r["days_share"],
                 salary_share=r["salary_share"], cap_reference=_plain(r["cap_reference"]),
                 cap_applied=r["cap_applied"], final_amount=r["final_amount"], rule_source=result["rule_source"]))
    row.status, row.allocated_by_id, row.allocated_at = "ALLOCATED", actor_id, datetime.now(timezone.utc)
    row.allocation_fingerprint, row.allocation_residue = _fingerprint(row, facts), result["residue"]
    row.rule_source = result["rule_source"]
    _audit(db, actor_id=actor_id, action="allocate_ptu", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"workers": len(facts), "residue": str(result["residue"])})
    db.commit()
    return cycle_view(db, row)


def approve_allocation(db: Session, org_id: int, cycle_id: int, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    row = _cycle(db, org_id, cycle_id)
    if row.status != "ALLOCATED":
        raise BadRequestException(f"Only an ALLOCATED cycle can be approved (this one is {row.status})")
    _four_eyes(actor_id, row.allocated_by_id, "the PTU allocation", org_id)
    if _fingerprint(row, qualifying_facts(db, row)) != row.allocation_fingerprint:
        raise MXBlock("MX_PTU_ALLOCATION_STALE",
                      "a committed change to the fiscal year (or an exclusion) changed the qualifying facts since the "
                      "allocation — allocate again", org_id)
    row.status, row.allocation_approved_by_id = "APPROVED", actor_id
    _audit(db, actor_id=actor_id, action="approve_ptu_allocation", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"status": "APPROVED"})
    db.commit()
    return cycle_view(db, row)


def _plain(value):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service._plain(value)


# ── the PTU run ─────────────────────────────────────────────────────────────

def _payable(db: Session, row) -> list:
    A = _m().PayrollMxPtuAllocation
    return (db.query(A).filter(A.cycle_id == row.id, A.eligible.is_(True), A.final_amount > 0)
            .order_by(A.employee_id).all())


def create_ptu_run(db: Session, org_id: int, cycle_id: int, pay_date: date, actor_id: Optional[int]) -> dict:
    """The PTU run of an APPROVED cycle (period = the fiscal year), paid on
    `pay_date`. Atomic: if the calculation fails, nothing is left behind."""
    from app.modules.payroll import service

    _guard(db, org_id)
    m = _m()
    row = _cycle(db, org_id, cycle_id)
    if row.status != "APPROVED":
        raise BadRequestException(f"Only an APPROVED cycle gets a PTU run (this one is {row.status})")
    if row.ptu_run_id and db.get(m.PayrollRun, row.ptu_run_id) is not None:
        raise BadRequestException(f"the cycle already has PTU run {row.ptu_run_id}")
    if not isinstance(pay_date, date):
        raise BadRequestException("payDate is required")
    if pay_date.year <= row.fiscal_year:
        raise BadRequestException("PTU of a fiscal year is paid after that year ends")
    payable = _payable(db, row)
    if not payable:
        raise BadRequestException("no eligible worker has an amount to pay")
    run = m.PayrollRun(organization_id=org_id, period_label=f"PTU {row.fiscal_year} (cycle {row.id})",
                       period_start=date(row.fiscal_year, 1, 1), period_end=date(row.fiscal_year, 12, 31),
                       pay_date=pay_date, status="Draft", created_by=actor_id, mx_run_type="PTU")
    db.add(run)
    db.flush()
    row.ptu_run_id = run.id
    db.commit()
    run_id = run.id
    try:
        service.generate_payslips_for_run(db, run, org_id, [a.employee_id for a in payable])
    except Exception:
        db.rollback()
        row = db.get(m.PayrollMxPtuCycle, cycle_id)
        row.ptu_run_id = None
        leftover = db.get(m.PayrollRun, run_id)
        if leftover is not None:
            db.delete(leftover)
        db.commit()
        raise
    _audit(db, actor_id=actor_id, action="open_ptu_run", entity_type="mx_ptu_cycle", entity_id=row.id,
           new={"runId": run_id, "payDate": pay_date.isoformat()})
    db.commit()
    return {"runId": run_id, "cycleId": row.id, "payDate": pay_date.isoformat(), "employees": len(payable)}


def for_run(db: Session, run):
    C = _m().PayrollMxPtuCycle
    row = db.query(C).filter(C.ptu_run_id == run.id).first()
    if row is None:
        raise MXBlock("MX_PTU_CYCLE_MISSING", f"run {run.id} is not linked to a PTU cycle", run.organization_id)
    return row


def select_for_run(db: Session, org_id: int, run, employee_ids) -> list:
    """A PTU run pays exactly its cycle's eligible workers with an amount,
    whatever the shared filters say (a leaver keeps the right, 9c)."""
    m = _m()
    C = m.PayrollMxPtuCycle
    row = db.query(C).filter(C.ptu_run_id == run.id).first()
    if row is None:
        return []
    wanted = set(employee_ids or [])
    out = []
    for a in _payable(db, row):
        emp = db.get(m.PayrollEmployee, a.employee_id)
        if emp is not None and (not wanted or emp.id in wanted):
            out.append(emp)
    return out


def allocation_for(db: Session, run, employee_id: int):
    A = _m().PayrollMxPtuAllocation
    row = for_run(db, run)
    a = db.query(A).filter(A.cycle_id == row.id, A.employee_id == employee_id).first()
    if a is None or not a.eligible or _dec(a.final_amount) <= 0:
        raise MXBlock("MX_PTU_ALLOCATION_MISSING", f"employee {employee_id} has no PTU to pay in cycle {row.id}",
                      run.organization_id)
    return row, a


def on_commit(db: Session, run) -> int:
    """Inside the APPROVED transition of a PTU run: each allocation is linked
    to its payslip; the cycle is DISTRIBUTED."""
    from app.modules.payroll import mexico_run_service

    if (run.mx_run_type or "ORDINARY") != "PTU":
        return 0
    A = _m().PayrollMxPtuAllocation
    row = for_run(db, run)
    n = 0
    for item in mexico_run_service._mx_items(db, run):
        a = db.query(A).filter(A.cycle_id == row.id, A.employee_id == item.employee_id).first()
        if a is not None:
            a.payslip_item_id = item.id
            n += 1
    row.status = "DISTRIBUTED"
    return n


def on_reset(db: Session, run) -> int:
    if (run.mx_run_type or "ORDINARY") != "PTU":
        return 0
    A = _m().PayrollMxPtuAllocation
    row = for_run(db, run)
    n = 0
    for a in db.query(A).filter(A.cycle_id == row.id, A.payslip_item_id.isnot(None)):
        a.payslip_item_id = None
        n += 1
    row.status = "APPROVED"
    db.flush()
    return n


# ── views ───────────────────────────────────────────────────────────────────

def allocation_view(a) -> dict:
    return {"employeeId": a.employee_id, "eligible": a.eligible, "exclusionReason": a.exclusion_reason,
            "exclusionEvidenceRef": a.exclusion_evidence_ref, "qualifyingDays": str(a.qualifying_days),
            "qualifyingSalary": str(a.qualifying_salary), "salaryByKind": a.salary_by_kind,
            "daysShare": str(a.days_share), "salaryShare": str(a.salary_share), "capReference": a.cap_reference,
            "capApplied": a.cap_applied, "finalAmount": str(a.final_amount), "payslipItemId": a.payslip_item_id}


def cycle_view(db: Session, row) -> dict:
    m = _m()
    run = db.get(m.PayrollRun, row.ptu_run_id) if row.ptu_run_id else None
    A = m.PayrollMxPtuAllocation
    allocations = db.query(A).filter(A.cycle_id == row.id).order_by(A.employee_id).all()
    return {"id": row.id, "employerId": row.employer_profile_id, "fiscalYear": row.fiscal_year,
            "distributableAmount": str(row.distributable_amount), "evidenceRef": row.evidence_ref, "note": row.note,
            "status": row.status, "recordedById": row.recorded_by_id, "approvedById": row.approved_by_id,
            "paymentDeadline": row.payment_deadline.isoformat() if row.payment_deadline else None,
            "deadlineRuleRef": row.deadline_rule_ref, "operatorExclusions": row.operator_exclusions or [],
            "allocatedById": row.allocated_by_id,
            "residue": None if row.allocation_residue is None else str(row.allocation_residue),
            "ruleSource": row.rule_source, "allocations": [allocation_view(a) for a in allocations],
            "allocatedTotal": str(sum((_dec(a.final_amount) for a in allocations), _ZERO)),
            "ptuRun": None if run is None else {"id": run.id, "status": run.status,
                                                "payDate": run.pay_date.isoformat() if run.pay_date else None,
                                                "committed": _committed(run)},
            "cancelledReason": row.cancelled_reason}


def list_cycles(db: Session, org_id: int) -> list:
    _guard(db, org_id)
    C = _m().PayrollMxPtuCycle
    return [cycle_view(db, r) for r in db.query(C).filter(C.organization_id == org_id).order_by(C.id.desc())]


def get_cycle(db: Session, org_id: int, cycle_id: int) -> dict:
    _guard(db, org_id)
    return cycle_view(db, _cycle(db, org_id, cycle_id))


def employee_ptu(db: Session, org_id: int, employee_id: int) -> list:
    _guard(db, org_id)
    m = _m()
    emp = db.get(m.PayrollEmployee, employee_id)
    if emp is None or emp.organization_id != org_id:
        raise NotFoundException(f"Employee {employee_id} not found")
    A, C = m.PayrollMxPtuAllocation, m.PayrollMxPtuCycle
    rows = (db.query(A, C).join(C, A.cycle_id == C.id).filter(A.employee_id == employee_id)
            .order_by(C.fiscal_year.desc()).all())
    return [{"cycleId": c.id, "fiscalYear": c.fiscal_year, "cycleStatus": c.status, **allocation_view(a)}
            for a, c in rows]
