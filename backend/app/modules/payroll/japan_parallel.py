"""
japan_parallel.py — Japan parallel payroll cycles (ZP-JP-ENG-001 §14, release
gate G7; Phase 9).

An incumbent payroll's figures for a committed Japan run are imported as CSV
and compared with Zoiko's frozen results, per employee and concept, with
tolerance ZERO. Each difference is explained (a reason) and accepted by a
different person; the cycle is accepted by a person other than its importer
once every difference is accepted and every row matched. G7 needs accepted
cycles for at least ``MIN_ACCEPTED_CYCLES`` distinct pay months.

The file must carry no identifier: a header naming one, or any cell shaped
like a 12-digit number (a My Number), refuses the whole file before a row is
written. Only the employee code links a row to a payslip. Nothing is
recomputed — Zoiko's side is the payslip as committed.
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

JP = "JP"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MIN_ACCEPTED_CYCLES = 2
CONCEPTS = ("gross", "withholding", "social_insurance_employee", "employment_insurance_employee",
            "resident_tax", "net_pay")
_COMMITTED = ("PAID", "CLOSED")
_ID_HEADER = re.compile(r"my[ _-]?number|個人番号|マイナンバー|\bpassport\b|\bbank\b|\baccount\b|\biban\b|"
                        r"\bresidence[ _-]?card\b|\bpension[ _-]?(no|number)\b|基礎年金番号", re.I)
_ID_VALUE = re.compile(r"^\D*(\d[\s-]?){12}\D*$")


def _jp_m():
    from app.modules.payroll import models

    return models


def _jp_now():
    return datetime.now(timezone.utc)


def _jp_dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def zoiko_amounts(item) -> dict:
    """The committed figures, read from the payslip as stored (never recomputed)."""
    snap = item.jp_calculation_snapshot or {}
    bonus = snap.get("jp_bonus") or {}
    return {
        "gross": _jp_dec(item.gross_pay),
        "withholding": _jp_dec(snap.get("jp_wht_total") if snap.get("jp_wht_total") is not None else item.tds),
        "social_insurance_employee": _jp_dec(snap.get("jp_si_employee_total"))
        + _jp_dec(bonus.get("jp_bonus_si_employee_total")),
        "employment_insurance_employee": _jp_dec(snap.get("jp_ei_employee")) + _jp_dec(bonus.get("jp_bonus_ei_employee")),
        "resident_tax": _jp_dec(snap.get("jp_resident_tax")),
        "net_pay": _jp_dec(item.net_pay),
    }


def _jp_amount(value, line: int, column: str) -> Decimal:
    text = str(value if value is not None else "").strip().replace(",", "").replace("¥", "").replace("円", "")
    try:
        amount = Decimal(text or "0")
    except InvalidOperation:
        raise BadRequestException(f"Line {line}, column '{column}' is not an amount.")
    if amount != amount.to_integral_value():
        raise BadRequestException(f"Line {line}, column '{column}' has fractional yen.")
    return amount


def _jp_parse(csv_text: str, mapping: dict) -> list:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise BadRequestException("csv is required.")
    if len(csv_text.encode("utf-8")) > MAX_BYTES:
        raise BadRequestException(f"The file is larger than {MAX_BYTES} bytes.")
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    named = [h for h in headers if _ID_HEADER.search(h or "")]
    if named:
        raise BadRequestException(f"The file carries identifier column(s) {named}; remove them and re-export.")
    if not isinstance(mapping, dict) or not mapping.get("employeeCode"):
        raise BadRequestException("columnMapping.employeeCode is required.")
    unknown = sorted(set(mapping) - {"employeeCode", *CONCEPTS})
    if unknown:
        raise BadRequestException(f"columnMapping has unknown concept(s) {unknown}.")
    if not any(mapping.get(c) for c in CONCEPTS):
        raise BadRequestException("Map at least one concept to compare.")
    missing = [col for col in mapping.values() if col and col not in headers]
    if missing:
        raise BadRequestException(f"Mapped column(s) {missing} are not in the file.")
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise BadRequestException(f"The file has more than {MAX_ROWS} rows.")
    code_column = mapping["employeeCode"]
    for n, row in enumerate(rows, start=2):
        for column, value in row.items():
            if column != code_column and value and _ID_VALUE.match(str(value)):
                raise BadRequestException(f"Line {n}, column '{column}' holds a 12-digit value shaped like a "
                                          "My Number; the file is refused.")
    return rows


def _jp_row(row) -> dict:
    out = {}
    for c in row.__table__.columns:
        value = getattr(row, c.name)
        out[c.name] = value.isoformat() if hasattr(value, "isoformat") else (
            str(value) if isinstance(value, Decimal) else value)
    return out


def import_jp_parallel(db: Session, organization_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """data = {payrollRunId, sourceLabel, csv, columnMapping}."""
    m = _jp_m()
    data = data or {}
    try:
        run_id = int(data.get("payrollRunId") or data.get("payroll_run_id"))
    except (TypeError, ValueError):
        raise BadRequestException("payrollRunId is required.")
    run = (db.query(m.PayrollRun)
           .filter(m.PayrollRun.id == run_id, m.PayrollRun.organization_id == organization_id).first())
    if run is None:
        raise NotFoundException("Payroll run not found.")
    if str(getattr(run.status, "value", run.status)).upper() not in _COMMITTED:
        raise BadRequestException("Only a committed (Paid / Closed) run is compared with an incumbent payroll.")
    label = str(data.get("sourceLabel") or "").strip()
    if not label:
        raise BadRequestException("sourceLabel (the incumbent payroll) is required.")
    mapping = data.get("columnMapping") or {}
    csv_text = data.get("csv") or ""
    rows = _jp_parse(csv_text, mapping)
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    if db.query(m.PayrollJpParallelImport).filter(m.PayrollJpParallelImport.payroll_run_id == run.id,
                                                  m.PayrollJpParallelImport.file_sha256 == digest).first():
        raise BadRequestException("This exact file was already imported for the run.")
    items = (db.query(m.PayslipItem, m.PayrollEmployee.employee_code)
             .join(m.PayrollEmployee, m.PayrollEmployee.id == m.PayslipItem.employee_id)
             .filter(m.PayslipItem.payroll_run_id == run.id, m.PayslipItem.country_code == JP).all())
    if not items:
        raise BadRequestException("The run has no Japan payslips.")
    by_code = {str(code or "").strip(): item for item, code in items}
    imp = m.PayrollJpParallelImport(
        organization_id=organization_id, payroll_run_id=run.id,
        period=f"{run.pay_date.year}-{run.pay_date.month:02d}", source_label=label[:120], file_sha256=digest,
        column_mapping={k: v for k, v in mapping.items() if v}, row_count=len(rows), matched_count=0,
        unmatched_count=0, status="OPEN", created_by_id=actor_id)
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
            column = mapping.get(concept)
            if not column:
                continue
            theirs = _jp_amount(row.get(column), n, column)
            if ours[concept] != theirs:
                db.add(m.PayrollJpParallelDifference(
                    organization_id=organization_id, import_id=imp.id, employee_id=item.employee_id,
                    concept=concept, zoiko_amount=ours[concept], incumbent_amount=theirs,
                    delta=ours[concept] - theirs, status="UNEXPLAINED"))
    unmatched += len(set(by_code) - seen)            # Zoiko payslips the file does not cover
    imp.matched_count, imp.unmatched_count = len(seen), unmatched
    db.flush()
    return jp_parallel_summary(db, organization_id, imp.id)


def _jp_import(db: Session, organization_id: int, import_id: int):
    m = _jp_m()
    imp = (db.query(m.PayrollJpParallelImport)
           .filter(m.PayrollJpParallelImport.id == import_id,
                   m.PayrollJpParallelImport.organization_id == organization_id).first())
    if imp is None:
        raise NotFoundException("Japan parallel import not found.")
    return imp


def _jp_difference(db: Session, organization_id: int, difference_id: int):
    m = _jp_m()
    row = (db.query(m.PayrollJpParallelDifference)
           .filter(m.PayrollJpParallelDifference.id == difference_id,
                   m.PayrollJpParallelDifference.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Japan parallel difference not found.")
    return row


def jp_parallel_summary(db: Session, organization_id: int, import_id: int) -> dict:
    m = _jp_m()
    imp = _jp_import(db, organization_id, import_id)
    diffs = (db.query(m.PayrollJpParallelDifference)
             .filter(m.PayrollJpParallelDifference.import_id == imp.id)
             .order_by(m.PayrollJpParallelDifference.id).all())
    clean = imp.unmatched_count == 0 and all(d.status == "ACCEPTED" for d in diffs)
    return {**_jp_row(imp), "differences": [_jp_row(d) for d in diffs], "clean": clean}


def list_jp_parallel_imports(db: Session, organization_id: int) -> list:
    m = _jp_m()
    return [_jp_row(i) for i in db.query(m.PayrollJpParallelImport)
            .filter(m.PayrollJpParallelImport.organization_id == organization_id)
            .order_by(m.PayrollJpParallelImport.id.desc()).all()]


def explain_jp_parallel_difference(db: Session, organization_id: int, difference_id: int, reason: str,
                       actor_id: Optional[int]) -> dict:
    row = _jp_difference(db, organization_id, difference_id)
    if row.status == "ACCEPTED":
        raise BadRequestException("An accepted difference is final.")
    if not (reason or "").strip():
        raise BadRequestException("A difference is explained with a reason.")
    row.status, row.reason = "EXPLAINED", reason.strip()[:1000]
    row.explained_by_id, row.explained_at = actor_id, _jp_now()
    db.flush()
    return _jp_row(row)


def accept_jp_parallel_difference(db: Session, organization_id: int, difference_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.service import require_four_eyes

    row = _jp_difference(db, organization_id, difference_id)
    if row.status != "EXPLAINED":
        raise BadRequestException("Only an EXPLAINED difference is accepted.")
    require_four_eyes(row.explained_by_id, actor_id, "Accepting a Japan parallel-run difference", db=db,
                      entity_type="jp_parallel_difference", entity_id=row.id, current_status=row.status)
    row.status, row.accepted_by_id, row.accepted_at = "ACCEPTED", actor_id, _jp_now()
    db.flush()
    return _jp_row(row)


def accept_jp_parallel_import(db: Session, organization_id: int, import_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.service import require_four_eyes

    imp = _jp_import(db, organization_id, import_id)
    if imp.status != "OPEN":
        raise BadRequestException(f"The import is {imp.status}.")
    state = jp_parallel_summary(db, organization_id, import_id)
    if not state["clean"]:
        raise BadRequestException("Every row must match and every difference be accepted first.")
    require_four_eyes(imp.created_by_id, actor_id, "Accepting a Japan parallel cycle", db=db,
                      entity_type="jp_parallel_import", entity_id=imp.id, current_status=imp.status)
    imp.status, imp.accepted_by_id, imp.accepted_at = "ACCEPTED", actor_id, _jp_now()
    db.flush()
    return jp_parallel_summary(db, organization_id, import_id)


def withdraw_jp_parallel_import(db: Session, organization_id: int, import_id: int) -> dict:
    imp = _jp_import(db, organization_id, import_id)
    if imp.status != "OPEN":
        raise BadRequestException(f"The import is {imp.status}.")
    imp.status = "WITHDRAWN"
    db.flush()
    return _jp_row(imp)


def jp_accepted_parallel_periods(db: Session) -> set:
    """Pay months with an ACCEPTED cycle (any organisation): the G7 evidence."""
    m = _jp_m()
    return {p for (p,) in db.query(m.PayrollJpParallelImport.period)
            .filter(m.PayrollJpParallelImport.status == "ACCEPTED").distinct()}
