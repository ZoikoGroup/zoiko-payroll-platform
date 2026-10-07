"""
modules/payroll/switzerland_service.py
--------------------------------------
Switzerland (CH spec) governed data:

* Step 4 — Quellensteuer (QST) tariff ingestion (this docstring, below).
* Step 5 — employer scheme profiles, the versioned entity profile, CH earning
  classification (TaxabilityRule) and wage floors (CollectiveAgreement); see
  the section banner further down for its transaction contract.

A canton's QST tariff is never typed in or scraped: it enters the platform
only as an authority tariff FILE, imported byte-for-byte, and moves through

    IMPORTED -> VALIDATED | REJECTED -> APPROVED -> ACTIVE -> SUPERSEDED

* import   — SHA-256 identity, an identical file is refused (never re-imported
             as a second copy); parsed by the parser registered for the file's
             format_version; rows inserted exactly as parsed.
* validate — structural checks only (bands monotonic, no gaps/overlaps per
             tariff_code + children + church_tax, rates 0..100). The report is
             stored; a structurally unsound file is REJECTED. Validation never
             invents or "corrects" a figure.
* approve  — by a Super Admin other than the importer.
* activate — by a Super Admin other than the approver. Any ACTIVE file for the
             same canton whose period overlaps becomes SUPERSEDED.

Tariff rows are never updated or deleted (enforced at the ORM layer in
models.py). A SUPERSEDED file stays readable by id so a historical payslip can
always be replayed against the exact rows it used (lookup_qst_rate).
"""

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.switzerland_content import CH_CANTON_CODES
from app.modules.payroll.models import ChQstTariffFile, ChQstTariffRow

SPEC = "CH spec — QST tariff ingestion"
MAX_TARIFF_FILE_BYTES = 50 * 1024 * 1024
# Files whose rows a calculation may read: the one live now, and every file
# that was live before (replay). A file that never reached ACTIVE never
# drives a calculation.
LOOKUP_STATUSES = ("ACTIVE", "SUPERSEDED")


def _audit(db, actor_id, action, entity_id, old=None, new=None, reason=None, commit=True):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type="ch_qst_tariff_file", entity_id=entity_id,
                     legal_reference=SPEC, old_value=old, new_value=new, reason=reason, auto_commit=commit)


# ── Parsers (selected by format_version) ────────────────────────────────

class TariffParseError(ValueError):
    pass


# ESTV Quellensteuer tariff file — fixed-width record layout, 0-based
# [start, end) slices. EVERY position below is "VERIFY AGAINST ESTV SPEC":
# it is written from the ESTV "Aufbau der Tarifdateien" record description
# as understood at build time and has NOT been checked against the current
# published ESTV specification or a real ESTV file. Do not import a real
# canton file until each position is confirmed (and the synthetic test
# fixture updated to match).
ESTV_FIXED_WIDTH_V1_LAYOUT = {
    "record_type":      (0, 2),    # VERIFY AGAINST ESTV SPEC — "00" header / "06" tariff / "99" trailer
    "transaction_type": (2, 4),    # VERIFY AGAINST ESTV SPEC — "01" = new (only full snapshots accepted)
    "canton":           (4, 6),    # VERIFY AGAINST ESTV SPEC — 2-letter canton, e.g. "ZH"
    "tariff_code":      (6, 16),   # VERIFY AGAINST ESTV SPEC — e.g. "A0N" (group, children, church Y/N)
    "valid_from":       (16, 24),  # VERIFY AGAINST ESTV SPEC — YYYYMMDD
    "income_from":      (24, 33),  # VERIFY AGAINST ESTV SPEC — taxable income from, in Rappen (CHF x 100)
    "tariff_step":      (33, 42),  # VERIFY AGAINST ESTV SPEC — band width in Rappen; 0 = open-ended top band
    "sex_code":         (42, 43),  # VERIFY AGAINST ESTV SPEC — not used
    "children":         (43, 45),  # VERIFY AGAINST ESTV SPEC — number of children
    "min_tax":          (45, 54),  # VERIFY AGAINST ESTV SPEC — minimum tax in Rappen
    "rate":             (54, 59),  # VERIFY AGAINST ESTV SPEC — tax rate in % x 100 (e.g. 00125 = 1.25 %)
}
ESTV_FIXED_WIDTH_V1_RECORD_LEN = 59  # VERIFY AGAINST ESTV SPEC — minimum tariff-record length
ESTV_HEADER, ESTV_TARIFF, ESTV_TRAILER = "00", "06", "99"  # VERIFY AGAINST ESTV SPEC


def _field(line: str, name: str) -> str:
    start, end = ESTV_FIXED_WIDTH_V1_LAYOUT[name]
    return line[start:end]


def _digits(line: str, name: str, lineno: int) -> int:
    raw = _field(line, name)
    if not raw.isdigit():
        raise TariffParseError(f"line {lineno}: {name} must be digits, got {raw!r}")
    return int(raw)


def parse_estv_fixed_width_v1(file_bytes: bytes, canton: str) -> Tuple[List[dict], dict]:
    """ESTV fixed-width tariff file -> (row dicts, parse summary). Raises
    TariffParseError on any record it cannot read; nothing is guessed."""
    text = file_bytes.decode("latin-1")  # ESTV files are single-byte; latin-1 never fails, so bad bytes surface as field errors
    canton2 = canton[3:]
    rows, valid_from_dates, record_types = [], set(), {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rtype = _field(line, "record_type")
        record_types[rtype] = record_types.get(rtype, 0) + 1
        if rtype in (ESTV_HEADER, ESTV_TRAILER):
            continue
        if rtype != ESTV_TARIFF:
            raise TariffParseError(f"line {lineno}: unknown record type {rtype!r}")
        if len(line) < ESTV_FIXED_WIDTH_V1_RECORD_LEN:
            raise TariffParseError(f"line {lineno}: tariff record shorter than {ESTV_FIXED_WIDTH_V1_RECORD_LEN} chars")
        if _field(line, "transaction_type") != "01":
            raise TariffParseError(f"line {lineno}: only transaction type 01 (full snapshot) is supported")
        if _field(line, "canton") != canton2:
            raise TariffParseError(f"line {lineno}: record canton {_field(line, 'canton')!r} is not {canton2!r}")
        code = _field(line, "tariff_code").strip()
        if len(code) < 3 or not code[0].isalpha() or code[-1] not in ("Y", "N"):
            raise TariffParseError(f"line {lineno}: unreadable tariff code {code!r}")
        children = _digits(line, "children", lineno)
        code_children = code[1:-1]
        if not code_children.isdigit() or int(code_children) != children:
            raise TariffParseError(f"line {lineno}: tariff code {code!r} disagrees with children field {children}")
        try:
            valid_from = datetime.strptime(_field(line, "valid_from"), "%Y%m%d").date()
        except ValueError:
            raise TariffParseError(f"line {lineno}: unreadable valid-from date {_field(line, 'valid_from')!r}")
        valid_from_dates.add(valid_from)
        income_from = Decimal(_digits(line, "income_from", lineno)) / 100
        step = Decimal(_digits(line, "tariff_step", lineno)) / 100
        rows.append({
            "tariff_code": code[0],
            "children": children,
            "church_tax": code[-1] == "Y",
            "income_from": income_from,
            "income_to": (income_from + step) if step > 0 else None,
            "rate_pct": Decimal(_digits(line, "rate", lineno)) / 100,
            "min_tax": Decimal(_digits(line, "min_tax", lineno)) / 100,
            "raw_record": line[:200],
        })
    if not rows:
        raise TariffParseError("the file contains no tariff records")
    return rows, {
        "parser": "parse_estv_fixed_width_v1",
        "recordTypes": record_types,
        "validFromDates": sorted(d.isoformat() for d in valid_from_dates),
    }


TARIFF_PARSERS: Dict[str, Callable[[bytes, str], Tuple[List[dict], dict]]] = {
    "ESTV_FIXED_WIDTH_V1": parse_estv_fixed_width_v1,
}


# ── Lifecycle ───────────────────────────────────────────────────────────

def _iso(value):
    return value.isoformat() if value else None


def _parse_date(value, name) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise BadRequestException(f"{name} must be an ISO date (YYYY-MM-DD)")


def tariff_file_view(row: ChQstTariffFile) -> dict:
    return {
        "id": row.id, "canton": row.canton, "taxYear": row.tax_year, "formatVersion": row.format_version,
        "publicationDate": _iso(row.publication_date), "effectiveFrom": _iso(row.effective_from),
        "effectiveTo": _iso(row.effective_to), "sourceDocumentId": row.source_document_id,
        "fileSha256": row.file_sha256, "rowCount": row.row_count, "status": row.status,
        "supersedesId": row.supersedes_id,
        "importedById": row.imported_by_id, "importedAt": _iso(row.imported_at),
        "approvedById": row.approved_by_id, "approvedAt": _iso(row.approved_at),
        "activatedById": row.activated_by_id, "activatedAt": _iso(row.activated_at),
        "validationReport": row.validation_report,
    }


def _get(db: Session, tariff_file_id: int, lock: bool = False) -> ChQstTariffFile:
    q = db.query(ChQstTariffFile).filter(ChQstTariffFile.id == tariff_file_id)
    row = (q.with_for_update() if lock else q).first()
    if row is None:
        raise NotFoundException("QST tariff file", tariff_file_id)
    return row


def get_qst_tariff_file(db: Session, tariff_file_id: int) -> dict:
    """Any status, including SUPERSEDED — the replay path reads by id."""
    return tariff_file_view(_get(db, tariff_file_id))


def list_qst_tariff_files(db: Session, canton: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    q = db.query(ChQstTariffFile)
    if canton:
        q = q.filter(ChQstTariffFile.canton == canton)
    if status:
        q = q.filter(ChQstTariffFile.status == status)
    return [tariff_file_view(r) for r in q.order_by(ChQstTariffFile.canton, ChQstTariffFile.id.desc())]


def import_qst_tariff_file(db: Session, canton: str, file_bytes: bytes, metadata: dict,
                           actor_id: Optional[int]) -> dict:
    """Import one authority tariff file for a canton. metadata keys:
    format_version (required, selects the parser), effective_from (required),
    effective_to, tax_year, publication_date, source_document_id."""
    if canton not in CH_CANTON_CODES:
        raise BadRequestException(f"canton must be one of the CH-XX codes, got {canton!r}")
    if not file_bytes:
        raise BadRequestException("the tariff file is empty")
    if len(file_bytes) > MAX_TARIFF_FILE_BYTES:
        raise BadRequestException(f"the tariff file exceeds {MAX_TARIFF_FILE_BYTES} bytes")
    format_version = (metadata.get("format_version") or "").strip()
    parser = TARIFF_PARSERS.get(format_version)
    if parser is None:
        raise BadRequestException(f"no parser for format_version {format_version!r} "
                                  f"(known: {', '.join(sorted(TARIFF_PARSERS))})")
    effective_from = _parse_date(metadata.get("effective_from"), "effective_from")
    effective_to = _parse_date(metadata.get("effective_to"), "effective_to")
    if effective_from is None:
        raise BadRequestException("effective_from is required")
    if effective_to is not None and effective_to < effective_from:
        raise BadRequestException("effective_to is before effective_from")

    sha = hashlib.sha256(file_bytes).hexdigest()
    existing = (db.query(ChQstTariffFile)
                .filter(ChQstTariffFile.canton == canton, ChQstTariffFile.file_sha256 == sha).first())
    if existing is not None:
        raise BadRequestException(f"this exact file (sha256 {sha[:12]}…) was already imported for {canton} "
                                  f"as tariff file {existing.id} ({existing.status})")
    try:
        parsed, summary = parser(file_bytes, canton)
    except TariffParseError as e:
        raise BadRequestException(f"tariff file could not be parsed: {e}")

    row = ChQstTariffFile(
        canton=canton, tax_year=metadata.get("tax_year"), format_version=format_version,
        publication_date=_parse_date(metadata.get("publication_date"), "publication_date"),
        effective_from=effective_from, effective_to=effective_to,
        source_document_id=metadata.get("source_document_id"), file_sha256=sha, row_count=len(parsed),
        status="IMPORTED", imported_by_id=actor_id, imported_at=datetime.utcnow(),
        validation_report={"import": summary},
    )
    db.add(row)
    db.flush()
    db.bulk_insert_mappings(ChQstTariffRow, [{**r, "tariff_file_id": row.id} for r in parsed])
    _audit(db, actor_id, "import", row.id, new={"status": "IMPORTED", "canton": canton, "fileSha256": sha,
                                                 "rowCount": len(parsed), "formatVersion": format_version},
           commit=False)
    db.commit()
    return tariff_file_view(row)


def _validate_rows(tariff_file: ChQstTariffFile, rows: List[ChQstTariffRow]) -> Tuple[List[str], List[str], int]:
    errors, warnings = [], []
    groups: Dict[tuple, List[ChQstTariffRow]] = {}
    for r in rows:
        groups.setdefault((r.tariff_code, r.children, r.church_tax), []).append(r)
        if r.rate_pct is None or not (Decimal("0") <= r.rate_pct <= Decimal("100")):
            errors.append(f"row {r.id}: rate {r.rate_pct} is outside 0..100")
        if r.min_tax is not None and r.min_tax < 0:
            errors.append(f"row {r.id}: negative minimum tax {r.min_tax}")
        if r.income_from is None or r.income_from < 0:
            errors.append(f"row {r.id}: income_from {r.income_from} is missing or negative")
    for (code, children, church), bands in groups.items():
        label = f"{code}/children={children}/church={'Y' if church else 'N'}"
        bands = sorted(bands, key=lambda b: (b.income_from is None, b.income_from or 0))
        if bands[0].income_from is not None and bands[0].income_from != 0:
            errors.append(f"{label}: first band starts at {bands[0].income_from}, not 0 (gap)")
        for i, b in enumerate(bands):
            last = i == len(bands) - 1
            if b.income_to is None and not last:
                errors.append(f"{label}: open-ended band at {b.income_from} is not the top band (overlap)")
            if b.income_to is not None and b.income_from is not None and b.income_to <= b.income_from:
                errors.append(f"{label}: band {b.income_from}..{b.income_to} is not increasing")
            if last:
                break
            nxt = bands[i + 1]
            if b.income_to is None or nxt.income_from is None:
                continue
            if nxt.income_from <= b.income_from:
                errors.append(f"{label}: duplicate band start {nxt.income_from} (overlap)")
            elif nxt.income_from > b.income_to:
                errors.append(f"{label}: gap between {b.income_to} and {nxt.income_from}")
            elif nxt.income_from < b.income_to:
                errors.append(f"{label}: bands {b.income_from}..{b.income_to} and {nxt.income_from}.. overlap")
            if (b.rate_pct is not None and nxt.rate_pct is not None and nxt.rate_pct < b.rate_pct):
                warnings.append(f"{label}: rate falls from {b.rate_pct} to {nxt.rate_pct} at {nxt.income_from}")
    if not rows:
        errors.append("the file has no tariff rows")
    if tariff_file.row_count != len(rows):
        errors.append(f"row_count {tariff_file.row_count} does not match the {len(rows)} stored rows")
    dates = ((tariff_file.validation_report or {}).get("import") or {}).get("validFromDates") or []
    if tariff_file.effective_from and any(d != tariff_file.effective_from.isoformat() for d in dates):
        errors.append(f"record valid-from dates {dates} disagree with effective_from "
                      f"{tariff_file.effective_from.isoformat()}")
    return errors, warnings, len(groups)


def validate_qst_tariff_file(db: Session, tariff_file_id: int, actor_id: Optional[int]) -> dict:
    tariff_file = _get(db, tariff_file_id, lock=True)
    if tariff_file.status != "IMPORTED":
        raise BadRequestException(f"only an IMPORTED tariff file can be validated (this one is {tariff_file.status})")
    rows = db.query(ChQstTariffRow).filter(ChQstTariffRow.tariff_file_id == tariff_file.id).all()
    errors, warnings, group_count = _validate_rows(tariff_file, rows)
    outcome = "REJECTED" if errors else "VALIDATED"
    tariff_file.validation_report = {
        **(tariff_file.validation_report or {}),
        "validation": {
            "outcome": outcome, "errors": errors, "warnings": warnings, "rowCount": len(rows),
            "groupCount": group_count, "validatedById": actor_id, "validatedAt": datetime.utcnow().isoformat(),
            "checks": ["rate_0_100", "income_from_non_negative", "bands_monotonic", "no_gaps", "no_overlaps",
                       "single_open_ended_top_band", "row_count_matches", "valid_from_matches_effective_from"],
        },
    }
    tariff_file.status = outcome
    db.flush()
    _audit(db, actor_id, "validate", tariff_file.id, old={"status": "IMPORTED"},
           new={"status": outcome, "errorCount": len(errors), "warningCount": len(warnings)}, commit=False)
    db.commit()
    return tariff_file_view(tariff_file)


def approve_qst_tariff_file(db: Session, tariff_file_id: int, actor_id: Optional[int],
                            reason: Optional[str] = None) -> dict:
    tariff_file = _get(db, tariff_file_id, lock=True)
    if tariff_file.status != "VALIDATED":
        raise BadRequestException(f"only a VALIDATED tariff file can be approved (this one is {tariff_file.status})")
    if actor_id is None or actor_id == tariff_file.imported_by_id:
        raise BadRequestException("the tariff file must be approved by a Super Admin other than its importer")
    tariff_file.status, tariff_file.approved_by_id, tariff_file.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "approve", tariff_file.id, old={"status": "VALIDATED"}, new={"status": "APPROVED"},
           reason=reason, commit=False)
    db.commit()
    return tariff_file_view(tariff_file)


def _periods_overlap(a_from, a_to, b_from, b_to) -> bool:
    return (a_to is None or b_from is None or b_from <= a_to) and (b_to is None or a_from is None or a_from <= b_to)


def activate_qst_tariff_file(db: Session, tariff_file_id: int, actor_id: Optional[int],
                             reason: Optional[str] = None) -> dict:
    # lock every file of the canton (id order) so two concurrent activations cannot both end ACTIVE
    target = _get(db, tariff_file_id)
    (db.query(ChQstTariffFile).filter(ChQstTariffFile.canton == target.canton)
     .order_by(ChQstTariffFile.id).with_for_update().all())
    db.refresh(target)
    if target.status != "APPROVED":
        raise BadRequestException(f"only an APPROVED tariff file can be activated (this one is {target.status})")
    if actor_id is None or actor_id == target.approved_by_id:
        raise BadRequestException("the tariff file must be activated by a Super Admin other than its approver")
    superseded = [
        prev for prev in db.query(ChQstTariffFile).filter(
            ChQstTariffFile.canton == target.canton, ChQstTariffFile.status == "ACTIVE",
            ChQstTariffFile.id != target.id).order_by(ChQstTariffFile.id)
        if _periods_overlap(prev.effective_from, prev.effective_to, target.effective_from, target.effective_to)
    ]
    for prev in superseded:
        prev.status = "SUPERSEDED"
        _audit(db, actor_id, "supersede", prev.id, old={"status": "ACTIVE"},
               new={"status": "SUPERSEDED", "supersededById": target.id}, reason=reason, commit=False)
    if superseded:
        target.supersedes_id = superseded[-1].id
    target.status, target.activated_by_id, target.activated_at = "ACTIVE", actor_id, datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "activate", target.id, old={"status": "APPROVED"},
           new={"status": "ACTIVE", "supersededIds": [p.id for p in superseded]}, reason=reason, commit=False)
    db.commit()
    return tariff_file_view(target)


# ── Lookup ──────────────────────────────────────────────────────────────

def lookup_qst_rate(db: Session, tariff_file_id: int, tariff_code: str, children: Optional[int],
                    church_tax: Optional[bool], income) -> Tuple[Decimal, Optional[Decimal], int]:
    """The band containing `income` (income_from <= income < income_to; the
    open-ended top band has no upper bound) -> (rate_pct, min_tax, row_id).
    Reads by file id, so a SUPERSEDED file replays exactly as it was."""
    tariff_file = _get(db, tariff_file_id)
    if tariff_file.status not in LOOKUP_STATUSES:
        raise BadRequestException(f"tariff file {tariff_file_id} is {tariff_file.status}; only an ACTIVE or "
                                  f"SUPERSEDED file can be used for a calculation")
    try:
        amount = Decimal(str(income))
    except InvalidOperation:
        raise BadRequestException(f"income {income!r} is not a number")
    if amount < 0:
        raise BadRequestException("income cannot be negative")
    q = db.query(ChQstTariffRow).filter(
        ChQstTariffRow.tariff_file_id == tariff_file_id, ChQstTariffRow.tariff_code == tariff_code,
        ChQstTariffRow.children == children if children is not None else ChQstTariffRow.children.is_(None),
        ChQstTariffRow.church_tax == church_tax if church_tax is not None else ChQstTariffRow.church_tax.is_(None),
        ChQstTariffRow.income_from <= amount,
        (ChQstTariffRow.income_to.is_(None)) | (ChQstTariffRow.income_to > amount),
    ).order_by(ChQstTariffRow.income_from.desc())
    row = q.first()
    if row is None:
        raise NotFoundException(f"QST band for {tariff_code}/children={children}/church={church_tax} "
                                f"at income {amount} in tariff file", tariff_file_id)
    return Decimal(row.rate_pct), (Decimal(row.min_tax) if row.min_tax is not None else None), row.id


# ════════════════════════════════════════════════════════════════════════
# CH Step 5 — employer schemes, entity profile, earning classification,
# wage floors.
#
# Transaction contract: every function below FLUSHES and never commits. The
# CH write routes commit through switzerland_http.ch_write, so the write, its
# audit entry and its idempotency record are one atomic unit.
# ════════════════════════════════════════════════════════════════════════

import json  # noqa: E402
import re  # noqa: E402
from datetime import timedelta  # noqa: E402

from pydantic import ValidationError  # noqa: E402

from app.modules.payroll.engine.countries.switzerland_content import (  # noqa: E402
    CH_AHV, CH_ALV, CH_BVG, CH_EO, CH_IV, CH_KTG, CH_QST, CH_UVG,
)
from app.modules.payroll.models import (  # noqa: E402
    ChEntityProfile, ChSchemeProfile, CollectiveAgreement, EmployeeStatutoryProfile, SourceArtifact,
    TaxabilityRule, TaxConfigurationAudit,
)
from app.modules.payroll.switzerland_schemas import validate_scheme_rules  # noqa: E402

CH_UID_RE = re.compile(r"^CHE-\d{3}\.\d{3}\.\d{3}$")
CH_TAXABILITY_COMPONENTS = (CH_AHV, CH_IV, CH_EO, CH_ALV, CH_UVG, CH_BVG, CH_KTG, CH_QST)
CH_WAGE_FLOOR_TYPES = ("CH_CANTON_MINIMUM", "CH_GAV", "CH_NAV")


def _ch_audit(db, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None, correlation_id=None):
    from app.modules.payroll.service import record_tax_audit

    if correlation_id:
        new = {**(new or {}), "correlationId": correlation_id}
    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     legal_reference="CH spec — Step 5", old_value=old, new_value=new, reason=reason,
                     auto_commit=False)


def _bad_input(exc: Exception) -> BadRequestException:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]
        return BadRequestException("; ".join(parts))
    return BadRequestException(str(exc))


def _check_dates(effective_from, effective_to):
    if effective_to is not None and effective_from is not None and effective_to < effective_from:
        raise BadRequestException("effectiveTo is before effectiveFrom")


def _check_source(db, source_document_id):
    if source_document_id is not None and db.get(SourceArtifact, source_document_id) is None:
        raise NotFoundException("Source artifact", source_document_id)


def _authors(db, entity_type: str, entity_id: int) -> set:
    """Everyone who created or edited a governed row, from its audit trail —
    so four-eyes also excludes a later editor, not only the creator."""
    rows = (db.query(TaxConfigurationAudit.actor_id)
            .filter(TaxConfigurationAudit.entity_type == entity_type, TaxConfigurationAudit.entity_id == entity_id,
                    TaxConfigurationAudit.action.in_(("create", "update"))))
    return {r[0] for r in rows if r[0] is not None}


# ── scheme profiles ─────────────────────────────────────────────────────

def _rules_sha256(rules: dict) -> str:
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scheme_view(row: ChSchemeProfile) -> dict:
    return {
        "id": row.id, "organizationId": row.organization_id, "catalog": row.organization_id is None,
        "schemeType": row.scheme_type, "schemeCode": row.scheme_code, "name": row.name,
        "authorityIdentifier": row.authority_identifier, "canton": row.canton, "rules": row.rules,
        "rulesSha256": row.rules_sha256, "version": row.version, "status": row.status,
        "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
        "previousVersionId": row.previous_version_id, "sourceDocumentId": row.source_document_id,
        "createdById": row.created_by_id, "approvedById": row.approved_by_id, "activatedById": row.activated_by_id,
    }


def _in_scope(query, organization_id):
    return query.filter(ChSchemeProfile.organization_id.is_(None) if organization_id is None
                        else ChSchemeProfile.organization_id == organization_id)


def list_schemes(db: Session, organization_id: Optional[int], include_catalog: bool = True,
                 scheme_type: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    """An org sees its own assignments plus the platform catalog; the
    platform (organization_id None) sees the catalog only."""
    q = db.query(ChSchemeProfile)
    if organization_id is None:
        q = q.filter(ChSchemeProfile.organization_id.is_(None))
    elif include_catalog:
        q = q.filter((ChSchemeProfile.organization_id == organization_id) | ChSchemeProfile.organization_id.is_(None))
    else:
        q = q.filter(ChSchemeProfile.organization_id == organization_id)
    if scheme_type:
        q = q.filter(ChSchemeProfile.scheme_type == scheme_type)
    if status:
        q = q.filter(ChSchemeProfile.status == status)
    return [scheme_view(r) for r in q.order_by(ChSchemeProfile.scheme_type, ChSchemeProfile.scheme_code,
                                               ChSchemeProfile.id)]


def _visible_scheme(db, scheme_id, organization_id) -> ChSchemeProfile:
    row = db.get(ChSchemeProfile, scheme_id)
    if row is None or row.organization_id not in (None, organization_id):
        raise NotFoundException("CH scheme profile", scheme_id)
    return row


def _writable_scheme(db, scheme_id, organization_id) -> ChSchemeProfile:
    # an org can never write a catalog row and the platform never writes an org's row
    row = db.get(ChSchemeProfile, scheme_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundException("CH scheme profile", scheme_id)
    return row


def get_scheme(db: Session, scheme_id: int, organization_id: Optional[int]) -> dict:
    return scheme_view(_visible_scheme(db, scheme_id, organization_id))


def create_scheme(db: Session, organization_id: Optional[int], data, actor_id: Optional[int],
                  correlation_id: Optional[str] = None) -> dict:
    try:
        rules = validate_scheme_rules(data.schemeType, data.rules)
    except (ValueError, ValidationError) as e:
        raise _bad_input(e)
    _check_dates(data.effectiveFrom, data.effectiveTo)
    _check_source(db, data.sourceDocumentId)
    same_code = _in_scope(db.query(ChSchemeProfile), organization_id).filter(
        ChSchemeProfile.scheme_type == data.schemeType, ChSchemeProfile.scheme_code == data.schemeCode)
    if same_code.filter(ChSchemeProfile.version == data.version).first() is not None:
        raise BadRequestException(f"{data.schemeType} {data.schemeCode} version {data.version} already exists; "
                                  "use a new version number")
    previous = same_code.order_by(ChSchemeProfile.id.desc()).first()
    row = ChSchemeProfile(
        organization_id=organization_id, scheme_type=data.schemeType, scheme_code=data.schemeCode, name=data.name,
        authority_identifier=data.authorityIdentifier, canton=data.canton, rules=rules,
        rules_sha256=_rules_sha256(rules), version=data.version, status="DRAFT",
        effective_from=data.effectiveFrom, effective_to=data.effectiveTo,
        previous_version_id=previous.id if previous else None, source_document_id=data.sourceDocumentId,
        created_by_id=actor_id,
    )
    db.add(row)
    db.flush()
    _ch_audit(db, actor_id, "create", "ch_scheme_profile", row.id,
              new={"status": "DRAFT", "schemeType": row.scheme_type, "schemeCode": row.scheme_code,
                   "version": row.version, "rulesSha256": row.rules_sha256}, reason=data.reason,
              correlation_id=correlation_id)
    return scheme_view(row)


def update_scheme(db: Session, scheme_id: int, organization_id: Optional[int], data, actor_id: Optional[int],
                  correlation_id: Optional[str] = None) -> dict:
    row = _writable_scheme(db, scheme_id, organization_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"scheme {row.id} is {row.status}; only a DRAFT can be edited — create a new "
                                  "version instead")
    fields = data.model_fields_set - {"reason"}
    old = {"rulesSha256": row.rules_sha256, "effectiveFrom": _iso(row.effective_from),
           "effectiveTo": _iso(row.effective_to)}
    if "rules" in fields:
        try:
            row.rules = validate_scheme_rules(row.scheme_type, data.rules)
        except (ValueError, ValidationError) as e:
            raise _bad_input(e)
        row.rules_sha256 = _rules_sha256(row.rules)
    for attr, col in (("name", "name"), ("authorityIdentifier", "authority_identifier"), ("canton", "canton"),
                      ("effectiveFrom", "effective_from"), ("effectiveTo", "effective_to"),
                      ("sourceDocumentId", "source_document_id")):
        if attr in fields:
            if attr in ("name", "effectiveFrom") and getattr(data, attr) is None:
                raise BadRequestException(f"{attr} cannot be empty")
            setattr(row, col, getattr(data, attr))
    _check_dates(row.effective_from, row.effective_to)
    _check_source(db, row.source_document_id)
    db.flush()
    _ch_audit(db, actor_id, "update", "ch_scheme_profile", row.id, old=old,
              new={"rulesSha256": row.rules_sha256, "effectiveFrom": _iso(row.effective_from),
                   "effectiveTo": _iso(row.effective_to), "fields": sorted(fields)},
              reason=data.reason, correlation_id=correlation_id)
    return scheme_view(row)


def delete_scheme(db: Session, scheme_id: int, organization_id: Optional[int], actor_id: Optional[int],
                  reason: Optional[str] = None, correlation_id: Optional[str] = None) -> dict:
    row = _writable_scheme(db, scheme_id, organization_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"scheme {row.id} is {row.status}; only a DRAFT can be deleted")
    referenced = (
        db.query(ChEntityProfile).filter((ChEntityProfile.compensation_office_scheme_id == row.id)
                                         | (ChEntityProfile.fak_scheme_id == row.id)).first()
        or db.query(EmployeeStatutoryProfile).filter(
            (EmployeeStatutoryProfile.ch_bvg_plan_scheme_id == row.id)
            | (EmployeeStatutoryProfile.ch_uvg_policy_scheme_id == row.id)
            | (EmployeeStatutoryProfile.ch_ktg_policy_scheme_id == row.id)).first()
        or db.query(ChSchemeProfile).filter(ChSchemeProfile.previous_version_id == row.id).first()
    )
    if referenced is not None:
        raise BadRequestException(f"scheme {row.id} is referenced ({type(referenced).__name__} {referenced.id}) "
                                  "and cannot be deleted")
    view = scheme_view(row)
    _ch_audit(db, actor_id, "delete", "ch_scheme_profile", row.id,
              old={"status": row.status, "rulesSha256": row.rules_sha256}, reason=reason,
              correlation_id=correlation_id)
    db.delete(row)
    db.flush()
    return {**view, "deleted": True}


def approve_scheme(db: Session, scheme_id: int, organization_id: Optional[int], actor_id: Optional[int],
                   reason: Optional[str] = None, correlation_id: Optional[str] = None) -> dict:
    row = _writable_scheme(db, scheme_id, organization_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT scheme can be approved (this one is {row.status})")
    if actor_id is None or actor_id in ({row.created_by_id} | _authors(db, "ch_scheme_profile", row.id)):
        raise BadRequestException("the scheme must be approved by a user other than its author or editors")
    row.status, row.approved_by_id = "APPROVED", actor_id
    db.flush()
    _ch_audit(db, actor_id, "approve", "ch_scheme_profile", row.id, old={"status": "DRAFT"},
              new={"status": "APPROVED", "rulesSha256": row.rules_sha256}, reason=reason,
              correlation_id=correlation_id)
    return scheme_view(row)


def activate_scheme(db: Session, scheme_id: int, organization_id: Optional[int], actor_id: Optional[int],
                    reason: Optional[str] = None, correlation_id: Optional[str] = None) -> dict:
    row = _writable_scheme(db, scheme_id, organization_id)
    # lock every version of this scheme code so two activations cannot both end LIVE
    _in_scope(db.query(ChSchemeProfile), organization_id).filter(
        ChSchemeProfile.scheme_type == row.scheme_type, ChSchemeProfile.scheme_code == row.scheme_code,
    ).order_by(ChSchemeProfile.id).with_for_update().all()
    if row.status != "APPROVED":
        raise BadRequestException(f"only an APPROVED scheme can be activated (this one is {row.status})")
    if actor_id is None or actor_id == row.approved_by_id:
        raise BadRequestException("the scheme must be activated by a user other than its approver")
    retired = [
        prev for prev in _in_scope(db.query(ChSchemeProfile), organization_id).filter(
            ChSchemeProfile.scheme_type == row.scheme_type, ChSchemeProfile.scheme_code == row.scheme_code,
            ChSchemeProfile.status == "LIVE", ChSchemeProfile.id != row.id).order_by(ChSchemeProfile.id)
        if _periods_overlap(prev.effective_from, prev.effective_to, row.effective_from, row.effective_to)
    ]
    for prev in retired:
        prev.status = "RETIRED"
        _ch_audit(db, actor_id, "retire", "ch_scheme_profile", prev.id, old={"status": "LIVE"},
                  new={"status": "RETIRED", "replacedById": row.id}, reason=reason, correlation_id=correlation_id)
    row.status, row.activated_by_id = "LIVE", actor_id
    db.flush()
    _ch_audit(db, actor_id, "activate", "ch_scheme_profile", row.id, old={"status": "APPROVED"},
              new={"status": "LIVE", "retiredIds": [p.id for p in retired]}, reason=reason,
              correlation_id=correlation_id)
    return scheme_view(row)


# ── entity profile (versioned) ──────────────────────────────────────────

def _profile_view(row: ChEntityProfile) -> dict:
    return {
        "id": row.id, "organizationId": row.organization_id, "uid": row.uid, "seatCanton": row.seat_canton,
        "cantonRegistrations": row.canton_registrations or [],
        "compensationOfficeSchemeId": row.compensation_office_scheme_id, "fakSchemeId": row.fak_scheme_id,
        "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
        "previousVersionId": row.previous_version_id, "readinessStatus": row.readiness_status,
        "readinessEvidence": row.readiness_evidence, "createdById": row.created_by_id,
    }


def _scheme_check(db, key, label, scheme_id, scheme_type, on: date) -> dict:
    if scheme_id is None:
        return {"key": key, "passed": False, "detail": f"no {label} assigned"}
    s = db.get(ChSchemeProfile, scheme_id)
    if s is None or s.scheme_type != scheme_type:
        return {"key": key, "passed": False, "detail": f"{label} {scheme_id} is not a {scheme_type} scheme"}
    if s.status != "LIVE":
        return {"key": key, "passed": False, "detail": f"{label} {s.scheme_code} v{s.version} is {s.status}, not LIVE"}
    if not (s.effective_from <= on and (s.effective_to is None or on <= s.effective_to)):
        return {"key": key, "passed": False, "detail": f"{label} {s.scheme_code} is not in force on {on.isoformat()}"}
    return {"key": key, "passed": True, "detail": f"{label} {s.scheme_code} v{s.version} LIVE"}


def compute_entity_readiness(db: Session, profile: ChEntityProfile, on: Optional[date] = None) -> Tuple[str, list]:
    """Derived only from stored facts — a client can never set readiness.
    READY or NOT_READY; LIVE is a go-live decision this path never makes."""
    on = on or profile.effective_from
    registered = {r.get("canton") for r in (profile.canton_registrations or [])}
    seat_registered = bool(profile.seat_canton) and profile.seat_canton in registered
    checks = [
        {"key": "uid", "passed": bool(profile.uid and CH_UID_RE.match(profile.uid)),
         "detail": "UID present (CHE-nnn.nnn.nnn)" if profile.uid else "UID missing"},
        {"key": "seat_canton", "passed": bool(profile.seat_canton),
         "detail": profile.seat_canton or "seat canton missing"},
        {"key": "seat_canton_registered", "passed": seat_registered,
         "detail": "seat canton has a canton registration" if seat_registered
         else "no canton registration for the seat canton"},
        _scheme_check(db, "compensation_office", "compensation office", profile.compensation_office_scheme_id,
                      "COMPENSATION_OFFICE", on),
        _scheme_check(db, "fak", "FAK fund", profile.fak_scheme_id, "FAK", on),
    ]
    return ("READY" if all(c["passed"] for c in checks) else "NOT_READY"), checks


def _profile_in_force(db, organization_id, on: date) -> Optional[ChEntityProfile]:
    return (db.query(ChEntityProfile)
            .filter(ChEntityProfile.organization_id == organization_id, ChEntityProfile.effective_from <= on,
                    (ChEntityProfile.effective_to.is_(None)) | (ChEntityProfile.effective_to >= on))
            .order_by(ChEntityProfile.effective_from.desc()).first())


def get_entity_profile(db: Session, organization_id: int, on: Optional[date] = None) -> dict:
    """The version in force on `on` (default today) with its readiness
    re-derived now (not persisted — a GET never writes), plus every version."""
    on = on or date.today()
    versions = (db.query(ChEntityProfile).filter(ChEntityProfile.organization_id == organization_id)
                .order_by(ChEntityProfile.effective_from).all())
    current = _profile_in_force(db, organization_id, on)
    live = None
    if current is not None:
        status, checks = compute_entity_readiness(db, current, on)
        live = {"status": status, "checks": checks, "asOf": on.isoformat()}
    return {"current": _profile_view(current) if current else None, "readinessNow": live,
            "versions": [_profile_view(v) for v in versions]}


def _assignable_scheme(db, scheme_id, organization_id, scheme_type, label):
    if scheme_id is None:
        return
    s = db.get(ChSchemeProfile, scheme_id)
    if s is None or s.organization_id not in (None, organization_id):
        raise NotFoundException(f"{label} scheme", scheme_id)
    if s.scheme_type != scheme_type:
        raise BadRequestException(f"{label} must be a {scheme_type} scheme (scheme {scheme_id} is {s.scheme_type})")
    if s.status == "RETIRED":
        raise BadRequestException(f"{label} scheme {scheme_id} is RETIRED and cannot be assigned")


def save_entity_profile(db: Session, organization_id: int, data, actor_id: Optional[int],
                        correlation_id: Optional[str] = None) -> dict:
    """A new profile version starting data.effectiveFrom. The previous
    version is closed the day before; no version is ever rewritten."""
    if data.uid is not None and not CH_UID_RE.match(data.uid):
        raise BadRequestException("uid must look like CHE-123.456.789")
    _assignable_scheme(db, data.compensationOfficeSchemeId, organization_id, "COMPENSATION_OFFICE",
                       "compensation office")
    _assignable_scheme(db, data.fakSchemeId, organization_id, "FAK", "FAK fund")
    versions = (db.query(ChEntityProfile).filter(ChEntityProfile.organization_id == organization_id)
                .order_by(ChEntityProfile.effective_from.desc()).with_for_update().all())
    latest = versions[0] if versions else None
    if latest is not None and data.effectiveFrom <= latest.effective_from:
        raise BadRequestException(f"a new version must start after the latest version's start "
                                  f"({latest.effective_from.isoformat()}); versions are never rewritten")
    row = ChEntityProfile(
        organization_id=organization_id, uid=data.uid, seat_canton=data.seatCanton,
        canton_registrations=[r.model_dump(exclude_none=True) for r in data.cantonRegistrations],
        compensation_office_scheme_id=data.compensationOfficeSchemeId, fak_scheme_id=data.fakSchemeId,
        effective_from=data.effectiveFrom, previous_version_id=latest.id if latest else None,
        created_by_id=actor_id,
    )
    # readiness is set BEFORE the insert: a stored version is never updated afterwards
    row.readiness_status, checks = compute_entity_readiness(db, row)
    row.readiness_evidence = {"checks": checks, "computedAt": datetime.utcnow().isoformat()}
    closed_from = None
    if latest is not None and (latest.effective_to is None or latest.effective_to >= data.effectiveFrom):
        closed_from = latest.effective_to
        latest.effective_to = data.effectiveFrom - timedelta(days=1)
    db.add(row)
    db.flush()
    if latest is not None and latest.effective_to != closed_from:
        _ch_audit(db, actor_id, "close", "ch_entity_profile", latest.id, old={"effectiveTo": _iso(closed_from)},
                  new={"effectiveTo": _iso(latest.effective_to), "replacedById": row.id},
                  reason=data.reason, correlation_id=correlation_id)
    _ch_audit(db, actor_id, "create", "ch_entity_profile", row.id,
              new={"effectiveFrom": _iso(row.effective_from), "readinessStatus": row.readiness_status,
                   "previousVersionId": row.previous_version_id}, reason=data.reason, correlation_id=correlation_id)
    return _profile_view(row)


# ── earning classification (TaxabilityRule, CH) ─────────────────────────
# Platform statutory classification (organization_id NULL). A CH rule only
# takes effect once Approved (service.get_taxability_classification filters
# CH reads on status == "Approved"); legacy rows of every other country are
# untouched. A changed classification is a new row; approving it closes the
# previous Approved row for the same scope the day before.

def _rule_view(row: TaxabilityRule) -> dict:
    return {
        "id": row.id, "jurisdictionCountry": row.jurisdiction_country, "jurisdictionState": row.jurisdiction_state,
        "earningType": row.earning_type, "taxComponent": row.tax_component, "isTaxable": row.is_taxable,
        "treatment": row.treatment, "status": row.status, "effectiveFrom": _iso(row.effective_from),
        "effectiveTo": _iso(row.effective_to), "sourceDocumentId": row.source_document_id,
        "createdById": row.created_by_id, "approvedById": row.approved_by_id,
    }


def list_ch_taxability_rules(db: Session, status: Optional[str] = None) -> List[dict]:
    q = db.query(TaxabilityRule).filter(TaxabilityRule.jurisdiction_country == "CH",
                                        TaxabilityRule.organization_id.is_(None))
    if status:
        q = q.filter(TaxabilityRule.status == status)
    return [_rule_view(r) for r in q.order_by(TaxabilityRule.tax_component, TaxabilityRule.earning_type,
                                              TaxabilityRule.effective_from)]


def create_ch_taxability_rule(db: Session, data, actor_id: Optional[int],
                              correlation_id: Optional[str] = None) -> dict:
    if data.taxComponent not in CH_TAXABILITY_COMPONENTS:
        raise BadRequestException(f"taxComponent must be one of {list(CH_TAXABILITY_COMPONENTS)}")
    _check_dates(data.effectiveFrom, data.effectiveTo)
    _check_source(db, data.sourceDocumentId)
    row = TaxabilityRule(
        jurisdiction_country="CH", jurisdiction_state=data.jurisdictionState, earning_type=data.earningType,
        tax_component=data.taxComponent, is_taxable=data.isTaxable, treatment=data.treatment,
        effective_from=data.effectiveFrom, effective_to=data.effectiveTo, organization_id=None,
        status="Draft", source_document_id=data.sourceDocumentId, created_by_id=actor_id,
    )
    db.add(row)
    db.flush()
    _ch_audit(db, actor_id, "create", "taxability_rule", row.id,
              new={"status": "Draft", "earningType": row.earning_type, "taxComponent": row.tax_component,
                   "isTaxable": row.is_taxable, "treatment": row.treatment}, reason=data.reason,
              correlation_id=correlation_id)
    return _rule_view(row)


def approve_ch_taxability_rule(db: Session, rule_id: int, actor_id: Optional[int], reason: Optional[str] = None,
                               correlation_id: Optional[str] = None) -> dict:
    row = db.get(TaxabilityRule, rule_id)
    if row is None or row.jurisdiction_country != "CH" or row.organization_id is not None:
        raise NotFoundException("CH taxability rule", rule_id)
    if row.status != "Draft":
        raise BadRequestException(f"only a Draft rule can be approved (this one is {row.status})")
    if actor_id is None or actor_id == row.created_by_id:
        raise BadRequestException("the rule must be approved by a Super Admin other than its author")
    if row.source_document_id is None:
        raise BadRequestException("a CH classification needs a source document before it can be approved")
    previous = (db.query(TaxabilityRule).filter(
        TaxabilityRule.jurisdiction_country == "CH", TaxabilityRule.organization_id.is_(None),
        TaxabilityRule.status == "Approved", TaxabilityRule.earning_type == row.earning_type,
        TaxabilityRule.tax_component == row.tax_component,
        TaxabilityRule.jurisdiction_state.is_(None) if row.jurisdiction_state is None
        else TaxabilityRule.jurisdiction_state == row.jurisdiction_state,
    ).with_for_update().all())
    to_close = []
    for prev in previous:
        if not _periods_overlap(prev.effective_from, prev.effective_to, row.effective_from, row.effective_to):
            continue
        if prev.effective_from is None or prev.effective_from >= row.effective_from:
            raise BadRequestException(f"approved rule {prev.id} already governs from "
                                      f"{_iso(prev.effective_from)}; a replacement must start later")
        to_close.append(prev)
    for prev in to_close:
        old_to = prev.effective_to
        prev.effective_to = row.effective_from - timedelta(days=1)
        _ch_audit(db, actor_id, "close", "taxability_rule", prev.id, old={"effectiveTo": _iso(old_to)},
                  new={"effectiveTo": _iso(prev.effective_to), "replacedById": row.id}, reason=reason,
                  correlation_id=correlation_id)
    row.status, row.approved_by_id = "Approved", actor_id
    db.flush()
    _ch_audit(db, actor_id, "approve", "taxability_rule", row.id, old={"status": "Draft"},
              new={"status": "Approved", "closedIds": [p.id for p in to_close]}, reason=reason,
              correlation_id=correlation_id)
    return _rule_view(row)


# ── wage floors (CollectiveAgreement, CH) ───────────────────────────────

def _floor_view(row: CollectiveAgreement) -> dict:
    return {
        "id": row.id, "agreementType": row.agreement_type, "agreementCode": row.agreement_code, "name": row.name,
        "version": row.version, "jurisdictionState": row.jurisdiction_state, "employerScope": row.employer_scope,
        "employeeGroup": row.employee_group, "wageFloor": (row.modules or {}).get("wage_floor"),
        "status": row.status, "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
        "sourceDocumentId": row.source_document_id, "previousVersionId": row.previous_version_id,
        "createdById": row.created_by_id, "approvedById": row.approved_by_id,
    }


def list_ch_wage_floors(db: Session, canton: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    q = db.query(CollectiveAgreement).filter(CollectiveAgreement.jurisdiction_country == "CH",
                                             CollectiveAgreement.agreement_type.in_(CH_WAGE_FLOOR_TYPES))
    if canton:
        q = q.filter(CollectiveAgreement.jurisdiction_state == canton)
    if status:
        q = q.filter(CollectiveAgreement.status == status)
    return [_floor_view(r) for r in q.order_by(CollectiveAgreement.agreement_code, CollectiveAgreement.id)]


def create_ch_wage_floor(db: Session, data, actor_id: Optional[int], correlation_id: Optional[str] = None) -> dict:
    _check_source(db, data.sourceDocumentId)
    if (db.query(CollectiveAgreement).filter(CollectiveAgreement.agreement_code == data.agreementCode,
                                             CollectiveAgreement.version == data.version).first()) is not None:
        raise BadRequestException(f"agreement {data.agreementCode} v{data.version} already exists")
    previous = (db.query(CollectiveAgreement).filter(CollectiveAgreement.agreement_code == data.agreementCode)
                .order_by(CollectiveAgreement.id.desc()).first())
    if previous is not None and previous.jurisdiction_country != "CH":
        raise BadRequestException(f"agreement code {data.agreementCode} belongs to {previous.jurisdiction_country}")
    row = CollectiveAgreement(
        organization_id=None, jurisdiction_country="CH", jurisdiction_state=data.jurisdictionState,
        agreement_code=data.agreementCode, name=data.name, agreement_type=data.agreementType,
        employer_scope=data.employerScope, employee_group=data.employeeGroup, version=data.version,
        effective_from=data.effectiveFrom, effective_to=data.effectiveTo, status="Draft",
        modules={"wage_floor": data.wageFloor.model_dump(mode="json", exclude_none=True)},
        source_document_id=data.sourceDocumentId, previous_version_id=previous.id if previous else None,
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.flush()
    _ch_audit(db, actor_id, "create", "collective_agreement", row.id,
              new={"status": "Draft", "agreementType": row.agreement_type, "code": row.agreement_code,
                   "version": row.version, "canton": row.jurisdiction_state}, reason=data.reason,
              correlation_id=correlation_id)
    return _floor_view(row)


def _ch_floor(db, agreement_id) -> CollectiveAgreement:
    row = db.get(CollectiveAgreement, agreement_id)
    if row is None or row.jurisdiction_country != "CH" or row.agreement_type not in CH_WAGE_FLOOR_TYPES:
        raise NotFoundException("CH wage floor", agreement_id)
    return row


def approve_ch_wage_floor(db: Session, agreement_id: int, actor_id: Optional[int], reason: Optional[str] = None,
                          correlation_id: Optional[str] = None) -> dict:
    row = _ch_floor(db, agreement_id)
    if row.status != "Draft":
        raise BadRequestException(f"only a Draft wage floor can be approved (this one is {row.status})")
    if actor_id is None or actor_id in (row.created_by_id, row.updated_by_id):
        raise BadRequestException("the wage floor must be approved by a Super Admin other than its author")
    row.status, row.approved_by_id = "Approved", actor_id
    db.flush()
    _ch_audit(db, actor_id, "approve", "collective_agreement", row.id, old={"status": "Draft"},
              new={"status": "Approved"}, reason=reason, correlation_id=correlation_id)
    return _floor_view(row)


def activate_ch_wage_floor(db: Session, agreement_id: int, actor_id: Optional[int], reason: Optional[str] = None,
                           correlation_id: Optional[str] = None) -> dict:
    row = _ch_floor(db, agreement_id)
    if row.status != "Approved":
        raise BadRequestException(f"only an Approved wage floor can be activated (this one is {row.status})")
    if actor_id is None or actor_id == row.approved_by_id:
        raise BadRequestException("the wage floor must be activated by a Super Admin other than its approver")
    if row.source_document_id is None:
        raise BadRequestException("a wage floor needs a source document before it can go Active")
    superseded = (db.query(CollectiveAgreement)
                  .filter(CollectiveAgreement.agreement_code == row.agreement_code, CollectiveAgreement.id != row.id,
                          CollectiveAgreement.status == "Active").all())
    for prev in superseded:
        prev.status = "Superseded"
        _ch_audit(db, actor_id, "supersede", "collective_agreement", prev.id, old={"status": "Active"},
                  new={"status": "Superseded", "replacedById": row.id}, reason=reason, correlation_id=correlation_id)
    row.status = "Active"
    db.flush()
    _ch_audit(db, actor_id, "activate", "collective_agreement", row.id, old={"status": "Approved"},
              new={"status": "Active", "supersededIds": [p.id for p in superseded]}, reason=reason,
              correlation_id=correlation_id)
    return _floor_view(row)


# ════════════════════════════════════════════════════════════════════════
# CH Step 6 — calculation-input resolver (read-only).
#
# resolve_ch_calc_inputs gathers every fact a Swiss payslip needs, in the
# order the CH plan fixes, and FAILS CLOSED: each missing or ungoverned item
# becomes a structured {key, reason} entry in `blocked` instead of a default.
# All blocks are collected (the resolver does not stop at the first), so one
# call tells an operator everything that must be fixed. Cantons come ONLY
# from the explicit ch_* profile fields — work_state, addresses and the
# entity's seat canton are never used to infer a worker's canton.
# ════════════════════════════════════════════════════════════════════════

from app.modules.payroll.engine.countries.switzerland_content import (  # noqa: E402
    CH_QST_ANNUAL_MODEL_CANTONS, CH_QST_MODELS, CH_YTD_COMPONENTS,
)
from app.modules.payroll.models import (  # noqa: E402
    ChAbsenceBenefitEvent, ChFamilyAllowanceEntitlement, ContributionRate, JurisdictionPack, PayrollYtdAccumulator,
)

CH_QST_SUBJECT_VALUES = ("YES", "NO", "REVIEW_REQUIRED")
CH_MARRIED_STATUSES = ("MARRIED", "REGISTERED_PARTNERSHIP")
# Residence countries with a cross-border taxation agreement that can move
# the taxing right away from Swiss source tax — VERIFY AGAINST ESTV / the
# agreements before relying on this list; it only ever yields REVIEW_REQUIRED.
CH_CROSS_BORDER_AGREEMENT_COUNTRIES = ("FR", "IT", "DE", "AT")
ZERO_CHF = Decimal("0")


def ch_tax_year_key(year: int) -> str:
    """PayrollYtdAccumulator.tax_year for a Swiss calendar year (the
    "IT-CY-2026" / "US-CY-2026" convention)."""
    return f"CH-CY-{year}"


def _in_force(row_from, row_to, on: date) -> bool:
    return (row_from is None or row_from <= on) and (row_to is None or on <= row_to)


def _active_pack(db: Session, canton: Optional[str], on: date) -> Optional[JurisdictionPack]:
    """The Active CH pack in force on `on` for exactly this canton (None =
    the federal pack). Never falls back from a canton to the federal pack."""
    q = db.query(JurisdictionPack).filter(
        JurisdictionPack.jurisdiction_country == "CH", JurisdictionPack.status == "Active",
        JurisdictionPack.jurisdiction_locality.is_(None),
        JurisdictionPack.jurisdiction_state.is_(None) if canton is None
        else JurisdictionPack.jurisdiction_state == canton,
        (JurisdictionPack.effective_from.is_(None)) | (JurisdictionPack.effective_from <= on),
        (JurisdictionPack.effective_to.is_(None)) | (JurisdictionPack.effective_to >= on),
    )
    return q.order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first()


def _pack_params(db: Session, pack: Optional[JurisdictionPack], on: date) -> Dict[str, ContributionRate]:
    if pack is None:
        return {}
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    return {r.component_key: r for r in rows if _in_force(r.effective_from, r.effective_to, on)}


def _param_view(row: ContributionRate) -> dict:
    return {"employeePct": row.employee_rate_pct, "employerPct": row.employer_rate_pct,
            "amount": row.flat_amount, "text": row.text_value}


def _pack_summary(db: Session, pack: Optional[JurisdictionPack], on: date) -> Optional[dict]:
    if pack is None:
        return None
    return {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "canton": pack.jurisdiction_state,
            "effectiveFrom": _iso(pack.effective_from), "effectiveTo": _iso(pack.effective_to),
            "parameters": {k: _param_view(r) for k, r in sorted(_pack_params(db, pack, on).items())}}


def _live_scheme(db: Session, scheme_id: Optional[int], organization_id: int, scheme_type: str,
                 on: date) -> Tuple[Optional[ChSchemeProfile], Optional[str]]:
    if scheme_id is None:
        return None, "not assigned"
    s = db.get(ChSchemeProfile, scheme_id)
    if s is None or s.organization_id not in (None, organization_id):
        return None, f"scheme {scheme_id} does not exist for this employer"
    if s.scheme_type != scheme_type:
        return None, f"scheme {scheme_id} is a {s.scheme_type}, not a {scheme_type}"
    if s.status != "LIVE":
        return None, f"{s.scheme_code} v{s.version} is {s.status}, not LIVE"
    if not _in_force(s.effective_from, s.effective_to, on):
        return None, f"{s.scheme_code} v{s.version} is not in force on {on.isoformat()}"
    return s, None


def _active_floor(db: Session, agreement_id: int, on: date) -> Tuple[Optional[CollectiveAgreement], Optional[str]]:
    a = db.get(CollectiveAgreement, agreement_id)
    if a is None or a.jurisdiction_country != "CH" or a.agreement_type not in CH_WAGE_FLOOR_TYPES:
        return None, f"agreement {agreement_id} is not a CH wage floor"
    if a.status != "Active":
        return None, f"{a.agreement_code} v{a.version} is {a.status}, not Active"
    if not _in_force(a.effective_from, a.effective_to, on):
        return None, f"{a.agreement_code} v{a.version} is not in force on {on.isoformat()}"
    return a, None


def _canton_minimums(db: Session, canton: str, on: date) -> List[CollectiveAgreement]:
    rows = db.query(CollectiveAgreement).filter(
        CollectiveAgreement.jurisdiction_country == "CH", CollectiveAgreement.agreement_type == "CH_CANTON_MINIMUM",
        CollectiveAgreement.jurisdiction_state == canton, CollectiveAgreement.status == "Active").all()
    return [r for r in rows if _in_force(r.effective_from, r.effective_to, on)]


def _ytd(db: Session, employee_id: int, year: int) -> dict:
    """Running totals per CH component; a component with no row has had no
    CH payroll this year at this employer, so its total is a true zero."""
    rows = {r.tax_component: r for r in db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == employee_id,
        PayrollYtdAccumulator.tax_year == ch_tax_year_key(year)).all()}
    out = {}
    for component in CH_YTD_COMPONENTS:
        row = rows.get(component)
        out[component] = {
            "wages": Decimal(str(row.ytd_taxable_wages)) if row is not None else ZERO_CHF,
            "withheld": Decimal(str(row.ytd_tax_withheld)) if row is not None else ZERO_CHF,
            "recorded": row is not None,
        }
    return out


def _bvg_eligibility(employee, federal_params: dict, on: date, blocked: list) -> Optional[bool]:
    """BVG mandatory insurance: annual salary at or above the entry threshold
    and from 1 January after the 17th birthday (BVG Art. 2 / 7 — VERIFY the
    age rule against the G1 statutory review). None = cannot be determined
    (blocked)."""
    threshold_row = federal_params.get("ch_bvg_entry_threshold")
    threshold = threshold_row.flat_amount if threshold_row is not None else None
    dob = getattr(employee, "date_of_birth", None)
    annual = getattr(employee, "ctc", None)
    if threshold is None:
        _block(blocked, "ch_bvg_entry_threshold", "the Active federal pack has no BVG entry threshold")
    if dob is None:
        _block(blocked, "ch_date_of_birth", "date of birth is needed to decide BVG insurance")
    if annual is None or Decimal(str(annual)) <= 0:
        _block(blocked, "ch_annual_salary", "annual salary (ctc) is needed to decide BVG insurance")
    if threshold is None or dob is None or annual is None or Decimal(str(annual)) <= 0:
        return None
    return Decimal(str(annual)) >= Decimal(str(threshold)) and on.year - dob.year > 17


def _block(blocked: list, key: str, reason: str) -> None:
    blocked.append({"key": key, "reason": reason})


def _valid_canton(value) -> bool:
    return value in CH_CANTON_CODES


def resolve_ch_calc_inputs(db: Session, organization_id: int, employee, payroll_date: date,
                           period_start: Optional[date] = None, period_end: Optional[date] = None) -> dict:
    """{"ready", "blocked": [{key, reason}], "inputs"} for one CH employee on
    `payroll_date`. Read-only — never writes, never defaults a missing fact."""
    from app.modules.payroll.service import get_taxability_classification, resolve_employee_statutory_profile

    on = payroll_date
    period_start = period_start or on.replace(day=1)
    period_end = period_end or on
    blocked: list = []
    inputs: dict = {"employeeId": employee.id, "payrollDate": on.isoformat(),
                    "periodStart": period_start.isoformat(), "periodEnd": period_end.isoformat()}

    # 1. entity profile
    entity = _profile_in_force(db, organization_id, on)
    if entity is None:
        _block(blocked, "ch_entity_profile", f"no CH employer profile is in force on {on.isoformat()}")
    inputs["entityProfileId"] = entity.id if entity else None

    # 2. worker profile
    profile = resolve_employee_statutory_profile(db, employee.id, organization_id, as_of=on)
    if profile is None or profile.country_code != "CH":
        _block(blocked, "ch_worker_profile", f"no CH statutory profile is in force on {on.isoformat()}")
        profile = None
    get = (lambda attr: getattr(profile, attr, None)) if profile is not None else (lambda attr: None)
    inputs["workerProfileId"] = profile.id if profile else None

    # 3. cantons — explicit ch_* fields only
    work, residence, residence_country = get("ch_work_canton"), get("ch_residence_canton"), get("ch_residence_country")
    qst_subject, qst_canton = get("ch_qst_subject"), get("ch_qst_canton")
    if profile is not None:
        if not _valid_canton(work):
            _block(blocked, "ch_work_canton", "work canton is missing or not a CH-XX code "
                                              "(work_state and addresses are never used to infer it)")
        if not residence_country:
            _block(blocked, "ch_residence_country", "residence country is missing")
        elif residence_country == "CH" and not _valid_canton(residence):
            _block(blocked, "ch_residence_canton", "a Swiss resident needs a CH-XX residence canton")
        elif residence_country != "CH" and residence is not None:
            _block(blocked, "ch_residence_canton",
                   f"a residence canton is set although the residence country is {residence_country}")
        if qst_subject is None or qst_subject not in CH_QST_SUBJECT_VALUES:
            _block(blocked, "ch_qst_subject", "QST liability (YES / NO / REVIEW_REQUIRED) is not recorded")
        elif qst_subject == "REVIEW_REQUIRED":
            _block(blocked, "ch_qst_subject_review", "QST liability is under review — it is never inferred")
        if qst_subject == "YES":
            if not _valid_canton(qst_canton):
                _block(blocked, "ch_qst_canton", "a QST-liable worker needs a CH-XX QST canton")
            if not get("ch_qst_tariff_code"):
                _block(blocked, "ch_qst_tariff_code", "a QST-liable worker needs a tariff code")
            if get("ch_children_count") is None:
                _block(blocked, "ch_children_count", "children count is needed for the QST tariff")
            if get("ch_church_tax") is None:
                _block(blocked, "ch_church_tax", "church-tax liability is needed for the QST tariff")
    inputs["cantons"] = {"work": work, "residence": residence, "residenceCountry": residence_country,
                         "qst": qst_canton if qst_subject == "YES" else None}
    inputs["qstSubject"] = qst_subject

    # 4. federal pack
    federal = _active_pack(db, None, on)
    if federal is None:
        _block(blocked, "ch_federal_pack", f"no Active federal CH pack is in force on {on.isoformat()}")
    federal_params = _pack_params(db, federal, on)
    inputs["federalPack"] = _pack_summary(db, federal, on)

    # 5. work-canton pack (FAK, floor)
    work_pack = None
    if _valid_canton(work):
        work_pack = _active_pack(db, work, on)
        if work_pack is None:
            _block(blocked, "ch_work_canton_pack", f"no Active {work} pack is in force on {on.isoformat()}")
    inputs["workCantonPack"] = _pack_summary(db, work_pack, on)

    # 6. QST-canton pack + its ACTIVE tariff file
    inputs["qst"] = None
    if qst_subject == "YES" and _valid_canton(qst_canton):
        qst_pack = _active_pack(db, qst_canton, on)
        if qst_pack is None:
            _block(blocked, "ch_qst_canton_pack", f"no Active {qst_canton} pack is in force on {on.isoformat()}")
        else:
            params = _pack_params(db, qst_pack, on)
            model_row, file_row = params.get("ch_qst_model"), params.get("ch_qst_tariff_file_id")
            model = (model_row.text_value or "").strip().upper() if model_row is not None else ""
            if model not in CH_QST_MODELS:
                _block(blocked, "ch_qst_model", f"the {qst_canton} pack does not set the QST model (MONTHLY | ANNUAL)")
            raw_id = (file_row.text_value or "").strip() if file_row is not None else ""
            tariff = db.get(ChQstTariffFile, int(raw_id)) if raw_id.isdigit() else None
            reason = None
            if tariff is None:
                reason = f"the {qst_canton} pack does not point to a QST tariff file"
            elif tariff.canton != qst_canton:
                reason = f"tariff file {tariff.id} belongs to {tariff.canton}, not {qst_canton}"
            elif tariff.status != "ACTIVE":
                reason = f"tariff file {tariff.id} is {tariff.status}, not ACTIVE"
            elif not _in_force(tariff.effective_from, tariff.effective_to, on):
                reason = f"tariff file {tariff.id} is not in force on {on.isoformat()}"
            if reason:
                _block(blocked, "ch_qst_tariff_file", reason)
            inputs["qst"] = {"packId": qst_pack.id, "model": model or None,
                             "tariffFileId": tariff.id if tariff is not None and not reason else None,
                             "tariffCode": get("ch_qst_tariff_code"), "children": get("ch_children_count"),
                             "churchTax": get("ch_church_tax")}

    # 7. schemes LIVE on the date
    schemes: dict = {}
    if entity is not None:
        for key, attr, scheme_type, label in (
                ("ch_compensation_office", "compensation_office_scheme_id", "COMPENSATION_OFFICE", "compensation office"),
                ("ch_fak_scheme", "fak_scheme_id", "FAK", "FAK fund")):
            s, why = _live_scheme(db, getattr(entity, attr), organization_id, scheme_type, on)
            if s is None:
                _block(blocked, key, f"{label}: {why}")
            schemes[scheme_type] = s.id if s else None
    bvg_eligible = _bvg_eligibility(employee, federal_params, on, blocked) if federal is not None else None
    inputs["bvgEligible"] = bvg_eligible
    if profile is not None:
        if bvg_eligible:
            s, why = _live_scheme(db, get("ch_bvg_plan_scheme_id"), organization_id, "BVG_PLAN", on)
            if s is None:
                _block(blocked, "ch_bvg_plan", f"BVG-insured worker — BVG plan: {why}")
            schemes["BVG_PLAN"] = s.id if s else None
        s, why = _live_scheme(db, get("ch_uvg_policy_scheme_id"), organization_id, "UVG_POLICY", on)
        if s is None:
            _block(blocked, "ch_uvg_policy", f"UVG policy (always required): {why}")
        else:
            codes = {rc.get("code") for rc in (s.rules or {}).get("risk_classes", [])}
            if get("ch_uvg_risk_class") not in codes:
                _block(blocked, "ch_uvg_risk_class",
                       f"risk class {get('ch_uvg_risk_class')!r} is not in UVG policy {s.scheme_code}")
        schemes["UVG_POLICY"] = s.id if s else None
        if get("ch_ktg_policy_scheme_id") is not None:
            s, why = _live_scheme(db, get("ch_ktg_policy_scheme_id"), organization_id, "KTG_POLICY", on)
            if s is None:
                _block(blocked, "ch_ktg_policy", f"KTG policy: {why}")
            schemes["KTG_POLICY"] = s.id if s else None
    inputs["schemes"] = schemes

    # 8. wage floor
    floor_id = get("ch_wage_floor_agreement_id")
    if floor_id is not None:
        floor, why = _active_floor(db, floor_id, on)
        if floor is None:
            _block(blocked, "ch_wage_floor", f"assigned wage floor: {why}")
        inputs["wageFloorAgreementId"] = floor.id if floor else None
    inputs["cantonMinimumIds"] = [a.id for a in _canton_minimums(db, work, on)] if _valid_canton(work) else []

    # 9. CH earning classification (Approved rules only)
    needed = [CH_AHV, CH_IV, CH_EO, CH_ALV, CH_UVG]
    if bvg_eligible:
        needed.append(CH_BVG)
    if get("ch_ktg_policy_scheme_id") is not None:
        needed.append(CH_KTG)
    if qst_subject == "YES":
        needed.append(CH_QST)
    classification = {}
    for component in needed:
        classification[component] = get_taxability_classification(db, "CH", component, organization_id, as_of=on)
        if not classification[component]:
            _block(blocked, f"ch_taxability:{component}", f"no Approved CH earning classification for {component}")
    inputs["taxability"] = classification

    # 10. approved FAK entitlements overlapping the period
    entitlements = db.query(ChFamilyAllowanceEntitlement).filter(
        ChFamilyAllowanceEntitlement.employee_id == employee.id,
        ChFamilyAllowanceEntitlement.organization_id == organization_id,
        ChFamilyAllowanceEntitlement.status == "APPROVED").all()
    inputs["fakEntitlementIds"] = [e.id for e in entitlements
                                   if (e.period_from is None or e.period_from <= period_end)
                                   and (e.period_to is None or e.period_to >= period_start)]

    # 11. absence-benefit events in the period
    events = db.query(ChAbsenceBenefitEvent).filter(
        ChAbsenceBenefitEvent.employee_id == employee.id, ChAbsenceBenefitEvent.organization_id == organization_id,
        ChAbsenceBenefitEvent.period_from <= period_end,
        (ChAbsenceBenefitEvent.period_to.is_(None)) | (ChAbsenceBenefitEvent.period_to >= period_start)).all()
    inputs["absenceEventIds"] = [e.id for e in events]

    # 12. YTD accumulators
    inputs["ytd"] = _ytd(db, employee.id, on.year)

    # 13. pay frequency
    frequency = getattr(employee, "pay_frequency", None)
    if frequency != "Monthly":
        _block(blocked, "ch_pay_frequency", f"Swiss payroll runs Monthly only (this employee is {frequency!r})")
    return {"ready": not blocked, "blocked": blocked, "inputs": inputs}


# ── QST applicability (read-only, advisory) ─────────────────────────────

def qst_resolve(db: Session, organization_id: int, facts: dict) -> dict:
    """What the facts say about Swiss source tax for one worker — ADVISORY.
    The authoritative value stays the profile's ch_qst_subject, which is
    recorded by a person and never inferred. Writes nothing.

    Applicability (VERIFY AGAINST ESTV before relying on it):
      * Swiss nationals — NOT_SUBJECT (ordinary assessment);
      * resident in CH with a C permit — NOT_SUBJECT;
      * resident in CH, foreign, married to a Swiss national / C-permit
        holder — NOT_SUBJECT (spouse status unknown -> REVIEW_REQUIRED);
      * other foreign residents in CH — SUBJECT;
      * resident abroad — SUBJECT, or REVIEW_REQUIRED where a cross-border
        agreement may move the taxing right.
    """
    on = facts.get("on_date") or date.today()
    nationality, residence_country = facts.get("nationality"), facts.get("residence_country")
    permit, marital = facts.get("permit_type"), facts.get("marital_status")
    missing: list = []
    for key in ("nationality", "residence_country"):
        if not facts.get(key):
            missing.append(key)

    applicability, reason = "UNDETERMINED", "facts missing"
    if not missing:
        if nationality == "CH":
            applicability, reason = "NOT_SUBJECT", "Swiss nationals are taxed by ordinary assessment"
        elif residence_country == "CH":
            if not permit:
                missing.append("permit_type")
            elif permit == "C":
                applicability, reason = "NOT_SUBJECT", "C-permit holders resident in Switzerland are not taxed at source"
            elif marital in CH_MARRIED_STATUSES and facts.get("spouse_swiss_or_permit_c") is True:
                applicability, reason = "NOT_SUBJECT", "married to a Swiss national or C-permit holder"
            elif marital in CH_MARRIED_STATUSES and facts.get("spouse_swiss_or_permit_c") is None:
                applicability, reason = "REVIEW_REQUIRED", "married — the spouse's nationality / permit decides"
                missing.append("spouse_swiss_or_permit_c")
            else:
                applicability, reason = "SUBJECT", f"foreign resident with a {permit} permit"
        elif residence_country in CH_CROSS_BORDER_AGREEMENT_COUNTRIES:
            applicability, reason = "REVIEW_REQUIRED", (f"resident in {residence_country}: a cross-border agreement "
                                                        "may change who taxes this income")
        else:
            applicability, reason = "SUBJECT", f"resident abroad ({residence_country})"

    required = []
    if applicability in ("SUBJECT", "REVIEW_REQUIRED"):
        required = ["qst_canton", "marital_status", "children_count", "church_tax"]
        if marital in CH_MARRIED_STATUSES:
            required.append("spouse_employed")
        missing += [k for k in required if facts.get(k) is None and k not in missing]

    canton = facts.get("qst_canton")
    model = None
    if canton is not None and not _valid_canton(canton):
        missing.append("qst_canton")
        canton = None
    if canton:
        reference = "ANNUAL" if canton in CH_QST_ANNUAL_MODEL_CANTONS else "MONTHLY"
        pack = _active_pack(db, canton, on)
        row = _pack_params(db, pack, on).get("ch_qst_model") if pack else None
        configured = (row.text_value or "").strip().upper() if row is not None and row.text_value else None
        model = {"value": configured or reference,
                 "source": f"{pack.pack_id} v{pack.version}" if configured else "reference list (S9) — no Active "
                                                                             "canton pack sets it",
                 "authoritative": bool(configured),
                 "conflict": bool(configured and configured != reference)}
    return {"applicability": applicability, "reason": reason, "advisory": True, "model": model,
            "requiredTariffFacts": required, "missingFacts": sorted(set(missing)), "onDate": on.isoformat()}


# ── what is in force (read-only) ────────────────────────────────────────

def rules_effective(db: Session, organization_id: int, on: Optional[date] = None,
                    canton: Optional[str] = None) -> dict:
    """Everything governed that is in force on `on` for this employer and a
    canton (default: the seat canton of the entity profile in force)."""
    from app.modules.payroll.service import get_taxability_classification

    on = on or date.today()
    entity = _profile_in_force(db, organization_id, on)
    if canton is not None and not _valid_canton(canton):
        raise BadRequestException(f"canton must be one of the CH-XX codes, got {canton!r}")
    canton = canton or (entity.seat_canton if entity else None)
    tariffs = []
    if canton:
        tariffs = [tariff_file_view(t) for t in db.query(ChQstTariffFile).filter(
            ChQstTariffFile.canton == canton, ChQstTariffFile.status == "ACTIVE").order_by(ChQstTariffFile.id)
            if _in_force(t.effective_from, t.effective_to, on)]
    schemes = [scheme_view(s) for s in db.query(ChSchemeProfile).filter(
        (ChSchemeProfile.organization_id == organization_id) | ChSchemeProfile.organization_id.is_(None),
        ChSchemeProfile.status == "LIVE").order_by(ChSchemeProfile.scheme_type, ChSchemeProfile.id)
        if _in_force(s.effective_from, s.effective_to, on)]
    floors = [_floor_view(a) for a in db.query(CollectiveAgreement).filter(
        CollectiveAgreement.jurisdiction_country == "CH", CollectiveAgreement.agreement_type.in_(CH_WAGE_FLOOR_TYPES),
        CollectiveAgreement.status == "Active").order_by(CollectiveAgreement.id)
        if _in_force(a.effective_from, a.effective_to, on)
        and (a.jurisdiction_state is None or a.jurisdiction_state == canton)]
    return {
        "onDate": on.isoformat(), "canton": canton,
        "entityProfile": _profile_view(entity) if entity else None,
        "federalPack": _pack_summary(db, _active_pack(db, None, on), on),
        "cantonPack": _pack_summary(db, _active_pack(db, canton, on), on) if canton else None,
        "qstTariffFiles": tariffs,
        "schemes": schemes,
        "taxability": {c: get_taxability_classification(db, "CH", c, organization_id, as_of=on)
                       for c in CH_TAXABILITY_COMPONENTS},
        "wageFloors": floors,
    }
