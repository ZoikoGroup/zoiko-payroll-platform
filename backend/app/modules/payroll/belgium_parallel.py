"""Belgium parallel payroll cycles (ZP-BE-ENG-001 Block C2; spec §16 "parallel
payroll acceptance", release gate G4; mirrors poland_parallel.py).

An independent payroll's output for a committed Belgian run (the ledger is
posted at approval, G-29: Approved / Authorized / Paid / Closed) is imported as
CSV and compared with Zoiko's frozen payslips per employee and concept: gross,
professional withholding, employee ONSS, social work bonus, net pay and the
employer's contributions. Nothing is recomputed. The tolerance per concept
comes ONLY from the signed content key be_parallel_tolerance_<concept>; while
it is not signed the comparison is exact (zero tolerance). Each difference is
explained, then accepted by a different person; the cycle is accepted by a
person other than its importer once every row matched and every difference is
accepted. G4 needs, for every launch design partner, accepted cycles in at
least MIN_MONTHS distinct pay months ("two representative parallel payroll
cycles per design partner").

The file must carry no identifier (spec §15): a header naming one, or any cell
shaped like a NISS / BIS (eleven digits), an enterprise number (ten digits) or
a Belgian IBAN, refuses the whole file before a row is written. Only the
employee code links a row to a payslip.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as be

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MIN_MONTHS = 2
CONCEPTS = ("gross", "withholding", "onss_employee", "work_bonus_social", "net", "employer_onss")
TOLERANCE_KEYS = {c: f"be_parallel_tolerance_{c}" for c in CONCEPTS}
_COMMITTED = ("APPROVED", "AUTHORIZED", "PAID", "CLOSED")
_ID_HEADER = re.compile(r"niss|insz|\bbis\b|rijksregister|registre|national|enterprise|ondernemings|kbo|bce|"
                        r"\bonss\b|\brsz\b|iban|\bbic\b|\bbank\b|account|rekening|passport|identity|tax[ _-]?id", re.I)
_DIGITS = re.compile(r"^[\d\s./-]+$")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def be_parallel_amounts(item) -> dict:
    """The committed figures, read from the payslip as stored (never recomputed)."""
    s = item.be_calculation_snapshot or {}
    return {"gross": _dec(item.gross_pay), "withholding": _dec(s.get("be_withholding")),
            "onss_employee": _dec(s.get("be_onss_employee")), "work_bonus_social": _dec(s.get("be_social_work_bonus")),
            "net": _dec(item.net_pay), "employer_onss": _dec(s.get("be_employer_total"))}


def be_identifier_shape(value) -> Optional[str]:
    """'NISS / BIS' / 'enterprise number' / 'IBAN' when a cell looks like one."""
    text = str(value or "").strip()
    compact = re.sub(r"[\s./-]", "", text).upper()
    if compact.startswith("BE") and compact[2:].isdigit() and len(compact) == 16:
        return "IBAN"
    if not text or not _DIGITS.match(text):
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11:
        return "NISS / BIS"
    if len(digits) == 10:
        return "enterprise number"
    return None


def _be_parallel_amount(value, line: int, column: str) -> Decimal:
    text = (str(value if value is not None else "").strip().replace(" ", "").replace(" ", "")
            .replace("EUR", "").replace("€", ""))
    # "1.234,56" (nl / fr) and "1,234.56" (en) both read as 1234.56.
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text or "0")
    except InvalidOperation:
        raise BadRequestException(f"Line {line}, column '{column}' is not an amount.")
    if amount != amount.quantize(Decimal("0.01")):
        raise BadRequestException(f"Line {line}, column '{column}' has more than two decimal places.")
    return amount


def _be_parallel_parse(csv_text: str, mapping: dict) -> list:
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
            kind = be_identifier_shape(value) if column != code_column else None
            if kind:
                raise BadRequestException(f"Line {n}, column '{column}' holds a value shaped like a {kind}; "
                                          "the file is refused.")
    return rows


def be_parallel_tolerances(db: Session, organization_id: int, pay_date) -> dict:
    """{concept: tolerance} from the SIGNED content in force on the pay date;
    zero (an exact comparison) for every key that is not signed."""
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

    pack = be._be_pack_for(db, organization_id, pay_date)
    out = {}
    for concept, key in TOLERANCE_KEYS.items():
        value = Decimal("0")
        if pack is not None:
            try:
                value = abs(pack.amount(key))
            except BECalculationBlockedError:
                value = Decimal("0")
        out[concept] = value
    return out


def _be_parallel_models():
    return be._models()


def be_parallel_import_view(row) -> dict:
    return {"id": row.id, "runId": row.run_id, "payDate": row.pay_date.isoformat(),
            "cycleMonth": row.cycle_month.isoformat(), "legalEntityId": row.legal_entity_id,
            "sourceName": row.source_name, "fileHash": row.file_hash, "rowCount": row.row_count,
            "matchedCount": row.matched_count, "unmatchedCount": row.unmatched_count, "columnMap": row.column_map,
            "status": row.status, "createdById": row.created_by_id, "acceptedById": row.approved_by_id,
            "withdrawnReason": row.withdrawn_reason}


def be_parallel_difference_view(row) -> dict:
    return {"id": row.id, "importId": row.import_id, "employeeId": row.employee_id,
            "payslipItemId": row.payslip_item_id, "concept": row.concept,
            "incumbentAmount": str(row.incumbent_amount), "zoikoAmount": str(row.zoiko_amount),
            "difference": str(row.difference), "explanation": row.explanation, "explainedById": row.explained_by_id,
            "acceptedById": row.approved_by_id, "status": row.status}


def _be_parallel_import(db: Session, organization_id: int, import_id: int):
    I = _be_parallel_models().PayrollBeParallelImport
    row = db.query(I).filter(I.id == import_id, I.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian parallel import")
    return row


def _be_parallel_difference(db: Session, organization_id: int, difference_id: int):
    D = _be_parallel_models().PayrollBeParallelDifference
    row = db.query(D).filter(D.id == difference_id, D.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian parallel difference")
    return row


def be_parallel_summary(db: Session, organization_id: int, import_id: int) -> dict:
    D = _be_parallel_models().PayrollBeParallelDifference
    row = _be_parallel_import(db, organization_id, import_id)
    diffs = db.query(D).filter(D.import_id == row.id).order_by(D.id).all()
    clean = row.unmatched_count == 0 and all(d.status == "ACCEPTED" for d in diffs)
    return {**be_parallel_import_view(row), "differences": [be_parallel_difference_view(d) for d in diffs], "clean": clean}


def list_be_parallel_imports(db: Session, organization_id: int) -> list:
    I = _be_parallel_models().PayrollBeParallelImport
    return [be_parallel_import_view(r) for r in db.query(I).filter(I.organization_id == organization_id).order_by(I.id.desc())]


def import_be_parallel(db: Session, organization_id: int, data: dict, actor_id) -> dict:
    """data = {runId, sourceName, csv, columnMap, reason}."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    m = _be_parallel_models()
    data = dict(data or {})
    reason = be._reason(data.get("reason"))
    try:
        run_id = int(data.get("runId"))
    except (TypeError, ValueError):
        raise BadRequestException("runId is required.")
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    if be._run_status(run).upper() not in _COMMITTED:
        raise BadRequestException("Only a committed (Approved / Authorized / Paid / Closed) run is compared with an "
                                  "independent payroll.")
    source = str(data.get("sourceName") or "").strip()
    if not source:
        raise BadRequestException("sourceName (the independent payroll) is required.")
    mapping = {k: v for k, v in dict(data.get("columnMap") or {}).items() if v}
    csv_text = data.get("csv") or ""
    rows = _be_parallel_parse(csv_text, mapping)
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    I = m.PayrollBeParallelImport
    if (db.query(I.id).filter(I.organization_id == organization_id, I.run_id == run.id, I.file_hash == digest,
                              I.status != "WITHDRAWN").first()):
        raise BadRequestException("This exact file was already imported for the run.")
    items = (db.query(PayslipItem, PayrollEmployee.employee_code, PayrollEmployee.legal_entity_id)
             .join(PayrollEmployee, PayrollEmployee.id == PayslipItem.employee_id)
             .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == be.BE).all())
    if not items:
        raise BadRequestException("The run has no Belgian payslips.")
    entities = {entity for _item, _code, entity in items}
    by_code = {str(code or "").strip(): item for item, code, _entity in items}
    tolerance = be_parallel_tolerances(db, organization_id, run.pay_date)
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
        ours = be_parallel_amounts(item)
        for concept in CONCEPTS:
            column = mapping.get(concept)
            if not column:
                continue
            theirs = _be_parallel_amount(line.get(column), n, column)
            if abs(ours[concept] - theirs) > tolerance[concept]:
                db.add(m.PayrollBeParallelDifference(
                    organization_id=organization_id, legal_entity_id=row.legal_entity_id, import_id=row.id,
                    employee_id=item.employee_id, payslip_item_id=item.id, concept=concept,
                    incumbent_amount=theirs, zoiko_amount=ours[concept], difference=ours[concept] - theirs,
                    status="OPEN", created_by_id=actor_id))
    unmatched += len(set(by_code) - seen)            # Zoiko payslips the file does not cover
    row.matched_count, row.unmatched_count = len(seen), unmatched
    db.flush()
    be._audit(db, actor_id, "imported", "be_parallel_import", row.id,
              new={"run": run.id, "rows": len(rows), "unmatched": unmatched,
                   "tolerance": {k: str(v) for k, v in tolerance.items()}}, reason=reason)
    return be_parallel_summary(db, organization_id, row.id)


def explain_be_parallel_difference(db: Session, organization_id: int, difference_id: int, reason, actor_id) -> dict:
    row = _be_parallel_difference(db, organization_id, difference_id)
    if row.status == "ACCEPTED":
        raise BadRequestException("An accepted difference is final.")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A difference is explained with a reason.")
    row.status, row.explanation, row.explained_by_id = "EXPLAINED", text[:300], actor_id
    db.flush()
    be._audit(db, actor_id, "explained", "be_parallel_difference", row.id, new={"concept": row.concept}, reason=text)
    return be_parallel_difference_view(row)


def accept_be_parallel_difference(db: Session, organization_id: int, difference_id: int, actor_id) -> dict:
    from app.modules.payroll.service import require_four_eyes

    row = _be_parallel_difference(db, organization_id, difference_id)
    if row.status != "EXPLAINED":
        raise BadRequestException("Only an EXPLAINED difference is accepted.")
    require_four_eyes(row.explained_by_id, actor_id, "Accepting a Belgian parallel-run difference", db=db,
                      entity_type="be_parallel_difference", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "ACCEPTED", actor_id, datetime.utcnow()
    db.flush()
    be._audit(db, actor_id, "accepted", "be_parallel_difference", row.id, new={"status": "ACCEPTED"})
    return be_parallel_difference_view(row)


def accept_be_parallel_import(db: Session, organization_id: int, import_id: int, actor_id) -> dict:
    from app.modules.payroll.service import require_four_eyes

    row = _be_parallel_import(db, organization_id, import_id)
    if row.status != "OPEN":
        raise BadRequestException(f"The import is {row.status}.")
    if not be_parallel_summary(db, organization_id, import_id)["clean"]:
        raise BadRequestException("Every row must match and every difference be accepted first.")
    require_four_eyes(row.created_by_id, actor_id, "Accepting a Belgian parallel cycle", db=db,
                      entity_type="be_parallel_import", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "ACCEPTED", actor_id, datetime.utcnow()
    db.flush()
    be._audit(db, actor_id, "accepted", "be_parallel_import", row.id, new={"status": "ACCEPTED"})
    return be_parallel_summary(db, organization_id, import_id)


def withdraw_be_parallel_import(db: Session, organization_id: int, import_id: int, reason, actor_id) -> dict:
    text = be._reason(reason)
    row = _be_parallel_import(db, organization_id, import_id)
    if row.status != "OPEN":
        raise BadRequestException(f"The import is {row.status}.")
    row.status, row.withdrawn_reason = "WITHDRAWN", text[:300]
    db.flush()
    be._audit(db, actor_id, "withdrawn", "be_parallel_import", row.id, new={"status": "WITHDRAWN"}, reason=text)
    return be_parallel_import_view(row)


def be_parallel_accepted_months(db: Session) -> dict:
    """{organization_id: {cycle months}} of ACCEPTED cycles — the G4 evidence."""
    I = _be_parallel_models().PayrollBeParallelImport
    out = {}
    for org, month in db.query(I.organization_id, I.cycle_month).filter(I.status == "ACCEPTED").distinct():
        out.setdefault(org, set()).add(month)
    return out


def be_g4_state(db: Session, launch_orgs) -> tuple:
    """(ok, detail): every launch design partner has accepted cycles in at
    least MIN_MONTHS distinct pay months; no launch partner -> not met."""
    months = be_parallel_accepted_months(db)
    launch = sorted(launch_orgs or ())
    if not launch:
        return False, "no launch design partner is named (BE_CANARY_ORG_IDS is empty)"
    short = [org for org in launch if len(months.get(org, ())) < MIN_MONTHS]
    return not short, (f"{len(launch) - len(short)} of {len(launch)} launch partner(s) with accepted cycles in "
                       f"{MIN_MONTHS}+ distinct months" + (f"; missing: {short}" if short else ""))
