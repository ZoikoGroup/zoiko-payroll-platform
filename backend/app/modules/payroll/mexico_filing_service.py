"""
modules/payroll/mexico_filing_service.py
----------------------------------------
Mexico Phase 8 (docs/mexico/MEXICO_PHASE_8_PLAN.md) — the authority side of a
committed payroll, in file-export mode (D1: Zoiko never transmits):

  B3  authority liability ledger — SAT_ISR per organisation, IMSS / INFONAVIT
      per IMSS registration, ISN per state, by pay-date month (D4); fed ONLY
      from committed rows, each linked once (no double counting); rows
      committed after a period left Zoiko go to a complementary liability
      (`sequence` + 1); payment is RECORDED evidence (no money moves — Phase 10)
  B4  SUA reconciliation — Zoiko per-worker × per-branch totals against the
      figures the operator enters from SUA (D5, zero tolerance); every
      difference is BLOCKING until explained and approved by a second person
      (D6); a period reconciles only by someone other than whoever entered
      the SUA figures
  B5  state ISN returns (MX-046) with the employee → return → ledger check;
      amendments are new rows
  B6  the ISR remittance record = the SAT_ISR liability (declaration +
      payment references)
  B8  reset registration — downstream_reasons / withdraw_on_reset

Due dates: mexico_due_dates (sourced only; DUE_DATE_UNSOURCED otherwise).
The UNKNOWN rule and the state machines: mexico_authority_lifecycle.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll import mexico_authority_lifecycle as L
from app.modules.payroll import mexico_due_dates as due
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
AUTHORITIES = ("SAT_ISR", "IMSS", "INFONAVIT", "ISN")
# Zoiko WORKFLOW labels for a SUA difference (D5) — not statutory codes.
EXPLANATION_CODES = ("TIMING", "SUA_VERSION", "DATA_CORRECTION", "OTHER")
_SRC_ISN = "payroll_mx_isn_liabilities"
_SRC_ISR, _SRC_CREDIT = "payslip_items.isr_withheld", "payslip_items.infonavit_credit"
_SRC_HOUSING = "payslip_items.infonavit_employer"     # Phase 6 ledgers carry no INFONAVIT line


def _dec(value) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _s(value) -> Optional[str]:
    return None if value is None else str(value)


def guard(db: Session, org_id: int) -> None:
    from app.modules.payroll import mexico_dormancy, mexico_run_service

    if not mexico_dormancy.onboarding_enabled():
        raise MXBlock("MX_DORMANT", mexico_dormancy.DORMANT_MESSAGE, org_id)
    if not mexico_run_service._org_runs_mexico(db, org_id):
        raise MXBlock("MX_ORG_NOT_MEXICAN", "Mexico is not one of the organisation's payroll countries", org_id)


def committed_runs(db: Session, org_id: int) -> list:
    m = L.models()
    runs = (db.query(m.PayrollRun).filter(m.PayrollRun.organization_id == org_id)
            .order_by(m.PayrollRun.pay_date, m.PayrollRun.id).all())
    return [r for r in runs if (r.mx_approval_fingerprint or {}).get("committedAt")]


def _items(db: Session, run) -> list:
    from app.modules.payroll import mexico_run_service

    return mexico_run_service._mx_items(db, run)


def registration_for(db: Session, employee_id: int, on):
    """The employee's ACTIVE IMSS registration in force on `on`, or None."""
    from app.modules.payroll import mexico_employee_service, mexico_run_service

    prof = mexico_employee_service._profile_on(db, employee_id, on)
    return mexico_run_service._registration(db, prof, on) if prof is not None else None


# ── B3: the authority liability ledger ──────────────────────────────────────

def _scope(authority: str, registration_id=None, state=None) -> str:
    if authority == "SAT_ISR":
        return "ORG"
    return f"REG:{registration_id}" if authority in ("IMSS", "INFONAVIT") else f"ST:{state}"


def _open_liability(db: Session, org_id: int, authority: str, period_key: str, registration_id=None, state=None):
    """The liability that may still take sources: ACCRUED and never sent.
    Otherwise a new one — `sequence` + 1 when the period already left Zoiko."""
    m = L.models()
    A = m.PayrollMxAuthorityLiability
    scope = _scope(authority, registration_id, state)
    rows = (db.query(A).filter(A.organization_id == org_id, A.authority == authority, A.scope_key == scope,
                               A.period_key == period_key).order_by(A.sequence).all())
    for row in rows:
        if row.status == "ACCRUED" and row.payload_hash is None:
            return row
    if rows and rows[-1].status == "WITHDRAWN" and rows[-1].payload_hash is None:
        # Withdrawn by a reset and never sent: the re-committed run accrues into it again.
        L.transition(db, org_id, "LIABILITY", rows[-1], "ACCRUED", "REACCRUED")
        return rows[-1]
    seq = (rows[-1].sequence + 1) if rows else 0
    due_date, rule = due.liability_due(db, authority, period_key, state if authority == "ISN" else None)
    row = A(organization_id=org_id, authority=authority, registration_id=registration_id,
            state_code=state if authority == "ISN" else None, scope_key=scope, period_key=period_key, sequence=seq,
            amount=_ZERO, components={}, due_date=due_date, due_rule_ref=rule, status="ACCRUED",
            idempotency_key=L.idempotency_key("mxliab", org_id, authority, scope, period_key, seq))
    db.add(row)
    db.flush()
    L.event(db, org_id, "LIABILITY", row, "ACCRUED", None, {"sequence": seq}, None, "ACCRUED")
    return row


def _recompute(db: Session, liab) -> None:
    m = L.models()
    S = m.PayrollMxAuthorityLiabilitySource
    total, comps = _ZERO, defaultdict(lambda: _ZERO)
    for src in db.query(S).filter(S.liability_id == liab.id):
        total += _dec(src.amount)
        comps[f"{src.branch_code}:{src.side or '-'}"] += _dec(src.amount)
    liab.amount = total
    liab.components = {k: str(v) for k, v in sorted(comps.items())}


def _candidate_sources(db: Session, run, item):
    """(authority, registration_id, state, source_table, row_id, branch, side, base, amount) for one
    committed payslip — or a skip reason.

    IMSS comes from the committed snapshot's per-branch / per-side amounts —
    the emitted amounts, each rounded once (engine _by_branch) — so a
    liability equals what the payslips charged. The Phase 6 branch-line
    ledger keeps the unrounded segment lines (4 dp) as the trace.

    Phase 9a: a CORRECTION payslip contributes its DELTAS (corrected −
    original, possibly negative); its ISN delta rows are already in the ISN
    ledger (mexico_run_service.commit_run)."""
    from app.modules.payroll import mexico_correction_service as corrections

    m = L.models()
    res = corrections.result_of(item)
    is_correction = (run.mx_run_type or "ORDINARY") == "CORRECTION"
    base = corrections.result_of(corrections.original_item_for(db, item)) if is_correction else {}
    keep = (lambda v: v != 0) if is_correction else (lambda v: v > 0)
    out, skips = [], []
    reg = registration_for(db, item.employee_id, run.pay_date)
    branches = {}
    for r, sign in ((res, 1), (base, -1)):
        for b in r.get("imss") or []:
            if b.get("branch"):
                key = (b["branch"], b.get("side"))
                branches[key] = branches.get(key, _ZERO) + sign * _dec(b.get("amount"))
    if is_correction:
        branches = {k: v for k, v in branches.items() if v != 0}
    housing = _dec(res.get("infonavit_employer")) - _dec(base.get("infonavit_employer"))
    credit = _dec(res.get("infonavit_credit")) - _dec(base.get("infonavit_credit"))
    if (branches or keep(housing) or keep(credit)) and reg is None:
        skips.append({"employeeId": item.employee_id, "payslipItemId": item.id, "code": "MX_REGISTRATION_MISSING",
                      "message": "no ACTIVE IMSS registration in force on the pay date — IMSS / INFONAVIT not accrued"})
    elif reg is not None:
        for (branch, side), amount in branches.items():
            table = f"imss:{branch}:{side or '-'}"[:40]
            out.append(("IMSS", reg.id, None, table, item.id, branch, side, None, amount))
        if keep(housing):
            out.append(("INFONAVIT", reg.id, None, _SRC_HOUSING, item.id, "INFONAVIT", "employer", None, housing))
        if keep(credit):
            out.append(("INFONAVIT", reg.id, None, _SRC_CREDIT, item.id, "INFONAVIT_CREDIT", "employee", None,
                        credit))
    isr = _dec(res.get("isr_withheld")) - _dec(base.get("isr_withheld"))
    if keep(isr):
        out.append(("SAT_ISR", None, None, _SRC_ISR, item.id, "ISR", "employee",
                    _dec(res.get("isr_taxable")) - _dec(base.get("isr_taxable")), isr))
    for isn in db.query(m.PayrollMxIsnLiability).filter(m.PayrollMxIsnLiability.payslip_item_id == item.id):
        out.append(("ISN", None, isn.state_code, _SRC_ISN, isn.id, "ISN", "employer", isn.base_amount, isn.amount))
    return out, skips


def accrue(db: Session, org_id: int, actor_id: Optional[int] = None) -> dict:
    """Link every committed row not yet in the ledger. Idempotent: a second
    call adds nothing (uq source row)."""
    guard(db, org_id)
    m = L.models()
    S = m.PayrollMxAuthorityLiabilitySource
    linked = {(t, i) for t, i in db.query(S.source_table, S.source_row_id).filter(S.organization_id == org_id)}
    touched, added, skipped = {}, 0, []
    for run in committed_runs(db, org_id):
        period_key = run.pay_date.strftime("%Y-%m")
        for item in _items(db, run):
            cands, skips = _candidate_sources(db, run, item)
            skipped += skips
            for authority, reg_id, state, table, row_id, branch, side, base, amount in cands:
                if (table, row_id) in linked:
                    continue
                liab = _open_liability(db, org_id, authority, period_key, reg_id, state)
                db.add(S(liability_id=liab.id, organization_id=org_id, payroll_run_id=run.id, payslip_item_id=item.id,
                         employee_id=item.employee_id, source_table=table, source_row_id=row_id, branch_code=branch,
                         side=side, base_amount=base, amount=_dec(amount)))
                linked.add((table, row_id))
                touched[liab.id] = liab
                added += 1
    db.flush()
    for liab in touched.values():
        _recompute(db, liab)
    _refresh_due_dates(db, org_id)
    db.commit()
    return {"sourcesAdded": added, "liabilitiesTouched": len(touched), "skipped": skipped}


def _refresh_due_dates(db: Session, org_id: int) -> None:
    """A calendar row activated later dates liabilities / returns that had none."""
    m = L.models()
    for liab in db.query(m.PayrollMxAuthorityLiability).filter(
            m.PayrollMxAuthorityLiability.organization_id == org_id, m.PayrollMxAuthorityLiability.due_date.is_(None)):
        liab.due_date, liab.due_rule_ref = due.liability_due(db, liab.authority, liab.period_key, liab.state_code)
    for ret in db.query(m.PayrollMxIsnReturn).filter(m.PayrollMxIsnReturn.organization_id == org_id,
                                                     m.PayrollMxIsnReturn.due_date.is_(None)):
        ret.due_date, ret.due_rule_ref = due.liability_due(db, "ISN", ret.period_key, ret.state_code)


def _liability(db: Session, org_id: int, liability_id: int):
    return L.load(db, "LIABILITY", org_id, liability_id)


def file_liability(db: Session, org_id: int, liability_id: int, reference: str, actor_id, evidence_ref=None) -> dict:
    """Record the declaration (ISR monthly remittance, IMSS / INFONAVIT via
    SUA, ISN via its return) as filed, with the authority's reference."""
    guard(db, org_id)
    liab = _liability(db, org_id, liability_id)
    if liab.authority == "ISN":
        raise BadRequestException("An ISN liability is filed through its state return (ISN returns)")
    if liab.status not in ("ACCRUED",):
        raise BadRequestException(f"Only an ACCRUED liability can be filed (this one is {liab.status})")
    if liab.amount is None or _dec(liab.amount) <= 0:
        raise BadRequestException("Nothing to file — the liability has no committed amount")
    ref = L.require_reference(reference, "Filing a liability")
    L.freeze("LIABILITY", liab)
    liab.declaration_reference, liab.filed_by_id = ref, actor_id
    if evidence_ref:
        liab.evidence_ref = evidence_ref[:200]
    L.transition(db, org_id, "LIABILITY", liab, "FILED", "FILED", actor_id, {"reference": ref})
    db.commit()
    return liability_view(db, liab)


def pay_liability(db: Session, org_id: int, liability_id: int, reference: str, actor_id, evidence_ref=None) -> dict:
    """Record a payment made OUTSIDE Zoiko (no money moves here — Phase 10)."""
    guard(db, org_id)
    liab = _liability(db, org_id, liability_id)
    if liab.status != "FILED":
        raise BadRequestException(f"Only a FILED liability can be recorded as paid (this one is {liab.status})")
    ref = L.require_reference(reference, "Recording a payment")
    liab.payment_reference, liab.paid_by_id = ref, actor_id
    if evidence_ref:
        liab.evidence_ref = evidence_ref[:200]
    L.transition(db, org_id, "LIABILITY", liab, "PAID", "PAYMENT_RECORDED", actor_id, {"reference": ref})
    db.commit()
    return liability_view(db, liab)


def reconcile_liability(db: Session, org_id: int, liability_id: int, actor_id) -> dict:
    guard(db, org_id)
    m = L.models()
    liab = _liability(db, org_id, liability_id)
    if liab.status != "PAID":
        raise BadRequestException(f"Only a PAID liability can be reconciled (this one is {liab.status})")
    L.require_different(actor_id, liab.paid_by_id, "Reconciling a liability (after its payment was recorded)", org_id)
    if liab.authority in ("IMSS", "INFONAVIT"):
        sua = (db.query(m.PayrollMxSuaPeriod).filter(m.PayrollMxSuaPeriod.organization_id == org_id,
                                                     m.PayrollMxSuaPeriod.registration_id == liab.registration_id,
                                                     m.PayrollMxSuaPeriod.period_key == liab.period_key).first())
        if sua is None or sua.status not in ("RECONCILED", "PAID"):
            raise MXBlock("MX_SUA_NOT_RECONCILED", "IMSS / INFONAVIT reconcile only against a RECONCILED SUA period "
                                                   "for the same registration and month (MX-033)", org_id)
    if liab.authority == "ISN":
        ret = _latest_return(db, org_id, liab.state_code, liab.period_key)
        if ret is None or ret.status != "ACCEPTED":
            raise MXBlock("MX_ISN_RETURN_NOT_ACCEPTED", "an ISN liability reconciles only against its ACCEPTED "
                                                        "state return", org_id)
    liab.reconciled_by_id = actor_id
    L.transition(db, org_id, "LIABILITY", liab, "RECONCILED", "RECONCILED", actor_id)
    db.commit()
    return liability_view(db, liab)


def liability_view(db: Session, liab, with_sources: bool = False) -> dict:
    m = L.models()
    out = {"id": liab.id, "authority": liab.authority, "registrationId": liab.registration_id,
           "stateCode": liab.state_code, "periodKey": liab.period_key, "sequence": liab.sequence,
           "complementary": liab.sequence > 0, "amount": _s(liab.amount), "components": liab.components or {},
           "dueDate": liab.due_date.isoformat() if liab.due_date else None, "dueRule": liab.due_rule_ref,
           "dueState": due.due_state(liab.due_date, liab.status in ("FILED", "PAID", "RECONCILED", "WITHDRAWN")),
           "status": liab.status, "declarationReference": liab.declaration_reference,
           "paymentReference": liab.payment_reference, "evidenceRef": liab.evidence_ref,
           "payloadHash": liab.payload_hash, "idempotencyKey": liab.idempotency_key,
           "unknown": L.unknown_view(db, "LIABILITY", liab)}
    if with_sources:
        S = m.PayrollMxAuthorityLiabilitySource
        out["sources"] = [{"id": s.id, "runId": s.payroll_run_id, "payslipItemId": s.payslip_item_id,
                           "employeeId": s.employee_id, "branch": s.branch_code, "side": s.side,
                           "base": _s(s.base_amount), "amount": _s(s.amount), "table": s.source_table}
                          for s in db.query(S).filter(S.liability_id == liab.id).order_by(S.id)]
        out["events"] = L.event_views(db, "LIABILITY", liab)
    return out


def list_liabilities(db: Session, org_id: int, period_key: Optional[str] = None) -> list:
    m = L.models()
    A = m.PayrollMxAuthorityLiability
    q = db.query(A).filter(A.organization_id == org_id)
    if period_key:
        q = q.filter(A.period_key == period_key)
    return [liability_view(db, r) for r in q.order_by(A.period_key.desc(), A.authority, A.scope_key, A.sequence)]


# ── B4: SUA reconciliation ──────────────────────────────────────────────────

def _zoiko_totals(db: Session, org_id: int, registration_id: int, period_key: str) -> dict:
    """{"<employee>|<branch>:<side>": amount} from every IMSS / INFONAVIT source."""
    m = L.models()
    A, S = m.PayrollMxAuthorityLiability, m.PayrollMxAuthorityLiabilitySource
    out = defaultdict(lambda: _ZERO)
    q = (db.query(S).join(A, A.id == S.liability_id)
         .filter(A.organization_id == org_id, A.registration_id == registration_id, A.period_key == period_key,
                 A.authority.in_(("IMSS", "INFONAVIT")), A.status != "WITHDRAWN"))
    for src in q:
        out[f"{src.employee_id}|{src.branch_code}:{src.side or '-'}"] += _dec(src.amount)
    return {k: str(v) for k, v in sorted(out.items())}


def open_sua_period(db: Session, org_id: int, registration_id: int, period_key: str, actor_id) -> dict:
    guard(db, org_id)
    m = L.models()
    reg = db.get(m.PayrollMxImssRegistration, registration_id)
    if reg is None or reg.organization_id != org_id:
        raise BadRequestException("IMSS registration not found for this organisation")
    P = m.PayrollMxSuaPeriod
    row = db.query(P).filter(P.organization_id == org_id, P.registration_id == registration_id,
                             P.period_key == period_key).first()
    if row is None:
        totals = _zoiko_totals(db, org_id, registration_id, period_key)
        if not totals:
            raise BadRequestException("No committed IMSS / INFONAVIT amounts for this registration and month — "
                                      "accrue the liabilities first")
        row = P(organization_id=org_id, registration_id=registration_id, period_key=period_key, zoiko_totals=totals,
                status="DRAFT", created_by_id=actor_id,
                idempotency_key=L.idempotency_key("mxsua", org_id, registration_id, period_key))
        db.add(row)
        db.flush()
        L.event(db, org_id, "SUA_PERIOD", row, "OPENED", actor_id, {"keys": len(totals)}, None, "DRAFT")
        db.commit()
    elif row.status == "WITHDRAWN":
        totals = _zoiko_totals(db, org_id, registration_id, period_key)
        if not totals:
            raise BadRequestException("No committed IMSS / INFONAVIT amounts for this registration and month")
        row.zoiko_totals, row.sua_totals, row.difference_total = totals, None, None
        _rebuild_differences(db, row)
        L.transition(db, org_id, "SUA_PERIOD", row, "DRAFT", "REOPENED", actor_id)
        db.commit()
    return sua_view(db, row, detail=True)


def _sua(db: Session, org_id: int, period_id: int):
    return L.load(db, "SUA_PERIOD", org_id, period_id)


def _rebuild_differences(db: Session, period) -> None:
    m = L.models()
    D = m.PayrollMxSuaDifference
    db.query(D).filter(D.sua_period_id == period.id).delete(synchronize_session=False)
    if period.sua_totals is None:                      # no SUA figures yet: nothing to compare
        period.difference_total = None
        return
    zoiko, sua = period.zoiko_totals or {}, period.sua_totals
    total = _ZERO
    for key in sorted(set(zoiko) | set(sua)):
        z, s = _dec(zoiko.get(key)), _dec(sua.get(key))
        if z == s:                                     # zero tolerance (D5): only exact matches pass
            continue
        employee_id, branch = key.split("|", 1)
        db.add(D(sua_period_id=period.id, employee_id=int(employee_id), branch_code=branch, zoiko_amount=z,
                 sua_amount=s, difference=z - s, status="OPEN"))
        total += abs(z - s)
    period.difference_total = total


def enter_sua_figures(db: Session, org_id: int, period_id: int, rows: list, sua_version: Optional[str],
                      actor_id) -> dict:
    """The operator's SUA figures through the Zoiko template (D5) — one row per
    worker × branch × side. Replaces earlier figures (and their differences)."""
    guard(db, org_id)
    period = _sua(db, org_id, period_id)
    if period.status != "DRAFT":
        raise BadRequestException(f"SUA figures can only be entered on a DRAFT period (this one is {period.status})")
    if not isinstance(rows, list) or not rows:
        raise BadRequestException("Enter at least one SUA figure (employeeId, branch, side, amount)")
    figures = {}
    for r in rows:
        try:
            key = f"{int(r['employeeId'])}|{str(r['branch']).strip()}:{(str(r.get('side') or '-')).strip()}"
            amount = Decimal(str(r["amount"]))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise BadRequestException("Each SUA figure needs employeeId, branch, side and a numeric amount")
        if key in figures:
            raise BadRequestException(f"Duplicate SUA figure for {key}")
        figures[key] = str(amount)
    period.zoiko_totals = _zoiko_totals(db, org_id, period.registration_id, period.period_key)
    period.sua_totals = figures
    period.sua_version = (sua_version or "").strip()[:20] or None
    period.figures_entered_by_id, period.figures_entered_at = actor_id, L.now()
    _rebuild_differences(db, period)
    db.flush()
    L.event(db, org_id, "SUA_PERIOD", period, "SUA_FIGURES_ENTERED", actor_id,
            {"rows": len(figures), "suaVersion": period.sua_version, "differenceTotal": _s(period.difference_total)})
    db.commit()
    return sua_view(db, period, detail=True)


def explain_difference(db: Session, org_id: int, difference_id: int, code: str, explanation: str, actor_id) -> dict:
    guard(db, org_id)
    diff = L.load(db, "SUA_DIFFERENCE", org_id, difference_id)
    period = _sua(db, org_id, diff.sua_period_id)
    if period.status != "DRAFT":
        raise BadRequestException("The SUA period is no longer DRAFT")
    if (code or "").strip() not in EXPLANATION_CODES:
        raise BadRequestException(f"Explanation code must be one of {', '.join(EXPLANATION_CODES)}")
    text = (explanation or "").strip()
    if not text:
        raise BadRequestException("A difference needs a written explanation")
    if diff.status != "OPEN":
        raise BadRequestException(f"Only an OPEN difference can be explained (this one is {diff.status})")
    diff.explanation_code, diff.explanation, diff.explained_by_id = code.strip(), text[:500], actor_id
    L.transition(db, org_id, "SUA_DIFFERENCE", diff, "EXPLAINED", "EXPLAINED", actor_id, {"code": diff.explanation_code})
    db.commit()
    return sua_view(db, period, detail=True)


def approve_difference(db: Session, org_id: int, difference_id: int, actor_id) -> dict:
    guard(db, org_id)
    diff = L.load(db, "SUA_DIFFERENCE", org_id, difference_id)
    period = _sua(db, org_id, diff.sua_period_id)
    if diff.status != "EXPLAINED":
        raise BadRequestException(f"Only an EXPLAINED difference can be approved (this one is {diff.status})")
    L.require_different(actor_id, diff.explained_by_id, "Approving a SUA difference explanation", org_id)
    diff.approved_by_id = actor_id
    L.transition(db, org_id, "SUA_DIFFERENCE", diff, "APPROVED", "APPROVED", actor_id)
    db.commit()
    return sua_view(db, period, detail=True)


def reconcile_sua(db: Session, org_id: int, period_id: int, actor_id) -> dict:
    guard(db, org_id)
    m = L.models()
    period = _sua(db, org_id, period_id)
    if period.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT SUA period can be reconciled (this one is {period.status})")
    if period.sua_totals is None:
        raise MXBlock("MX_SUA_FIGURES_MISSING", "enter the SUA figures first", org_id)
    if _zoiko_totals(db, org_id, period.registration_id, period.period_key) != (period.zoiko_totals or {}):
        raise MXBlock("MX_SUA_STALE", "committed amounts changed since the SUA figures were entered — "
                                      "re-enter the figures", org_id)
    D = m.PayrollMxSuaDifference
    blocking = db.query(D).filter(D.sua_period_id == period.id, D.status != "APPROVED").count()
    if blocking:
        raise MXBlock("MX_SUA_DIFFERENCES_OPEN", f"{blocking} difference(s) not explained and approved — "
                                                 "differences are BLOCKING until then (MX-033)", org_id)
    L.require_different(actor_id, period.figures_entered_by_id, "Reconciling a SUA period", org_id)
    period.reconciled_by_id, period.reconciled_at = actor_id, L.now()
    L.transition(db, org_id, "SUA_PERIOD", period, "RECONCILED", "RECONCILED", actor_id)
    db.commit()
    return sua_view(db, period, detail=True)


def record_sua_payment(db: Session, org_id: int, period_id: int, reference: str, capture_line: Optional[str],
                       actor_id, evidence_ref=None) -> dict:
    """SIPARE payment made OUTSIDE Zoiko (layout X1, bank Phase 10)."""
    guard(db, org_id)
    period = _sua(db, org_id, period_id)
    if period.status != "RECONCILED":
        raise BadRequestException(f"Only a RECONCILED SUA period can be recorded as paid (this one is {period.status})")
    ref = L.require_reference(reference, "Recording a SUA / SIPARE payment")
    L.freeze("SUA_PERIOD", period)
    period.payment_reference = ref
    period.capture_line = (capture_line or "").strip()[:60] or None
    if evidence_ref:
        period.evidence_ref = evidence_ref[:200]
    L.transition(db, org_id, "SUA_PERIOD", period, "PAID", "PAYMENT_RECORDED", actor_id, {"reference": ref})
    db.commit()
    return sua_view(db, period, detail=True)


def sua_view(db: Session, period, detail: bool = False) -> dict:
    m = L.models()
    D = m.PayrollMxSuaDifference
    diffs = db.query(D).filter(D.sua_period_id == period.id).order_by(D.id).all()
    out = {"id": period.id, "registrationId": period.registration_id, "periodKey": period.period_key,
           "suaVersion": period.sua_version, "status": period.status,
           "differenceTotal": _s(period.difference_total), "figuresEntered": period.sua_totals is not None,
           "openDifferences": sum(1 for d in diffs if d.status != "APPROVED"), "differences": len(diffs),
           "captureLine": period.capture_line, "paymentReference": period.payment_reference,
           "unknown": L.unknown_view(db, "SUA_PERIOD", period)}
    if detail:
        out["zoikoTotals"] = period.zoiko_totals or {}
        out["suaTotals"] = period.sua_totals or {}
        out["differenceRows"] = [{"id": d.id, "employeeId": d.employee_id, "branch": d.branch_code,
                                  "zoiko": _s(d.zoiko_amount), "sua": _s(d.sua_amount), "difference": _s(d.difference),
                                  "status": d.status, "code": d.explanation_code, "explanation": d.explanation,
                                  "explainedById": d.explained_by_id, "approvedById": d.approved_by_id}
                                 for d in diffs]
        out["events"] = L.event_views(db, "SUA_PERIOD", period)
        out["explanationCodes"] = list(EXPLANATION_CODES)
    return out


def list_sua_periods(db: Session, org_id: int) -> list:
    m = L.models()
    P = m.PayrollMxSuaPeriod
    return [sua_view(db, p) for p in db.query(P).filter(P.organization_id == org_id)
            .order_by(P.period_key.desc(), P.registration_id)]


# ── B5: state ISN returns ───────────────────────────────────────────────────

def _latest_return(db: Session, org_id: int, state: str, period_key: str):
    m = L.models()
    R = m.PayrollMxIsnReturn
    return (db.query(R).filter(R.organization_id == org_id, R.state_code == state, R.period_key == period_key)
            .order_by(R.sequence.desc()).first())


def _isn_figures(db: Session, org_id: int, state: str, period_key: str) -> tuple:
    """(base, amount, latest live liability) over every non-withdrawn ISN liability of the state × month."""
    m = L.models()
    A, S = m.PayrollMxAuthorityLiability, m.PayrollMxAuthorityLiabilitySource
    liabs = (db.query(A).filter(A.organization_id == org_id, A.authority == "ISN", A.state_code == state,
                                A.period_key == period_key, A.status != "WITHDRAWN").order_by(A.sequence).all())
    base = amount = _ZERO
    for liab in liabs:
        for src in db.query(S).filter(S.liability_id == liab.id):
            base += _dec(src.base_amount)
            amount += _dec(src.amount)
    return base, amount, (liabs[-1] if liabs else None)


def _isn_registration(db: Session, org_id: int, state: str, period_key: str):
    from datetime import date

    m = L.models()
    R = m.PayrollMxIsnRegistration
    year, month = (int(p) for p in period_key.split("-"))
    first = date(year, month, 1)
    for reg in db.query(R).filter(R.organization_id == org_id, R.state_code == state, R.status == "OPEN"):
        if reg.effective_from <= first and (reg.effective_to is None or reg.effective_to >= first):
            return reg
    return None


def draft_isn_return(db: Session, org_id: int, state: str, period_key: str, actor_id) -> dict:
    guard(db, org_id)
    m = L.models()
    state = (state or "").strip().upper()
    reg = _isn_registration(db, org_id, state, period_key)
    if reg is None:
        raise MXBlock("MX_ISN_REGISTRATION_MISSING", f"no OPEN ISN registration in {state} for {period_key}", org_id)
    base, amount, liab = _isn_figures(db, org_id, state, period_key)
    if liab is None:
        raise BadRequestException(f"No committed ISN liability for {state} {period_key} — accrue first")
    latest = _latest_return(db, org_id, state, period_key)
    if latest is not None and latest.status in ("DRAFT", "WITHDRAWN") and latest.payload_hash is None:
        if latest.status == "WITHDRAWN":
            L.transition(db, org_id, "ISN_RETURN", latest, "DRAFT", "REDRAFTED", actor_id)
        latest.base_total, latest.amount, latest.liability_id = base, amount, liab.id
        L.event(db, org_id, "ISN_RETURN", latest, "REFRESHED", actor_id, {"amount": str(amount)})
        db.commit()
        return isn_view(db, latest, detail=True)
    if latest is not None and latest.status in ("DRAFT", "UNKNOWN", "FILED"):
        raise BadRequestException(f"The {state} {period_key} return is {latest.status} — record its outcome first")
    seq = (latest.sequence + 1) if latest is not None else 0
    due_date, rule = due.liability_due(db, "ISN", period_key, state)
    ret = m.PayrollMxIsnReturn(
        organization_id=org_id, isn_registration_id=reg.id, liability_id=liab.id, state_code=state,
        period_key=period_key, sequence=seq, base_total=base, amount=amount, due_date=due_date, due_rule_ref=rule,
        status="DRAFT", amendment_of_id=latest.id if latest is not None else None, created_by_id=actor_id,
        idempotency_key=L.idempotency_key("mxisn", org_id, state, period_key, seq))
    db.add(ret)
    db.flush()
    L.event(db, org_id, "ISN_RETURN", ret, "AMENDMENT_DRAFTED" if latest is not None else "DRAFTED", actor_id,
            {"amendmentOf": ret.amendment_of_id, "amount": str(amount)}, None, "DRAFT")
    db.commit()
    return isn_view(db, ret, detail=True)


def isn_reconciliation(db: Session, ret) -> dict:
    """MX-046: employee / location detail -> return -> ledger, all three."""
    m = L.models()
    A, S, I = m.PayrollMxAuthorityLiability, m.PayrollMxAuthorityLiabilitySource, m.PayrollMxIsnLiability
    ledger = _ZERO
    detail = defaultdict(lambda: _ZERO)
    for src in (db.query(S).join(A, A.id == S.liability_id)
                .filter(A.organization_id == ret.organization_id, A.authority == "ISN",
                        A.state_code == ret.state_code, A.period_key == ret.period_key, A.status != "WITHDRAWN")):
        ledger += _dec(src.amount)
        row = db.get(I, src.source_row_id)
        detail[src.employee_id] += _dec(row.amount) if row is not None else _ZERO
    detail_total = sum(detail.values(), _ZERO)
    return {"detailTotal": str(detail_total), "returnAmount": str(_dec(ret.amount)), "ledgerTotal": str(ledger),
            "byEmployee": {str(k): str(v) for k, v in sorted(detail.items())},
            "matches": detail_total == _dec(ret.amount) == ledger}


def _return(db: Session, org_id: int, return_id: int):
    return L.load(db, "ISN_RETURN", org_id, return_id)


def file_isn_return(db: Session, org_id: int, return_id: int, reference: str, actor_id, evidence_ref=None) -> dict:
    guard(db, org_id)
    ret = _return(db, org_id, return_id)
    if ret.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT return can be filed (this one is {ret.status})")
    rec = isn_reconciliation(db, ret)
    if not rec["matches"]:
        raise MXBlock("MX_ISN_RETURN_UNRECONCILED", "the return does not equal its employee detail and ledger — "
                                                     "refresh the draft (MX-046)", org_id)
    ref = L.require_reference(reference, "Filing an ISN return")
    L.freeze("ISN_RETURN", ret)
    ret.filing_reference, ret.filed_by_id = ref, actor_id
    if evidence_ref:
        ret.evidence_ref = evidence_ref[:200]
    L.transition(db, org_id, "ISN_RETURN", ret, "FILED", "FILED", actor_id, {"reference": ref})
    _file_isn_liabilities(db, org_id, ret, ref, actor_id)
    db.commit()
    return isn_view(db, ret, detail=True)


def _file_isn_liabilities(db: Session, org_id: int, ret, ref: str, actor_id) -> None:
    """Filing the return files the state × month liabilities it covers."""
    m = L.models()
    A = m.PayrollMxAuthorityLiability
    for liab in db.query(A).filter(A.organization_id == org_id, A.authority == "ISN", A.state_code == ret.state_code,
                                   A.period_key == ret.period_key, A.status.in_(("ACCRUED", "UNKNOWN"))):
        if liab.status == "ACCRUED":
            L.freeze("LIABILITY", liab)
        liab.declaration_reference, liab.filed_by_id = ref, actor_id
        L.transition(db, org_id, "LIABILITY", liab, "FILED", "FILED_BY_RETURN", actor_id, {"returnId": ret.id})


def record_isn_outcome(db: Session, org_id: int, return_id: int, outcome: str, actor_id) -> dict:
    guard(db, org_id)
    ret = _return(db, org_id, return_id)
    outcome = (outcome or "").upper()
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise BadRequestException("Outcome must be ACCEPTED or REJECTED")
    if ret.status != "FILED":
        raise BadRequestException(f"Only a FILED return has an outcome (this one is {ret.status})")
    if outcome == "ACCEPTED":
        L.require_different(actor_id, ret.filed_by_id, "Recording an ISN return as ACCEPTED", org_id)
    ret.outcome_by_id = actor_id
    L.transition(db, org_id, "ISN_RETURN", ret, outcome, outcome, actor_id)
    db.commit()
    return isn_view(db, ret, detail=True)


def isn_view(db: Session, ret, detail: bool = False) -> dict:
    out = {"id": ret.id, "stateCode": ret.state_code, "periodKey": ret.period_key, "sequence": ret.sequence,
           "amendmentOfId": ret.amendment_of_id, "baseTotal": _s(ret.base_total), "amount": _s(ret.amount),
           "dueDate": ret.due_date.isoformat() if ret.due_date else None, "dueRule": ret.due_rule_ref,
           "dueState": due.due_state(ret.due_date, ret.status in ("FILED", "ACCEPTED", "WITHDRAWN")),
           "status": ret.status, "filingReference": ret.filing_reference, "liabilityId": ret.liability_id,
           "unknown": L.unknown_view(db, "ISN_RETURN", ret)}
    if detail:
        out["reconciliation"] = isn_reconciliation(db, ret)
        out["events"] = L.event_views(db, "ISN_RETURN", ret)
    return out


def list_isn_returns(db: Session, org_id: int) -> list:
    m = L.models()
    R = m.PayrollMxIsnReturn
    return [isn_view(db, r) for r in db.query(R).filter(R.organization_id == org_id)
            .order_by(R.period_key.desc(), R.state_code, R.sequence)]


# ── B8: reset registration and the run's Authorities lane ───────────────────

def _run_liabilities(db: Session, run) -> list:
    m = L.models()
    A, S = m.PayrollMxAuthorityLiability, m.PayrollMxAuthorityLiabilitySource
    ids = {lid for (lid,) in db.query(S.liability_id).filter(S.payroll_run_id == run.id)}
    return db.query(A).filter(A.id.in_(ids)).all() if ids else []


def downstream_reasons(db: Session, run) -> list:
    """Why a reset of this committed run is refused (plan §6)."""
    m = L.models()
    reasons = []
    for mv in db.query(m.PayrollMxImssMovement).filter(m.PayrollMxImssMovement.payroll_run_id == run.id):
        if mv.status in ("EXPORTED", "FILED", "ACCEPTED", "REJECTED", "UNKNOWN") or mv.payload_hash:
            reasons.append(f"IMSS movement {mv.id} ({mv.movement_type}) is {mv.status}")
    liabs = _run_liabilities(db, run)
    for liab in liabs:
        if liab.status not in ("ACCRUED", "WITHDRAWN") or liab.payload_hash:
            reasons.append(f"{liab.authority} liability {liab.period_key} #{liab.sequence} is {liab.status}")
        if liab.authority in ("IMSS", "INFONAVIT"):
            sua = (db.query(m.PayrollMxSuaPeriod).filter(m.PayrollMxSuaPeriod.organization_id == run.organization_id,
                                                         m.PayrollMxSuaPeriod.registration_id == liab.registration_id,
                                                         m.PayrollMxSuaPeriod.period_key == liab.period_key).first())
            if sua is not None and sua.status in ("RECONCILED", "PAID", "UNKNOWN"):
                reasons.append(f"SUA period {sua.period_key} (registration {sua.registration_id}) is {sua.status}")
        if liab.authority == "ISN":
            R = m.PayrollMxIsnReturn
            for ret in db.query(R).filter(R.organization_id == run.organization_id, R.state_code == liab.state_code,
                                          R.period_key == liab.period_key):
                if ret.status not in ("DRAFT", "WITHDRAWN") or ret.payload_hash:
                    reasons.append(f"ISN return {ret.state_code} {ret.period_key} #{ret.sequence} is {ret.status}")
    return sorted(set(reasons))


def withdraw_on_reset(db: Session, run, actor_id) -> dict:
    """An allowed reset (nothing acted): void the run's PENDING movements,
    unlink its liability sources and recompute what they fed. Runs BEFORE the
    run's ledgers are deleted."""
    m = L.models()
    org_id = run.organization_id
    voided = 0
    for mv in db.query(m.PayrollMxImssMovement).filter(m.PayrollMxImssMovement.payroll_run_id == run.id,
                                                       m.PayrollMxImssMovement.status == "PENDING"):
        L.transition(db, org_id, "MOVEMENT", mv, "VOIDED", "VOIDED_ON_RESET", actor_id)
        voided += 1
    liabs = _run_liabilities(db, run)
    S = m.PayrollMxAuthorityLiabilitySource
    removed = db.query(S).filter(S.payroll_run_id == run.id).delete(synchronize_session=False)
    db.flush()
    for liab in liabs:
        _recompute(db, liab)
        if not db.query(S).filter(S.liability_id == liab.id).count():
            L.transition(db, org_id, "LIABILITY", liab, "WITHDRAWN", "WITHDRAWN_ON_RESET", actor_id)
    db.flush()                                    # autoflush is off: the queries below must see the withdrawals
    for liab in liabs:
        if liab.authority == "ISN":
            ret = _latest_return(db, org_id, liab.state_code, liab.period_key)
            if ret is not None and ret.status == "DRAFT" and ret.payload_hash is None:
                base, amount, live = _isn_figures(db, org_id, liab.state_code, liab.period_key)
                if live is None:
                    L.transition(db, org_id, "ISN_RETURN", ret, "WITHDRAWN", "WITHDRAWN_ON_RESET", actor_id)
                else:
                    ret.base_total, ret.amount, ret.liability_id = base, amount, live.id
        if liab.authority in ("IMSS", "INFONAVIT"):
            P = m.PayrollMxSuaPeriod
            sua = db.query(P).filter(P.organization_id == org_id, P.registration_id == liab.registration_id,
                                     P.period_key == liab.period_key, P.status == "DRAFT").first()
            if sua is not None:
                sua.zoiko_totals = _zoiko_totals(db, org_id, liab.registration_id, liab.period_key)
                if not sua.zoiko_totals:
                    L.transition(db, org_id, "SUA_PERIOD", sua, "WITHDRAWN", "WITHDRAWN_ON_RESET", actor_id)
                elif sua.sua_totals is not None:
                    _rebuild_differences(db, sua)
    return {"movementsVoided": voided, "liabilitySourcesRemoved": removed}


def run_lane(db: Session, run) -> dict:
    """The run's "Authorities" badge (MX-041): its own lifecycle only."""
    m = L.models()
    liabs = [l for l in _run_liabilities(db, run) if l.status != "WITHDRAWN"]
    moves = [mv for mv in db.query(m.PayrollMxImssMovement).filter(m.PayrollMxImssMovement.payroll_run_id == run.id)
             if mv.status not in ("VOIDED", "WITHDRAWN")]
    if not liabs and not moves:
        return {"status": "NOT_STARTED", "detail": "no authority liability or IMSS movement includes this run yet"}
    states = {l.status for l in liabs} | {mv.status for mv in moves}
    counts = defaultdict(int)
    for l in liabs:
        counts[f"{l.authority} {l.status}"] += 1
    detail = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    if moves:
        detail += (", " if detail else "") + f"movements: {len(moves)}"
    if "UNKNOWN" in states:
        status = "UNKNOWN"
    elif liabs and all(l.status == "RECONCILED" for l in liabs) and all(mv.status == "ACCEPTED" for mv in moves):
        status = "RECONCILED"
    elif liabs and all(l.status in ("PAID", "RECONCILED") for l in liabs):
        status = "PAID"
    elif states - {"ACCRUED", "PENDING"}:
        status = "IN_PROGRESS"
    else:
        status = "ACCRUED"
    return {"status": status, "detail": detail}
