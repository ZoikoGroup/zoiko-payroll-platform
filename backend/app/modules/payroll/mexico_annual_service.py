"""
modules/payroll/mexico_annual_service.py
----------------------------------------
Mexico Phase 9e (docs/mexico/MEXICO_PHASE_9E_PLAN.md, D1–D10): the annual ISR
adjustment.

  * COMPUTE — per legal employer and ended fiscal year (D1), per worker that
    employer paid, from COMMITTED runs only (a payslip a committed correction
    supersedes is left out; special runs are included and labelled by run
    type; a previous year's adjustment applied in this year is taken out of
    this year's withholding) (D2 / D3). The transcribed rule decides
    eligibility and the annual ISR (D4); the difference is annual ISR −
    withheld. Each row keeps its inputs, the rule source and a fingerprint.
  * operator EXCLUSIONS — only a catalog reason, with evidence, approved by a
    second person (D5) → WAIVED at approval.
  * APPROVE — a second person, per employer-year; refused if a committed change
    made any row's inputs stale (D8).
  * APPLY — to a later, uncommitted ORDINARY run chosen by the operator: each
    approved worker's difference is applied to that payslip's withholding by
    the transcribed rule, as its own section (D6 / D7; the year's payslips and
    CFDIs are never edited, MX-010). Commit marks the row APPLIED (linked to
    the payslip, with the change and any carry-forward); a reset reverts it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
RUN_TYPES = ("ORDINARY", "CORRECTION", "AGUINALDO", "PTU", "FINIQUITO")


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


def _hash(value) -> str:
    from app.modules.payroll import mexico_run_service

    return mexico_run_service._hash(value)


def _plain(value):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service._plain(value)


def _employer(db: Session, org_id: int, employer_id) -> int:
    try:
        employer_id = int(employer_id)
    except (TypeError, ValueError):
        raise BadRequestException("employerId is required")
    emp = db.get(_m().PayrollMxEmployerProfile, employer_id)
    if emp is None or emp.organization_id != org_id or emp.previous_version_id is not None:
        raise NotFoundException(f"Legal employer {employer_id} not found")
    return employer_id


def _year(value) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise BadRequestException("fiscalYear is required")
    if year >= _today().year:
        raise BadRequestException("the annual adjustment is computed for a fiscal year that has ended")
    return year


def _employer_year_rows(db: Session, org_id: int, employer_id: int, year: int) -> list:
    A = _m().PayrollMxAnnualIsrAdjustment
    return (db.query(A).filter(A.organization_id == org_id, A.employer_profile_id == employer_id,
                               A.fiscal_year == year).order_by(A.employee_id).all())


def _adjustment_row(db: Session, org_id: int, row_id: int):
    row = db.get(_m().PayrollMxAnnualIsrAdjustment, row_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Annual adjustment {row_id} not found")
    return row


def exclusion_reasons(db: Session, org_id: int) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import annual_adjustment

    _guard(db, org_id)
    rows = annual_adjustment.exclusion_catalog()
    return {"reasons": rows, "transcribed": bool(rows),
            "block": None if rows else {"code": "MX_ANNUAL_ADJUSTMENT_EXCLUSION_RULE_MISSING",
                                        "message": "the annual-adjustment exclusion catalog (S24) is not transcribed — "
                                                   "no operator exclusion can be recorded"}}


# ── inputs (committed runs only) ────────────────────────────────────────────

def worker_facts(db: Session, org_id: int, employer_id: int, year: int) -> list:
    from app.modules.payroll import mexico_filing_service

    m = _m()
    superseded = {c.original_item_id for c in db.query(m.PayrollMxRunCorrection)
                  .filter(m.PayrollMxRunCorrection.status == "COMMITTED")}
    items = (db.query(m.PayslipItem, m.PayrollRun).join(m.PayrollRun, m.PayslipItem.payroll_run_id == m.PayrollRun.id)
             .filter(m.PayslipItem.organization_id == org_id, m.PayslipItem.country_code == "MX",
                     m.PayrollRun.pay_date >= date(year, 1, 1), m.PayrollRun.pay_date <= date(year, 12, 31))
             .order_by(m.PayslipItem.employee_id, m.PayrollRun.pay_date, m.PayslipItem.id).all())
    workers = {}
    for item, run in items:
        kind = run.mx_run_type or "ORDINARY"
        if kind not in RUN_TYPES or not (run.mx_approval_fingerprint or {}).get("committedAt") or item.id in superseded:
            continue
        reg = mexico_filing_service.registration_for(db, item.employee_id, min(run.period_end, run.pay_date))
        if reg is None or reg.employer_profile_id != employer_id:
            continue
        res = (item.mx_calculation_snapshot or {}).get("result") or {}
        w = workers.setdefault(item.employee_id, {"employee_id": item.employee_id, "income_by_run_type": {},
                                                  "annual_taxable": _ZERO, "withheld_total": _ZERO,
                                                  "subsidy_applied_total": _ZERO})
        taxable = _dec(res.get("isr_taxable"))
        w["income_by_run_type"][kind] = w["income_by_run_type"].get(kind, _ZERO) + taxable
        w["annual_taxable"] += taxable
        prior = _dec(((res.get("annual_adjustment") or {}).get("change")))       # an earlier year's adjustment
        w["withheld_total"] += _dec(res.get("isr_withheld")) - prior
        w["subsidy_applied_total"] += _dec((res.get("subsidy") or {}).get("applied"))
    out = []
    for employee_id in sorted(workers):
        emp = db.get(m.PayrollEmployee, employee_id)
        out.append({**workers[employee_id], "date_of_joining": emp.date_of_joining if emp else None,
                    "date_of_leaving": emp.date_of_leaving if emp else None})
    return out


# ── compute / exclusions / approve ──────────────────────────────────────────

def compute(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """Compute (or re-compute) an employer-year. Every rule problem blocks
    before anything is written. Approved operator exclusions are kept."""
    from app.modules.payroll.engine.jurisdictions.mexico import annual_adjustment

    _guard(db, org_id)
    m = _m()
    employer_id = _employer(db, org_id, data.get("employer_profile_id"))
    year = _year(data.get("fiscal_year"))
    existing = _employer_year_rows(db, org_id, employer_id, year)
    if any(r.status in ("APPROVED", "APPLIED") for r in existing):
        raise BadRequestException(f"the {year} adjustment of this employer is already approved — it is not re-computed")
    facts = worker_facts(db, org_id, employer_id, year)
    if not facts:
        raise BadRequestException(f"the employer has no committed Mexican payslip paid in {year}")
    keep = {r.employee_id: r for r in existing if r.exclusion_recorded_by_id}     # operator exclusions survive
    computed = []
    for f in facts:
        excl = keep.get(f["employee_id"])
        worker = {**f, "operator_exclusion": excl.exclusion_reason if excl is not None and excl.exclusion_approved_by_id else None}
        computed.append((f, annual_adjustment.compute(worker, year)))      # BLOCKS while the rule is empty
    source = annual_adjustment.rule_source()
    A = m.PayrollMxAnnualIsrAdjustment
    for r in existing:
        if r.employee_id not in keep:
            db.delete(r)
    db.flush()
    for f, c in computed:
        row = keep.get(f["employee_id"])
        if row is None:
            row = A(organization_id=org_id, employer_profile_id=employer_id, fiscal_year=year,
                    employee_id=f["employee_id"])
            db.add(row)
        row.status, row.eligible = "COMPUTED", c["eligible"]
        if not row.exclusion_recorded_by_id:
            row.exclusion_reason = c["reason"]                          # the rule's reason, if it excluded
        row.income_by_run_type = _plain(f["income_by_run_type"])
        row.annual_taxable, row.withheld_total = f["annual_taxable"], f["withheld_total"]
        row.subsidy_applied_total = f["subsidy_applied_total"]
        row.annual_isr, row.difference = c["annual_isr"], c["difference"]
        row.inputs_fingerprint, row.rule_source, row.computed_by_id = _hash(f), source, actor_id
    _audit(db, actor_id=actor_id, action="compute_annual_adjustment", entity_type="mx_annual_adjustment",
           entity_id=employer_id, new={"fiscalYear": year, "workers": len(facts)})
    db.commit()
    return employer_year_view(db, org_id, employer_id, year)


def record_exclusion(db: Session, org_id: int, row_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import annual_adjustment

    _guard(db, org_id)
    row = _adjustment_row(db, org_id, row_id)
    if row.status != "COMPUTED":
        raise BadRequestException(f"A {row.status} adjustment cannot be excluded")
    code = str(data.get("reason_code") or "").strip()
    annual_adjustment.exclusion_reason(code)            # BLOCKS while the catalog is empty / the code unknown
    evidence = str(data.get("evidence_ref") or "").strip()
    if not evidence:
        raise BadRequestException("An exclusion needs an evidence reference (e.g. the worker's written notice)")
    row.exclusion_reason, row.exclusion_evidence_ref = code, evidence[:300]
    row.exclusion_recorded_by_id, row.exclusion_approved_by_id = actor_id, None
    _audit(db, actor_id=actor_id, action="record_annual_adjustment_exclusion", entity_type="mx_annual_adjustment",
           entity_id=row.id, new={"reason": code})
    db.commit()
    return row_view(row)


def approve_exclusion(db: Session, org_id: int, row_id: int, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    row = _adjustment_row(db, org_id, row_id)
    if row.status != "COMPUTED" or not row.exclusion_recorded_by_id:
        raise BadRequestException("There is no pending exclusion on this adjustment")
    _four_eyes(actor_id, row.exclusion_recorded_by_id, "an annual-adjustment exclusion", org_id)
    row.exclusion_approved_by_id, row.eligible = actor_id, False
    row.annual_isr, row.difference = None, None
    _audit(db, actor_id=actor_id, action="approve_annual_adjustment_exclusion", entity_type="mx_annual_adjustment",
           entity_id=row.id, new={"reason": row.exclusion_reason})
    db.commit()
    return row_view(row)


def approve(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    employer_id = _employer(db, org_id, data.get("employer_profile_id"))
    year = _year(data.get("fiscal_year"))
    rows = [r for r in _employer_year_rows(db, org_id, employer_id, year) if r.status == "COMPUTED"]
    if not rows:
        raise BadRequestException("Nothing computed to approve for this employer and year")
    pending = [r.employee_id for r in rows if r.exclusion_recorded_by_id and not r.exclusion_approved_by_id]
    if pending:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_EXCLUSION_PENDING",
                      f"exclusion(s) for employee(s) {pending} are not approved yet", org_id)
    _four_eyes(actor_id, rows[0].computed_by_id, "the annual adjustment", org_id)
    current = {f["employee_id"]: _hash(f) for f in worker_facts(db, org_id, employer_id, year)}
    stale = [r.employee_id for r in rows if current.get(r.employee_id) != r.inputs_fingerprint]
    if stale or set(current) != {r.employee_id for r in rows}:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_STALE",
                      "a committed change to the fiscal year changed the inputs since they were computed — compute "
                      "again", org_id)
    for r in rows:
        r.status, r.approved_by_id = ("APPROVED" if r.eligible else "WAIVED"), actor_id
    _audit(db, actor_id=actor_id, action="approve_annual_adjustment", entity_type="mx_annual_adjustment",
           entity_id=employer_id, new={"fiscalYear": year, "rows": len(rows)})
    db.commit()
    return employer_year_view(db, org_id, employer_id, year)


# ── apply to a later ordinary run ───────────────────────────────────────────

def apply_to_run(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    _guard(db, org_id)
    m = _m()
    employer_id = _employer(db, org_id, data.get("employer_profile_id"))
    year = _year(data.get("fiscal_year"))
    try:
        run = db.get(m.PayrollRun, int(data.get("run_id")))
    except (TypeError, ValueError):
        run = None
    if run is None or run.organization_id != org_id:
        raise NotFoundException("Payroll run not found")
    if (run.mx_run_type or "ORDINARY") != "ORDINARY":
        raise BadRequestException("The adjustment is applied in an ORDINARY run")
    if (run.mx_approval_fingerprint or {}).get("committedAt") or run.status == "Approved":
        raise BadRequestException("The run is already committed — choose an open run")
    if run.pay_date is None or run.pay_date.year <= year:
        raise BadRequestException(f"The adjustment of {year} is applied in a run paid after that year")
    rows = [r for r in _employer_year_rows(db, org_id, employer_id, year) if r.status == "APPROVED" and r.eligible
            and _dec(r.difference) != 0 and r.applied_run_id is None]
    for r in rows:
        r.applied_run_id = run.id
    _audit(db, actor_id=actor_id, action="assign_annual_adjustment", entity_type="mx_annual_adjustment",
           entity_id=employer_id, new={"fiscalYear": year, "runId": run.id, "rows": [r.id for r in rows]})
    db.commit()
    return {"runId": run.id, "assigned": [r.employee_id for r in rows],
            "note": "Generate (or regenerate) the run's payslips: each assigned worker's payslip shows the adjustment."}


def for_payslip(db: Session, run, employee_id: int) -> Optional[dict]:
    """The adjustment this ordinary payslip applies, or None."""
    if run is None or (run.mx_run_type or "ORDINARY") != "ORDINARY":
        return None
    A = _m().PayrollMxAnnualIsrAdjustment
    row = (db.query(A).filter(A.applied_run_id == run.id, A.employee_id == employee_id,
                              A.status.in_(("APPROVED", "APPLIED"))).first())
    if row is None:
        return None
    return {"id": row.id, "fiscal_year": row.fiscal_year, "difference": _dec(row.difference)}


def on_commit(db: Session, run) -> int:
    from app.modules.payroll import mexico_run_service

    if (run.mx_run_type or "ORDINARY") != "ORDINARY":
        return 0
    A = _m().PayrollMxAnnualIsrAdjustment
    n = 0
    for item in mexico_run_service._mx_items(db, run):
        annual = ((item.mx_calculation_snapshot or {}).get("result") or {}).get("annual_adjustment")
        if not annual:
            continue
        row = db.get(A, int(annual["adjustment_id"]))
        if row is not None and row.status == "APPROVED" and row.applied_run_id == run.id:
            row.status, row.applied_item_id = "APPLIED", item.id
            row.applied_withheld_change, row.carry_forward = _dec(annual["change"]), _dec(annual["carry_forward"])
            n += 1
    return n


def on_reset(db: Session, run) -> int:
    A = _m().PayrollMxAnnualIsrAdjustment
    n = 0
    for row in db.query(A).filter(A.applied_run_id == run.id, A.status == "APPLIED"):
        row.status, row.applied_item_id, row.applied_withheld_change, row.carry_forward = "APPROVED", None, None, None
        n += 1
    return n


# ── views ───────────────────────────────────────────────────────────────────

def row_view(r) -> dict:
    def s(v):
        return None if v is None else str(v)

    return {"id": r.id, "employerId": r.employer_profile_id, "fiscalYear": r.fiscal_year, "employeeId": r.employee_id,
            "status": r.status, "eligible": r.eligible, "exclusionReason": r.exclusion_reason,
            "exclusionEvidenceRef": r.exclusion_evidence_ref,
            "exclusionPending": bool(r.exclusion_recorded_by_id and not r.exclusion_approved_by_id),
            "incomeByRunType": r.income_by_run_type, "annualTaxable": s(r.annual_taxable),
            "withheldTotal": s(r.withheld_total), "subsidyAppliedTotal": s(r.subsidy_applied_total),
            "annualIsr": s(r.annual_isr), "difference": s(r.difference), "ruleSource": r.rule_source,
            "appliedRunId": r.applied_run_id, "appliedItemId": r.applied_item_id,
            "appliedWithheldChange": s(r.applied_withheld_change), "carryForward": s(r.carry_forward)}


def employer_year_view(db: Session, org_id: int, employer_id: int, year: int) -> dict:
    rows = _employer_year_rows(db, org_id, employer_id, year)
    return {"employerId": employer_id, "fiscalYear": year, "rows": [row_view(r) for r in rows]}


def list_adjustments(db: Session, org_id: int) -> list:
    _guard(db, org_id)
    A = _m().PayrollMxAnnualIsrAdjustment
    pairs = sorted({(r.employer_profile_id, r.fiscal_year) for r in db.query(A).filter(A.organization_id == org_id)},
                   key=lambda p: (-p[1], p[0]))
    return [employer_year_view(db, org_id, e, y) for e, y in pairs]


def employee_adjustments(db: Session, org_id: int, employee_id: int) -> list:
    _guard(db, org_id)
    m = _m()
    emp = db.get(m.PayrollEmployee, employee_id)
    if emp is None or emp.organization_id != org_id:
        raise NotFoundException(f"Employee {employee_id} not found")
    A = m.PayrollMxAnnualIsrAdjustment
    return [row_view(r) for r in db.query(A).filter(A.employee_id == employee_id).order_by(A.fiscal_year.desc())]
