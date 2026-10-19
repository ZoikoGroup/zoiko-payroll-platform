"""
modules/payroll/mexico_correction_service.py
--------------------------------------------
Mexico Phase 9a — correction runs (docs/mexico/MEXICO_PHASE_9_PLAN.md B2, D10).

A CORRECTION run recalculates selected COMMITTED Mexican payslips for the
original period (same period dates and pay date, current inputs). It never
edits the original payslip, its CFDI or its ledgers:

  * commit posts DELTAS (corrected − original) to the aggregate ledgers
    (ISN liabilities, variable accumulators, benefit accruals) and the full
    corrected rows to the per-payslip traces (IMSS lines, SBC history);
  * the authority ledger (Phase 8) accrues the deltas — into a complementary
    liability when the period already left Zoiko;
  * CFDI (Phase 7): the corrected payslip's document REPLACES the original's
    stamped one (substitution lineage); an untransmitted original is voided;
  * month-to-date (subsidy, MX-013): a committed correction contributes its
    delta only to runs committed AFTER it — an already committed run is never
    changed by a correction (no approval drift); the correction's own
    calculation excludes the payslips it replaces (and their earlier chain).

One live correction per original payslip; a later correction targets the
corrected payslip (a chain). A committed original with a live correction
refuses reset; a draft correction is voided (its uncommitted run deleted).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
# Snapshot result fields whose delta is recorded (all money, all committed facts).
DELTA_FIELDS = ("gross", "isr_taxable", "isr_withheld", "imss_employee", "imss_employer", "infonavit_employer",
                "infonavit_credit", "employee_total", "employer_total")


def _m():
    from app.modules.payroll import models as m

    return m


def _dec(value) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _committed(run) -> bool:
    return bool((run.mx_approval_fingerprint or {}).get("committedAt"))


def _audit(db, **kw):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, **kw)


def result_of(item) -> dict:
    return (getattr(item, "mx_calculation_snapshot", None) or {}).get("result") or {}


# ── lookups ─────────────────────────────────────────────────────────────────

def for_corrected_item(db: Session, item_id: int):
    m = _m()
    C = m.PayrollMxRunCorrection
    return (db.query(C).filter(C.corrected_item_id == item_id, C.status != "VOIDED").first())


def original_item_for(db: Session, corrected_item):
    corr = for_corrected_item(db, corrected_item.id)
    return db.get(_m().PayslipItem, corr.original_item_id) if corr is not None else None


def replaced_chain(db: Session, run) -> set:
    """Payslip ids a CORRECTION run replaces, with their earlier chain (the
    original a previous committed correction itself replaced)."""
    m = _m()
    C = m.PayrollMxRunCorrection
    if run is None or (getattr(run, "mx_run_type", None) or "ORDINARY") != "CORRECTION":
        return set()
    out = set()
    frontier = [c.original_item_id for c in db.query(C).filter(C.correction_run_id == run.id, C.status != "VOIDED")]
    while frontier:
        item_id = frontier.pop()
        if item_id in out:
            continue
        out.add(item_id)
        prev = db.query(C).filter(C.corrected_item_id == item_id, C.status == "COMMITTED").first()
        if prev is not None:
            frontier.append(prev.original_item_id)
    return out


def contribution(db: Session, item, run_of_item, me, my_committed_at):
    """(taxable, subsidy_applied) this committed payslip adds to `me`'s
    month-to-date, or None when it must not count. Ordinary payslips are
    gated by the caller's payment order; a CORRECTION payslip adds its delta
    and only to runs committed after the correction (or not committed)."""
    res = result_of(item)
    taxable, applied = _dec(res.get("isr_taxable")), _dec((res.get("subsidy") or {}).get("applied"))
    if (run_of_item.mx_run_type or "ORDINARY") != "CORRECTION":
        return taxable, applied
    corr_at = (run_of_item.mx_approval_fingerprint or {}).get("committedAt")
    if my_committed_at is not None and corr_at is not None and             datetime.fromisoformat(corr_at) >= datetime.fromisoformat(my_committed_at):
        return None
    original = original_item_for(db, item)
    if original is None:
        return taxable, applied
    o = result_of(original)
    return (taxable - _dec(o.get("isr_taxable")),
            applied - _dec((o.get("subsidy") or {}).get("applied")))


# ── create / void ───────────────────────────────────────────────────────────

def _run(db: Session, org_id: int, run_id: int):
    run = db.get(_m().PayrollRun, run_id)
    if run is None or run.organization_id != org_id:
        raise NotFoundException(f"Payroll run {run_id} not found")
    return run


def create_correction(db: Session, org_id: int, original_run_id: int, item_ids: list, reason: str,
                      actor_id: Optional[int]) -> dict:
    """Open a CORRECTION run for selected committed payslips and calculate it."""
    from app.modules.payroll import mexico_filing_service, mexico_run_service, service

    mexico_filing_service.guard(db, org_id)
    m = _m()
    C = m.PayrollMxRunCorrection
    original = _run(db, org_id, original_run_id)
    if not _committed(original):
        raise BadRequestException("Only a committed (Approved) Mexican run can be corrected")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A correction needs a reason")
    wanted = {int(i) for i in (item_ids or [])}
    if not wanted:
        raise BadRequestException("Choose at least one payslip to correct")
    items = [i for i in mexico_run_service._mx_items(db, original) if i.id in wanted]
    if len(items) != len(wanted):
        raise BadRequestException("Every payslip to correct must be a Mexican payslip of this run")
    live = {c.original_item_id for c in db.query(C).filter(C.original_item_id.in_(wanted), C.status != "VOIDED")}
    if live:
        raise MXBlock("MX_CORRECTION_ALREADY_OPEN",
                      f"payslip(s) {', '.join(str(i) for i in sorted(live))} already have a correction — correct "
                      "the corrected payslip instead (or void the draft)", org_id)
    run = m.PayrollRun(organization_id=org_id, period_label=f"Correction — {original.period_label}"[:100],
                       period_start=original.period_start, period_end=original.period_end,
                       pay_date=original.pay_date, status="Draft", created_by=actor_id, mx_run_type="CORRECTION")
    db.add(run)
    db.flush()
    rows = [C(organization_id=org_id, correction_run_id=run.id, original_run_id=original.id, original_item_id=i.id,
              employee_id=i.employee_id, reason=text[:500], status="DRAFT", requested_by_id=actor_id) for i in items]
    db.add_all(rows)
    db.commit()
    run_id, row_ids = run.id, [r.id for r in rows]
    try:
        service.generate_payslips_for_run(db, run, org_id, [i.employee_id for i in items])
    except Exception:
        # Never leave a half-made correction: no calculated payslip, no correction.
        db.rollback()
        db.query(C).filter(C.id.in_(row_ids)).delete(synchronize_session=False)
        leftover = db.get(m.PayrollRun, run_id)
        if leftover is not None:
            db.delete(leftover)
        db.commit()
        raise
    db.refresh(run)
    by_employee = {i.employee_id: i for i in mexico_run_service._mx_items(db, run)}
    for row in rows:
        new = by_employee.get(row.employee_id)
        row.corrected_item_id = new.id if new is not None else None
    _audit(db, actor_id=actor_id, action="open_correction", entity_type="mx_run_correction", entity_id=run.id,
           new={"originalRunId": original.id, "originalItems": sorted(wanted)}, reason=text[:300])
    db.commit()
    return run_view(db, org_id, run.id)


def void(db: Session, org_id: int, correction_run_id: int, reason: str, actor_id: Optional[int]) -> dict:
    """Void a DRAFT correction: its records are kept (VOIDED) and its
    uncommitted run is deleted. A committed correction is reset like a run."""
    from app.modules.payroll import mexico_filing_service, service

    mexico_filing_service.guard(db, org_id)
    m = _m()
    run = _run(db, org_id, correction_run_id)
    if (run.mx_run_type or "") != "CORRECTION":
        raise BadRequestException("This is not a correction run")
    if _committed(run) or run.status not in ("Draft", "Review"):
        raise BadRequestException("Only an uncommitted correction can be voided — reset a committed one first")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Voiding a correction needs a reason")
    now = datetime.now(timezone.utc)
    rows = db.query(m.PayrollMxRunCorrection).filter(m.PayrollMxRunCorrection.correction_run_id == run.id).all()
    for row in rows:
        row.status, row.voided_by_id, row.void_reason, row.voided_at = "VOIDED", actor_id, text[:300], now
        row.corrected_item_id, row.correction_run_id = None, None     # the run is deleted below; the audit keeps its id
    run.status = "Draft"                         # uncommitted and never acted: back to Draft so it can be deleted
    _audit(db, actor_id=actor_id, action="void_correction", entity_type="mx_run_correction", entity_id=run.id,
           new={"corrections": [r.id for r in rows], "correctionRunId": run.id}, reason=text[:300])
    db.commit()
    service.delete_payroll_run(db, run.id, org_id)
    return {"correctionRunId": correction_run_id, "voided": [r.id for r in rows]}


def refuse_delete_unless_voided(db: Session, run) -> None:
    """The shared Draft-run delete (service.delete_payroll_run): a Mexican
    correction run goes only through void(), so its records stay for audit."""
    from fastapi import HTTPException
    from fastapi import status as http_status

    m = _m()
    live = (db.query(m.PayrollMxRunCorrection)
            .filter(m.PayrollMxRunCorrection.correction_run_id == run.id, m.PayrollMxRunCorrection.status != "VOIDED")
            .count())
    if live:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            "This is a Mexican correction run — void the correction instead (its record is kept for audit)."))


# ── commit / reset hooks (called by mexico_run_service) ─────────────────────

def deltas_for(original, corrected) -> dict:
    o, c = result_of(original), result_of(corrected)
    out = {f: str(_dec(c.get(f)) - _dec(o.get(f))) for f in DELTA_FIELDS}
    out["net_pay"] = str(_dec(getattr(corrected, "net_pay", None)) - _dec(getattr(original, "net_pay", None)))
    out["isn"] = str(_dec((c.get("isn") or {}).get("amount")) - _dec((o.get("isn") or {}).get("amount")))
    imss = {}
    for res, sign in ((c, 1), (o, -1)):
        for b in res.get("imss") or []:
            key = f"{b.get('branch')}:{b.get('side')}"
            imss[key] = imss.get(key, _ZERO) + sign * _dec(b.get("amount"))
    out["imss"] = {k: str(v) for k, v in sorted(imss.items()) if v != 0}
    return out


def on_commit(db: Session, run) -> None:
    """Inside the APPROVED transition of a CORRECTION run (before committedAt):
    every draft correction gets its deltas and becomes COMMITTED."""
    m = _m()
    now = datetime.now(timezone.utc)
    for row in db.query(m.PayrollMxRunCorrection).filter(m.PayrollMxRunCorrection.correction_run_id == run.id,
                                                         m.PayrollMxRunCorrection.status == "DRAFT"):
        corrected = db.get(m.PayslipItem, row.corrected_item_id) if row.corrected_item_id else None
        if corrected is None:
            raise MXBlock("MX_CORRECTION_NOT_CALCULATED",
                          f"the correction of payslip {row.original_item_id} has no recalculated payslip",
                          run.organization_id)
        row.deltas = deltas_for(db.get(m.PayslipItem, row.original_item_id), corrected)
        row.status, row.committed_at = "COMMITTED", now


def on_reset(db: Session, run) -> int:
    """A committed correction run reset back to Review: its corrections are
    drafts again (deltas cleared with the ledgers the reset removes)."""
    m = _m()
    n = 0
    for row in db.query(m.PayrollMxRunCorrection).filter(m.PayrollMxRunCorrection.correction_run_id == run.id,
                                                         m.PayrollMxRunCorrection.status == "COMMITTED"):
        row.status, row.deltas, row.committed_at = "DRAFT", None, None
        n += 1
    return n


def downstream_reasons(db: Session, run) -> list:
    """A run whose payslips carry a live correction cannot be reset (the
    correction is built on its committed figures)."""
    m = _m()
    C = m.PayrollMxRunCorrection
    return [f"payslip {c.original_item_id} has a {c.status} correction (run {c.correction_run_id})"
            for c in db.query(C).filter(C.original_run_id == run.id, C.status != "VOIDED").order_by(C.id)]


# ── CFDI (Phase 7) ──────────────────────────────────────────────────────────

def cfdi_original(db: Session, corrected_item, actor_id=None):
    """The original document the corrected payslip's CFDI replaces (STAMPED),
    or None. An untransmitted original is voided; one in flight refuses."""
    from app.modules.payroll import mexico_cfdi_service as S

    m = _m()
    original = original_item_for(db, corrected_item)
    if original is None:
        return None
    D = m.PayrollMxCfdiDocument
    doc = (db.query(D).filter(D.payslip_item_id == original.id).order_by(D.id.desc()).first())
    if doc is None or doc.status in ("VOIDED", "REJECTED", "CANCELLED", "REPLACED"):
        return None
    if doc.status == "STAMPED":
        return doc
    if doc.status in ("GENERATED", "SIGNED"):
        S._transition(db, doc, "VOIDED", "VOIDED_BY_CORRECTION", actor_id, {"correctedItemId": corrected_item.id})
        for o in db.query(m.PayrollMxCfdiOutboxItem).filter(m.PayrollMxCfdiOutboxItem.document_id == doc.id,
                                                            m.PayrollMxCfdiOutboxItem.status == "PENDING"):
            o.status, o.last_error = "FAILED", "original voided by a correction"
        return None
    raise MXBlock("MX_CFDI_ORIGINAL_IN_FLIGHT",
                  f"the original CFDI (folio {doc.folio}) is {doc.status} — resolve it before the correction's CFDI",
                  corrected_item.organization_id)


# ── views ───────────────────────────────────────────────────────────────────

def correction_view(row) -> dict:
    return {"id": row.id, "correctionRunId": row.correction_run_id, "originalRunId": row.original_run_id,
            "originalItemId": row.original_item_id, "correctedItemId": row.corrected_item_id,
            "employeeId": row.employee_id, "reason": row.reason, "status": row.status, "deltas": row.deltas,
            "committedAt": row.committed_at.isoformat() if row.committed_at else None,
            "voidReason": row.void_reason}


def run_view(db: Session, org_id: int, run_id: int) -> dict:
    """Corrections OF this run (as original) and BY this run (as a correction run)."""
    m = _m()
    C = m.PayrollMxRunCorrection
    run = _run(db, org_id, run_id)
    of = db.query(C).filter(C.original_run_id == run.id).order_by(C.id).all()
    by = db.query(C).filter(C.correction_run_id == run.id).order_by(C.id).all()
    return {"runId": run.id, "runType": run.mx_run_type or "ORDINARY", "committed": _committed(run),
            "correctable": _committed(run),
            "corrections": [correction_view(c) for c in of], "corrects": [correction_view(c) for c in by]}
