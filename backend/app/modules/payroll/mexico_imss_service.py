"""
modules/payroll/mexico_imss_service.py
--------------------------------------
Mexico Phase 8 B1 / B9 (docs/mexico/MEXICO_PHASE_8_PLAN.md): IMSS affiliation
movements (MX-025) generated ONCE from committed events, the operator worklist
(file-export mode, D1 — the real IDSE layout is X1, so the export is a Zoiko
worklist labelled "not an IMSS / IDSE file"), the movement outcomes, and the
Social Security Center summary (spec §14).

Sources (D2, until the S13 / S10 rules on which changes need a movement are
transcribed):
  ALTA          the employee's first committed SBC row under an IMSS
                registration; event date = date_of_joining (required)
  MODIFICACION  EVERY committed SBC change (sbc_total differs from the
                previous committed row under the same registration); the
                operator may withdraw one only with a recorded reason
  BAJA          only an APPROVED termination (Phase 9c, D6 — the employee's
                date_of_leaving alone no longer generates one) for an employee
                with a live ALTA; approving the termination generates it

MX-061: the NSS is read only to build a worklist on request (D12) — never
stored by this module, never logged; every view masks it; each export is
audited without it.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll import mexico_authority_lifecycle as L
from app.modules.payroll import mexico_due_dates as due
from app.modules.payroll import mexico_filing_service as F
from app.modules.payroll.engine.countries import mexico_content as _content
from app.modules.payroll.engine.countries.mexico import MXBlock

WORKLIST_BANNER = "ZOIKO WORKLIST - NOT AN IMSS / IDSE FILE - key these movements into IDSE, then record the outcome in Zoiko"
_LIVE_BLOCKERS = ("VOIDED",)        # a voided movement (run reset) never blocks regeneration


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _existing(db: Session, org_id: int) -> dict:
    m = L.models()
    out = defaultdict(list)
    for mv in db.query(m.PayrollMxImssMovement).filter(m.PayrollMxImssMovement.organization_id == org_id):
        out[mv.source_key].append(mv)
    return out


def _new_movement(db: Session, org_id: int, existing: dict, *, source_kind, source_key, movement_type, reg_id,
                  employee_id, run_id, event_date, sbc, actor_id, replaces=None):
    m = L.models()
    attempt = len(existing.get(source_key, []))
    due_date, rule = due.movement_due(event_date)
    mv = m.PayrollMxImssMovement(
        organization_id=org_id, registration_id=reg_id, employee_id=employee_id, payroll_run_id=run_id,
        source_kind=source_kind, source_key=source_key, movement_type=movement_type, event_date=event_date,
        sbc=sbc, due_date=due_date, due_rule_ref=rule, status="PENDING", created_by_id=actor_id,
        replaces_movement_id=replaces.id if replaces is not None else None,
        idempotency_key=L.idempotency_key("mximss", org_id, source_key, attempt))
    db.add(mv)
    db.flush()
    existing[source_key].append(mv)
    L.event(db, org_id, "MOVEMENT", mv, "REGENERATED" if replaces is not None else "GENERATED", actor_id,
            {"type": movement_type, "sourceKind": source_kind, "dueRule": rule}, None, "PENDING")
    return mv


def _blocked(existing: dict, key: str) -> bool:
    return any(mv.status not in _LIVE_BLOCKERS for mv in existing.get(key, []))


def generate_movements(db: Session, org_id: int, actor_id: Optional[int] = None) -> dict:
    """Idempotent: a committed event yields one movement, ever (a voided one —
    its run was reset — may be regenerated after the re-commit)."""
    F.guard(db, org_id)
    m = L.models()
    existing = _existing(db, org_id)
    created, skipped = [], []
    H = m.PayrollMxSbcHistory
    rows = (db.query(H).filter(H.organization_id == org_id)
            .order_by(H.employee_id, H.effective_from, H.id).all())
    by_employee = defaultdict(list)
    for row in rows:
        by_employee[row.employee_id].append(row)
    for employee_id, hist in by_employee.items():
        emp = db.get(m.PayrollEmployee, employee_id)
        prev_by_reg = {}
        for row in hist:
            reg = F.registration_for(db, employee_id, row.effective_from)
            if reg is None:
                skipped.append({"employeeId": employee_id, "code": "MX_REGISTRATION_MISSING",
                                "message": f"no ACTIVE IMSS registration in force on {row.effective_from}"})
                continue
            prev = prev_by_reg.get(reg.id)
            prev_by_reg[reg.id] = row
            if prev is None:
                if emp is None or emp.date_of_joining is None:
                    skipped.append({"employeeId": employee_id, "code": "MX_HIRE_DATE_MISSING",
                                    "message": "the employee has no date of joining — no ALTA can be generated"})
                    continue
                key = f"ALTA:{employee_id}:{reg.id}:{emp.date_of_joining.isoformat()}"
                if not _blocked(existing, key):
                    created.append(_new_movement(
                        db, org_id, existing, source_kind="FIRST_RUN", source_key=key, movement_type="ALTA",
                        reg_id=reg.id, employee_id=employee_id, run_id=row.payroll_run_id,
                        event_date=emp.date_of_joining, sbc=row.sbc_total, actor_id=actor_id))
            elif _dec(prev.sbc_total) != _dec(row.sbc_total):
                key = f"SBC:{row.id}"
                if not _blocked(existing, key):
                    created.append(_new_movement(
                        db, org_id, existing, source_kind="SBC_CHANGE", source_key=key, movement_type="MODIFICACION",
                        reg_id=reg.id, employee_id=employee_id, run_id=row.payroll_run_id,
                        event_date=row.effective_from, sbc=row.sbc_total, actor_id=actor_id))
        term = _settling_termination(db, employee_id)
        if term is not None:
            created += _bajas(db, org_id, existing, employee_id, hist, prev_by_reg, term, actor_id)
    db.commit()
    return {"created": [movement_view(db, mv) for mv in created], "skipped": _dedupe(skipped)}


def _settling_termination(db: Session, employee_id: int):
    from app.modules.payroll import mexico_termination_service

    return mexico_termination_service.settling(db, employee_id)


def _bajas(db: Session, org_id: int, existing: dict, employee_id: int, hist: list, regs, term, actor_id) -> list:
    """One BAJA per registration with a live ALTA, dated the termination date."""
    last = hist[-1] if hist else None
    out = []
    for reg_id in regs:
        alta_live = any(k.startswith(f"ALTA:{employee_id}:{reg_id}:") and
                        any(mv.status not in ("VOIDED", "REJECTED", "WITHDRAWN") for mv in mvs)
                        for k, mvs in existing.items())
        key = f"BAJA:{employee_id}:{reg_id}:{term.termination_date.isoformat()}"
        if alta_live and not _blocked(existing, key):
            out.append(_new_movement(
                db, org_id, existing, source_kind="TERMINATION", source_key=key, movement_type="BAJA",
                reg_id=reg_id, employee_id=employee_id, run_id=None, event_date=term.termination_date,
                sbc=last.sbc_total if last is not None else None, actor_id=actor_id))
    return out


def baja_for_termination(db: Session, org_id: int, term, actor_id) -> dict:
    """Phase 9c: the BAJA of one approved termination, generated at approval
    (no commit — the caller's transaction). Skipped, with the reason, when the
    employee has no live ALTA (never committed in a run: nothing to deregister)."""
    m = L.models()
    H = m.PayrollMxSbcHistory
    hist = (db.query(H).filter(H.organization_id == org_id, H.employee_id == term.employee_id)
            .order_by(H.effective_from, H.id).all())
    regs = []
    for row in hist:
        reg = F.registration_for(db, term.employee_id, row.effective_from)
        if reg is not None and reg.id not in regs:
            regs.append(reg.id)
    existing = _existing(db, org_id)
    created = _bajas(db, org_id, existing, term.employee_id, hist, regs, term, actor_id)
    skipped = [] if created else [{"employeeId": term.employee_id, "code": "MX_NO_LIVE_ALTA",
                                   "message": "no live ALTA for this employee — no BAJA is needed"}]
    return {"created": created, "skipped": skipped}


def _dedupe(rows: list) -> list:
    seen, out = set(), []
    for r in rows:
        key = (r["employeeId"], r["code"], r["message"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _movement(db: Session, org_id: int, movement_id: int):
    return L.load(db, "MOVEMENT", org_id, movement_id)


def export_worklist(db: Session, org_id: int, actor_id, movement_ids: Optional[list] = None) -> dict:
    """The operator's worklist for keying into IDSE (D1 / D12): built on
    request, returned once, never stored; marks the movements EXPORTED and
    freezes their payload (a retry re-exports exactly the same facts)."""
    F.guard(db, org_id)
    m = L.models()
    M = m.PayrollMxImssMovement
    q = db.query(M).filter(M.organization_id == org_id, M.status == "PENDING")
    if movement_ids:
        q = q.filter(M.id.in_([int(i) for i in movement_ids]))
    moves = q.order_by(M.event_date, M.id).all()
    if not moves:
        raise BadRequestException("No PENDING movements to export")
    missing = []
    rows = []
    for mv in moves:
        emp = db.get(m.PayrollEmployee, mv.employee_id)
        nss = ((emp.compliance_fields or {}).get("nss") if emp is not None else None) or ""
        if not str(nss).strip():
            missing.append(mv.employee_id)
        reg = db.get(m.PayrollMxImssRegistration, mv.registration_id)
        rows.append([mv.id, mv.movement_type, reg.registro_patronal if reg else "", mv.employee_id,
                     emp.name if emp else "", str(nss).strip(), mv.event_date.isoformat(),
                     "" if mv.sbc is None else str(mv.sbc), mv.due_date.isoformat() if mv.due_date else due.UNSOURCED])
    if missing:
        raise MXBlock("MX_NSS_MISSING", f"employee(s) {', '.join(str(e) for e in sorted(set(missing)))} have no NSS "
                                        "on their profile — nothing was exported", org_id)
    batch = f"MXW-{org_id}-{L.now().strftime('%Y%m%d%H%M%S')}"
    for mv in moves:
        L.freeze("MOVEMENT", mv)
        mv.export_batch_ref, mv.exported_at = batch, L.now()
        L.transition(db, org_id, "MOVEMENT", mv, "EXPORTED",
                     "RE_EXPORTED" if any(e.event_type == "RETRY_READY" for e in L.events(db, "MOVEMENT", mv))
                     else "EXPORTED", actor_id, {"batch": batch})
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, actor_id=actor_id, action="export_imss_worklist", entity_type="mx_imss_worklist",
                          entity_id=org_id, new={"batch": batch, "movements": [mv.id for mv in moves]})
    db.commit()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([WORKLIST_BANNER, batch])
    writer.writerow(["zoiko_movement_id", "movement_type", "registro_patronal", "employee_id", "employee_name", "nss",
                     "event_date", "sbc", "due_date"])
    writer.writerows(rows)
    return {"batchRef": batch, "count": len(moves), "filename": f"{batch}-worklist.csv", "content": buf.getvalue()}


def record_outcome(db: Session, org_id: int, movement_id: int, outcome: str, actor_id, reference: Optional[str] = None,
                   evidence_ref: Optional[str] = None, reason: Optional[str] = None) -> dict:
    F.guard(db, org_id)
    mv = _movement(db, org_id, movement_id)
    outcome = (outcome or "").upper()
    if outcome == "FILED":
        if mv.status != "EXPORTED":
            raise BadRequestException(f"Only an EXPORTED movement can be recorded as filed (this one is {mv.status})")
        mv.authority_reference = L.require_reference(reference, "Recording a movement as filed")
        mv.outcome_recorded_by_id = actor_id
        if evidence_ref:
            mv.evidence_ref = evidence_ref[:200]
        L.transition(db, org_id, "MOVEMENT", mv, "FILED", "FILED", actor_id, {"reference": mv.authority_reference})
    elif outcome == "ACCEPTED":
        if mv.status != "FILED":
            raise BadRequestException(f"Only a FILED movement can be accepted (this one is {mv.status})")
        L.require_different(actor_id, mv.outcome_recorded_by_id, "Recording a movement as ACCEPTED", org_id)
        mv.accepted_by_id = actor_id
        L.transition(db, org_id, "MOVEMENT", mv, "ACCEPTED", "ACCEPTED", actor_id)
    elif outcome == "REJECTED":
        if mv.status not in ("EXPORTED", "FILED"):
            raise BadRequestException(f"Only an EXPORTED or FILED movement can be rejected (this one is {mv.status})")
        text = (reason or "").strip()
        if not text:
            raise BadRequestException("A rejection needs the authority's reason")
        L.transition(db, org_id, "MOVEMENT", mv, "REJECTED", "REJECTED", actor_id, {"reason": text[:300]})
    else:
        raise BadRequestException("Outcome must be FILED, ACCEPTED or REJECTED")
    db.commit()
    return movement_view(db, mv, detail=True)


def withdraw(db: Session, org_id: int, movement_id: int, reason: str, actor_id) -> dict:
    """D2: a generated movement the operator decides is not required — only
    before it ever left Zoiko, and only with a recorded reason."""
    F.guard(db, org_id)
    mv = _movement(db, org_id, movement_id)
    withdraw_movement(db, org_id, mv, reason, actor_id)
    db.commit()
    return movement_view(db, mv, detail=True)


def withdraw_movement(db: Session, org_id: int, mv, reason: str, actor_id) -> None:
    """The withdrawal itself, in the caller's transaction (no commit)."""
    if mv.status != "PENDING" or mv.payload_hash is not None:
        raise BadRequestException("Only a PENDING movement that was never exported can be withdrawn")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Withdrawing a movement needs a reason")
    mv.withdrawn_reason = text[:300]
    L.transition(db, org_id, "MOVEMENT", mv, "WITHDRAWN", "WITHDRAWN", actor_id, {"reason": mv.withdrawn_reason})


def regenerate(db: Session, org_id: int, movement_id: int, actor_id) -> dict:
    """A REJECTED movement re-issued with the same facts as a new row (new key)."""
    F.guard(db, org_id)
    mv = _movement(db, org_id, movement_id)
    if mv.status != "REJECTED":
        raise BadRequestException("Only a REJECTED movement can be regenerated")
    existing = _existing(db, org_id)
    if any(o.status not in ("VOIDED", "REJECTED") for o in existing.get(mv.source_key, [])):
        raise BadRequestException("A live movement already exists for this event")
    new = _new_movement(db, org_id, existing, source_kind=mv.source_kind, source_key=mv.source_key,
                        movement_type=mv.movement_type, reg_id=mv.registration_id, employee_id=mv.employee_id,
                        run_id=mv.payroll_run_id, event_date=mv.event_date, sbc=mv.sbc, actor_id=actor_id, replaces=mv)
    db.commit()
    return movement_view(db, new, detail=True)


def movement_view(db: Session, mv, detail: bool = False) -> dict:
    from app.modules.payroll.employee_validation import mask_identifier

    m = L.models()
    emp = db.get(m.PayrollEmployee, mv.employee_id)
    reg = db.get(m.PayrollMxImssRegistration, mv.registration_id)
    out = {"id": mv.id, "type": mv.movement_type, "sourceKind": mv.source_kind, "registrationId": mv.registration_id,
           "registroPatronal": reg.registro_patronal if reg else None, "employeeId": mv.employee_id,
           "employeeName": emp.name if emp else None,
           "nssMasked": mask_identifier((emp.compliance_fields or {}).get("nss")) if emp else None,
           "runId": mv.payroll_run_id, "eventDate": mv.event_date.isoformat(),
           "sbc": None if mv.sbc is None else str(mv.sbc),
           "dueDate": mv.due_date.isoformat() if mv.due_date else None, "dueRule": mv.due_rule_ref,
           "dueState": due.due_state(mv.due_date, mv.status in ("FILED", "ACCEPTED", "WITHDRAWN", "VOIDED")),
           "status": mv.status, "exportBatchRef": mv.export_batch_ref, "authorityReference": mv.authority_reference,
           "withdrawnReason": mv.withdrawn_reason, "replacesMovementId": mv.replaces_movement_id,
           "payloadHash": mv.payload_hash, "idempotencyKey": mv.idempotency_key,
           "unknown": L.unknown_view(db, "MOVEMENT", mv)}
    if detail:
        out["events"] = L.event_views(db, "MOVEMENT", mv)
    return out


def list_movements(db: Session, org_id: int, status: Optional[str] = None) -> list:
    m = L.models()
    M = m.PayrollMxImssMovement
    q = db.query(M).filter(M.organization_id == org_id)
    if status:
        q = q.filter(M.status == status.upper())
    return [movement_view(db, mv) for mv in q.order_by(M.event_date.desc(), M.id.desc())]


# ── the Social Security Center summary (spec §14) and the blocks ────────────

def blocks(db: Session) -> list:
    """X1–X7 of the plan, each with whether it still applies on this platform."""
    from app.modules.payroll.models import StatutoryFilingCalendar as C

    active_calendar = db.query(C).filter(C.jurisdiction_country == "MX", C.status == "Active").count()
    out = [
        {"code": "MX_IDSE_SUA_SIPARE_LAYOUTS", "item": "X1",
         "message": "IDSE / SUA / SIPARE file layouts (S12, S13, S16) are not saved — exports are Zoiko worklists"},
        {"code": "MX_AUTHORITY_TRANSMISSION", "item": "X3",
         "message": "no transmission to IDSE / SIPARE / SAT / state portals — file-export mode (D1)"},
        {"code": "MX_AUTHORITY_BANK_PAYMENT", "item": "X4",
         "message": "authority payments are recorded evidence only — bank payment is Phase 10"},
        {"code": "MX_BIMONTHLY_PERIODS", "item": "X5",
         "message": "liabilities accrue by calendar month; bimonthly payment periods need S12 / S16 / S10"},
        {"code": "MX_WORK_RISK_REVIEW", "item": "X6",
         "message": "the annual work-risk premium review needs S10 / S14 / S29 (deferred, D10)"},
    ]
    if _content.MX_IMSS_MOVEMENT_DEADLINE is None or not _content.MX_OFFICIAL_HOLIDAYS:
        out.insert(1, {"code": due.UNSOURCED, "item": "X2",
                       "message": "the movement deadline (S13 / S10) and the official holiday calendar are not "
                                  "transcribed — movements have no due date"})
    if not active_calendar:
        out.insert(2, {"code": "MX_FILING_CALENDAR_EMPTY", "item": "X2",
                       "message": "no Active Mexico filing-calendar row (S24 / S10 / S27 / S22) — liabilities and "
                                  "returns have no due date"})
    from app.core import object_storage

    if object_storage.durable_storage_refusal("Mexico authority evidence") is not None:
        out.append({"code": "MX_EVIDENCE_STORAGE", "item": "X7",
                    "message": "Cloud Storage is not configured in production — evidence is recorded by reference"})
    return out


def center_summary(db: Session, org_id: int) -> dict:
    F.guard(db, org_id)
    m = L.models()
    from datetime import date

    today = date.today()
    regs = []
    for reg in db.query(m.PayrollMxImssRegistration).filter(m.PayrollMxImssRegistration.organization_id == org_id):
        premium = (db.query(m.PayrollMxRiskPremium)
                   .filter(m.PayrollMxRiskPremium.registration_id == reg.id, m.PayrollMxRiskPremium.status == "ACTIVE",
                           m.PayrollMxRiskPremium.period_from <= today, m.PayrollMxRiskPremium.period_to >= today)
                   .first())
        ok = reg.status == "ACTIVE" and premium is not None
        regs.append({"id": reg.id, "registroPatronal": reg.registro_patronal, "riskClass": reg.risk_class,
                     "fraction": reg.fraction, "status": reg.status,
                     "riskPremiumPct": None if premium is None else str(premium.premium_rate_pct),
                     "effectiveFrom": reg.effective_from.isoformat(),
                     "effectiveTo": reg.effective_to.isoformat() if reg.effective_to else None,
                     "card": "VERIFIED" if ok else "ACTION_REQUIRED"})

    def counts(model, field="status"):
        out = defaultdict(int)
        for (value,) in db.query(getattr(model, field)).filter(model.organization_id == org_id):
            out[value] += 1
        return dict(out)

    D, P = m.PayrollMxSuaDifference, m.PayrollMxSuaPeriod
    open_diffs = (db.query(D).join(P, P.id == D.sua_period_id)
                  .filter(P.organization_id == org_id, D.status != "APPROVED").count())
    return {"registrations": regs, "movements": counts(m.PayrollMxImssMovement),
            "liabilities": counts(m.PayrollMxAuthorityLiability), "suaPeriods": counts(P),
            "isnReturns": counts(m.PayrollMxIsnReturn), "openDifferences": open_diffs,
            "unknown": sum(c.get("UNKNOWN", 0) for c in (counts(m.PayrollMxImssMovement),
                                                         counts(m.PayrollMxAuthorityLiability), counts(P),
                                                         counts(m.PayrollMxIsnReturn))),
            "blocks": blocks(db)}


def overview(db: Session, organization_id: Optional[int] = None) -> dict:
    """Super Admin, read-only: counts across Mexican organisations + the blocks."""
    m = L.models()

    def counts(model):
        q = db.query(model.status)
        if organization_id is not None:
            q = q.filter(model.organization_id == organization_id)
        out = defaultdict(int)
        for (value,) in q:
            out[value] += 1
        return dict(out)

    return {"organizationId": organization_id, "movements": counts(m.PayrollMxImssMovement),
            "liabilities": counts(m.PayrollMxAuthorityLiability), "suaPeriods": counts(m.PayrollMxSuaPeriod),
            "isnReturns": counts(m.PayrollMxIsnReturn), "blocks": blocks(db)}
