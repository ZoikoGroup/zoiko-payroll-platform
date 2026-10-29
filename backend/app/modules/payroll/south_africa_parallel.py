"""
payroll/south_africa_parallel.py
--------------------------------
South Africa G6 parallel payroll comparison (ZP-ZA-ENG-001 §13: "two parallel
payroll cycles against a trusted incumbent / qualified bureau ... every material
difference explained and approved"; Phase 10). "ZA" is South Africa ("SA" is
Saudi Arabia). Same shape as Mexico X4 (mexico_parallel_service).

  * An incumbent's results for one COMMITTED ZA run are imported from CSV with an
    explicit column mapping and compared, employee by employee and concept by
    concept, with Zoiko's committed payslips (money columns + frozen snapshot) -
    never recomputed.
  * Employees are matched by their employee code only. A column whose header
    names an identifier, or a cell shaped like one (ID number, tax reference,
    passport, bank account), is refused and the value is never echoed back.
    Only the mapping, the file's SHA-256 and counts are kept, never the file.
  * Every non-zero delta starts UNEXPLAINED; EXPLAINED needs a reason; ACCEPTED
    needs someone other than the explainer. An import is accepted only by
    someone other than its importer.
  * Whether a cycle is clean depends on the owner's materiality threshold
    (decision D-4, content row za_parallel_materiality_amount). While that row is
    empty no cycle is ever clean - Zoiko does not pick a tolerance.
  * Nothing here changes a payslip, run, ledger or filing. ETI is not a concept:
    it is never an employee line (ZA-010).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

ZA = "ZA"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
CONCEPTS = ("gross", "paye", "uif_employee", "uif_employer", "sdl", "other_deductions", "net")
COMMITTED = ("Paid", "Closed")
OPEN_DIFFS = ("UNEXPLAINED", "EXPLAINED")
MATERIALITY_KEY = "za_parallel_materiality_amount"
# A header naming an identifier is refused whatever it holds (POPIA minimisation).
_ID_HEADER = re.compile(r"\b(id|identity|id[ _-]?(number|no)|passport|tax[ _-]?(no|number|ref|reference)|"
                        r"income[ _-]?tax|account|bank|iban|branch[ _-]?code)\b", re.I)
# Cells shaped like an identifier: a 9+ digit integer (13-digit ID, 10-digit tax
# reference, bank account) or a passport number. No ZA payroll amount is a bare
# 9+ digit integer.
_ID_VALUE = re.compile(r"^(?:\d{9,}|[A-Z]{1,2}\d{6,9})$", re.I)
_CENT = Decimal("0.01")


def _m():
    from app.modules.payroll import models

    return models


def _now():
    return datetime.now(timezone.utc)


def _status(run) -> str:
    return str(getattr(run.status, "value", run.status))


def materiality() -> Optional[Decimal]:
    """D-4's threshold from the content row; None while it is empty by design."""
    from app.modules.payroll.engine.countries import south_africa_content as content

    for row in content.ZA_SCALAR_CONTENT:
        if row[0] == MATERIALITY_KEY:
            return None if row[4] in (None, "") else Decimal(str(row[4]))
    return None


def _committed_run(db: Session, org_id: int, run_id):
    m = _m()
    try:
        run_id = int(run_id)
    except (TypeError, ValueError):
        raise BadRequestException("payrollRunId is required.")
    run = db.query(m.PayrollRun).filter(m.PayrollRun.id == run_id, m.PayrollRun.organization_id == org_id).first()
    if run is None:
        raise NotFoundException("PayrollRun", run_id)
    if _status(run) not in COMMITTED:
        raise BadRequestException("Only a committed (Paid / Closed) run is compared with an incumbent payroll.")
    return run


def zoiko_amounts(item) -> dict:
    """The committed figures, read from the payslip as stored (never recomputed)."""
    snap = item.za_calculation_snapshot or {}

    def dec(value):
        return Decimal(str(value or 0)).quantize(_CENT)

    return {"gross": dec(item.gross_pay), "paye": dec(item.tds), "uif_employee": dec(item.esi),
            "uif_employer": dec(item.employer_esi), "sdl": dec(item.employer_payroll_tax),
            "other_deductions": dec(snap.get("za_other_deductions")), "net": dec(item.net_pay)}


def _mapping(raw, headers) -> dict:
    if not isinstance(raw, dict):
        raise BadRequestException("columnMapping must map employeeCode and each compared concept to a CSV column.")
    employee_col = raw.get("employeeCode") or raw.get("employee_code")
    if not employee_col or employee_col not in headers:
        raise BadRequestException("columnMapping.employeeCode must name a column of the file.")
    concepts = {}
    for concept in CONCEPTS:
        col = raw.get(concept)
        if col in (None, ""):
            continue
        if col not in headers:
            raise BadRequestException(f"columnMapping.{concept} names a column that is not in the file.")
        concepts[concept] = col
    if not concepts:
        raise BadRequestException(f"Map at least one concept: {', '.join(CONCEPTS)}.")
    return {"employeeCode": employee_col, **concepts}


def _parse(csv_text: str, raw_mapping) -> tuple:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise BadRequestException("csv (the incumbent's results as CSV text) is required.")
    if len(csv_text.encode("utf-8")) > MAX_BYTES:
        raise BadRequestException("The file is larger than 2 MB.")
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    mapping = _mapping(raw_mapping, headers)
    # The mapped employee-code column may be headed "Employee ID"; its VALUES are still checked below.
    bad = [h for h in headers if h != mapping["employeeCode"] and _ID_HEADER.search(h or "")]
    if bad:
        raise BadRequestException(f"{len(bad)} column(s) name a personal identifier; remove them - employees are "
                                  "matched by employee code only.")
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise BadRequestException(f"The file has more than {MAX_ROWS} rows.")
    for n, row in enumerate(rows, start=2):
        for col, value in row.items():
            if col is None:
                raise BadRequestException(f"Line {n} has more cells than the header.")
            if _ID_VALUE.match(str(value or "").strip()):
                raise BadRequestException(f"Line {n}, column '{col}' holds a value shaped like a personal "
                                          "identifier; it was refused and is not shown.")
    return rows, mapping


def _amount(value, line: int, col: str) -> Decimal:
    text = str(value if value is not None else "").strip().replace(",", "").replace("R", "").replace(" ", "")
    try:
        return Decimal(text or "0").quantize(_CENT)
    except InvalidOperation:
        raise BadRequestException(f"Line {line}, column '{col}' is not an amount.")


def import_za_parallel(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """data = {payrollRunId, sourceLabel, csv, columnMapping}."""
    m = _m()
    data = data or {}
    run = _committed_run(db, org_id, data.get("payrollRunId") or data.get("payroll_run_id"))
    label = str(data.get("sourceLabel") or data.get("source_label") or "").strip()
    if not label:
        raise BadRequestException("sourceLabel (the incumbent payroll / bureau) is required.")
    csv_text = data.get("csv") or ""
    rows, mapping = _parse(csv_text, data.get("columnMapping") or data.get("column_mapping"))
    items = (db.query(m.PayslipItem)
             .filter(m.PayslipItem.payroll_run_id == run.id, m.PayslipItem.country_code == ZA).all())
    if not items:
        raise BadRequestException("The run has no South African payslips.")
    codes = {e.id: (e.employee_code or "").strip() for e in
             db.query(m.PayrollEmployee).filter(m.PayrollEmployee.id.in_([i.employee_id for i in items])).all()}
    by_code = {codes.get(i.employee_id): i for i in items if codes.get(i.employee_id)}

    imp = m.PayrollZaParallelImport(organization_id=org_id, payroll_run_id=run.id, source_label=label[:120],
                                    file_sha256=hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
                                    column_mapping=mapping, row_count=len(rows), status="OPEN",
                                    created_by_id=actor_id)
    db.add(imp)
    db.flush()
    seen, unmatched = set(), 0
    for n, row in enumerate(rows, start=2):
        code = str(row.get(mapping["employeeCode"]) or "").strip()
        item = by_code.get(code)
        if item is None or code in seen:
            unmatched += 1
            continue
        seen.add(code)
        ours = zoiko_amounts(item)
        for concept in CONCEPTS:
            col = mapping.get(concept)
            if not col:
                continue
            theirs = _amount(row.get(col), n, col)
            if ours[concept] != theirs:
                db.add(m.PayrollZaParallelDifference(
                    organization_id=org_id, import_id=imp.id, employee_id=item.employee_id, concept=concept,
                    zoiko_amount=ours[concept], incumbent_amount=theirs, delta=ours[concept] - theirs,
                    status="UNEXPLAINED"))
    imp.matched_count, imp.unmatched_count = len(seen), unmatched
    db.flush()
    return za_parallel_summary(db, org_id, imp.id)


def _import(db: Session, org_id: int, import_id: int):
    m = _m()
    imp = db.query(m.PayrollZaParallelImport).filter(m.PayrollZaParallelImport.id == import_id,
                                                     m.PayrollZaParallelImport.organization_id == org_id).first()
    if imp is None:
        raise NotFoundException("PayrollZaParallelImport", import_id)
    return imp


def _difference(db: Session, org_id: int, diff_id: int):
    m = _m()
    row = db.query(m.PayrollZaParallelDifference).filter(m.PayrollZaParallelDifference.id == diff_id,
                                                         m.PayrollZaParallelDifference.organization_id == org_id).first()
    if row is None:
        raise NotFoundException("PayrollZaParallelDifference", diff_id)
    if _import(db, org_id, row.import_id).status != "OPEN":
        raise BadRequestException("The import is no longer open.")
    return row


def _clean(db: Session, imp, diffs) -> tuple:
    """(clean, reason). Never clean without D-4's threshold."""
    m = _m()
    threshold = materiality()
    if threshold is None:
        return False, ("the parallel-cycle materiality threshold (decision D-4, za_parallel_materiality_amount) is "
                       "not recorded - no cycle is clean until it is")
    payslips = (db.query(m.PayslipItem.id)
                .filter(m.PayslipItem.payroll_run_id == imp.payroll_run_id, m.PayslipItem.country_code == ZA).count())
    if imp.unmatched_count or imp.matched_count != payslips:
        return False, (f"{imp.unmatched_count} file row(s) unmatched and {payslips - imp.matched_count} payslip(s) "
                       "missing from the file")
    material = [d for d in diffs if d.status in OPEN_DIFFS and abs(Decimal(str(d.delta))) > threshold]
    if material:
        return False, f"{len(material)} difference(s) above R{threshold} are not yet accepted by a second person"
    return True, None


def za_parallel_summary(db: Session, org_id: int, import_id: int) -> dict:
    m = _m()
    imp = _import(db, org_id, import_id)
    diffs = (db.query(m.PayrollZaParallelDifference).filter(m.PayrollZaParallelDifference.import_id == imp.id)
             .order_by(m.PayrollZaParallelDifference.id).all())
    run = db.get(m.PayrollRun, imp.payroll_run_id)
    clean, reason = _clean(db, imp, diffs)
    threshold = materiality()
    return {
        "id": imp.id, "payrollRunId": imp.payroll_run_id,
        "payDate": run.pay_date.isoformat() if run is not None and run.pay_date else None,
        "sourceLabel": imp.source_label, "fileSha256": imp.file_sha256, "status": imp.status,
        "rowCount": imp.row_count, "matchedCount": imp.matched_count, "unmatchedCount": imp.unmatched_count,
        "materiality": None if threshold is None else str(threshold), "clean": clean, "reason": reason,
        "counts": {s: sum(d.status == s for d in diffs) for s in ("UNEXPLAINED", "EXPLAINED", "ACCEPTED")},
        "differences": [{"id": d.id, "employeeId": d.employee_id, "concept": d.concept,
                         "zoikoAmount": str(d.zoiko_amount), "incumbentAmount": str(d.incumbent_amount),
                         "delta": str(d.delta), "status": d.status, "reason": d.reason,
                         "explainedById": d.explained_by_id, "acceptedById": d.accepted_by_id} for d in diffs],
        "createdById": imp.created_by_id, "acceptedById": imp.accepted_by_id,
    }


def list_za_parallel_imports(db: Session, org_id: int, run_id: Optional[int] = None) -> list:
    m = _m()
    q = db.query(m.PayrollZaParallelImport).filter(m.PayrollZaParallelImport.organization_id == org_id)
    if run_id is not None:
        q = q.filter(m.PayrollZaParallelImport.payroll_run_id == run_id)
    return [{"id": i.id, "payrollRunId": i.payroll_run_id, "sourceLabel": i.source_label, "status": i.status,
             "rowCount": i.row_count, "matchedCount": i.matched_count, "unmatchedCount": i.unmatched_count,
             "createdAt": i.created_at.isoformat() if i.created_at else None}
            for i in q.order_by(m.PayrollZaParallelImport.id.desc()).all()]


def explain_za_parallel_difference(db: Session, org_id: int, diff_id: int, reason, actor_id: Optional[int]) -> dict:
    row = _difference(db, org_id, diff_id)
    text = str(reason or "").strip()
    if not text:
        raise BadRequestException("An explanation needs a reason.")
    if row.status == "ACCEPTED":
        raise BadRequestException("The difference is already accepted.")
    row.reason, row.status, row.explained_by_id, row.explained_at = text[:1000], "EXPLAINED", actor_id, _now()
    row.accepted_by_id = row.accepted_at = None
    db.flush()
    return za_parallel_summary(db, org_id, row.import_id)


def accept_za_parallel_difference(db: Session, org_id: int, diff_id: int, actor_id: Optional[int]) -> dict:
    row = _difference(db, org_id, diff_id)
    if row.status != "EXPLAINED":
        raise BadRequestException("Only an explained difference can be accepted.")
    if actor_id is None or actor_id == row.explained_by_id:
        raise BadRequestException("The explanation must be accepted by someone other than its author (four-eyes).")
    row.status, row.accepted_by_id, row.accepted_at = "ACCEPTED", actor_id, _now()
    db.flush()
    return za_parallel_summary(db, org_id, row.import_id)


def accept_za_parallel_import(db: Session, org_id: int, import_id: int, actor_id: Optional[int]) -> dict:
    imp = _import(db, org_id, import_id)
    if imp.status != "OPEN":
        raise BadRequestException(f"The import is {imp.status}, not OPEN.")
    if actor_id is None or actor_id == imp.created_by_id:
        raise BadRequestException("A parallel cycle must be accepted by someone other than its importer (four-eyes).")
    summary = za_parallel_summary(db, org_id, import_id)
    if not summary["clean"]:
        raise BadRequestException(f"The cycle is not clean: {summary['reason']}.")
    imp.status, imp.accepted_by_id, imp.accepted_at = "ACCEPTED", actor_id, _now()
    db.flush()
    return za_parallel_summary(db, org_id, import_id)


def withdraw_za_parallel_import(db: Session, org_id: int, import_id: int, actor_id: Optional[int] = None) -> dict:
    imp = _import(db, org_id, import_id)
    if imp.status != "OPEN":
        raise BadRequestException(f"The import is {imp.status}; only an OPEN import can be withdrawn.")
    imp.status = "WITHDRAWN"
    db.flush()
    return za_parallel_summary(db, org_id, import_id)


def accepted_cycle_months(db: Session) -> set:
    """(year, month) of every ACCEPTED cycle's run - the G6 code check."""
    m = _m()
    rows = (db.query(m.PayrollRun.pay_date)
            .join(m.PayrollZaParallelImport, m.PayrollZaParallelImport.payroll_run_id == m.PayrollRun.id)
            .filter(m.PayrollZaParallelImport.status == "ACCEPTED").all())
    return {(d.year, d.month) for (d,) in rows if d is not None}
