"""
payroll/mexico_parallel_service.py
----------------------------------
Mexico final mile X4 (MEXICO_FINAL_MILE_MASTER_PROMPT.md): the G8 parallel
payroll comparison (spec §22, MX-064). A legacy payroll's results for one
committed Zoiko run are imported from CSV with an explicit column mapping and
compared, employee by employee and concept by concept, with Zoiko's committed
snapshot (never recomputed).

  * Employees are matched by their internal reference (employee code) — never by
    RFC / CURP / NSS. A file carrying an identifier column, or a cell that looks
    like one, is refused (no value is echoed back); only the mapping, the file's
    SHA-256 and counts are kept, never the file.
  * Every non-zero delta starts UNEXPLAINED. EXPLAINED needs a reason; ACCEPTED
    needs a second reviewer (four-eyes). Nothing here ever changes a payslip.
  * Whether a cycle is clean depends on the release owner's materiality threshold
    (D-25, decision register X1). While D-25 is not approved no cycle is ever
    declared clean — Zoiko does not pick a tolerance.
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

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException

MATERIALITY_DECISION = "D-25"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
CONCEPTS = ("net", "isr_withheld", "subsidy_applied", "imss_employee", "imss_employer", "retiro", "ceav_employee",
            "ceav_employer", "infonavit_employer", "infonavit_credit", "isn", "employer_total")
OPEN_STATES = ("UNEXPLAINED", "EXPLAINED")
# Column names that name an identifier (MX-061): refused whatever they hold.
_ID_HEADER = re.compile(r"\b(rfc|curp|nss|clabe|imss[ _-]?(number|no|num)|seguro[ _-]?social|cuenta|account)\b", re.I)
# Values shaped like an identifier: RFC (12/13), CURP (18), NSS (11 digits), CLABE (18 digits).
_ID_VALUE = re.compile(r"^(?:[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}|[A-Z]{4}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d|\d{11}|\d{18})$", re.I)
_CENT = Decimal("0.01")


def _m():
    from app.modules.payroll import models

    return models


def _now():
    return datetime.now(timezone.utc)


def _committed_run(db: Session, org_id: int, run_id) -> object:
    m = _m()
    try:
        run = db.get(m.PayrollRun, int(run_id))
    except (TypeError, ValueError):
        raise BadRequestException("run_id is required")
    if run is None or run.organization_id != org_id:
        raise NotFoundException("payroll run", run_id)
    if not (run.mx_approval_fingerprint or {}).get("committedAt"):
        raise BadRequestException(f"run {run.id} is not committed — a parallel cycle compares committed results only")
    return run


def zoiko_amounts(item) -> dict:
    """One committed payslip's amounts per CONCEPT, read from its frozen snapshot."""
    res = (item.mx_calculation_snapshot or {}).get("result") or {}

    def d(v):
        return Decimal(str(v)).quantize(_CENT) if v not in (None, "") else Decimal("0.00")

    def branch(name, side):
        return sum((d(r.get("amount")) for r in res.get("imss") or []
                    if r.get("branch") == name and r.get("side") == side), Decimal("0.00"))

    return {"net": d(item.net_pay), "isr_withheld": d(res.get("isr_withheld")),
            "subsidy_applied": d((res.get("subsidy") or {}).get("applied")),
            "imss_employee": d(res.get("imss_employee")), "imss_employer": d(res.get("imss_employer")),
            "retiro": branch("RETIRO", "employer"), "ceav_employee": branch("CEAV", "employee"),
            "ceav_employer": branch("CEAV", "employer"), "infonavit_employer": d(res.get("infonavit_employer")),
            "infonavit_credit": d(res.get("infonavit_credit")), "isn": d((res.get("isn") or {}).get("amount")),
            "employer_total": d(res.get("employer_total"))}


def _mapping(raw, headers) -> dict:
    """{"employee_code": column, concept: column, …} — every column a real header."""
    if not isinstance(raw, dict) or not raw.get("employee_code"):
        raise BadRequestException("column_mapping must name the employee_code column and at least one concept")
    unknown = sorted(set(raw) - {"employee_code", *CONCEPTS})
    if unknown:
        raise BadRequestException(f"Unknown mapping keys: {', '.join(unknown)} (concepts: {', '.join(CONCEPTS)})")
    if len(raw) < 2:
        raise BadRequestException("column_mapping must map at least one concept")
    missing = [c for c in raw.values() if c not in headers]
    if missing:
        raise BadRequestException(f"Mapped columns not in the file header: {', '.join(map(str, missing))}")
    return {k: str(v) for k, v in raw.items()}


def _parse(csv_text: str, raw_mapping) -> tuple:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise BadRequestException("csv is required (the legacy payroll's results, one row per employee)")
    if len(csv_text.encode("utf-8")) > MAX_BYTES:
        raise BadRequestException(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        raise BadRequestException("The file has no header row")
    named = [i + 1 for i, h in enumerate(headers) if _ID_HEADER.search(h)]
    if named:
        raise BadRequestException(f"Columns {named} name an identifier (RFC / CURP / NSS / CLABE / account). Remove "
                                  "them: parallel cycles match by employee code only (MX-061).")
    mapping = _mapping(raw_mapping, headers)
    col = {k: headers.index(v) for k, v in mapping.items()}
    rows, seen = {}, set()
    for n, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise BadRequestException(f"The file has more than {MAX_ROWS} rows")
        cells = [c.strip() for c in cells]
        if any(_ID_VALUE.match(c) for c in cells):
            raise BadRequestException(f"Row {n} holds a value shaped like an RFC / CURP / NSS / CLABE. Remove it: "
                                      "parallel cycles match by employee code only (MX-061).")
        code = cells[col["employee_code"]] if col["employee_code"] < len(cells) else ""
        if not code:
            raise BadRequestException(f"Row {n} has no employee code")
        if code in seen:
            raise BadRequestException(f"Row {n} repeats employee code {code}")
        seen.add(code)
        amounts = {}
        for concept, i in col.items():
            if concept == "employee_code":
                continue
            text = (cells[i] if i < len(cells) else "").replace(",", "")
            try:
                amounts[concept] = Decimal(text).quantize(_CENT)
            except (InvalidOperation, ValueError):
                raise BadRequestException(f"Row {n}, column {mapping[concept]!r}: not an amount")
        rows[code] = amounts
    if not rows:
        raise BadRequestException("The file has no data rows")
    return mapping, rows


def import_parallel(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """Import one legacy cycle for a committed run and record every difference.
    A re-import of the same run supersedes the CURRENT one (kept, read-only)."""
    m = _m()
    data = data or {}
    run = _committed_run(db, org_id, data.get("run_id"))
    label = str(data.get("source_label") or "").strip()
    if not label or len(label) > 120:
        raise BadRequestException("source_label is required (the legacy system's name, at most 120 characters)")
    csv_text = data.get("csv")
    mapping, rows = _parse(csv_text, data.get("column_mapping"))
    items = (db.query(m.PayslipItem).filter(m.PayslipItem.payroll_run_id == run.id,
                                           m.PayslipItem.mx_calculation_snapshot.isnot(None)).all())
    emps = {e.id: e for e in db.query(m.PayrollEmployee).filter(
        m.PayrollEmployee.id.in_([i.employee_id for i in items] or [0]))}
    by_code = {emps[i.employee_id].employee_code: i for i in items if emps[i.employee_id].employee_code}
    I = m.PayrollMxParallelImport
    for old in db.query(I).filter(I.organization_id == org_id, I.payroll_run_id == run.id, I.status == "CURRENT"):
        old.status = "SUPERSEDED"
    imp = I(organization_id=org_id, payroll_run_id=run.id, source_label=label, column_mapping=mapping,
            file_sha256=hashlib.sha256(csv_text.encode("utf-8")).hexdigest(), row_count=len(rows),
            unmatched={"legacyOnly": sorted(set(rows) - set(by_code)), "zoikoOnly": sorted(set(by_code) - set(rows))},
            status="CURRENT", created_by_id=actor_id)
    db.add(imp)
    db.flush()
    for code in sorted(set(rows) & set(by_code)):
        item = by_code[code]
        zoiko = zoiko_amounts(item)
        for concept, legacy in rows[code].items():
            delta = zoiko[concept] - legacy
            db.add(m.PayrollMxParallelDifference(
                organization_id=org_id, import_id=imp.id, employee_id=item.employee_id, concept=concept,
                legacy_amount=legacy, zoiko_amount=zoiko[concept], delta=delta,
                state="MATCH" if delta == 0 else "UNEXPLAINED"))
    db.commit()
    return parallel_import_view(db, org_id, imp.id)


def _import(db: Session, org_id: int, import_id: int):
    row = db.get(_m().PayrollMxParallelImport, import_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException("parallel import", import_id)
    return row


def _difference(db: Session, org_id: int, diff_id: int):
    row = db.get(_m().PayrollMxParallelDifference, diff_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException("parallel difference", diff_id)
    if _import(db, org_id, row.import_id).status != "CURRENT":
        raise BadRequestException("This import was superseded or withdrawn — review the current import")
    return row


def _materiality(db: Session):
    """The release owner's approved D-25 threshold (MXN), or None."""
    D = _m().PayrollMxDecision
    row = (db.query(D).filter(D.code == MATERIALITY_DECISION, D.status.in_(("APPROVED", "TRANSCRIBED")))
           .order_by(D.version.desc()).first())
    if row is None:
        return None
    try:
        return Decimal(str(row.chosen_option))
    except (InvalidOperation, ValueError):
        return None


def explain_parallel_difference(db: Session, org_id: int, diff_id: int, reason, actor_id: Optional[int]) -> dict:
    row = _difference(db, org_id, diff_id)
    if row.state not in OPEN_STATES:
        raise BadRequestException(f"A {row.state} difference cannot be explained")
    reason = str(reason or "").strip()
    if not reason or len(reason) > 500:
        raise BadRequestException("reason is required (at most 500 characters)")
    if any(_ID_VALUE.match(w.strip(".,;:()")) for w in reason.split()):
        raise BadRequestException("The reason holds a value shaped like an RFC / CURP / NSS / CLABE — remove it")
    row.state, row.reason, row.explained_by_id, row.explained_at = "EXPLAINED", reason, actor_id, _now()
    db.commit()
    return _diff_view(row, {})


def accept_parallel_difference(db: Session, org_id: int, diff_id: int, actor_id: Optional[int]) -> dict:
    row = _difference(db, org_id, diff_id)
    if row.state != "EXPLAINED":
        raise BadRequestException("Only an EXPLAINED difference can be accepted")
    if actor_id is None or actor_id == row.explained_by_id:
        raise ForbiddenException("A second reviewer must accept the explanation (four-eyes)")
    row.state, row.accepted_by_id, row.accepted_at = "ACCEPTED", actor_id, _now()
    db.commit()
    return _diff_view(row, {})


def _diff_view(r, refs: dict) -> dict:
    return {"id": r.id, "employee": refs.get(r.employee_id, f"#{r.employee_id}"), "employeeId": r.employee_id,
            "concept": r.concept, "legacy": str(r.legacy_amount), "zoiko": str(r.zoiko_amount), "delta": str(r.delta),
            "state": r.state, "reason": r.reason, "explainedById": r.explained_by_id,
            "acceptedById": r.accepted_by_id}


def parallel_summary(db: Session, imp) -> dict:
    """Counts per state and concept, and the cycle's clean verdict against D-25."""
    m = _m()
    rows = db.query(m.PayrollMxParallelDifference).filter(m.PayrollMxParallelDifference.import_id == imp.id).all()
    states = {s: sum(1 for r in rows if r.state == s) for s in ("MATCH", "UNEXPLAINED", "EXPLAINED", "ACCEPTED")}
    concepts = {}
    for r in rows:
        c = concepts.setdefault(r.concept, {"rows": 0, "differences": 0, "absDelta": Decimal("0.00")})
        c["rows"] += 1
        if r.state != "MATCH":
            c["differences"] += 1
            c["absDelta"] += abs(r.delta)
    threshold = _materiality(db)
    unmatched = imp.unmatched or {}
    if threshold is None:
        clean, note = None, ("The release owner's materiality threshold (D-25) is not approved: no cycle can be "
                             "declared clean.")
        material = None
    else:
        material = sum(1 for r in rows if r.state in OPEN_STATES and abs(r.delta) > threshold)
        clean = material == 0 and not unmatched.get("legacyOnly") and not unmatched.get("zoikoOnly")
        note = None if clean else "Material differences are not all accepted, or some employees are unmatched."
    return {"states": states, "concepts": {k: {**v, "absDelta": str(v["absDelta"])} for k, v in concepts.items()},
            "materiality": {"decision": MATERIALITY_DECISION, "threshold": str(threshold) if threshold is not None
                            else None, "openMaterial": material},
            "clean": clean, "note": note}


def _import_head(imp) -> dict:
    return {"id": imp.id, "runId": imp.payroll_run_id, "sourceLabel": imp.source_label,
            "columnMapping": imp.column_mapping, "fileSha256": imp.file_sha256, "rowCount": imp.row_count,
            "unmatched": imp.unmatched, "status": imp.status, "createdById": imp.created_by_id,
            "createdAt": imp.created_at.isoformat() if imp.created_at else None}


def list_parallel_imports(db: Session, org_id: int, run_id: Optional[int] = None) -> list:
    I = _m().PayrollMxParallelImport
    q = db.query(I).filter(I.organization_id == org_id)
    if run_id is not None:
        q = q.filter(I.payroll_run_id == run_id)
    return [{**_import_head(i), "summary": parallel_summary(db, i)} for i in q.order_by(I.id.desc())]


def parallel_import_view(db: Session, org_id: int, import_id: int) -> dict:
    from app.modules.payroll.mexico_report_service import _employee_refs

    m = _m()
    imp = _import(db, org_id, import_id)
    rows = (db.query(m.PayrollMxParallelDifference).filter(m.PayrollMxParallelDifference.import_id == imp.id)
            .order_by(m.PayrollMxParallelDifference.employee_id, m.PayrollMxParallelDifference.id).all())
    refs = _employee_refs(db, {r.employee_id for r in rows})
    return {**_import_head(imp), "summary": parallel_summary(db, imp), "differences": [_diff_view(r, refs) for r in rows]}


def withdraw_parallel_import(db: Session, org_id: int, import_id: int) -> dict:
    imp = _import(db, org_id, import_id)
    if imp.status != "CURRENT":
        raise BadRequestException(f"A {imp.status} import cannot be withdrawn")
    imp.status = "WITHDRAWN"
    db.commit()
    return _import_head(imp)
