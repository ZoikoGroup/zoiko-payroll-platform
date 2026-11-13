"""Poland parallel payroll cycles (ZP-PL-ENG-001 Phase 9; AC-PL-03, release
gate G6; mirrors nz_parallel.py).

An incumbent payroll's figures for a committed (Paid / Closed) Poland run are
imported as CSV and compared with Zoiko's frozen payslips, per employee and
concept, at ZERO tolerance (gross, PIT advance, employee ZUS, health, employee
PPK, employer ZUS, employer funds, employer PPK, net pay). Nothing is
recomputed. Each difference is explained, then accepted by a different
person; the cycle is accepted by a person other than its importer once every
row matched and every difference is accepted. G6 needs at least MIN_EMPLOYERS
legal employers that each have accepted cycles in at least MIN_MONTHS distinct
pay months ("two parallel payroll cycles for at least two Polish design
employers", AC-PL-03).

The file must carry no identifier (PL-025): a header naming one, or any cell
that is a valid PESEL, a valid NIP or shaped like a Polish bank account,
refuses the whole file before a row is written. Only the employee code links
a row to a payslip.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import poland_service as pls

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MIN_MONTHS = 2
MIN_EMPLOYERS = 2
CONCEPTS = ("gross", "pit_advance", "zus_employee", "health", "ppk_employee", "zus_employer", "employer_funds",
            "ppk_employer", "net_pay")
_COMMITTED = ("PAID", "CLOSED")
_ID_HEADER = re.compile(r"pesel|\bnip\b|regon|\bnrs\b|iban|tax[ _-]?(number|no|id)|\bbank\b|account|passport|"
                        r"driver|licen[cs]e|dow[oó]d|identity", re.I)
_DIGITS_ONLY = re.compile(r"^[\d\s-]+$")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def zoiko_amounts(item) -> dict:
    """The committed figures, read from the payslip as stored (never recomputed)."""
    s = item.pl_calculation_snapshot or {}

    def total(key):
        return sum((_dec(v) for v in (s.get(key) or {}).values()), Decimal("0"))

    return {"gross": _dec(item.gross_pay), "pit_advance": _dec(s.get("pl_pit_advance")),
            "zus_employee": total("pl_zus_employee"), "health": _dec(s.get("pl_health")),
            "ppk_employee": total("pl_ppk_employee"), "zus_employer": total("pl_zus_employer"),
            "employer_funds": total("pl_funds"), "ppk_employer": total("pl_ppk_employer"),
            "net_pay": _dec(item.net_pay)}


def identifier_in(value) -> Optional[str]:
    """'PESEL' / 'NIP' / 'bank account' when a cell looks like one, else None."""
    from app.modules.payroll.employee_validation import pl_nip_is_valid, pl_pesel_is_valid

    text = str(value or "").strip()
    compact = re.sub(r"[\s-]", "", text).upper()
    if compact.startswith("PL") and compact[2:].isdigit() and len(compact) == 28:
        return "bank account"
    if not text or not _DIGITS_ONLY.match(text):
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and pl_pesel_is_valid(digits):
        return "PESEL"
    if len(digits) == 10 and pl_nip_is_valid(digits):
        return "NIP"
    if len(digits) == 26:
        return "bank account"
    return None


def _amount(value, line: int, column: str) -> Decimal:
    text = (str(value if value is not None else "").strip().replace(" ", "").replace("\u00a0", "")
            .replace("PLN", "").replace("zł", ""))
    # "1 234,56" (Polish) and "1,234.56" (English) both read as 1234.56.
    text = text.replace(",", "") if "." in text else text.replace(",", ".")
    try:
        amount = Decimal(text or "0")
    except InvalidOperation:
        raise BadRequestException(f"Line {line}, column '{column}' is not an amount.")
    if amount != amount.quantize(Decimal("0.01")):
        raise BadRequestException(f"Line {line}, column '{column}' has more than two decimal places.")
    return amount


def _parse(csv_text: str, mapping: dict) -> list:
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
        raise BadRequestException("columnMap.employeeCode is required.")
    unknown = sorted(set(mapping) - {"employeeCode", *CONCEPTS})
    if unknown:
        raise BadRequestException(f"columnMap has unknown concept(s) {unknown}.")
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
            kind = identifier_in(value) if column != code_column else None
            if kind:
                raise BadRequestException(f"Line {n}, column '{column}' holds a value shaped like a {kind}; "
                                          "the file is refused.")
    return rows


def import_view(row) -> dict:
    return {"id": row.id, "runId": row.run_id, "payDate": row.pay_date.isoformat(),
            "cycleMonth": row.cycle_month.isoformat(), "legalEntityId": row.legal_entity_id,
            "sourceName": row.source_name, "fileHash": row.file_hash, "rowCount": row.row_count,
            "matchedCount": row.matched_count, "unmatchedCount": row.unmatched_count, "columnMap": row.column_map,
            "status": row.status, "createdById": row.created_by_id, "acceptedById": row.approved_by_id,
            "withdrawnReason": row.withdrawn_reason}


def difference_view(row) -> dict:
    return {"id": row.id, "importId": row.import_id, "employeeId": row.employee_id,
            "payslipItemId": row.payslip_item_id, "concept": row.concept,
            "incumbentAmount": str(row.incumbent_amount), "zoikoAmount": str(row.zoiko_amount),
            "difference": str(row.difference), "explanation": row.explanation, "explainedById": row.explained_by_id,
            "acceptedById": row.approved_by_id, "status": row.status}


def _import(db: Session, organization_id: int, import_id: int):
    m = pls._models()
    row = (db.query(m.PayrollPlParallelImport).filter(m.PayrollPlParallelImport.id == import_id,
                                                      m.PayrollPlParallelImport.organization_id == organization_id)
           .first())
    if row is None:
        raise NotFoundException("Poland parallel import")
    return row


def _difference(db: Session, organization_id: int, difference_id: int):
    m = pls._models()
    D = m.PayrollPlParallelDifference
    row = db.query(D).filter(D.id == difference_id, D.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Poland parallel difference")
    return row


def parallel_summary(db: Session, organization_id: int, import_id: int) -> dict:
    m = pls._models()
    row = _import(db, organization_id, import_id)
    diffs = (db.query(m.PayrollPlParallelDifference).filter(m.PayrollPlParallelDifference.import_id == row.id)
             .order_by(m.PayrollPlParallelDifference.id).all())
    clean = row.unmatched_count == 0 and all(d.status == "ACCEPTED" for d in diffs)
    return {**import_view(row), "differences": [difference_view(d) for d in diffs], "clean": clean}


def list_parallel_imports(db: Session, organization_id: int) -> list:
    m = pls._models()
    I = m.PayrollPlParallelImport
    return [import_view(r) for r in db.query(I).filter(I.organization_id == organization_id).order_by(I.id.desc())]


def import_parallel(db: Session, organization_id: int, data: dict, actor_id) -> dict:
    """data = {runId, sourceName, csv, columnMap, reason}."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    m = pls._models()
    data = dict(data or {})
    reason = pls._reason(data.get("reason"))
    try:
        run_id = int(data.get("runId"))
    except (TypeError, ValueError):
        raise BadRequestException("runId is required.")
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    if str(getattr(run.status, "value", run.status)).upper() not in _COMMITTED:
        raise BadRequestException("Only a committed (Paid / Closed) run is compared with an incumbent payroll.")
    source = str(data.get("sourceName") or "").strip()
    if not source:
        raise BadRequestException("sourceName (the incumbent payroll) is required.")
    mapping = {k: v for k, v in dict(data.get("columnMap") or {}).items() if v}
    csv_text = data.get("csv") or ""
    rows = _parse(csv_text, mapping)
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    I = m.PayrollPlParallelImport
    if (db.query(I.id).filter(I.organization_id == organization_id, I.run_id == run.id, I.file_hash == digest,
                              I.status != "WITHDRAWN").first()):
        raise BadRequestException("This exact file was already imported for the run.")
    items = (db.query(PayslipItem, PayrollEmployee.employee_code, PayrollEmployee.legal_entity_id)
             .join(PayrollEmployee, PayrollEmployee.id == PayslipItem.employee_id)
             .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == pls.PL).all())
    if not items:
        raise BadRequestException("The run has no Poland payslips.")
    entities = {entity for _item, _code, entity in items}
    by_code = {str(code or "").strip(): item for item, code, _entity in items}
    row = I(organization_id=organization_id, legal_entity_id=entities.pop() if len(entities) == 1 else None,
            run_id=run.id, pay_date=run.pay_date, cycle_month=run.pay_date.replace(day=1), source_name=source[:100],
            file_hash=digest, row_count=len(rows), column_map=mapping, status="OPEN", created_by_id=actor_id)
    db.add(row)
    db.flush()
    seen, unmatched = set(), 0
    for n, line in enumerate(rows, start=2):
        code = str(line.get(mapping["employeeCode"]) or "").strip()
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
            theirs = _amount(line.get(column), n, column)
            if ours[concept] != theirs:
                db.add(m.PayrollPlParallelDifference(
                    organization_id=organization_id, legal_entity_id=row.legal_entity_id, import_id=row.id,
                    employee_id=item.employee_id, payslip_item_id=item.id, concept=concept,
                    incumbent_amount=theirs, zoiko_amount=ours[concept], difference=ours[concept] - theirs,
                    status="OPEN", created_by_id=actor_id))
    unmatched += len(set(by_code) - seen)            # Zoiko payslips the file does not cover
    row.matched_count, row.unmatched_count = len(seen), unmatched
    db.flush()
    pls._audit(db, actor_id, "imported", "pl_parallel_import", row.id,
                  new={"run": run.id, "rows": len(rows), "unmatched": unmatched}, reason=reason)
    return parallel_summary(db, organization_id, row.id)


def explain_difference(db: Session, organization_id: int, difference_id: int, reason, actor_id) -> dict:
    row = _difference(db, organization_id, difference_id)
    if row.status == "ACCEPTED":
        raise BadRequestException("An accepted difference is final.")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A difference is explained with a reason.")
    row.status, row.explanation, row.explained_by_id = "EXPLAINED", text[:300], actor_id
    db.flush()
    pls._audit(db, actor_id, "explained", "pl_parallel_difference", row.id, new={"concept": row.concept},
                  reason=text)
    return difference_view(row)


def accept_difference(db: Session, organization_id: int, difference_id: int, actor_id) -> dict:
    from datetime import datetime

    from app.modules.payroll.service import require_four_eyes

    row = _difference(db, organization_id, difference_id)
    if row.status != "EXPLAINED":
        raise BadRequestException("Only an EXPLAINED difference is accepted.")
    require_four_eyes(row.explained_by_id, actor_id, "Accepting a Poland parallel-run difference", db=db,
                      entity_type="pl_parallel_difference", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "ACCEPTED", actor_id, datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "accepted", "pl_parallel_difference", row.id, new={"status": "ACCEPTED"})
    return difference_view(row)


def accept_import(db: Session, organization_id: int, import_id: int, actor_id) -> dict:
    from datetime import datetime

    from app.modules.payroll.service import require_four_eyes

    row = _import(db, organization_id, import_id)
    if row.status != "OPEN":
        raise BadRequestException(f"The import is {row.status}.")
    if not parallel_summary(db, organization_id, import_id)["clean"]:
        raise BadRequestException("Every row must match and every difference be accepted first.")
    require_four_eyes(row.created_by_id, actor_id, "Accepting a Poland parallel cycle", db=db,
                      entity_type="pl_parallel_import", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "ACCEPTED", actor_id, datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "accepted", "pl_parallel_import", row.id, new={"status": "ACCEPTED"})
    return parallel_summary(db, organization_id, import_id)


def withdraw_import(db: Session, organization_id: int, import_id: int, reason, actor_id) -> dict:
    text = pls._reason(reason)
    row = _import(db, organization_id, import_id)
    if row.status != "OPEN":
        raise BadRequestException(f"The import is {row.status}.")
    row.status, row.withdrawn_reason = "WITHDRAWN", text[:300]
    db.flush()
    pls._audit(db, actor_id, "withdrawn", "pl_parallel_import", row.id, new={"status": "WITHDRAWN"}, reason=text)
    return import_view(row)


def accepted_cycles(db: Session) -> dict:
    """{(organization_id, legal_entity_id): {cycle months}} of ACCEPTED cycles
    across every organisation — the G6 evidence."""
    m = pls._models()
    I = m.PayrollPlParallelImport
    out = {}
    for org, entity, month in (db.query(I.organization_id, I.legal_entity_id, I.cycle_month)
                               .filter(I.status == "ACCEPTED").distinct()):
        out.setdefault((org, entity), set()).add(month)
    return out


def g6_state(db: Session) -> tuple:
    """(ok, detail): at least MIN_EMPLOYERS legal employers each with accepted
    cycles in at least MIN_MONTHS distinct pay months."""
    cycles = accepted_cycles(db)
    qualified = [key for key, months in cycles.items() if len(months) >= MIN_MONTHS]
    detail = (f"{len(qualified)} legal employer(s) with accepted cycles in {MIN_MONTHS}+ distinct months "
              f"(needs {MIN_EMPLOYERS}); {sum(len(v) for v in cycles.values())} accepted cycle month(s) in total")
    return len(qualified) >= MIN_EMPLOYERS, detail
