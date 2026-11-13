"""Belgium filings and obligations (ZP-BE-ENG-001 Block C1; spec §10, BE-014 /
BE-018 / BE-033 .. BE-037; decision D9).

  forms       Dimona IN / OUT / UPDATE / CANCEL events from the employment
              lines (BE-033); DmfA per legal employer + quarter from the
              employment-line data and the accumulator ledger (BE-034); the
              professional-withholding (FinProf) object from the tax ledger;
              Belcotax 281.10 per employee + income year with an employee copy
              and correction / cancellation lineage (BE-014).
  payload     CANONICAL and schema-neutral: amounts as strings, identifiers
              masked only (never a NISS / BIS digit, BE-040). The idempotency
              key is a hash of internal ids, the period and the payload hash:
              no personal data (spec §15).
  schema      chosen by SUBMISSION date from the signed content registry
              be_filing_<form>_schema_versions (one signed row per version and
              submission window; seeded "[PENDING G1]"). VALIDATED needs that
              version, its archived XSD (a reviewed source artifact with a file
              whose SHA-256 matches) and a mapping of the canonical payload onto
              it (RENDERERS: none is supplied yet, G-08). Anything missing keeps
              the filing DRAFT with the reason in validation_note.
  states      DRAFT -> VALIDATED -> APPROVED -> TRANSMITTED -> ACCEPTED /
              REJECTED -> SETTLED (spec §10). DRAFT / VALIDATED are rebuilt in
              place (audited, back to DRAFT); APPROVED is SUPERSEDED by a new
              version; REJECTED is followed by a new ORIGINAL version; a
              TRANSMITTED / ACCEPTED / SETTLED filing is never touched again: a
              change is a CORRECTION (Belcotax: also a CANCELLATION) linked by
              corrects_id. Same payload -> nothing happens.
  transport   TransmissionAdapter; the only adapter refuses (gate G3 is not
              certified, D9). Submission and the authority's response are
              recorded by hand; a repeated record with the same reference is the
              same event, a different one is refused.
  obligations ONSS quarter balance, each ONSS advance on its own (BE-018),
              withholding and the manual-worker holiday fund; acceptance is kept
              apart from settlement (BE-036): accepted-but-unpaid stays open.
  due dates   only from an Active, sourced payroll_statutory_filing_calendar
              row (BE-035); never a recurrence formula.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as be

ZERO = Decimal("0")
CENT = Decimal("0.01")
AUTHORITY = {"DIMONA": "ONSS", "DMFA": "ONSS", "FINPROF": "SPF_FINANCE", "BELCOTAX": "SPF_FINANCE"}
SCHEMA_KEYS = {form: f"be_filing_{form.lower()}_schema_versions" for form in AUTHORITY}
# payroll_statutory_filing_calendar.report_type per form / obligation (BE-035).
CALENDAR_REPORT_TYPES = {"DMFA": "BE_DMFA", "FINPROF": "BE_FINPROF", "BELCOTAX": "BE_BELCOTAX",
                         "ONSS_QUARTER": "BE_DMFA", "ONSS_ADVANCE": "BE_ONSS_ADVANCE",
                         "WITHHOLDING": "BE_FINPROF", "HOLIDAY_FUND": "BE_HOLIDAY_FUND"}
EDITABLE = ("DRAFT", "VALIDATED")
SENT = ("TRANSMITTED", "ACCEPTED", "SETTLED")
ANSWERED = ("ACCEPTED", "REJECTED", "SETTLED")
WHT_FREQUENCIES = ("MONTHLY", "QUARTERLY")            # engineering vocabulary (G-30); anything else blocks
DIMONA_EVENTS = ("IN", "OUT", "UPDATE", "CANCEL")
UNSOURCED = "DUE_DATE_UNSOURCED"
FICHE = "281.10"                                      # the Belcotax fiche name (an identifier, not a value)
ONSS_LEDGER = ("ONSS_EMPLOYEE_BASE", "ONSS_EMPLOYEE", "ONSS_EMPLOYER_BASE", "ONSS_MANUAL_108_BASE",
               "WORK_BONUS_SOCIAL")
TAX_LEDGER = ("WITHHOLDING_TAXABLE", "WITHHOLDING", "WITHHOLDING_EXCEPTIONAL_TAXABLE", "WITHHOLDING_EXCEPTIONAL",
              "WORK_BONUS_FISCAL")
FICHE_LEDGER = TAX_LEDGER + ("ONSS_EMPLOYEE", "WORK_BONUS_SOCIAL")

# (form, schema version) -> callable(payload) -> XML bytes. EMPTY: no mapping of
# the canonical payload onto an official schema is supplied yet (G-08). A test
# may register a synthetic TEST ONLY renderer.
RENDERERS: dict = {}


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Belgium ({code}): {message}")


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _s(value) -> str:
    return format(_dec(value).quantize(CENT), "f")


def _today(on=None) -> date:
    return be._as_date(on, "date") if on is not None else date.today()


# ── periods ─────────────────────────────────────────────────────────────────
def quarter_key(on: date) -> str:
    return f"{on.year:04d}Q{(on.month - 1) // 3 + 1}"


def quarter_bounds(key: str) -> tuple:
    try:
        year, quarter = int(key[:4]), int(key[5:])
        if key[4] != "Q" or quarter not in (1, 2, 3, 4):
            raise ValueError
    except (ValueError, IndexError):
        raise BadRequestException("A quarter is written YYYYQn (n = 1..4).")
    first = 3 * quarter - 2
    return date(year, first, 1), date(year, first + 2, calendar.monthrange(year, first + 2)[1])


def month_bounds(key: str) -> tuple:
    try:
        year, month = int(key[:4]), int(key[5:7])
        if key[4] != "-" or len(key) != 7 or not 1 <= month <= 12:
            raise ValueError
    except (ValueError, IndexError):
        raise BadRequestException("A month is written YYYY-MM.")
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _period_bounds(key: str) -> tuple:
    if len(key) == 4:
        return date(int(key), 1, 1), date(int(key), 12, 31)
    if "Q" in key:
        return quarter_bounds(key)
    if len(key) == 7:
        return month_bounds(key)
    day = be._as_date(key, "period")
    return day, day


# ── due dates (BE-035) ──────────────────────────────────────────────────────
def due_on(db: Session, what: str, period_key: str) -> tuple:
    """(date, None) from the ONE Active, sourced calendar row of the report
    type and period; otherwise (None, DUE_DATE_UNSOURCED). Never computed."""
    from app.modules.payroll.models import StatutoryFilingCalendar as C

    report_type = CALENDAR_REPORT_TYPES.get(what)
    if report_type is None:
        return None, UNSOURCED
    rows = (db.query(C).filter(C.jurisdiction_country == be.BE, C.jurisdiction_state.is_(None),
                               C.report_type == report_type, C.period_key == period_key, C.status == "Active",
                               C.source_document_id.isnot(None)).all())
    if len(rows) != 1:
        return None, UNSOURCED
    return rows[0].due_date, None


def calendar_view(db: Session, year: Optional[int] = None) -> list:
    """The Belgian authority calendar rows (every status; only Active +
    sourced ones are used)."""
    from app.modules.payroll.models import StatutoryFilingCalendar as C

    query = db.query(C).filter(C.jurisdiction_country == be.BE)
    if year:
        query = query.filter(C.reporting_year == str(year))
    return [{"id": r.id, "reportType": r.report_type, "reportingYear": r.reporting_year, "periodKey": r.period_key,
             "periodLabel": r.period_label, "dueDate": r.due_date.isoformat() if r.due_date else None,
             "paymentDueDate": r.payment_due_date.isoformat() if r.payment_due_date else None, "status": r.status,
             "sourced": r.source_document_id is not None,
             "used": r.status == "Active" and r.source_document_id is not None}
            for r in query.order_by(C.reporting_year, C.report_type, C.period_key, C.id).all()]


# ── schema registry (BE-034) ────────────────────────────────────────────────
def schema_for(db: Session, organization_id: int, form_code: str, submission_date: date) -> tuple:
    """(version, slab row, None) of the signed schema-version row in force on
    the SUBMISSION date, or (None, None, reason)."""
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError
    from app.modules.payroll.engine.jurisdictions.belgium.pack import field

    pack = be._be_pack_for(db, organization_id, submission_date)
    if pack is None:
        return None, None, "no active Belgium rule pack on the submission date (content pending)"
    try:
        rows = pack.table(SCHEMA_KEYS[form_code])
    except BECalculationBlockedError as error:
        return None, None, f"schema version content pending ({error.key})"
    if len(rows) != 1:
        return None, None, f"{len(rows)} {form_code} schema versions are in force on {submission_date.isoformat()}"
    version = " ".join(str(field(rows[0], "tax_formula") or "").split())
    if not version:
        return None, None, "the signed schema version row has no version name"
    return version, rows[0], None


def archived_schema(db: Session, row) -> Optional[bytes]:
    """The archived XSD of a signed schema-version row: its reviewed source
    artifact's file, only when its SHA-256 matches the recorded checksum."""
    from app.modules.payroll.engine.jurisdictions.belgium.pack import field
    from app.modules.payroll.models import SourceArtifact

    source_id = field(row, "source_document_id")
    artifact = db.get(SourceArtifact, source_id) if source_id else None
    if artifact is None or not artifact.file_path or not artifact.checksum_sha256 or not artifact.reviewer_id:
        return None
    try:
        from app.modules.payroll.service import download_source_artifact_file

        data, _name, _type = download_source_artifact_file(db, artifact.id)
    except Exception:  # an unreadable archive is "not archived"
        return None
    return data if hashlib.sha256(data).hexdigest() == artifact.checksum_sha256 else None


def _xsd_errors(xsd: bytes, xml: bytes) -> list:
    from lxml import etree

    try:
        schema = etree.XMLSchema(etree.fromstring(xsd))
        document = etree.fromstring(xml)
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError) as error:
        return [f"unreadable schema or document: {error}"[:200]]
    if schema.validate(document):
        return []
    return [f"line {e.line}: {e.message}"[:200] for e in schema.error_log][:20]


# ── transmission (D9) ───────────────────────────────────────────────────────
class TransmissionAdapter:
    """An authority channel (Dimona / DmfA web services, FinProf, Belcotax-on-web)."""

    name = "abstract"

    def transmit(self, filing, document: bytes) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class UncertifiedAdapter(TransmissionAdapter):
    """The only adapter: gate G3 (authority connectivity) is not certified."""

    name = "UNCERTIFIED"

    def transmit(self, filing, document: bytes) -> dict:
        _conflict("BE_TRANSMISSION_NOT_CERTIFIED", "gate G3 is not certified: no authority channel is connected "
                  "(D9). Submit through the authority portal and record the submission and its response here.")


def adapter_for(authority: str) -> TransmissionAdapter:
    return UncertifiedAdapter()


# ── records ─────────────────────────────────────────────────────────────────
def _model():
    return be._models().PayrollBeFiling


def _idempotency_key(row_or_parts, digest: str) -> str:
    raw = "|".join(str(x) for x in (*row_or_parts, digest))
    return hashlib.sha256(raw.encode()).hexdigest()


def _key_parts(organization_id, legal_entity_id, form_code, key, subject, kind, version, corrects_id):
    return (organization_id, legal_entity_id, form_code, key, subject, kind, version, corrects_id)


def rendition(payload: dict) -> str:
    """The human-readable rendition (BE-037): one "path: value" line per leaf."""
    lines = []

    def walk(prefix, value):
        if isinstance(value, dict):
            for k in sorted(value):
                walk(f"{prefix}.{k}" if prefix else str(k), value[k])
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(f"{prefix}[{i}]", v)
        else:
            lines.append(f"{prefix}: {'' if value is None else value}")

    walk("", payload)
    return "\n".join(lines)


def _audit(db, actor_id, action, row_id, new):
    be._audit(db, actor_id, action, "be_filing", row_id, new=new)


def _latest(db: Session, organization_id, legal_entity_id, form_code, key, subject, kind="ORIGINAL"):
    F = _model()
    query = db.query(F).filter(F.organization_id == organization_id, F.form_code == form_code,
                               F.period_key == key, F.kind == kind)
    query = query.filter(F.legal_entity_id.is_(None) if legal_entity_id is None else F.legal_entity_id == legal_entity_id)
    query = query.filter(F.subject_key.is_(None) if subject is None else F.subject_key == subject)
    return query.order_by(F.version.desc(), F.id.desc()).first()


def _new_row(db: Session, organization_id, legal_entity_id, form_code, key, subject, kind, version, payload,
             run_ids, due, actor_id, corrects_id=None, previous_id=None):
    F = _model()
    digest = canonical_hash(payload)
    row = F(organization_id=organization_id, legal_entity_id=legal_entity_id, authority=AUTHORITY[form_code],
            form_code=form_code, period_key=key, subject_key=subject, kind=kind, version=version, run_ids=run_ids,
            payload=payload, payload_hash=digest, rendition=rendition(payload),
            idempotency_key=_idempotency_key(_key_parts(organization_id, legal_entity_id, form_code, key, subject,
                                                        kind, version, corrects_id), digest),
            due_on=due, status="DRAFT", corrects_id=corrects_id, previous_version_id=previous_id,
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "generated", row.id, {"form": form_code, "period": key, "kind": kind, "version": version,
                                               "hash": digest})
    return row


def _refresh(db: Session, row, payload, run_ids, due, actor_id):
    digest = canonical_hash(payload)
    old = {"hash": row.payload_hash, "status": row.status}
    row.payload, row.payload_hash, row.run_ids, row.due_on = payload, digest, run_ids, due
    row.rendition, row.status, row.schema_version, row.validation_note = rendition(payload), "DRAFT", None, None
    row.idempotency_key = _idempotency_key(_key_parts(row.organization_id, row.legal_entity_id, row.form_code,
                                                      row.period_key, row.subject_key, row.kind, row.version,
                                                      row.corrects_id), digest)
    row.updated_at = datetime.utcnow()
    db.flush()
    be._audit(db, actor_id, "regenerated", "be_filing", row.id, old=old, new={"hash": digest, "status": "DRAFT"})
    return row


def upsert_filing(db: Session, organization_id: int, legal_entity_id, form_code: str, key: str, payload: dict,
                  run_ids, due, actor_id, subject: Optional[str] = None):
    """Store `payload` for (employer, form, period, subject) under the
    versioning rules; the same payload again returns the existing row."""
    digest = canonical_hash(payload)
    latest = _latest(db, organization_id, legal_entity_id, form_code, key, subject)
    if latest is None:
        return _new_row(db, organization_id, legal_entity_id, form_code, key, subject, "ORIGINAL", 1, payload,
                        run_ids, due, actor_id)
    if latest.status in SENT:
        return correct_filing(db, latest, payload, run_ids, actor_id)
    if latest.payload_hash == digest and latest.status != "SUPERSEDED":
        return latest                                                      # nothing changed (idempotent)
    if latest.status in EDITABLE:
        return _refresh(db, latest, payload, run_ids, due, actor_id)
    if latest.status == "APPROVED":
        latest.status = "SUPERSEDED"
        _audit(db, actor_id, "superseded", latest.id, {"status": "SUPERSEDED"})
    return _new_row(db, organization_id, legal_entity_id, form_code, key, subject, "ORIGINAL", latest.version + 1,
                    payload, run_ids, due, actor_id, previous_id=latest.id)


def correct_filing(db: Session, original, payload: dict, run_ids, actor_id, kind: str = "CORRECTION"):
    """A CORRECTION (or CANCELLATION) linked to a transmitted / accepted
    filing; the original is never edited. Same payload -> no duplicate."""
    F = _model()
    marked = {**payload, "correction": kind, "corrects": original.id}
    if kind == "CORRECTION" and original.payload_hash == canonical_hash(payload):
        return original
    rows = (db.query(F).filter(F.corrects_id == original.id, F.kind == kind)
            .order_by(F.version.desc(), F.id.desc()).all())
    latest = rows[0] if rows else None
    if latest is not None and latest.payload_hash == canonical_hash(marked) and latest.status != "SUPERSEDED":
        return latest
    if latest is not None and latest.status in EDITABLE:
        return _refresh(db, latest, marked, run_ids, original.due_on, actor_id)
    if latest is not None and latest.status == "APPROVED":
        latest.status = "SUPERSEDED"
        _audit(db, actor_id, "superseded", latest.id, {"status": "SUPERSEDED"})
    return _new_row(db, original.organization_id, original.legal_entity_id, original.form_code, original.period_key,
                    original.subject_key, kind, (latest.version + 1) if latest else 1, marked, run_ids,
                    original.due_on, actor_id, corrects_id=original.id, previous_id=getattr(latest, "id", None))


# ── identity blocks (masked only) ───────────────────────────────────────────
def _employer(db: Session, organization_id: int, legal_entity_id, on: date) -> dict:
    reg = be._be_registration_for(db, organization_id, legal_entity_id, on)
    if reg is None or reg.status not in (be.STATUS_ACTIVE, be.STATUS_SUPERSEDED):
        _conflict("BE_EMPLOYER_NOT_REGISTERED", "no ACTIVE Belgian employer registration is in force for the period.")
    onss = None
    if reg.onss_number_vault_id:
        vault = db.get(be._models().PayrollBeIdentifierVault, reg.onss_number_vault_id)
        onss = be.identifier_view(vault).get("masked") if vault is not None else None
    return {"registrationId": reg.id, "legalName": reg.legal_name, "enterpriseNumber": reg.enterprise_number,
            "onssNumberMasked": onss, "employerCategory": reg.employer_category_code,
            "withholdingFrequency": reg.withholding_declaration_frequency,
            "verificationState": getattr(reg, "verification_state", None)}


def _worker(db: Session, organization_id: int, employee) -> dict:
    return {"employeeId": employee.id,
            "identifierMasked": be._be_identifier_masked(db, organization_id, employee.id)}


# ── Dimona (BE-033) ─────────────────────────────────────────────────────────
def _dimona_lines(db: Session, organization_id: int, employee_id: int) -> list:
    C = be._models().PayrollBeEmploymentClassification
    rows = (db.query(C).filter(C.organization_id == organization_id, C.employee_id == employee_id,
                               C.status == be.STATUS_ACTIVE).order_by(C.employment_line, C.effective_from.desc(),
                                                                      C.id.desc()).all())
    latest = {}
    for row in rows:
        latest.setdefault(row.employment_line, row)
    return [latest[k] for k in sorted(latest)]


def _dimona_payload(db, organization_id, employee, line, event, start, end, extra=None) -> dict:
    P = be._models().PayrollBeWorkerProfile
    profile = be._latest_for(db, P, organization_id, start, employee_id=employee.id)
    return {"form": "DIMONA", "event": event, "canonical": True,
            "employer": _employer(db, organization_id, getattr(employee, "legal_entity_id", None), start),
            "worker": {**_worker(db, organization_id, employee),
                       "workerCategory": getattr(profile, "worker_category", None),
                       "onssWorkerCode": getattr(profile, "onss_worker_code", None)},
            "employmentLine": line.employment_line, "jointCommittee": line.joint_committee,
            "subCommittee": line.sub_committee, "contractType": line.contract_type,
            "startDate": start.isoformat(), "endDate": end.isoformat() if end else None, **(extra or {})}


def build_be_dimona_events(db: Session, organization_id: int, employee_id: int, actor_id,
                           event: Optional[str] = None, reason: Optional[str] = None, line: Optional[str] = None) -> list:
    """Create / update / cancel the Dimona events of an employee's ACTIVE
    employment lines from their contract dates. IN once per line; a changed
    period after transmission is an UPDATE linked to the IN (never a silent
    date overwrite); OUT when the line has an end date; CANCEL (reason) links a
    CANCELLATION to an IN that was transmitted."""
    event = str(event or "SYNC").strip().upper()
    if event not in ("SYNC", "CANCEL"):
        raise BadRequestException("event must be SYNC (IN / UPDATE / OUT from the employment lines) or CANCEL.")
    employee = be._employee(db, organization_id, employee_id)
    lines = [ln for ln in _dimona_lines(db, organization_id, employee.id) if line is None or ln.employment_line == line]
    if not lines:
        _conflict("BE_DIMONA_NO_LINE", "the employee has no ACTIVE Belgian employment line.")
    entity = getattr(employee, "legal_entity_id", None)
    out = []
    for ln in lines:
        start = ln.contract_start_date
        if start is None:
            _conflict("BE_DIMONA_START_MISSING", f"employment line {ln.employment_line} has no contract start date.")
        end = ln.contract_end_date
        subject_in = f"E{employee.id}:{ln.employment_line}:IN"
        current = _dimona_in(db, organization_id, entity, subject_in)
        if event == "CANCEL":
            if current is None or current.status not in SENT:
                _conflict("BE_DIMONA_NOT_SENT", "only a transmitted Dimona IN is cancelled; delete nothing, a "
                          "DRAFT is simply rebuilt.")
            text = be._reason(reason)
            out.append(correct_filing(db, current, {**current.payload, "event": "CANCEL", "reason": text}, None,
                                      actor_id, kind="CANCELLATION"))
            continue
        payload = _dimona_payload(db, organization_id, employee, ln, "IN", start, end)
        if current is None:
            out.append(upsert_filing(db, organization_id, entity, "DIMONA", start.isoformat(), payload, None, None,
                                     actor_id, subject=subject_in))
        elif current.status in SENT:
            sent = current.payload or {}
            if (sent.get("startDate"), sent.get("endDate")) != (payload["startDate"], payload["endDate"]):
                update = {**payload, "event": "UPDATE", "previousStartDate": sent.get("startDate"),
                          "previousEndDate": sent.get("endDate")}
                out.append(correct_filing(db, current, update, None, actor_id))
            else:
                out.append(current)
        else:
            out.append(upsert_filing(db, organization_id, entity, "DIMONA", current.period_key, payload, None, None,
                                     actor_id, subject=subject_in))
        if end is not None:
            out_payload = _dimona_payload(db, organization_id, employee, ln, "OUT", start, end,
                                          {"inFilingId": (current or out[-1]).id})
            out.append(upsert_filing(db, organization_id, entity, "DIMONA", end.isoformat(), out_payload, None, None,
                                     actor_id, subject=f"E{employee.id}:{ln.employment_line}:OUT"))
    return out


def _dimona_in(db: Session, organization_id: int, entity, subject: str):
    F = _model()
    query = db.query(F).filter(F.organization_id == organization_id, F.form_code == "DIMONA", F.kind == "ORIGINAL",
                               F.subject_key == subject, F.status != "SUPERSEDED")
    query = query.filter(F.legal_entity_id.is_(None) if entity is None else F.legal_entity_id == entity)
    return query.order_by(F.version.desc(), F.id.desc()).first()


def dimona_status(db: Session, organization_id: int, employee_id: int, line: Optional[str], on: date) -> dict:
    """BE-033 preflight: the line's Dimona IN must be ACCEPTED (or SETTLED) and
    not cancelled by an accepted CANCELLATION; {ok, code, message}."""
    from app.modules.payroll.models import PayrollEmployee

    F = _model()
    employee = db.get(PayrollEmployee, employee_id)
    entity = getattr(employee, "legal_entity_id", None)
    lines = [line] if line else [ln.employment_line for ln in _dimona_lines(db, organization_id, employee_id)]
    for name in lines or [None]:
        if name is None:
            return {"ok": False, "code": "BE_DIMONA_IN_MISSING", "message": "no ACTIVE employment line to declare."}
        row = _dimona_in(db, organization_id, entity, f"E{employee_id}:{name}:IN")
        if row is None:
            return {"ok": False, "code": "BE_DIMONA_IN_MISSING",
                    "message": f"no Dimona IN exists for employment line {name} (BE-033)."}
        if row.status not in ("ACCEPTED", "SETTLED"):
            return {"ok": False, "code": "BE_DIMONA_IN_NOT_ACCEPTED",
                    "message": f"the Dimona IN of line {name} is {row.status}; the authority must accept it first."}
        cancelled = db.query(F.id).filter(F.corrects_id == row.id, F.kind == "CANCELLATION",
                                          F.status.in_(("ACCEPTED", "SETTLED"))).first()
        if cancelled:
            return {"ok": False, "code": "BE_DIMONA_IN_CANCELLED", "message": f"the Dimona IN of line {name} "
                    "was cancelled."}
    return {"ok": True, "code": None, "message": None}


# ── ledger sources ──────────────────────────────────────────────────────────
def _entries(db: Session, organization_id: int, legal_entity_id, start: date, end: date, accumulators,
             by_source_period: bool = False) -> list:
    """Committed RUN / CORRECTION ledger entries of [start, end]. Withholding
    and Belcotax follow the pay date; DmfA (by_source_period) puts a CORRECTION
    in the quarter its source period relates to, so a correction of an
    accepted quarter re-declares THAT quarter."""
    from sqlalchemy import and_, or_

    Entry = be._models().PayrollBeAccumulatorEntry
    in_window = and_(Entry.pay_date >= start, Entry.pay_date <= end)
    if by_source_period:
        source = and_(Entry.source_period_end.isnot(None), Entry.source_period_end >= start,
                      Entry.source_period_end <= end)
        in_window = or_(and_(Entry.entry_kind == "RUN", in_window),
                        and_(Entry.entry_kind == "CORRECTION", or_(source, and_(Entry.source_period_end.is_(None),
                                                                                in_window))))
    query = db.query(Entry).filter(Entry.organization_id == organization_id, in_window,
                                   Entry.accumulator.in_(accumulators),
                                   Entry.entry_kind.in_(("RUN", "CORRECTION")))
    query = query.filter(Entry.legal_entity_id.is_(None) if legal_entity_id is None
                         else Entry.legal_entity_id == legal_entity_id)
    return query.order_by(Entry.employee_id, Entry.id).all()


def _employer_contributions(db: Session, item_ids) -> dict:
    """{payslip_item_id: employer total} from the frozen BE snapshots (a
    correction payslip carries its employerTotalDelta)."""
    from app.modules.payroll.models import PayslipItem

    out = {}
    for item in db.query(PayslipItem).filter(PayslipItem.id.in_(sorted(item_ids))).all() if item_ids else []:
        s = item.be_calculation_snapshot or {}
        if s.get("correctionOf"):
            out[item.id] = (_dec(s.get("employerTotalDelta")), None)
        else:
            out[item.id] = (_dec(s.get("be_employer_total")), _dec((s.get("obligationDeltas") or {})
                                                                   .get("HOLIDAY_FUND_QUARTERLY")))
    return out


def _run_ids(entries) -> list:
    return sorted({e.run_id for e in entries if e.run_id is not None})


# ── DmfA (BE-034) ───────────────────────────────────────────────────────────
def build_be_dmfa(db: Session, organization_id: int, quarter: str, legal_entity_id, actor_id):
    """The DmfA of one legal employer + quarter from the committed ledger and
    the employment lines, plus its ONSS quarter / holiday-fund obligations."""
    from app.modules.payroll.models import PayrollEmployee

    be._legal_entity(db, organization_id, legal_entity_id)
    start, end = quarter_bounds(str(quarter).strip().upper())
    key = quarter_key(start)
    entries = _entries(db, organization_id, legal_entity_id, start, end, ONSS_LEDGER, by_source_period=True)
    if not entries:
        _conflict("BE_NO_COMMITTED_PAYROLL", f"no committed Belgian payroll in {key} for this employer.")
    employer = _employer(db, organization_id, legal_entity_id, end)
    employer_by_item = _employer_contributions(db, {e.payslip_item_id for e in entries if e.payslip_item_id})
    workers, totals = {}, {a: ZERO for a in ONSS_LEDGER}
    totals["employerContributions"], totals["holidayFund"] = ZERO, ZERO
    seen_items = set()
    for e in entries:
        employee = db.get(PayrollEmployee, e.employee_id)
        w = workers.setdefault(e.employee_id, {**_worker(db, organization_id, employee), "lines": {}})
        line = w["lines"].setdefault(e.employment_line or "-", {a: ZERO for a in ONSS_LEDGER}
                                     | {"employerContributions": ZERO, "payslipItemIds": set()})
        line[e.accumulator] += _dec(e.amount)
        totals[e.accumulator] += _dec(e.amount)
        if e.payslip_item_id and e.payslip_item_id not in seen_items:
            seen_items.add(e.payslip_item_id)
            employer_total, fund = employer_by_item.get(e.payslip_item_id, (ZERO, None))
            line["employerContributions"] += employer_total
            totals["employerContributions"] += employer_total
            totals["holidayFund"] += fund or ZERO
        if e.payslip_item_id:
            line["payslipItemIds"].add(e.payslip_item_id)
    C = be._models().PayrollBeEmploymentClassification
    worker_rows = []
    for employee_id in sorted(workers):
        w = workers[employee_id]
        lines = []
        for name in sorted(w["lines"]):
            data = w["lines"][name]
            cls = be._latest_for(db, C, organization_id, end, employee_id=employee_id, employment_line=name) \
                if name != "-" else None
            lines.append({"employmentLine": name, "jointCommittee": getattr(cls, "joint_committee", None),
                          "subCommittee": getattr(cls, "sub_committee", None),
                          "contractType": getattr(cls, "contract_type", None),
                          "bases": {a: _s(data[a]) for a in ("ONSS_EMPLOYEE_BASE", "ONSS_EMPLOYER_BASE",
                                                             "ONSS_MANUAL_108_BASE")},
                          "employeeContribution": _s(data["ONSS_EMPLOYEE"]),
                          "socialWorkBonus": _s(data["WORK_BONUS_SOCIAL"]),
                          "employerContributions": _s(data["employerContributions"]),
                          "payslipItemIds": sorted(data["payslipItemIds"]),
                          # DmfA worker / remuneration / contribution CODES are content (G-08).
                          "coding": "PENDING_CONTENT"})
        worker_rows.append({"employeeId": w["employeeId"], "identifierMasked": w["identifierMasked"],
                            "employmentLines": lines})
    onss_due = totals["ONSS_EMPLOYEE"] + totals["employerContributions"]
    payload = {"form": "DMFA", "quarter": key, "legalEntityId": legal_entity_id, "canonical": True,
               "employer": employer, "workers": worker_rows,
               "totals": {"employeeContributions": _s(totals["ONSS_EMPLOYEE"]),
                          "employerContributions": _s(totals["employerContributions"]),
                          "socialWorkBonus": _s(totals["WORK_BONUS_SOCIAL"]), "onssDue": _s(onss_due),
                          "holidayFund": _s(totals["holidayFund"])}}
    due, _why = due_on(db, "DMFA", key)
    filing = upsert_filing(db, organization_id, legal_entity_id, "DMFA", key, payload, _run_ids(entries), due, actor_id)
    obligations = [upsert_obligation(db, organization_id, legal_entity_id, "ONSS_QUARTER", key, onss_due, filing,
                                     _run_ids(entries), {"employee": _s(totals["ONSS_EMPLOYEE"]),
                                                         "employer": _s(totals["employerContributions"])}, actor_id)]
    if totals["holidayFund"] != ZERO:
        obligations.append(upsert_obligation(db, organization_id, legal_entity_id, "HOLIDAY_FUND", key,
                                             totals["holidayFund"], filing, _run_ids(entries),
                                             {"quarterly": _s(totals["holidayFund"])}, actor_id))
    return filing, obligations


# ── professional withholding (FinProf) ──────────────────────────────────────
def build_be_withholding(db: Session, organization_id: int, period: str, legal_entity_id, actor_id):
    """The withholding filing object of one employer + declaration period
    (MONTHLY YYYY-MM / QUARTERLY YYYYQn, from the registration: never assumed,
    BE-013) from the tax ledger, plus its WITHHOLDING obligation."""
    be._legal_entity(db, organization_id, legal_entity_id)
    period = str(period or "").strip().upper()
    start, end = quarter_bounds(period) if "Q" in period else month_bounds(period)
    employer = _employer(db, organization_id, legal_entity_id, end)
    frequency = (employer["withholdingFrequency"] or "").upper()
    if frequency not in WHT_FREQUENCIES:
        _conflict("BE_WHT_FREQUENCY_UNKNOWN", "the employer's withholding declaration frequency is not recorded "
                  "(BE-013: never assumed).")
    if (frequency == "QUARTERLY") != ("Q" in period):
        _conflict("BE_WHT_PERIOD_MISMATCH", f"the employer declares {frequency}; build a "
                  f"{'YYYYQn' if frequency == 'QUARTERLY' else 'YYYY-MM'} period.")
    entries = _entries(db, organization_id, legal_entity_id, start, end, TAX_LEDGER)
    if not entries:
        _conflict("BE_NO_COMMITTED_PAYROLL", f"no committed Belgian payroll in {period} for this employer.")
    sums = {a: ZERO for a in TAX_LEDGER}
    employees = set()
    for e in entries:
        sums[e.accumulator] += _dec(e.amount)
        employees.add(e.employee_id)
    total = sums["WITHHOLDING"] + sums["WITHHOLDING_EXCEPTIONAL"]
    payload = {"form": "FINPROF", "period": period, "frequency": frequency, "legalEntityId": legal_entity_id,
               "canonical": True, "employer": employer, "employeeCount": len(employees),
               "regular": {"taxable": _s(sums["WITHHOLDING_TAXABLE"]), "withheld": _s(sums["WITHHOLDING"])},
               "exceptional": {"taxable": _s(sums["WITHHOLDING_EXCEPTIONAL_TAXABLE"]),
                               "withheld": _s(sums["WITHHOLDING_EXCEPTIONAL"])},
               "fiscalWorkBonus": _s(sums["WORK_BONUS_FISCAL"]), "totalWithheld": _s(total),
               # the FinProf nature-of-income codes are content (G-08)
               "coding": "PENDING_CONTENT"}
    due, _why = due_on(db, "FINPROF", period)
    filing = upsert_filing(db, organization_id, legal_entity_id, "FINPROF", period, payload, _run_ids(entries), due,
                           actor_id)
    obligation = upsert_obligation(db, organization_id, legal_entity_id, "WITHHOLDING", period, total, filing,
                                   _run_ids(entries), {"regular": _s(sums["WITHHOLDING"]),
                                                       "exceptional": _s(sums["WITHHOLDING_EXCEPTIONAL"])}, actor_id)
    return filing, [obligation]


# ── Belcotax 281.10 (BE-014) ────────────────────────────────────────────────
def build_be_belcotax(db: Session, organization_id: int, income_year: int, legal_entity_id, actor_id,
                      today: Optional[date] = None) -> list:
    """One 281.10 fiche per employee for a CLOSED income year from the ledger,
    with an employee copy (the rendition). Rebuilding after transmission
    creates a CORRECTION; cancel_be_belcotax a CANCELLATION."""
    from app.modules.payroll.models import PayrollEmployee

    year = int(income_year)
    if _today(today) <= date(year, 12, 31):
        _conflict("BE_INCOME_YEAR_OPEN", f"{year} is not closed; {FICHE} fiches are built after the income year.")
    be._legal_entity(db, organization_id, legal_entity_id)
    entries = _entries(db, organization_id, legal_entity_id, date(year, 1, 1), date(year, 12, 31), FICHE_LEDGER)
    if not entries:
        _conflict("BE_NO_COMMITTED_PAYROLL", f"no committed Belgian payroll in {year} for this employer.")
    employer = _employer(db, organization_id, legal_entity_id, date(year, 12, 31))
    per = {}
    for e in entries:
        per.setdefault(e.employee_id, {a: ZERO for a in FICHE_LEDGER})[e.accumulator] += _dec(e.amount)
    due, _why = due_on(db, "BELCOTAX", str(year))
    out = []
    for employee_id in sorted(per):
        sums = per[employee_id]
        employee = db.get(PayrollEmployee, employee_id)
        payload = {"form": "BELCOTAX", "fiche": FICHE, "incomeYear": year, "legalEntityId": legal_entity_id,
                   "canonical": True, "employer": employer, "worker": _worker(db, organization_id, employee),
                   "remuneration": {"regularTaxable": _s(sums["WITHHOLDING_TAXABLE"]),
                                    "exceptionalTaxable": _s(sums["WITHHOLDING_EXCEPTIONAL_TAXABLE"])},
                   "withholding": {"regular": _s(sums["WITHHOLDING"]),
                                   "exceptional": _s(sums["WITHHOLDING_EXCEPTIONAL"])},
                   "onssEmployee": _s(sums["ONSS_EMPLOYEE"]),
                   "workBonus": {"social": _s(sums["WORK_BONUS_SOCIAL"]), "fiscal": _s(sums["WORK_BONUS_FISCAL"])},
                   # the 281.10 box codes are content (G-08)
                   "coding": "PENDING_CONTENT"}
        out.append(upsert_filing(db, organization_id, legal_entity_id, "BELCOTAX", str(year), payload,
                                 _run_ids([x for x in entries if x.employee_id == employee_id]), due, actor_id,
                                 subject=f"E{employee_id}"))
    return out


def cancel_be_belcotax(db: Session, organization_id: int, filing_id: int, reason, actor_id):
    row = _filing(db, organization_id, filing_id)
    if row.form_code != "BELCOTAX" or row.kind != "ORIGINAL":
        raise BadRequestException(f"Only an original Belcotax {FICHE} fiche is cancelled.")
    if row.status not in SENT:
        _conflict("BE_FILING_NOT_SENT", "only a transmitted fiche is cancelled; a DRAFT is simply rebuilt.")
    return correct_filing(db, row, {**row.payload, "cancelled": True, "reason": be._reason(reason)}, row.run_ids,
                          actor_id, kind="CANCELLATION")


def employee_copy(db: Session, organization_id: int, filing_id: int) -> dict:
    """The employee's copy of a 281.10 fiche (masked identifiers only)."""
    row = _filing(db, organization_id, filing_id)
    if row.form_code != "BELCOTAX":
        raise BadRequestException(f"Only a Belcotax {FICHE} fiche has an employee copy.")
    return {"filingId": row.id, "incomeYear": row.period_key, "kind": row.kind, "version": row.version,
            "status": row.status, "rendition": row.rendition}


# ── obligations (BE-018 / BE-036) ───────────────────────────────────────────
def _obligation_model():
    return be._models().PayrollBeObligation


def _obligation_key(organization_id, legal_entity_id, obligation_type, period_key, suffix="") -> str:
    raw = f"{organization_id}|{legal_entity_id}|{obligation_type}|{period_key}|{suffix}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _advances(db, organization_id, legal_entity_id, period_key) -> Decimal:
    O = _obligation_model()
    rows = db.query(O.amount_due).filter(O.organization_id == organization_id, O.obligation_type == "ONSS_ADVANCE",
                                         O.period_key == period_key)
    rows = rows.filter(O.legal_entity_id.is_(None) if legal_entity_id is None else O.legal_entity_id == legal_entity_id)
    return sum((_dec(r[0]) for r in rows.all()), ZERO)


def upsert_obligation(db: Session, organization_id: int, legal_entity_id, obligation_type: str, period_key: str,
                      amount: Decimal, filing, run_ids, components: dict, actor_id):
    """The obligation of (employer, type, period). An ONSS quarter carries the
    balance after the recorded advances. A change after a payment raises a
    CHANGED_AFTER_PAYMENT variance; the obligation is never silently reset."""
    O = _obligation_model()
    amount = _dec(amount)
    if obligation_type == "ONSS_QUARTER":
        advances = _advances(db, organization_id, legal_entity_id, period_key)
        components = {**components, "total": _s(amount), "advances": _s(advances)}
        amount = max(amount - advances, ZERO)
    key = _obligation_key(organization_id, legal_entity_id, obligation_type, period_key)
    row = db.query(O).filter(O.obligation_key == key).first()
    due, _why = due_on(db, obligation_type, period_key)
    if row is None:
        row = O(organization_id=organization_id, legal_entity_id=legal_entity_id, obligation_type=obligation_type,
                period_key=period_key, obligation_key=key, filing_id=getattr(filing, "id", None), due_on=due,
                amount_due=amount, paid_amount=ZERO, payments=[], run_ids=run_ids, components=components,
                acceptance_status=_acceptance(filing), status="DUE", created_by_id=actor_id)
        db.add(row)
        db.flush()
        be._audit(db, actor_id, "created", "be_obligation", row.id,
                  new={"type": obligation_type, "period": period_key, "amount": _s(amount)})
        return row
    old = _dec(row.amount_due)
    row.filing_id = getattr(filing, "id", row.filing_id)
    row.run_ids, row.components, row.due_on = run_ids, components, due or row.due_on
    row.acceptance_status = _acceptance(filing) if filing is not None else row.acceptance_status
    if old != amount:
        row.amount_due = amount
        if _dec(row.paid_amount) > ZERO:
            raise_variance(db, row, "CHANGED_AFTER_PAYMENT", old, amount, actor_id)
        be._audit(db, actor_id, "amount_changed", "be_obligation", row.id, old={"amount": _s(old)},
                  new={"amount": _s(amount)})
    _settle_status(row)
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def _acceptance(filing) -> str:
    if filing is None:
        return "NOT_FILED"
    return {"TRANSMITTED": "FILED", "ACCEPTED": "ACCEPTED", "SETTLED": "ACCEPTED",
            "REJECTED": "REJECTED"}.get(filing.status, "NOT_FILED")


def record_be_onss_advance(db: Session, organization_id: int, payload: dict, actor_id):
    """One ONSS advance (BE-018) as its OWN obligation: the amount and month
    come from the ONSS notice (never computed); idempotent per month."""
    payload = dict(payload or {})
    legal_entity_id = payload.get("legalEntityId")
    be._legal_entity(db, organization_id, legal_entity_id)
    month = str(payload.get("month") or "").strip()
    start, _end = month_bounds(month)
    amount = be._decimal(payload.get("amount"), "amount")
    if amount is None or amount <= ZERO:
        raise BadRequestException("amount (from the ONSS notice) must be above zero.")
    reference = str(payload.get("noticeRef") or "").strip()[:100]
    if not reference:
        raise BadRequestException("noticeRef (the ONSS notice reference) is required.")
    O = _obligation_model()
    quarter = quarter_key(start)
    key = _obligation_key(organization_id, legal_entity_id, "ONSS_ADVANCE", quarter, month)
    row = db.query(O).filter(O.obligation_key == key).first()
    if row is not None:
        if _dec(row.amount_due) == amount and (row.components or {}).get("noticeRef") == reference:
            return row                                                     # idempotent retry
        _conflict("BE_ADVANCE_EXISTS", f"the {month} ONSS advance is already recorded under another notice.")
    due, _why = due_on(db, "ONSS_ADVANCE", month)
    row = O(organization_id=organization_id, legal_entity_id=legal_entity_id, obligation_type="ONSS_ADVANCE",
            period_key=quarter, obligation_key=key, due_on=due, amount_due=amount, paid_amount=ZERO, payments=[],
            components={"month": month, "noticeRef": reference}, acceptance_status="NOT_FILED", status="DUE",
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    be._audit(db, actor_id, "created", "be_obligation", row.id, new={"type": "ONSS_ADVANCE", "month": month,
                                                                      "amount": _s(amount)})
    return row


def _obligation(db: Session, organization_id: int, obligation_id: int):
    O = _obligation_model()
    row = db.query(O).filter(O.id == obligation_id, O.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian obligation")
    return row


def _settle_status(row) -> None:
    if row.status == "RECONCILED":
        return
    paid, due = _dec(row.paid_amount), _dec(row.amount_due)
    row.status = ("DUE" if paid == ZERO and due > ZERO else "PAID" if paid == due
                  else "OVERPAID" if paid > due else "PART_PAID")


def record_be_obligation_payment(db: Session, organization_id: int, obligation_id: int, payload: dict, actor_id):
    """A payment against an obligation (bank reference; idempotent per
    reference). Settlement never touches the filing's acceptance (BE-036)."""
    payload = dict(payload or {})
    amount = be._decimal(payload.get("amount"), "amount")
    if amount is None or amount <= ZERO:
        raise BadRequestException("amount must be above zero.")
    reference = str(payload.get("reference") or "").strip()[:100]
    if not reference:
        raise BadRequestException("reference (the bank reference) is required.")
    paid_on = be._as_date(payload.get("paidOn") or date.today().isoformat(), "paidOn")
    row = _obligation(db, organization_id, obligation_id)
    payments = list(row.payments or [])
    for p in payments:
        if p.get("reference") == reference:
            if _dec(p.get("amount")) == amount:
                return row                                                 # idempotent retry
            _conflict("BE_PAYMENT_REFERENCE_REUSED", "this bank reference is already recorded with another amount.")
    if row.status == "RECONCILED":
        _conflict("BE_OBLIGATION_RECONCILED", "the obligation is reconciled; record a variance instead.")
    payments.append({"reference": reference, "amount": _s(amount), "paidOn": paid_on.isoformat(), "by": actor_id})
    row.payments = payments
    row.paid_amount = _dec(row.paid_amount) + amount
    _settle_status(row)
    if row.status == "OVERPAID":
        raise_variance(db, row, "OVERPAID", row.amount_due, row.paid_amount, actor_id)
    row.updated_at = datetime.utcnow()
    db.flush()
    be._audit(db, actor_id, "payment", "be_obligation", row.id, new={"amount": _s(amount), "status": row.status})
    _maybe_settle_filing(db, row.filing_id, actor_id)
    return row


def reconcile_be_obligation(db: Session, organization_id: int, obligation_id: int, actor_id):
    """PAID with no OPEN variance -> RECONCILED (by a person other than the one
    who recorded the obligation)."""
    from app.modules.payroll.service import require_four_eyes

    V = be._models().PayrollBeReconciliationVariance
    row = _obligation(db, organization_id, obligation_id)
    if row.status == "RECONCILED":
        return row
    if row.status != "PAID":
        _conflict("BE_OBLIGATION_NOT_PAID", f"the obligation is {row.status}; only a PAID obligation is reconciled.")
    if db.query(V.id).filter(V.obligation_id == row.id, V.status == "OPEN").first():
        _conflict("BE_VARIANCE_OPEN", "resolve the open variances first.")
    require_four_eyes(row.created_by_id, actor_id, "Reconciling a Belgian obligation", db=db,
                      entity_type="be_obligation", entity_id=row.id, current_status=row.status)
    row.status, row.reconciled_by_id, row.reconciled_at = "RECONCILED", actor_id, datetime.utcnow()
    db.flush()
    be._audit(db, actor_id, "reconciled", "be_obligation", row.id, new={"status": "RECONCILED"})
    _maybe_settle_filing(db, row.filing_id, actor_id)
    return row


def raise_variance(db: Session, obligation, kind: str, expected, actual, actor_id):
    V = be._models().PayrollBeReconciliationVariance
    expected, actual = _dec(expected), _dec(actual)
    row = V(organization_id=obligation.organization_id, legal_entity_id=obligation.legal_entity_id,
            obligation_id=obligation.id, variance_kind=kind, expected_amount=expected, actual_amount=actual,
            difference=actual - expected, status="OPEN", raised_by_id=actor_id)
    db.add(row)
    db.flush()
    be._audit(db, actor_id, "variance", "be_obligation", obligation.id,
              new={"kind": kind, "expected": _s(expected), "actual": _s(actual)})
    return row


def resolve_be_variance(db: Session, organization_id: int, variance_id: int, resolution, actor_id):
    V = be._models().PayrollBeReconciliationVariance
    row = db.query(V).filter(V.id == variance_id, V.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian reconciliation variance")
    text = be._reason(resolution)
    if row.status == "RESOLVED":
        return row
    if row.raised_by_id is not None and row.raised_by_id == actor_id:
        _conflict("FOUR_EYES_REQUIRED", "a variance is resolved by a person other than the one who raised it.")
    row.status, row.resolution, row.resolved_by_id, row.resolved_at = "RESOLVED", text, actor_id, datetime.utcnow()
    db.flush()
    be._audit(db, actor_id, "variance_resolved", "be_obligation", row.obligation_id, new={"variance": row.id})
    return row


def _maybe_settle_filing(db: Session, filing_id, actor_id) -> None:
    """An ACCEPTED filing becomes SETTLED only when every obligation it
    declared is PAID / RECONCILED (BE-036)."""
    if filing_id is None:
        return
    row = db.get(_model(), filing_id)
    if row is None or row.status != "ACCEPTED":
        return
    O = _obligation_model()
    statuses = [r[0] for r in db.query(O.status).filter(O.filing_id == row.id).all()]
    if statuses and all(s in ("PAID", "RECONCILED") for s in statuses):
        row.status = "SETTLED"
        db.flush()
        _audit(db, actor_id, "settled", row.id, {"status": "SETTLED"})


# ── workflow ────────────────────────────────────────────────────────────────
def _filing(db: Session, organization_id: int, filing_id: int):
    F = _model()
    row = db.query(F).filter(F.id == filing_id, F.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian filing")
    return row


def _verify_hash(row) -> None:
    if canonical_hash(row.payload) != row.payload_hash:
        _conflict("PAYLOAD_CHANGED_AFTER_APPROVAL", "the stored payload no longer matches its hash.")


def validate_be_filing(db: Session, organization_id: int, filing_id: int, actor_id, submission_date=None):
    """DRAFT -> VALIDATED against the schema version in force on the intended
    SUBMISSION date (default today). Otherwise the filing stays DRAFT and
    validation_note says why (content pending / schema not archived / no
    mapping / XSD errors)."""
    row = _filing(db, organization_id, filing_id)
    if row.status not in EDITABLE:
        raise BadRequestException("Only a DRAFT or VALIDATED Belgian filing is validated.")
    on = _today(submission_date)
    _verify_hash(row)
    version, schema_row, why = schema_for(db, organization_id, row.form_code, on)
    note = None
    if version is None:
        note = why
    else:
        xsd = archived_schema(db, schema_row)
        renderer: Optional[Callable] = RENDERERS.get((row.form_code, version))
        if xsd is None:
            note = f"schema not archived ({row.form_code} {version})"
        elif renderer is None:
            note = f"no mapping of the canonical payload onto {row.form_code} {version} (G-08)"
        else:
            errors = _xsd_errors(xsd, renderer(row.payload))
            note = f"XSD validation failed: {'; '.join(errors)}"[:300] if errors else None
    if note is not None:
        row.status, row.schema_version, row.validation_note = "DRAFT", None, note[:300]
        db.flush()
        _audit(db, actor_id, "validation_failed", row.id, {"note": row.validation_note})
        return row
    row.status, row.schema_version = "VALIDATED", version
    row.validation_note = f"validated for submission on {on.isoformat()}"
    db.flush()
    _audit(db, actor_id, "validated", row.id, {"schema": version, "submissionDate": on.isoformat()})
    return row


def _schema_still_in_force(db, row, on: date) -> None:
    version, _r, _why = schema_for(db, row.organization_id, row.form_code, on)
    if version != row.schema_version:
        row.status, row.schema_version = "DRAFT", None
        row.validation_note = f"schema version changed for submission on {on.isoformat()}; validate again"
        db.flush()
        _conflict("FILING_SCHEMA_MISMATCH", f"{row.form_code} schema in force on {on.isoformat()} is "
                  f"{version or 'not signed'}; the filing went back to DRAFT. Validate again.")


def approve_be_filing(db: Session, organization_id: int, filing_id: int, actor_id, on=None):
    """A second person approves a VALIDATED filing (four-eyes)."""
    from app.modules.payroll.service import require_four_eyes

    row = _filing(db, organization_id, filing_id)
    if row.status == "APPROVED" and row.approved_by_id == actor_id:
        return row
    if row.status != "VALIDATED":
        raise BadRequestException("Only a VALIDATED Belgian filing can be approved.")
    _verify_hash(row)
    require_four_eyes(row.created_by_id, actor_id, "Approving a Belgian filing", db=db, entity_type="be_filing",
                      entity_id=row.id, current_status=row.status)
    _schema_still_in_force(db, row, _today(on))
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "approved", row.id, {"status": "APPROVED", "schema": row.schema_version})
    return row


def transmit_be_filing(db: Session, organization_id: int, filing_id: int, actor_id):
    """Automatic transmission: refused while gate G3 is not certified (D9)."""
    row = _filing(db, organization_id, filing_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED Belgian filing can be transmitted.")
    renderer = RENDERERS.get((row.form_code, row.schema_version))
    document = renderer(row.payload) if renderer else b""
    return adapter_for(row.authority).transmit(row, document)


def record_be_filing_submission(db: Session, organization_id: int, filing_id: int, payload: dict, actor_id, on=None):
    """Record that the APPROVED payload was submitted through the authority's
    own channel: reference, mandate reference, actor and time (BE-037). The same
    reference again is the same submission; a different one is refused."""
    payload = dict(payload or {})
    ref = str(payload.get("submissionRef") or "").strip()[:100]
    if not ref:
        raise BadRequestException("submissionRef is required.")
    mandate = str(payload.get("mandateRef") or "").strip()[:100] or None
    row = _filing(db, organization_id, filing_id)
    if row.status in SENT or row.status == "REJECTED":
        if row.submission_ref == ref:
            return row                                                     # idempotent retry
        _conflict("BE_FILING_ALREADY_SUBMITTED", "this filing was already submitted under another reference; "
                  "a retransmission is a new version or a correction.")
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED Belgian filing can be submitted.")
    _verify_hash(row)
    _schema_still_in_force(db, row, _today(on))
    row.status, row.submission_ref, row.mandate_ref = "TRANSMITTED", ref, mandate
    row.transmitted_by_id, row.transmitted_at = actor_id, datetime.utcnow()
    _sync_obligations(db, row)
    db.flush()
    _audit(db, actor_id, "transmitted", row.id, {"status": "TRANSMITTED", "ref": ref, "mandate": mandate})
    return row


def record_be_filing_response(db: Session, organization_id: int, filing_id: int, payload: dict, actor_id):
    """ACCEPTED (receipt reference) or REJECTED (error codes). The receipt is
    immutable evidence; a rejection never touches payroll or a payment."""
    payload = dict(payload or {})
    outcome = str(payload.get("outcome") or "").strip().upper()
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise BadRequestException("outcome must be ACCEPTED or REJECTED.")
    receipt = str(payload.get("receiptRef") or "").strip()[:100] or None
    codes = [str(c).strip().upper()[:40] for c in (payload.get("errorCodes") or []) if str(c).strip()]
    if outcome == "ACCEPTED" and not receipt:
        raise BadRequestException("receiptRef is required for an ACCEPTED filing.")
    if outcome == "REJECTED" and not codes:
        raise BadRequestException("errorCodes are required for a REJECTED filing.")
    row = _filing(db, organization_id, filing_id)
    if row.status in ANSWERED:
        same = (row.status == outcome or (row.status == "SETTLED" and outcome == "ACCEPTED"))
        if same and row.receipt_ref == receipt and (outcome == "ACCEPTED" or (row.rejection or {}).get("codes") == codes):
            return row                                                     # idempotent retry
        _conflict("BE_FILING_ALREADY_ANSWERED", "the authority's response is already recorded and is immutable.")
    if row.status != "TRANSMITTED":
        raise BadRequestException("Only a TRANSMITTED Belgian filing can receive the authority's response.")
    row.status, row.receipt_ref, row.responded_at = outcome, receipt, datetime.utcnow()
    row.response = {"outcome": outcome, "receiptRef": receipt,
                    "message": str(payload.get("message") or "")[:300] or None}
    row.rejection = {"codes": codes, "message": row.response["message"]} if codes else None
    _sync_obligations(db, row)
    db.flush()
    _audit(db, actor_id, "responded", row.id, {"status": outcome, "errors": codes})
    if outcome == "ACCEPTED":
        _maybe_settle_filing(db, row.id, actor_id)
    return row


def _sync_obligations(db: Session, filing) -> None:
    """Acceptance state of the obligations a filing declares (or, for a
    correction, the original's)."""
    O = _obligation_model()
    ids = {filing.id} | ({filing.corrects_id} if filing.corrects_id else set())
    for row in db.query(O).filter(O.filing_id.in_(ids)).all():
        row.acceptance_status = _acceptance(filing)
        if filing.status == "ACCEPTED":
            row.accepted_at = datetime.utcnow()
        if filing.kind == "CORRECTION":
            row.filing_id = filing.id


# ── views ───────────────────────────────────────────────────────────────────
def filing_view(row, include_payload: bool = False) -> dict:
    out = {"id": row.id, "legalEntityId": row.legal_entity_id, "authority": row.authority, "formCode": row.form_code,
           "periodKey": row.period_key, "subjectKey": row.subject_key, "kind": row.kind, "version": row.version,
           "schemaVersion": row.schema_version, "validationNote": row.validation_note, "runIds": row.run_ids,
           "payloadHash": row.payload_hash, "idempotencyKey": row.idempotency_key,
           "dueOn": row.due_on.isoformat() if row.due_on else None, "dueSourced": row.due_on is not None,
           "status": row.status, "correctsId": row.corrects_id, "previousVersionId": row.previous_version_id,
           "submissionRef": row.submission_ref, "receiptRef": row.receipt_ref, "mandateRef": row.mandate_ref,
           "rejection": row.rejection, "createdById": row.created_by_id, "approvedById": row.approved_by_id,
           "transmittedById": row.transmitted_by_id,
           "transmittedAt": row.transmitted_at.isoformat() if row.transmitted_at else None,
           "respondedAt": row.responded_at.isoformat() if row.responded_at else None,
           "event": (row.payload or {}).get("event")}
    if include_payload:
        out["payload"] = row.payload                                        # masked identifiers only
        out["rendition"] = row.rendition
        out["response"] = row.response
    return out


def obligation_view(row) -> dict:
    return {"id": row.id, "legalEntityId": row.legal_entity_id, "type": row.obligation_type,
            "periodKey": row.period_key, "filingId": row.filing_id, "acceptanceStatus": row.acceptance_status,
            "acceptedAt": row.accepted_at.isoformat() if row.accepted_at else None,
            "dueOn": row.due_on.isoformat() if row.due_on else None, "dueSourced": row.due_on is not None,
            "amountDue": _s(row.amount_due), "paidAmount": _s(row.paid_amount), "status": row.status,
            "payments": row.payments or [], "components": row.components or {},
            "open": row.status not in ("PAID", "RECONCILED"),
            "reconciledById": row.reconciled_by_id}


def variance_view(row) -> dict:
    return {"id": row.id, "obligationId": row.obligation_id, "kind": row.variance_kind,
            "expected": _s(row.expected_amount), "actual": _s(row.actual_amount), "difference": _s(row.difference),
            "status": row.status, "resolution": row.resolution, "raisedById": row.raised_by_id,
            "resolvedById": row.resolved_by_id}


def list_be_filings(db: Session, organization_id: int, period=None, form_code=None, status=None) -> list:
    F = _model()
    query = db.query(F).filter(F.organization_id == organization_id)
    if period:
        query = query.filter(F.period_key == str(period).strip().upper())
    if form_code:
        query = query.filter(F.form_code == str(form_code).strip().upper())
    if status:
        query = query.filter(F.status == str(status).strip().upper())
    return [filing_view(r) for r in query.order_by(F.period_key.desc(), F.form_code, F.kind, F.version.desc(),
                                                   F.id.desc())]


def get_be_filing(db: Session, organization_id: int, filing_id: int) -> dict:
    return filing_view(_filing(db, organization_id, filing_id), include_payload=True)


def list_be_obligations(db: Session, organization_id: int, open_only: bool = False) -> list:
    O = _obligation_model()
    query = db.query(O).filter(O.organization_id == organization_id)
    rows = [obligation_view(r) for r in query.order_by(O.period_key.desc(), O.obligation_type, O.id).all()]
    return [r for r in rows if r["open"]] if open_only else rows


def list_be_variances(db: Session, organization_id: int) -> list:
    V = be._models().PayrollBeReconciliationVariance
    return [variance_view(r) for r in db.query(V).filter(V.organization_id == organization_id)
            .order_by(V.status, V.id).all()]


def exception_queue(db: Session, organization_id: int, today=None) -> list:
    """Spec §14 exception queue: rejected filing, late Dimona, filing stuck in
    validation, overdue / unpaid obligation, unexplained variance, payment
    failure. Each item: what failed, who is affected, what is blocked."""
    on = _today(today)
    F, O = _model(), _obligation_model()
    V = be._models().PayrollBeReconciliationVariance
    out = []
    for r in db.query(F).filter(F.organization_id == organization_id, F.status == "REJECTED").all():
        out.append({"category": "REJECTED_FILING", "severity": "HIGH", "filingId": r.id, "form": r.form_code,
                    "period": r.period_key, "blocks": "filing", "detail": ", ".join((r.rejection or {}).get("codes")
                                                                                    or [])})
    for r in db.query(F).filter(F.organization_id == organization_id, F.form_code == "DIMONA", F.kind == "ORIGINAL",
                                F.status.notin_(("ACCEPTED", "SETTLED", "SUPERSEDED"))).all():
        start = (r.payload or {}).get("startDate")
        if (r.payload or {}).get("event") == "IN" and start and date.fromisoformat(start) <= on:
            out.append({"category": "LATE_DIMONA", "severity": "HIGH", "filingId": r.id, "form": "DIMONA",
                        "period": r.period_key, "employeeId": ((r.payload or {}).get("worker") or {}).get("employeeId"),
                        "blocks": "payroll", "detail": f"start {start}; Dimona IN is {r.status}"})
    for r in db.query(F).filter(F.organization_id == organization_id, F.status == "DRAFT",
                                F.validation_note.isnot(None)).all():
        out.append({"category": "FILING_NOT_VALIDATED", "severity": "MEDIUM", "filingId": r.id, "form": r.form_code,
                    "period": r.period_key, "blocks": "filing", "detail": r.validation_note})
    for r in db.query(O).filter(O.organization_id == organization_id,
                                O.status.in_(("DUE", "PART_PAID"))).all():
        if r.due_on is not None and r.due_on < on:
            out.append({"category": "OVERDUE_OBLIGATION", "severity": "HIGH", "obligationId": r.id,
                        "type": r.obligation_type, "period": r.period_key, "blocks": "settlement",
                        "detail": f"due {r.due_on.isoformat()}; paid {_s(r.paid_amount)} of {_s(r.amount_due)}"})
        elif r.due_on is None:
            out.append({"category": "DUE_DATE_UNSOURCED", "severity": "MEDIUM", "obligationId": r.id,
                        "type": r.obligation_type, "period": r.period_key, "blocks": "settlement",
                        "detail": "no Active, sourced calendar row (BE-035)"})
    for r in db.query(V).filter(V.organization_id == organization_id, V.status == "OPEN").all():
        out.append({"category": "UNEXPLAINED_VARIANCE", "severity": "HIGH", "varianceId": r.id,
                    "obligationId": r.obligation_id, "blocks": "reconciliation",
                    "detail": f"{r.variance_kind}: {_s(r.difference)}"})
    B = be._models().PayrollBePaymentBatch
    for r in db.query(B).filter(B.organization_id == organization_id,
                                B.status.in_(("REJECTED", "RETURNED", "UNKNOWN"))).all():
        out.append({"category": "PAYMENT_FAILURE", "severity": "HIGH", "batchId": r.id, "blocks": "salary payment",
                    "detail": r.status})
    return out
