"""New Zealand payday filing (ZP-NZ-ENG-001 Phase 8; spec §9, NZ-018, NZ-019;
gate G3; decisions D-P8-2..4).

  records    one per legal employer, payday and schedule — Employment
             Information (EI: every employee paid that payday, summed across
             the payday's PAID runs) and Employee Details (ED: starters and
             leavers from the employment instances). Generated only from
             frozen PAID payslips; never edited by hand. IRD numbers appear as
             the vault id and masked form only (D-P8-4).
  versions   a DRAFT is regenerated in place; once APPROVED a change makes a
             new version (the old one SUPERSEDED); once SUBMITTED / ACCEPTED a
             change becomes an AMENDMENT. Same payload hash -> nothing happens
             (NZ-018). A correction (P6) becomes an AMENDMENT of the original
             payday (D-P8-3).
  due date   payday + the signed number of working days (electronic or paper),
             a working day per the signed rule (D-P8-2) with the signed
             national public holidays; unsigned -> due_on stays empty.
  submit     refused while content.NZ_EXPORT_SCHEMAS is empty (G3, D-3): only
             the JSON preview exists. An authority response never touches a
             remittance (NZ-019) and a rejection leaves payroll unchanged.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_remittance as rem

WORKING_DAY_RULE = "WEEKDAYS_EXCL_PUBLIC_HOLIDAYS_AND_25DEC_15JAN"
EI, ED = "EMPLOYMENT_INFORMATION", "EMPLOYEE_DETAILS"
PAID_STATUSES = ("Paid", "Closed")
EI_FIELDS = (("grossEarnings", "accumulatorDeltas", "PAYE_GROSS"), ("payeIncludingAcc", "obligations", "payeTotal"),
             ("studentLoan", "obligations", "studentLoan"), ("ksEmployee", "obligations", "ksEmployee"),
             ("ksEmployerNet", "obligations", "ksEmployerNet"), ("esct", "obligations", "esct"),
             ("childSupport", "obligations", "childSupport"))
ZERO = Decimal("0")


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"New Zealand ({code}): {message}")


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


# ── due date (pure + content) ───────────────────────────────────────────────
def _christmas_period(day: date) -> bool:
    return (day.month == 12 and day.day >= 25) or (day.month == 1 and day.day <= 15)


def nz_working_days_after(start: date, n: int, holidays: set, rule: str) -> date:
    """The n-th working day after `start` under the signed rule: weekdays, not
    a public holiday, not 25 December – 15 January."""
    if rule != WORKING_DAY_RULE:
        raise ValueError(f"unknown working-day rule {rule!r}")
    day, counted = start, 0
    while counted < n:
        day += timedelta(days=1)
        if day.weekday() >= 5 or day in holidays or _christmas_period(day):
            continue
        counted += 1
    return day


def _national_holidays(db: Session, year: int) -> Optional[set]:
    """Signed national public holidays of `year` from the in-force packs; None
    when the year has none (the deadline is then not computed)."""
    content = nzs._content()
    days = set()
    for on in (date(year, 1, 1), date(year, 12, 31)):
        _rate_map, slabs, _pack = nzs._nz_pack_in_force(db, on)
        for row in slabs or []:
            if (row.rule_type or "").upper() != content.NZ_PUBLIC_HOLIDAY_RULE or row.jurisdiction_state:
                continue
            if rem.MARK in (row.rate_label or "") or row.effective_from is None or row.effective_from.year != year:
                continue
            days.add(row.effective_from)
    return days or None


def filing_due_on(db: Session, pay_date: date, channel: str) -> Optional[date]:
    rate_map, _slabs, _pack = nzs._nz_pack_in_force(db, pay_date)
    rule = rem.signed_text(rate_map, "nz_working_day_rule")
    key = "nz_paper_filing_working_days" if channel == "PAPER" else "nz_payday_filing_working_days"
    days = rem.signed_amount(rate_map, key)
    if rule != WORKING_DAY_RULE or days is None:
        return None
    holidays = set()
    for year in {pay_date.year, pay_date.year + 1}:
        found = _national_holidays(db, year)
        if found is None and year == pay_date.year:
            return None
        holidays |= found or set()
    return nz_working_days_after(pay_date, int(days), holidays, rule)


# ── payloads ────────────────────────────────────────────────────────────────
def _ird(db: Session, organization_id: int, employee_id: int) -> dict:
    m = nzs._nz_models()
    V = m.PayrollNzIrdVault
    row = (db.query(V).filter(V.organization_id == organization_id, V.employee_id == employee_id,
                              V.status == "ACTIVE").first())
    view = nzs.nz_ird_view(row) if row is not None else {"id": None, "masked": None}
    return {"irdVaultId": view.get("id"), "irdMasked": view.get("masked")}


def _payday_items(db: Session, run, legal_entity_id) -> tuple:
    """Every NZ payslip of the payday and legal employer across its PAID runs
    (plus the run being paid now), corrections excluded."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun

    runs = (db.query(PayrollRun).filter(PayrollRun.organization_id == run.organization_id,
                                        PayrollRun.pay_date == run.pay_date).all())
    chosen = [r for r in runs if r.id == run.id or str(getattr(r.status, "value", r.status)) in PAID_STATUSES]
    chosen = [r for r in chosen if (r.nz_payment_kind or "REGULAR").upper() != "CORRECTION"]
    items = []
    for r in sorted(chosen, key=lambda x: x.id):
        for item in nzs._nz_run_items(db, r):
            employee = db.get(PayrollEmployee, item.employee_id)
            if getattr(employee, "legal_entity_id", None) == legal_entity_id:
                items.append(item)
    return sorted(r.id for r in chosen), items, chosen


def _ei_payload(db: Session, run, legal_entity_id, items, version: Optional[Decimal]) -> dict:
    per = {}
    for item in items:
        s = item.nz_calculation_snapshot or {}
        entry = per.setdefault(item.employee_id, {"employeeId": item.employee_id, **_ird(db, run.organization_id,
                                                                                            item.employee_id),
                                                 "taxCode": s.get("taxCode"), "payslipItemIds": [],
                                                 **{name: ZERO for name, _p, _k in EI_FIELDS}, "lumpSum": ZERO,
                                                 "childSupportVariationCode": None})
        entry["payslipItemIds"].append(item.id)
        entry["taxCode"] = s.get("taxCode") or entry["taxCode"]
        for name, part, key in EI_FIELDS:
            entry[name] += Decimal(str((s.get(part) or {}).get(key) or 0))
        entry["lumpSum"] += Decimal(str(((s.get("extraPay") or {}).get("bases") or {}).get("PAYE") or 0))
        code = (s.get("childSupport") or {}).get("variationCode")
        if code:
            entry["childSupportVariationCode"] = code
    employees = []
    for employee_id in sorted(per):
        entry = per[employee_id]
        employees.append({k: (format(v, "f") if isinstance(v, Decimal) else v) for k, v in entry.items()})
    return {"schedule": EI, "payloadVersion": None if version is None else str(version),
            "payDate": run.pay_date.isoformat(), "legalEntityId": legal_entity_id, "employees": employees}


def _ed_payload(db: Session, run, legal_entity_id, chosen, version: Optional[Decimal]) -> Optional[dict]:
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    E = m.PayrollNzEmployment
    start = min((r.period_start or r.pay_date) for r in chosen)
    end = max((r.period_end or r.pay_date) for r in chosen)
    rows = (db.query(E).filter(E.organization_id == run.organization_id,
                               ((E.start_date >= start) & (E.start_date <= end))
                               | ((E.end_date >= start) & (E.end_date <= end))).order_by(E.employee_id, E.id).all())
    starters, leavers = [], []
    for row in rows:
        employee = db.get(PayrollEmployee, row.employee_id)
        if getattr(employee, "legal_entity_id", None) != legal_entity_id or row.status == "DRAFT":
            continue
        profile = nzs._nz_one_active(db, m.PayrollNzEmployeeTaxProfile, run.organization_id, row.employee_id,
                                     run.pay_date, "tax profile")
        ks = nzs._nz_one_active(db, m.PayrollNzKiwiSaverElection, run.organization_id, row.employee_id,
                                run.pay_date, "KiwiSaver election")
        base = {"employeeId": row.employee_id, **_ird(db, run.organization_id, row.employee_id),
                "taxCode": getattr(profile, "tax_code", None), "kiwisaver": getattr(ks, "membership_state", None)}
        if start <= row.start_date <= end:
            starters.append({**base, "startDate": row.start_date.isoformat()})
        if row.end_date and start <= row.end_date <= end:
            leavers.append({**base, "endDate": row.end_date.isoformat(), "reason": row.termination_reason})
    if not starters and not leavers:
        return None
    return {"schedule": ED, "payloadVersion": None if version is None else str(version),
            "payDate": run.pay_date.isoformat(), "legalEntityId": legal_entity_id,
            "starters": starters, "leavers": leavers}


# ── records ─────────────────────────────────────────────────────────────────
def _latest(db: Session, organization_id: int, legal_entity_id, pay_date: date, filing_type: str, kind: str):
    m = nzs._nz_models()
    F = m.PayrollNzFiling
    query = db.query(F).filter(F.organization_id == organization_id, F.pay_date == pay_date,
                               F.filing_type == filing_type, F.kind == kind)
    query = query.filter(F.legal_entity_id.is_(None) if legal_entity_id is None else F.legal_entity_id == legal_entity_id)
    return query.order_by(F.version.desc()).first()


def _upsert(db: Session, run, legal_entity_id, filing_type: str, payload: dict, run_ids: list, channel: str,
            actor_id):
    m = nzs._nz_models()
    F = m.PayrollNzFiling
    digest = _canonical_hash(payload)
    latest = _latest(db, run.organization_id, legal_entity_id, run.pay_date, filing_type, "ORIGINAL")
    due = filing_due_on(db, run.pay_date, channel)
    if latest is not None and latest.payload_hash == digest:
        return latest                                                     # NZ-018: nothing changed
    if latest is not None and latest.status == "DRAFT":
        latest.payload, latest.payload_hash, latest.run_ids, latest.due_on = payload, digest, run_ids, due
        latest.updated_at = datetime.utcnow()
        db.flush()
        return latest
    if latest is not None and latest.status in ("SUBMITTED", "ACCEPTED"):
        return _new_amendment(db, latest, payload, run_ids, None, actor_id)
    version = 1
    if latest is not None:
        version = latest.version + 1
        if latest.status == "APPROVED":
            latest.status = "SUPERSEDED"
    row = F(organization_id=run.organization_id, legal_entity_id=legal_entity_id, pay_date=run.pay_date,
            filing_type=filing_type, kind="ORIGINAL", version=version, run_ids=run_ids, payload=payload,
            payload_hash=digest, channel=channel, due_on=due, status="DRAFT", created_by_id=actor_id,
            previous_version_id=getattr(latest, "id", None))
    db.add(row)
    db.flush()
    return row


def _new_amendment(db: Session, original, payload: dict, run_ids: list, correction_id, actor_id):
    m = nzs._nz_models()
    F = m.PayrollNzFiling
    digest = _canonical_hash(payload)
    same = (db.query(F).filter(F.amends_id == original.id, F.kind == "AMENDMENT", F.payload_hash == digest,
                               F.status != "SUPERSEDED").first())
    if same is not None:
        return same                                                       # NZ-018: no duplicate amendment
    count = (db.query(F).filter(F.amends_id == original.id, F.kind == "AMENDMENT").count())
    row = F(organization_id=original.organization_id, legal_entity_id=original.legal_entity_id,
            pay_date=original.pay_date, filing_type=original.filing_type, kind="AMENDMENT", version=count + 1,
            run_ids=run_ids, payload=payload, payload_hash=digest, channel=original.channel,
            due_on=None, status="DRAFT", amends_id=original.id, correction_id=correction_id, created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def build_filings(db: Session, run, actor_id) -> list:
    """At PAID: (re)build the payday's EI / ED records for every legal employer
    in the run; a CORRECTION run makes amendments of the original payday."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    m = nzs._nz_models()
    items = nzs._nz_run_items(db, run)
    if not items:
        return []
    if (run.nz_payment_kind or "").upper() == "CORRECTION":
        out = []
        F = m.PayrollNzFiling
        for item in items:
            snapshot = item.nz_calculation_snapshot or {}
            if not snapshot.get("correctionOf"):
                continue
            if db.query(F.id).filter(F.correction_id == snapshot.get("correctionId")).first():
                continue
            original_item = db.get(PayslipItem, snapshot["correctionOf"])
            original_run = db.get(PayrollRun, original_item.payroll_run_id)
            employee = db.get(PayrollEmployee, item.employee_id)
            original = _latest(db, run.organization_id, getattr(employee, "legal_entity_id", None),
                               original_run.pay_date, EI, "ORIGINAL")
            if original is None:
                _conflict("NZ_FILING_MISSING", "the corrected payday has no filing to amend.")
            payload = {"schedule": EI, "amendment": True, "amends": original.id,
                       "correctionId": snapshot.get("correctionId"), "employeeId": item.employee_id,
                       **_ird(db, run.organization_id, item.employee_id),
                       "deltas": (snapshot.get("deltas") or {}).get("obligations") or {},
                       "grossDelta": (snapshot.get("deltas") or {}).get("gross")}
            out.append(_new_amendment(db, original, payload, [run.id], snapshot.get("correctionId"), actor_id))
        return out
    entities = sorted({getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items},
                      key=lambda x: (x is not None, x or 0))
    out = []
    for entity in entities:
        profile = rem._profile(db, run.organization_id, entity, run.pay_date)
        rate_map, _slabs, _pack = nzs._nz_pack_in_force(db, run.pay_date)
        version = rem.signed_amount(rate_map, "nz_filing_payload_version")
        run_ids, payday_items, chosen = _payday_items(db, run, entity)
        out.append(_upsert(db, run, entity, EI, _ei_payload(db, run, entity, payday_items, version), run_ids,
                           profile.filing_method, actor_id))
        ed = _ed_payload(db, run, entity, chosen, version)
        if ed is not None:
            out.append(_upsert(db, run, entity, ED, ed, run_ids, profile.filing_method, actor_id))
    return out


# ── workflow ────────────────────────────────────────────────────────────────
def _filing(db: Session, organization_id: int, filing_id: int):
    m = nzs._nz_models()
    F = m.PayrollNzFiling
    row = db.query(F).filter(F.id == filing_id, F.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("New Zealand filing")
    return row


def approve_filing(db: Session, organization_id: int, filing_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _filing(db, organization_id, filing_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT filing can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a New Zealand payday filing", db=db,
                      entity_type="nz_filing", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    nzs._nz_audit(db, actor_id, "approved", "nz_filing", row.id, new={"status": "APPROVED"})
    return row


def submit_filing(db: Session, organization_id: int, filing_id: int, actor_id):
    """Refused until gate G3 certifies the payday-filing schema (D-3)."""
    row = _filing(db, organization_id, filing_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED filing can be submitted.")
    if not nzs._content().NZ_EXPORT_SCHEMAS:
        _conflict("NZ_EXPORT_SCHEMA_NOT_CERTIFIED", "the payday-filing schema is not certified (gate G3); only "
                  "the JSON preview is available.")
    _conflict("NZ_EXPORT_SCHEMA_NOT_CERTIFIED", "no certified exporter is installed.")


def record_authority_response(db: Session, organization_id: int, filing_id: int, payload: dict, actor_id):
    """ACCEPTED / REJECTED with the reference and structured error codes. Never
    touches a remittance (NZ-019); a rejection leaves payroll unchanged."""
    row = _filing(db, organization_id, filing_id)
    if row.status != "SUBMITTED":
        raise BadRequestException("Only a SUBMITTED filing can receive the authority's response.")
    payload = dict(payload or {})
    outcome = str(payload.get("outcome") or "").strip().upper()
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise BadRequestException("outcome must be ACCEPTED or REJECTED.")
    codes = [str(c).strip().upper()[:40] for c in (payload.get("errorCodes") or []) if str(c).strip()]
    row.status, row.authority_reference = outcome, (payload.get("reference") or "")[:100] or None
    row.authority_errors, row.responded_at = codes or None, datetime.utcnow()
    db.flush()
    nzs._nz_audit(db, actor_id, "responded", "nz_filing", row.id, new={"status": outcome, "errors": codes})
    return row


def filing_view(row, include_payload: bool = False) -> dict:
    out = {"id": row.id, "legalEntityId": row.legal_entity_id, "payDate": row.pay_date.isoformat(),
           "filingType": row.filing_type, "kind": row.kind, "version": row.version, "runIds": row.run_ids,
           "payloadHash": row.payload_hash, "channel": row.channel,
           "dueOn": row.due_on.isoformat() if row.due_on else None, "status": row.status,
           "amendsId": row.amends_id, "correctionId": row.correction_id,
           "authorityReference": row.authority_reference, "authorityErrors": row.authority_errors,
           "createdById": row.created_by_id, "approvedById": row.approved_by_id}
    if include_payload:
        out["payload"] = row.payload                                       # masked IRD only (D-P8-4)
    return out


def list_filings(db: Session, organization_id: int, pay_date=None, status=None) -> list:
    m = nzs._nz_models()
    F = m.PayrollNzFiling
    query = db.query(F).filter(F.organization_id == organization_id)
    if pay_date:
        query = query.filter(F.pay_date == nzs._as_date(pay_date, "payDate"))
    if status:
        query = query.filter(F.status == str(status).upper())
    return [filing_view(r) for r in query.order_by(F.pay_date.desc(), F.filing_type, F.kind, F.version.desc())]
