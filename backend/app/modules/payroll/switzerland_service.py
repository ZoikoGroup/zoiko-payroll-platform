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
    view = tariff_file_view(target)
    # Step 13: what each superseded file was used for — listed for deliberate
    # correction, never recalculated automatically
    view["supersededImpact"] = [{k: v for k, v in qst_tariff_affected_payslips(db, p.id).items()
                                 if k in ("tariffFileId", "months", "payslipCount", "autoRecalculated")}
                                for p in superseded]
    return view


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
    CH_AHV, CH_ALV, CH_BVG, CH_EO, CH_IV, CH_KTG, CH_QST, CH_UVG, CH_WAGE_FLOOR,
)
from app.modules.payroll.models import (  # noqa: E402
    ChEntityProfile, ChSchemeProfile, CollectiveAgreement, EmployeeStatutoryProfile, SourceArtifact,
    TaxabilityRule, TaxConfigurationAudit,
)
from app.modules.payroll.switzerland_schemas import validate_scheme_rules  # noqa: E402

CH_UID_RE = re.compile(r"^CHE-\d{3}\.\d{3}\.\d{3}$")
# CH_WAGE_FLOOR classifies which earnings count toward a wage floor (Step 11).
CH_TAXABILITY_COMPONENTS = (CH_AHV, CH_IV, CH_EO, CH_ALV, CH_UVG, CH_BVG, CH_KTG, CH_QST, CH_WAGE_FLOOR)
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


def _floor_fact(a: CollectiveAgreement, assigned: bool) -> dict:
    return {"id": a.id, "agreement_type": a.agreement_type, "agreement_code": a.agreement_code,
            "version": a.version, "canton": a.jurisdiction_state, "assigned": assigned,
            "wage_floor": (a.modules or {}).get("wage_floor")}


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

    # 8. wage floors — the assigned GAV / NAV (must be Active) plus every
    #    Active canton minimum of the work canton; the engine applies each only
    #    within its scope and reports NO_MANDATORY_FLOOR when none applies.
    floors = []
    floor_id = get("ch_wage_floor_agreement_id")
    if floor_id is not None:
        floor, why = _active_floor(db, floor_id, on)
        if floor is None:
            _block(blocked, "ch_wage_floor", f"assigned wage floor: {why}")
        else:
            floors.append(_floor_fact(floor, assigned=True))
        inputs["wageFloorAgreementId"] = floor.id if floor else None
    minimums = _canton_minimums(db, work, on) if _valid_canton(work) else []
    inputs["cantonMinimumIds"] = [a.id for a in minimums]
    floors += [_floor_fact(a, assigned=False) for a in minimums if a.id != floor_id]
    inputs["wageFloorAgreements"] = floors
    inputs["workerFloorFacts"] = {"occupation": get("ch_occupation"), "grade": get("ch_grade"),
                                  "experienceYears": get("ch_experience_years")}

    # 10. approved FAK entitlements overlapping the period, and the canton
    #     packs whose amounts pay them (resolved before the classification
    #     step because absence earnings need classifying too)
    entitlements = [e for e in db.query(ChFamilyAllowanceEntitlement).filter(
        ChFamilyAllowanceEntitlement.employee_id == employee.id,
        ChFamilyAllowanceEntitlement.organization_id == organization_id,
        ChFamilyAllowanceEntitlement.status == "APPROVED").order_by(ChFamilyAllowanceEntitlement.id)
        if (e.period_from is None or e.period_from <= period_end)
        and (e.period_to is None or e.period_to >= period_start)]
    inputs["fakEntitlementIds"] = [e.id for e in entitlements]
    inputs["fakEntitlements"] = [{
        "id": e.id, "allowance_type": e.allowance_type, "entitlement_basis": e.entitlement_basis,
        "canton": e.canton or work, "primary_amount": (e.precedence_evidence or {}).get("primary_amount"),
    } for e in entitlements]
    fak_cantons = {}
    for canton in sorted({e["canton"] for e in inputs["fakEntitlements"] if e["canton"]}):
        canton_pack = work_pack if canton == work else _active_pack(db, canton, on)
        if canton_pack is None:
            _block(blocked, f"ch_fak_canton_pack:{canton}",
                   f"an approved entitlement is paid from {canton}, which has no Active pack on {on.isoformat()}")
        fak_cantons[canton] = _pack_summary(db, canton_pack, on)
    inputs["fakCantonPacks"] = fak_cantons

    # 11. absence-benefit events in the period -> this period's allowance /
    #     top-up amounts (each becomes its own earning type in the engine)
    events = db.query(ChAbsenceBenefitEvent).filter(
        ChAbsenceBenefitEvent.employee_id == employee.id, ChAbsenceBenefitEvent.organization_id == organization_id,
        ChAbsenceBenefitEvent.period_from <= period_end,
        (ChAbsenceBenefitEvent.period_to.is_(None)) | (ChAbsenceBenefitEvent.period_to >= period_start)
    ).order_by(ChAbsenceBenefitEvent.period_from, ChAbsenceBenefitEvent.id).all()
    inputs["absenceEventIds"] = [e.id for e in events]
    absence = [a for a in (absence_period_amounts(e, period_start, period_end, blocked) for e in events) if a]
    inputs["absenceEarnings"] = absence
    absence_earning_types = sorted(
        {CH_ABSENCE_ALLOWANCE_EARNING[a["event_type"]] for a in absence if a["allowance"] > 0}
        | ({CH_EARNING_EMPLOYER_TOPUP} if any(a["topup"] > 0 for a in absence) else set()))

    # 9. CH earning classification (Approved rules only)
    needed = [CH_AHV, CH_IV, CH_EO, CH_ALV, CH_UVG]
    if bvg_eligible:
        needed.append(CH_BVG)
    if get("ch_ktg_policy_scheme_id") is not None:
        needed.append(CH_KTG)
    if qst_subject == "YES":
        needed.append(CH_QST)
    if floors:
        needed.append(CH_WAGE_FLOOR)
    classification = {}
    for component in needed:
        classification[component] = get_taxability_classification(db, "CH", component, organization_id, as_of=on)
        if not classification[component]:
            _block(blocked, f"ch_taxability:{component}", f"no Approved CH earning classification for {component}")
            continue
        for earning_type in absence_earning_types:
            if earning_type not in classification[component]:
                _block(blocked, f"ch_taxability:{component}:{earning_type}",
                       f"{earning_type} (absence earning) has no Approved {component} classification")
    inputs["taxability"] = classification

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


# ════════════════════════════════════════════════════════════════════════
# CH Step 11 — family-allowance entitlements and absence-benefit events.
# Same transaction contract as Step 5: flush only; the routes commit through
# switzerland_http.ch_write (write + audit + idempotency record together).
# ════════════════════════════════════════════════════════════════════════

from app.modules.payroll.engine.countries.switzerland_content import (  # noqa: E402
    CH_ABSENCE_ALLOWANCE_EARNING, CH_ABSENCE_EVENT_TYPES, CH_EARNING_EMPLOYER_TOPUP,
)
from app.modules.payroll.models import PayrollEmployee  # noqa: E402


def _org_employee(db: Session, organization_id: int, employee_id: int) -> PayrollEmployee:
    employee = db.get(PayrollEmployee, employee_id)
    if employee is None or employee.organization_id != organization_id:
        raise NotFoundException("Employee", employee_id)
    return employee


def _entitlement_view(row: ChFamilyAllowanceEntitlement) -> dict:
    evidence = row.precedence_evidence or {}
    return {
        "id": row.id, "employeeId": row.employee_id, "allowanceType": row.allowance_type,
        "childReference": row.child_reference, "childBirthDate": _iso(row.child_birth_date),
        "trainingStatus": row.training_status, "entitlementBasis": row.entitlement_basis,
        "primaryFundAmount": evidence.get("primary_amount"), "primaryFundReference": evidence.get("primary_reference"),
        "canton": row.canton, "fakSchemeId": row.fak_scheme_id, "periodFrom": _iso(row.period_from),
        "periodTo": _iso(row.period_to), "status": row.status, "fundDecisionReference": row.fund_decision_reference,
        "approvedById": row.approved_by_id, "sourceDocumentId": row.source_document_id,
    }


def _entitlement(db: Session, organization_id: int, entitlement_id: int) -> ChFamilyAllowanceEntitlement:
    row = db.get(ChFamilyAllowanceEntitlement, entitlement_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundException("Family allowance entitlement", entitlement_id)
    return row


def _check_fak_scheme(db, organization_id, scheme_id):
    if scheme_id is None:
        return
    s = db.get(ChSchemeProfile, scheme_id)
    if s is None or s.organization_id not in (None, organization_id):
        raise NotFoundException("FAK scheme", scheme_id)
    if s.scheme_type != "FAK":
        raise BadRequestException(f"scheme {scheme_id} is a {s.scheme_type}, not a FAK scheme")


def list_family_allowances(db: Session, organization_id: int, employee_id: Optional[int] = None,
                           status: Optional[str] = None) -> List[dict]:
    q = db.query(ChFamilyAllowanceEntitlement).filter(ChFamilyAllowanceEntitlement.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(ChFamilyAllowanceEntitlement.employee_id == employee_id)
    if status:
        q = q.filter(ChFamilyAllowanceEntitlement.status == status)
    return [_entitlement_view(r) for r in q.order_by(ChFamilyAllowanceEntitlement.id)]


def get_family_allowance(db: Session, organization_id: int, entitlement_id: int) -> dict:
    return _entitlement_view(_entitlement(db, organization_id, entitlement_id))


def create_family_allowance(db: Session, organization_id: int, data, actor_id: Optional[int],
                            correlation_id: Optional[str] = None) -> dict:
    _org_employee(db, organization_id, data.employeeId)
    _check_fak_scheme(db, organization_id, data.fakSchemeId)
    _check_source(db, data.sourceDocumentId)
    evidence = None
    if data.entitlementBasis == "DIFFERENTIAL":
        evidence = {"primary_amount": str(data.primaryFundAmount), "primary_reference": data.primaryFundReference}
    row = ChFamilyAllowanceEntitlement(
        organization_id=organization_id, employee_id=data.employeeId, allowance_type=data.allowanceType,
        child_reference=data.childReference, child_birth_date=data.childBirthDate,
        training_status=data.trainingStatus, entitlement_basis=data.entitlementBasis,
        precedence_evidence=evidence, canton=data.canton, fak_scheme_id=data.fakSchemeId,
        period_from=data.periodFrom, period_to=data.periodTo, status="REQUESTED",
        fund_decision_reference=data.fundDecisionReference, source_document_id=data.sourceDocumentId,
    )
    db.add(row)
    db.flush()
    _ch_audit(db, actor_id, "create", "ch_family_allowance_entitlement", row.id,
              new={"status": "REQUESTED", "allowanceType": row.allowance_type, "basis": row.entitlement_basis,
                   "employeeId": row.employee_id}, reason=data.reason, correlation_id=correlation_id)
    return _entitlement_view(row)


def update_family_allowance(db: Session, organization_id: int, entitlement_id: int, data, actor_id: Optional[int],
                            correlation_id: Optional[str] = None) -> dict:
    row = _entitlement(db, organization_id, entitlement_id)
    if row.status != "REQUESTED":
        raise BadRequestException(f"entitlement {row.id} is {row.status}; only a REQUESTED one can be edited")
    fields = data.model_fields_set - {"reason"}
    for attr, col in (("childReference", "child_reference"), ("childBirthDate", "child_birth_date"),
                      ("trainingStatus", "training_status"), ("canton", "canton"), ("fakSchemeId", "fak_scheme_id"),
                      ("periodFrom", "period_from"), ("periodTo", "period_to"),
                      ("fundDecisionReference", "fund_decision_reference"), ("sourceDocumentId", "source_document_id")):
        if attr in fields:
            if attr == "periodFrom" and data.periodFrom is None:
                raise BadRequestException("periodFrom cannot be empty")
            setattr(row, col, getattr(data, attr))
    if fields & {"primaryFundAmount", "primaryFundReference"}:
        if row.entitlement_basis != "DIFFERENTIAL":
            raise BadRequestException("primaryFundAmount / primaryFundReference apply only to a DIFFERENTIAL entitlement")
        evidence = dict(row.precedence_evidence or {})
        if "primaryFundAmount" in fields:
            if data.primaryFundAmount is None:
                raise BadRequestException("a DIFFERENTIAL entitlement needs primaryFundAmount")
            evidence["primary_amount"] = str(data.primaryFundAmount)
        if "primaryFundReference" in fields:
            evidence["primary_reference"] = data.primaryFundReference
        row.precedence_evidence = evidence
    if row.period_to is not None and row.period_to < row.period_from:
        raise BadRequestException("periodTo is before periodFrom")
    _check_fak_scheme(db, organization_id, row.fak_scheme_id)
    _check_source(db, row.source_document_id)
    db.flush()
    _ch_audit(db, actor_id, "update", "ch_family_allowance_entitlement", row.id, new={"fields": sorted(fields)},
              reason=data.reason, correlation_id=correlation_id)
    return _entitlement_view(row)


def delete_family_allowance(db: Session, organization_id: int, entitlement_id: int, actor_id: Optional[int],
                            correlation_id: Optional[str] = None) -> dict:
    row = _entitlement(db, organization_id, entitlement_id)
    if row.status != "REQUESTED":
        raise BadRequestException(f"entitlement {row.id} is {row.status}; only a REQUESTED one can be deleted")
    view = _entitlement_view(row)
    _ch_audit(db, actor_id, "delete", "ch_family_allowance_entitlement", row.id, old={"status": row.status},
              correlation_id=correlation_id)
    db.delete(row)
    db.flush()
    return {**view, "deleted": True}


def approve_family_allowance(db: Session, organization_id: int, entitlement_id: int, actor_id: Optional[int],
                             reason: Optional[str] = None, correlation_id: Optional[str] = None) -> dict:
    """Four-eyes: the approver is never anyone who created or edited the
    request. Approval records the family-allowance fund's decision, so its
    reference is required."""
    row = _entitlement(db, organization_id, entitlement_id)
    if row.status != "REQUESTED":
        raise BadRequestException(f"only a REQUESTED entitlement can be approved (this one is {row.status})")
    if actor_id is None or actor_id in _authors(db, "ch_family_allowance_entitlement", row.id):
        raise BadRequestException("the entitlement must be approved by a user other than its author or editors")
    if not row.fund_decision_reference:
        raise BadRequestException("approval records the fund's decision: fundDecisionReference is required")
    if row.entitlement_basis == "DIFFERENTIAL" and (row.precedence_evidence or {}).get("primary_amount") is None:
        raise BadRequestException("a DIFFERENTIAL entitlement needs the primary fund's amount before approval")
    row.status, row.approved_by_id = "APPROVED", actor_id
    db.flush()
    _ch_audit(db, actor_id, "approve", "ch_family_allowance_entitlement", row.id, old={"status": "REQUESTED"},
              new={"status": "APPROVED", "fundDecisionReference": row.fund_decision_reference}, reason=reason,
              correlation_id=correlation_id)
    return _entitlement_view(row)


# ── absence-benefit events ───────────────────────────────────────────────

_EVENT_FIELDS = (("periodTo", "period_to"), ("dailyAllowanceRate", "daily_allowance_rate"),
                 ("insuredSalaryBasis", "insured_salary_basis"), ("insurerClaimReference", "insurer_claim_reference"),
                 ("benefitAmountExpected", "benefit_amount_expected"),
                 ("benefitAmountReceived", "benefit_amount_received"),
                 ("employerTopupAmount", "employer_topup_amount"), ("evidenceDocumentId", "evidence_document_id"),
                 ("status", "status"))


def _event_view(row: ChAbsenceBenefitEvent) -> dict:
    def num(v):
        return str(v) if v is not None else None
    return {
        "id": row.id, "employeeId": row.employee_id, "eventType": row.event_type,
        "periodFrom": _iso(row.period_from), "periodTo": _iso(row.period_to),
        "dailyAllowanceRate": num(row.daily_allowance_rate), "insuredSalaryBasis": num(row.insured_salary_basis),
        "insurerClaimReference": row.insurer_claim_reference,
        "benefitAmountExpected": num(row.benefit_amount_expected),
        "benefitAmountReceived": num(row.benefit_amount_received),
        "employerTopupAmount": num(row.employer_topup_amount), "status": row.status,
        "evidenceDocumentId": row.evidence_document_id,
        "allowanceEarningType": CH_ABSENCE_ALLOWANCE_EARNING.get(row.event_type),
    }


def _event(db: Session, organization_id: int, event_id: int) -> ChAbsenceBenefitEvent:
    row = db.get(ChAbsenceBenefitEvent, event_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundException("Absence benefit event", event_id)
    return row


def list_absence_events(db: Session, organization_id: int, employee_id: Optional[int] = None) -> List[dict]:
    q = db.query(ChAbsenceBenefitEvent).filter(ChAbsenceBenefitEvent.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(ChAbsenceBenefitEvent.employee_id == employee_id)
    return [_event_view(r) for r in q.order_by(ChAbsenceBenefitEvent.period_from, ChAbsenceBenefitEvent.id)]


def get_absence_event(db: Session, organization_id: int, event_id: int) -> dict:
    return _event_view(_event(db, organization_id, event_id))


def create_absence_event(db: Session, organization_id: int, data, actor_id: Optional[int],
                         correlation_id: Optional[str] = None) -> dict:
    _org_employee(db, organization_id, data.employeeId)
    _check_source(db, data.evidenceDocumentId)
    row = ChAbsenceBenefitEvent(
        organization_id=organization_id, employee_id=data.employeeId, event_type=data.eventType,
        period_from=data.periodFrom, period_to=data.periodTo, daily_allowance_rate=data.dailyAllowanceRate,
        insured_salary_basis=data.insuredSalaryBasis, insurer_claim_reference=data.insurerClaimReference,
        benefit_amount_expected=data.benefitAmountExpected, benefit_amount_received=data.benefitAmountReceived,
        employer_topup_amount=data.employerTopupAmount, evidence_document_id=data.evidenceDocumentId, status="OPEN",
    )
    db.add(row)
    db.flush()
    _ch_audit(db, actor_id, "create", "ch_absence_benefit_event", row.id,
              new={"eventType": row.event_type, "employeeId": row.employee_id,
                   "periodFrom": _iso(row.period_from), "periodTo": _iso(row.period_to)},
              reason=data.reason, correlation_id=correlation_id)
    return _event_view(row)


def update_absence_event(db: Session, organization_id: int, event_id: int, data, actor_id: Optional[int],
                         correlation_id: Optional[str] = None) -> dict:
    row = _event(db, organization_id, event_id)
    if row.status != "OPEN":
        raise BadRequestException(f"absence event {row.id} is {row.status}; only an OPEN event can be edited")
    fields = data.model_fields_set - {"reason"}
    for attr, col in _EVENT_FIELDS:
        if attr in fields:
            if attr == "status" and data.status is None:
                raise BadRequestException("status cannot be empty")
            setattr(row, col, getattr(data, attr))
    if row.period_to is not None and row.period_to < row.period_from:
        raise BadRequestException("periodTo is before periodFrom")
    if CH_ABSENCE_ALLOWANCE_EARNING.get(row.event_type) is None and row.daily_allowance_rate is not None:
        raise BadRequestException(f"{row.event_type} carries no insurer daily allowance")
    _check_source(db, row.evidence_document_id)
    db.flush()
    _ch_audit(db, actor_id, "update", "ch_absence_benefit_event", row.id,
              new={"fields": sorted(fields), "status": row.status}, reason=data.reason, correlation_id=correlation_id)
    return _event_view(row)


def delete_absence_event(db: Session, organization_id: int, event_id: int, actor_id: Optional[int],
                         correlation_id: Optional[str] = None) -> dict:
    row = _event(db, organization_id, event_id)
    if row.status != "OPEN":
        raise BadRequestException(f"absence event {row.id} is {row.status}; only an OPEN event can be deleted")
    view = _event_view(row)
    _ch_audit(db, actor_id, "delete", "ch_absence_benefit_event", row.id, old={"eventType": row.event_type},
              correlation_id=correlation_id)
    db.delete(row)
    db.flush()
    return {**view, "deleted": True}


def absence_period_amounts(event: ChAbsenceBenefitEvent, period_start: date, period_end: date,
                           blocked: list) -> Optional[dict]:
    """The event's allowance and top-up for THIS period. Daily allowances are
    paid per calendar day of the event inside the period; the event's total
    employer top-up is apportioned by those days (so it needs a known end)."""
    start, end = max(period_start, event.period_from), min(period_end, event.period_to or period_end)
    if end < start:
        return None
    days = (end - start).days + 1
    allowance = ZERO_CHF
    if CH_ABSENCE_ALLOWANCE_EARNING.get(event.event_type) is not None:
        if event.daily_allowance_rate is None:
            _block(blocked, f"ch_absence_event:{event.id}",
                   f"{event.event_type} event has no daily allowance rate")
            return None
        allowance = Decimal(str(event.daily_allowance_rate)) * days
    topup = ZERO_CHF
    if event.employer_topup_amount:
        if event.period_to is None:
            _block(blocked, f"ch_absence_event:{event.id}",
                   "an employer top-up can only be apportioned once the event has an end date")
            return None
        event_days = (event.period_to - event.period_from).days + 1
        topup = (Decimal(str(event.employer_topup_amount)) * days / event_days).quantize(Decimal("0.01"))
    return {"event_id": event.id, "event_type": event.event_type, "days": days,
            "allowance": allowance, "topup": topup}


# ════════════════════════════════════════════════════════════════════════
# CH Step 12 — service wiring: rate map, calculation context, payslip
# snapshot, YTD posting, run-approval preflight + fingerprint, readiness
# gates and the Super Admin calculation preview.
# ════════════════════════════════════════════════════════════════════════

from types import SimpleNamespace  # noqa: E402

from app.modules.payroll.engine.countries.switzerland_content import (  # noqa: E402
    CH_ALV_PRORATION_RULE, CH_CANTONS,
)
from app.modules.payroll.models import (  # noqa: E402
    EmployeeStatutoryProfile, PayslipItem, SourceArtifact, TestCertificationRun,
)

# Flipped to True only once every ESTV_FIXED_WIDTH_V1_LAYOUT position is
# confirmed against the published ESTV specification (readiness gate G4).
ESTV_FIXED_WIDTH_V1_VERIFIED = False
CH_APPROVAL_ENTITY = "ch_run_approval"


def ch_rate_map(canonical_rates) -> dict:
    """The CH engine's rate_map: FEDERAL-pack rows only, keyed by
    component_key. Canton rows (jurisdiction_state set) never enter it —
    they reach the engine per canton through ch_canton_rate_maps."""
    return {r.component_key: r for r in canonical_rates or [] if r.jurisdiction_state is None}


def ch_earnings(basic, hra, special, overtime, additional_compensation, allowance_items=None) -> dict:
    """The payslip's salary components as CH earning types. Each must carry
    an Approved CH classification per obligation (the engine blocks
    otherwise); zero components are ignored by the engine."""
    earnings = {"base_salary": basic, "hra": hra, "special_allowance": special, "overtime": overtime,
                "additional_compensation": additional_compensation}
    for item in allowance_items or []:
        key = item["key"] if isinstance(item, dict) else getattr(item, "key")
        amount = item["amount"] if isinstance(item, dict) else getattr(item, "amount")
        earnings[key] = earnings.get(key, ZERO_CHF) + Decimal(str(amount))
    return {k: Decimal(str(v or 0)) for k, v in earnings.items()}


def _qst_treatments(db: Session, organization_id: int, on: date) -> dict:
    """{earning_type: PERIODIC | APERIODIC} from the Approved CH_QST rules in
    force (an org-specific rule wins over the platform one)."""
    rows = db.query(TaxabilityRule).filter(
        TaxabilityRule.jurisdiction_country == "CH", TaxabilityRule.tax_component == CH_QST,
        TaxabilityRule.status == "Approved",
        (TaxabilityRule.organization_id.is_(None)) | (TaxabilityRule.organization_id == organization_id),
        (TaxabilityRule.effective_from.is_(None)) | (TaxabilityRule.effective_from <= on),
        (TaxabilityRule.effective_to.is_(None)) | (TaxabilityRule.effective_to >= on)).all()
    out = {}
    for row in sorted(rows, key=lambda r: r.organization_id is None):
        if row.treatment:
            out.setdefault(row.earning_type, row.treatment)
    return out


def _blocked_error(key, reason, organization_id):
    from app.modules.payroll.engine.countries.switzerland import SwitzerlandCalculationBlockedError

    return SwitzerlandCalculationBlockedError(key, reason, organization_id)


def ch_calc_context(db: Session, organization_id: int, employee, payroll_date: date,
                    period_start: Optional[date], period_end: Optional[date], earnings: dict) -> dict:
    """Every ch_* context attribute the engine reads, for one payslip. A
    blocked resolver result RAISES SwitzerlandCalculationBlockedError (the
    MissingComplianceConfigurationError the run / preview already surface,
    same as Italy's blocks) — never a partial context."""
    from app.modules.payroll.engine.countries.switzerland import qst_lookup_incomes

    resolved = resolve_ch_calc_inputs(db, organization_id, employee, payroll_date, period_start, period_end)
    if resolved["blocked"]:
        blocks = resolved["blocked"]
        raise _blocked_error(blocks[0]["key"], "; ".join(f"{b['key']}: {b['reason']}" for b in blocks),
                             organization_id)
    i = resolved["inputs"]
    profile = db.get(EmployeeStatutoryProfile, i["workerProfileId"])
    schemes = i["schemes"]

    def scheme_rules(scheme_type):
        sid = schemes.get(scheme_type)
        return db.get(ChSchemeProfile, sid).rules if sid else None

    canton_maps = {}
    work = i["cantons"]["work"]
    pack_ids = {work: (i["workCantonPack"] or {}).get("id")}
    pack_ids.update({c: (p or {}).get("id") for c, p in i["fakCantonPacks"].items()})
    for canton, pack_id in pack_ids.items():
        if pack_id is not None:
            canton_maps[canton] = _pack_params(db, db.get(JurisdictionPack, pack_id), payroll_date)
    other_pct = profile.ch_other_employment_pct
    attrs = {
        "organization_id": organization_id, "payroll_date": payroll_date, "earnings": earnings, "ytd": i["ytd"],
        "ch_classification": i["taxability"], "ch_qst_treatment": _qst_treatments(db, organization_id, payroll_date),
        "ch_federal_pack_id": i["federalPack"]["id"], "ch_federal_pack_version": i["federalPack"]["version"],
        "ch_alv_proration_rule": CH_ALV_PRORATION_RULE,
        "ch_work_canton": work, "ch_canton_rate_maps": canton_maps,
        "ch_scheme_rules": scheme_rules("COMPENSATION_OFFICE"),
        "ch_fak_scheme_id": schemes.get("FAK"), "ch_fak_scheme_rules": scheme_rules("FAK"),
        "ch_bvg_plan_scheme_id": schemes.get("BVG_PLAN"), "ch_bvg_scheme_rules": scheme_rules("BVG_PLAN"),
        "ch_uvg_policy_scheme_id": schemes.get("UVG_POLICY"), "ch_uvg_scheme_rules": scheme_rules("UVG_POLICY"),
        "ch_uvg_risk_class": profile.ch_uvg_risk_class, "ch_weekly_hours": profile.ch_weekly_hours,
        "ch_annual_salary": getattr(employee, "ctc", None), "ch_date_of_birth": getattr(employee, "date_of_birth", None),
        # the profile stores a PERCENT (content convention); the engine wants a share 0..1
        "ch_multiple_employment": bool(profile.ch_multiple_employment),
        "ch_other_employment_pct": (Decimal(str(other_pct)) / 100) if other_pct is not None else None,
        "ch_occupation": profile.ch_occupation, "ch_grade": profile.ch_grade,
        "ch_experience_years": profile.ch_experience_years,
        "ch_wage_floor_agreements": i["wageFloorAgreements"],
        "ch_fak_entitlements": i["fakEntitlements"], "ch_absence_earnings": i["absenceEarnings"],
        "ch_children_count": profile.ch_children_count,
        "ch_qst_subject": i["qstSubject"],
    }
    if schemes.get("KTG_POLICY"):
        attrs.update(ch_ktg_policy_scheme_id=schemes["KTG_POLICY"], ch_ktg_scheme_rules=scheme_rules("KTG_POLICY"))
    qst = i.get("qst")
    if i["qstSubject"] == "YES" and qst:
        tariff = db.get(ChQstTariffFile, qst["tariffFileId"])
        attrs.update(ch_qst_canton=i["cantons"]["qst"], ch_qst_model=qst["model"],
                     ch_qst_tariff_code=qst["tariffCode"], ch_qst_tariff_file_id=tariff.id,
                     ch_qst_tariff_file_sha256=tariff.file_sha256, ch_qst_children=qst["children"],
                     ch_qst_church_tax=qst["churchTax"])
        incomes = qst_lookup_incomes(SimpleNamespace(rate_map={}, **attrs))
        for attr, income in (("ch_qst_rate", incomes["periodic"]), ("ch_qst_aperiodic_rate", incomes["aperiodic"])):
            if income is None:
                continue
            try:
                rate, min_tax, row_id = lookup_qst_rate(db, tariff.id, qst["tariffCode"], qst["children"],
                                                        qst["churchTax"], income)
            except (NotFoundException, BadRequestException) as exc:
                raise _blocked_error(attr, f"QST tariff lookup: {exc.detail}", organization_id)
            attrs[attr] = {"rate_pct": rate, "min_tax": min_tax, "row_id": row_id}
    return attrs


def apply_ch_context(ctx, attrs: dict) -> None:
    """Sets the resolved ch_* facts on a built PayrollContext (the same
    post-construction setattr pattern _compute_payslip_values already uses
    for Singapore's statutory month facts)."""
    for key, value in attrs.items():
        setattr(ctx, key, value)


def _json_safe(obj):
    return json.loads(json.dumps(obj, default=str))


def ch_payslip_snapshot(result, frozen: Optional[dict] = None) -> Optional[dict]:
    """PayslipItem.ch_calculation_snapshot for a Swiss result (None for every
    other country): the totals a report reads, every per-obligation amount
    (totalsAll, what a correction diffs against), the engine trace verbatim
    and — for a persisted payslip — the frozen calculation context a
    correction replays (Step 13)."""
    r = getattr(result, "ch_result", None)
    if not r:
        return None
    keys = ("ch_employee_total", "ch_employer_total", "ch_family_allowance_total", "ch_absence_earnings_total",
            "ch_qst_total", "ch_bvg_employee", "ch_bvg_employer", "ch_fak_employer", "ch_fak_employee")
    snap = {"totals": {k: r.get(k) for k in keys}, "totalsAll": _ch_totals_all(r),
            "trace": r.get("ch_calculation_trace")}
    if frozen is not None:
        snap["frozenContext"] = frozen
    return _json_safe(snap)


def post_ch_payslip_ytd(db: Session, employee_id: int, result, year: int, payslip_id: Optional[int]) -> None:
    """Persist exactly the running totals the engine reported (never a
    recomputation): ABSOLUTE writes to PayrollYtdAccumulator, so the shared
    ytdPostings lifecycle records them and reverses them if the payslip is
    regenerated or deleted — a regenerate re-posts, it never adds twice."""
    after = (((getattr(result, "ch_result", None) or {}).get("ch_calculation_trace") or {})
             .get("accumulators_after") or {})
    key = ch_tax_year_key(year)
    for component, totals in after.items():
        row = (db.query(PayrollYtdAccumulator)
               .filter(PayrollYtdAccumulator.employee_id == employee_id, PayrollYtdAccumulator.tax_year == key,
                       PayrollYtdAccumulator.tax_component == component).first())
        if row is None:
            row = PayrollYtdAccumulator(employee_id=employee_id, tax_year=key, tax_component=component,
                                        ytd_taxable_wages=ZERO_CHF, ytd_tax_withheld=ZERO_CHF)
            db.add(row)
        row.ytd_taxable_wages = Decimal(str(totals["wages"]))
        row.ytd_tax_withheld = Decimal(str(totals["withheld"]))
        row.last_updated_payslip_id = payslip_id
    db.flush()


# ── run approval: preflight + fingerprint ────────────────────────────────

def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def ch_run_items(db: Session, run) -> list:
    return (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == "CH")
            .order_by(PayslipItem.id).all())


def ch_run_preflight(db: Session, run) -> list:
    """Every resolver check for every CH payslip of the run, re-run now:
    [{employeeId, key, reason}] — empty means approvable."""
    blocks = []
    for item in ch_run_items(db, run):
        employee = db.get(PayrollEmployee, item.employee_id)
        out = resolve_ch_calc_inputs(db, run.organization_id, employee, run.pay_date, run.period_start, run.period_end)
        blocks += [{"employeeId": item.employee_id, **b} for b in out["blocked"]]
    return blocks


def ch_approval_fingerprint(db: Session, run) -> dict:
    """What a CH approval is bound to: the resolved inputs (YTD excluded — it
    legitimately moves when a LATER period posts; this run's own before/after
    figures are inside its payslip snapshots), the engine rule hashes, the
    scheme versions applied, and the payslip values."""
    inputs, rule_hashes, scheme_versions, payslips = [], [], [], []
    for item in ch_run_items(db, run):
        employee = db.get(PayrollEmployee, item.employee_id)
        out = resolve_ch_calc_inputs(db, run.organization_id, employee, run.pay_date, run.period_start, run.period_end)
        inputs.append([item.employee_id, out["blocked"], {k: v for k, v in out["inputs"].items() if k != "ytd"}])
        for scheme_id in sorted(v for v in out["inputs"]["schemes"].values() if v):
            s = db.get(ChSchemeProfile, scheme_id)
            scheme_versions.append([item.employee_id, s.id, s.scheme_code, s.version, s.status, s.rules_sha256])
        trace = (item.ch_calculation_snapshot or {}).get("trace") or {}
        rule_hashes.append([item.id, trace.get("input_hash"), trace.get("rule_hash")])
        payslips.append([item.id, item.employee_id, item.gross_pay, item.net_pay, item.total_deductions,
                         item.ch_calculation_snapshot])
    components = {"inputs": _digest(inputs), "ruleHashes": _digest(rule_hashes),
                  "schemeVersions": _digest(scheme_versions), "payslips": _digest(payslips)}
    return {"fingerprint": _digest(components), "components": components}


def ch_stored_approval(db: Session, run) -> Optional[dict]:
    row = (db.query(TaxConfigurationAudit)
           .filter(TaxConfigurationAudit.entity_type == CH_APPROVAL_ENTITY, TaxConfigurationAudit.entity_id == run.id)
           .order_by(TaxConfigurationAudit.id.desc()).first())
    return None if row is None or row.action != "create" else row.new_value


# ── Super Admin: readiness gates + calculation preview ──────────────────

def _canton_status(db: Session, canton: str, name: str, on: date, federal_params: dict) -> dict:
    pack = _active_pack(db, canton, on)
    params = _pack_params(db, pack, on)

    def amount(key):
        row = params.get(key)
        return row.flat_amount if row is not None else None

    def text(key):
        row = params.get(key)
        return (row.text_value or "").strip() or None if row is not None else None

    model, file_id = text("ch_qst_model"), text("ch_qst_tariff_file_id")
    tariff = db.get(ChQstTariffFile, int(file_id)) if file_id and file_id.isdigit() else None
    fak = {}
    for allowance, (canton_key, min_key) in (("child", ("ch_fak_child", "ch_fak_child_min")),
                                             ("education", ("ch_fak_education", "ch_fak_education_min"))):
        value, minimum = amount(canton_key), federal_params.get(min_key)
        minimum = minimum.flat_amount if minimum is not None else None
        fak[allowance] = {"amount": value, "federalMinimum": minimum,
                          "aboveMinimum": value is not None and minimum is not None and value >= minimum}
    tariff_ok = (tariff is not None and tariff.canton == canton and tariff.status == "ACTIVE"
                 and _in_force(tariff.effective_from, tariff.effective_to, on))
    ready = (pack is not None and model in CH_QST_MODELS and tariff_ok
             and all(f["aboveMinimum"] for f in fak.values()))
    return {"canton": canton, "name": name, "packId": pack.id if pack else None,
            "packVersion": pack.version if pack else None, "qstModel": model,
            "annualModel": canton in CH_QST_ANNUAL_MODEL_CANTONS,
            "tariffFileId": tariff.id if tariff else None, "tariffFileStatus": tariff.status if tariff else None,
            "fak": fak, "ready": ready}


def get_ch_readiness(db: Session, on: Optional[date] = None) -> dict:
    """Super Admin release gates G1-G7 for Switzerland, plus the per-canton
    status — read-only and re-derived from the database on every call.
    Switzerland is never ready because content merely exists."""
    from app.modules.payroll.service import _check_missing_required_keys

    on = on or date.today()
    gates = []

    def add(key, label, complete, detail):
        gates.append({"key": key, "label": label, "complete": bool(complete), "detail": detail})

    federal = _active_pack(db, None, on)
    candidate = federal or (db.query(JurisdictionPack).filter(
        JurisdictionPack.jurisdiction_country == "CH", JurisdictionPack.jurisdiction_state.is_(None))
        .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first())
    source = db.get(SourceArtifact, candidate.source_document_id) if candidate and candidate.source_document_id else None
    reviewed = bool(source and source.reviewer_approved_at)
    add("G1", "G1 — federal statutory content independently reviewed (every value needs_g1)", reviewed,
        "Reviewed." if reviewed else ("Link and review the federal pack's source evidence."
                                      if candidate else "No CH federal pack exists."))
    federal_params = _pack_params(db, federal, on)
    missing = [m["key"] for m in _check_missing_required_keys(federal_params, [], "CH")] if federal else []
    add("G2", "G2 — federal pack Active, approved by a distinct Super Admin, every required parameter set",
        federal is not None and federal.approved_by_id is not None and not missing,
        ("No Active federal pack in force." if federal is None else
         "Missing: " + ", ".join(missing) if missing else
         "Not approved by a distinct Super Admin." if federal.approved_by_id is None else
         f"{federal.pack_id} v{federal.version} Active."))
    cantons = [_canton_status(db, code, name, on, federal_params) for code, name in CH_CANTONS]
    not_ready = [c["canton"] for c in cantons if not c["ready"]]
    add("G3", "G3 — every canton pack Active: QST model, ACTIVE tariff file, FAK amounts >= federal minimum",
        not not_ready, "All 26 cantons ready." if not not_ready else f"Not ready: {', '.join(not_ready)}")
    annual_in_use = sorted(c["canton"] for c in cantons if c["qstModel"] == "ANNUAL")
    add("G4", "G4 — QST tariff ingestion verified (ESTV layout confirmed; annual model G1-signed)",
        ESTV_FIXED_WIDTH_V1_VERIFIED and not annual_in_use,
        ("ESTV_FIXED_WIDTH_V1 field positions are unverified (VERIFY AGAINST ESTV SPEC). "
         if not ESTV_FIXED_WIDTH_V1_VERIFIED else "")
        + (f"Annual-model arithmetic is PENDING G1 SIGN-OFF for {', '.join(annual_in_use)}."
           if annual_in_use else "No annual-model canton configured yet."))
    unclassified = [c for c in CH_TAXABILITY_COMPONENTS if c != CH_WAGE_FLOOR
                    and not db.query(TaxabilityRule).filter(
                        TaxabilityRule.jurisdiction_country == "CH", TaxabilityRule.tax_component == c,
                        TaxabilityRule.organization_id.is_(None), TaxabilityRule.status == "Approved").first()]
    add("G5", "G5 — Approved earning classification for every CH obligation", not unclassified,
        "Missing: " + ", ".join(unclassified) if unclassified else "Every obligation classified.")
    latest = (db.query(TestCertificationRun).filter(TestCertificationRun.jurisdiction_country == "CH")
              .order_by(TestCertificationRun.run_at.desc(), TestCertificationRun.id.desc()).first())
    add("G6", "G6 — golden-vector certification PASS", latest is not None and latest.status == "PASS",
        f"Latest run #{latest.id}: {latest.status}" if latest else "No CH certification run recorded.")
    add("G7", "G7 — ELM transmission and two reconciled parallel payroll cycles", False,
        "ELM generation is not built; parallel-run evidence is required from the implementation team.")
    blockers = [f"{g['label']}: {g['detail']}" for g in gates if not g["complete"]]
    return {"onDate": on.isoformat(), "ready": not blockers, "gates": gates, "cantons": cantons,
            "blockers": blockers}


def preview_ch_calculation(db: Session, data) -> dict:
    """Read-only Super Admin simulation for one real CH employee: the SAME
    resolver and production engine a payroll run uses. Writes nothing; a
    blocked calculation returns its reason, never a figure."""
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll

    employee = db.get(PayrollEmployee, data.employeeId)
    if employee is None or employee.organization_id != data.organizationId:
        raise NotFoundException("Employee", data.employeeId)
    on = data.payDate
    period_start, period_end = data.periodStart or on.replace(day=1), data.periodEnd or on
    earnings = ({k: Decimal(str(v)) for k, v in data.earnings.items()} if data.earnings else
                {"base_salary": (Decimal(str(employee.ctc or 0)) / 12).quantize(Decimal("0.01"))})
    federal = _active_pack(db, None, on)
    base = {"employeeId": employee.id, "payDate": on.isoformat(), "readOnly": True,
            "federalPack": {"id": federal.id, "packId": federal.pack_id, "version": federal.version} if federal else None}
    try:
        if federal is None:
            raise _blocked_error("ch_federal_pack", f"no Active federal CH pack is in force on {on.isoformat()}",
                                 data.organizationId)
        attrs = ch_calc_context(db, data.organizationId, employee, on, period_start, period_end, earnings)
        gross = sum(earnings.values(), ZERO_CHF)
        ctx = PayrollContext(gross=gross, basic=earnings.get("base_salary", ZERO_CHF), country="CH",
                             pay_frequency="Monthly", pay_date=on, rate_map=_pack_params(db, federal, on), slabs=[])
        apply_ch_context(ctx, attrs)
        result = calculate_payroll(ctx, "standard")
    except MissingComplianceConfigurationError as exc:
        return {**base, "blocked": True, "blockedKey": exc.key, "blockedReason": getattr(exc, "reason", None) or str(exc)}
    return {**base, "blocked": False,
            "result": {"gross": str(result.gross), "totalDeductions": str(result.total_deductions),
                       "netPay": str(result.net_pay)},
            "switzerland": ch_payslip_snapshot(result)}


# ════════════════════════════════════════════════════════════════════════
# CH Step 13 — corrections (append-only) and QST tariff-correction impact.
#
# Every CH payslip freezes the COMPLETE calculation context it was computed
# from (frozenContext in ch_calculation_snapshot: federal and canton rows,
# schemes, classification, YTD before, the tariff rows, the earnings). A
# correction replays that frozen context — never a pack, tariff or scheme
# resolved today — so content published later (a 2027 pack, a corrected
# tariff file) can never leak into a 2026 calculation. The original payslip
# is never modified: the correction is a delta payslip in its own run.
# ════════════════════════════════════════════════════════════════════════

CH_CORRECTION_MARKER = "[CH-CORRECTION]"
_CH_FINALIZED_RUN_STATUSES = ("Approved", "Authorized", "Paid", "Closed")
_CH_DATE_KEYS = ("payroll_date", "pay_date", "ch_date_of_birth")
_CH_CTX_SCALARS = ("gross", "basic", "hra", "special_allowance", "overtime", "additional_compensation")
_CH_CTX_INTS = ("unpaid_leave_days", "payroll_days", "calendar_days")
# Inputs a correction may restate. Anything else is refused: rules, rates and
# scheme content are never "corrected" through a payslip correction.
CH_CORRECTABLE_INPUTS = (
    "earnings", "ch_weekly_hours", "ch_uvg_risk_class", "ch_annual_salary", "ch_date_of_birth",
    "ch_multiple_employment", "ch_other_employment_pct", "ch_occupation", "ch_grade", "ch_experience_years",
    "ch_fak_entitlements", "ch_absence_earnings", "ch_qst_subject", "ch_qst_tariff_code", "ch_qst_children",
    "ch_qst_church_tax", "ch_qst_tariff_file_id", "ch_period_hours",
)
_CH_QST_LOOKUP_INPUTS = ("earnings", "ch_qst_tariff_code", "ch_qst_children", "ch_qst_church_tax",
                         "ch_qst_tariff_file_id", "ch_multiple_employment", "ch_other_employment_pct",
                         "ch_absence_earnings")
# obligation -> the engine result keys that carry it (employee / employer)
CH_CORRECTION_OBLIGATIONS = {
    "ch_ahv": ("ch_ahv_employee", "ch_ahv_employer"),
    "ch_iv": ("ch_iv_employee", "ch_iv_employer"),
    "ch_eo": ("ch_eo_employee", "ch_eo_employer"),
    "ch_alv": ("ch_alv_employee", "ch_alv_employer"),
    "ch_bvg": ("ch_bvg_employee", "ch_bvg_employer"),
    "ch_uvg": ("ch_uvg_employee", "ch_uvg_employer"),
    "ch_ktg": ("ch_ktg_employee", "ch_ktg_employer"),
    "ch_qst": ("ch_qst_total", None),
    "ch_fak": ("ch_fak_employee", "ch_fak_employer"),
    "ch_admin": (None, "ch_admin_cost_employer"),
    "ch_family_allowance": ("ch_family_allowance_total", None),
    "ch_absence": ("ch_absence_earnings_total", None),
}
_CH_DELTA_COLUMNS = ("gross_pay", "total_deductions", "net_pay")
# ELM domain an obligation is declared under (VERIFY against the ELM 5.x
# domain list when ELM generation is built).
_CH_ELM_DOMAINS = {"ch_ahv": "AHV", "ch_iv": "AHV", "ch_eo": "AHV", "ch_alv": "AHV", "ch_qst": "QST",
                   "ch_fak": "FAK", "ch_family_allowance": "FAK", "ch_uvg": "UVG", "ch_ktg": "KTG"}


def _row_freeze(row) -> dict:
    return {k: (str(getattr(row, k)) if getattr(row, k, None) is not None else None)
            for k in ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value")}


def _row_thaw(view: dict):
    def dec(v):
        return Decimal(v) if v is not None else None
    return SimpleNamespace(employee_rate_pct=dec(view.get("employee_rate_pct")),
                           employer_rate_pct=dec(view.get("employer_rate_pct")),
                           flat_amount=dec(view.get("flat_amount")), text_value=view.get("text_value"))


def ch_freeze_context(ctx, attrs: dict, calculation_mode: str = "standard") -> dict:
    """JSON-safe, COMPLETE calculation context of one CH payslip — enough to
    replay it later with no database lookup of packs, tariffs or schemes."""
    frozen_attrs = dict(attrs)
    frozen_attrs["ch_canton_rate_maps"] = {c: {k: _row_freeze(r) for k, r in m.items()}
                                           for c, m in (attrs.get("ch_canton_rate_maps") or {}).items()}
    return _json_safe({
        "version": 1, "calculationMode": calculation_mode,
        "ctx": {**{k: getattr(ctx, k, None) for k in _CH_CTX_SCALARS + _CH_CTX_INTS},
                "pay_frequency": getattr(ctx, "pay_frequency", None), "pay_date": getattr(ctx, "pay_date", None)},
        "rateMap": {k: _row_freeze(r) for k, r in (getattr(ctx, "rate_map", None) or {}).items()},
        "attrs": frozen_attrs,
    })


def _thaw_value(key, value):
    if key in _CH_DATE_KEYS and isinstance(value, str):
        return date.fromisoformat(value[:10])
    return value


def ch_thaw_context(frozen: dict):
    """A PayrollContext rebuilt from a frozen context (see ch_freeze_context)."""
    from app.modules.payroll.engine.base import PayrollContext

    c = frozen["ctx"]
    ctx = PayrollContext(
        gross=Decimal(c["gross"]), basic=Decimal(c["basic"]), country="CH",
        rate_map={k: _row_thaw(v) for k, v in frozen["rateMap"].items()}, slabs=[],
        pay_frequency=c.get("pay_frequency") or "Monthly", pay_date=_thaw_value("pay_date", c.get("pay_date")))
    for k in _CH_CTX_SCALARS[2:]:
        setattr(ctx, k, Decimal(c[k]) if c.get(k) is not None else ZERO_CHF)
    for k in _CH_CTX_INTS:
        if c.get(k) is not None:
            setattr(ctx, k, int(c[k]))
    attrs = {k: _thaw_value(k, v) for k, v in frozen["attrs"].items()}
    attrs["ch_canton_rate_maps"] = {cn: {k: _row_thaw(v) for k, v in m.items()}
                                    for cn, m in (attrs.get("ch_canton_rate_maps") or {}).items()}
    attrs["earnings"] = {k: Decimal(str(v)) for k, v in (attrs.get("earnings") or {}).items()}
    apply_ch_context(ctx, attrs)
    return ctx


def ch_replay(frozen: dict):
    """Re-run the production engine on a frozen context (no DB reads)."""
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(ch_thaw_context(frozen), frozen.get("calculationMode") or "standard")


def _ch_metrics(r: dict) -> dict:
    out = {}
    for obligation, (ee_key, er_key) in CH_CORRECTION_OBLIGATIONS.items():
        out[obligation] = {"employee": Decimal(str(r.get(ee_key) or 0)) if ee_key else ZERO_CHF,
                           "employer": Decimal(str(r.get(er_key) or 0)) if er_key else ZERO_CHF}
    return out


def _ch_accumulators(snapshot: dict) -> dict:
    after = ((snapshot or {}).get("trace") or {}).get("accumulators_after") or {}
    return {c: {"wages": Decimal(str(v["wages"])), "withheld": Decimal(str(v["withheld"]))} for c, v in after.items()}


def _ch_correction_chain(db: Session, original: PayslipItem) -> list:
    return [i for i in db.query(PayslipItem).filter(PayslipItem.employee_id == original.employee_id,
                                                    PayslipItem.country_code == "CH").order_by(PayslipItem.id).all()
            if ((i.ch_calculation_snapshot or {}).get("correction") or {}).get("originalPayslipId") == original.id]


def is_ch_correction_run(run) -> bool:
    return bool(run is not None and (run.notes or "").startswith(CH_CORRECTION_MARKER))


def _apply_corrected_inputs(db: Session, frozen: dict, corrected: dict, organization_id: int) -> dict:
    unknown = sorted(set(corrected) - set(CH_CORRECTABLE_INPUTS))
    if unknown:
        raise BadRequestException(f"not correctable through a payslip correction: {unknown} "
                                  f"(allowed: {list(CH_CORRECTABLE_INPUTS)})")
    new = json.loads(json.dumps(frozen))
    for key, value in corrected.items():
        if key == "earnings":
            if not isinstance(value, dict):
                raise BadRequestException("earnings must be {earning_type: amount}")
            new["attrs"]["earnings"] = {**new["attrs"].get("earnings", {}),
                                        **{k: str(Decimal(str(v))) for k, v in value.items()}}
            new["ctx"]["gross"] = str(sum((Decimal(str(v)) for v in new["attrs"]["earnings"].values()), ZERO_CHF))
            if "base_salary" in value:
                new["ctx"]["basic"] = str(Decimal(str(value["base_salary"])))
        else:
            new["attrs"][key] = _json_safe(value)
    attrs = new["attrs"]
    if attrs.get("ch_qst_subject") == "YES" and set(corrected) & set(_CH_QST_LOOKUP_INPUTS):
        # the tariff row follows the restated facts — looked up on the FILE the
        # payslip names (an ACTIVE or a SUPERSEDED one, replayable by id)
        from app.modules.payroll.engine.countries.switzerland import qst_lookup_incomes

        ctx = ch_thaw_context(new)
        incomes = qst_lookup_incomes(ctx)
        file_id = attrs.get("ch_qst_tariff_file_id")
        tariff = db.get(ChQstTariffFile, int(file_id)) if file_id is not None else None
        if tariff is None or tariff.canton != attrs.get("ch_qst_canton"):
            raise BadRequestException(f"QST tariff file {file_id} is not a file of {attrs.get('ch_qst_canton')}")
        attrs["ch_qst_tariff_file_sha256"] = tariff.file_sha256
        for attr, income in (("ch_qst_rate", incomes["periodic"]), ("ch_qst_aperiodic_rate", incomes["aperiodic"])):
            attrs.pop(attr, None)
            if income is None:
                continue
            rate, min_tax, row_id = lookup_qst_rate(db, tariff.id, attrs.get("ch_qst_tariff_code"),
                                                    attrs.get("ch_qst_children"), attrs.get("ch_qst_church_tax"), income)
            attrs[attr] = _json_safe({"rate_pct": rate, "min_tax": min_tax, "row_id": row_id})
    return new


def create_ch_correction(db: Session, organization_id: int, original_payslip_id: int, reason: str,
                         affected_obligations: list, corrected_inputs: Optional[dict], actor_id: Optional[int],
                         idempotency_key: Optional[str] = None, correlation_id: Optional[str] = None) -> dict:
    """Append-only correction of a finalized CH payslip: replay its frozen
    context with the restated inputs, book the per-obligation delta as a new
    payslip in a correction run, post the YTD deltas, link ELM corrections.
    Flushes only; the route commits through ch_write."""
    from app.modules.payroll.models import ChElmSubmission, PayrollRun, PayslipStatus
    from app.modules.payroll.service import _ytd_capture_state, _ytd_record_postings

    if not (reason or "").strip():
        raise BadRequestException("A correction needs a reason.")
    obligations = sorted(set(affected_obligations or []))
    if not obligations or set(obligations) - set(CH_CORRECTION_OBLIGATIONS):
        raise BadRequestException(f"affectedObligations must name one or more of {sorted(CH_CORRECTION_OBLIGATIONS)}")
    item = db.query(PayslipItem).filter(PayslipItem.id == original_payslip_id,
                                        PayslipItem.organization_id == organization_id).first()
    if item is None:
        raise NotFoundException("Payslip", original_payslip_id)
    if (item.country_code or "").upper() != "CH":
        raise BadRequestException("CH corrections apply to Swiss payslips only.")
    snapshot = item.ch_calculation_snapshot or {}
    if snapshot.get("correction"):
        raise BadRequestException("Correct the original payslip, not a correction delta.")
    run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).with_for_update().one()
    if str(getattr(run.status, "value", run.status)) not in _CH_FINALIZED_RUN_STATUSES:
        raise BadRequestException("This payslip's run is not finalized — recalculate it in place instead.")
    frozen = snapshot.get("frozenContext")
    if not frozen:
        raise BadRequestException("This payslip has no frozen calculation context, so it cannot be replayed exactly.")

    # 1. integrity: the frozen context must reproduce the original exactly
    original_trace = snapshot.get("trace") or {}
    replay = (ch_replay(frozen).ch_result or {}).get("ch_calculation_trace") or {}
    if (replay.get("input_hash"), replay.get("rule_hash")) != (original_trace.get("input_hash"),
                                                              original_trace.get("rule_hash")):
        raise BadRequestException("Replaying the frozen context does not reproduce the original payslip — refusing "
                                  "to correct on a drifted basis.")

    # 2. restate on the LATEST basis of the chain (earlier corrections stay applied)
    chain = _ch_correction_chain(db, item)
    basis = (chain[-1].ch_calculation_snapshot or {}).get("frozenContext") if chain else frozen
    new_frozen = _apply_corrected_inputs(db, basis, corrected_inputs or {}, organization_id)
    result = ch_replay(new_frozen)
    new_r = result.ch_result
    new_trace = new_r.get("ch_calculation_trace") or {}

    # 3. per-obligation delta against the effective position: each link of the
    #    chain stores its FULL corrected totals (totalsAll), so the effective
    #    totals are the latest link's; its columns / YTD carry deltas, summed.
    base_totals = ((chain[-1].ch_calculation_snapshot or {}) if chain else snapshot).get("totalsAll") or {}
    effective = _ch_metrics(base_totals)
    effective_cols = {c: Decimal(str(getattr(item, c) or 0)) for c in _CH_DELTA_COLUMNS}
    effective_acc = _ch_accumulators(snapshot)
    for c in chain:
        cs = c.ch_calculation_snapshot or {}
        for col in _CH_DELTA_COLUMNS:
            effective_cols[col] += Decimal(str(getattr(c, col) or 0))
        for comp, v in ((cs.get("correction") or {}).get("ytdDelta") or {}).items():
            acc = effective_acc.setdefault(comp, {"wages": ZERO_CHF, "withheld": ZERO_CHF})
            acc["wages"] += Decimal(v["wages"])
            acc["withheld"] += Decimal(v["withheld"])
    after = _ch_metrics(new_r)
    delta = {ob: {side: after[ob][side] - effective[ob][side] for side in ("employee", "employer")}
             for ob in CH_CORRECTION_OBLIGATIONS}
    changed = sorted(ob for ob, sides in delta.items() if any(sides.values()))
    if not changed:
        raise BadRequestException("The corrected inputs produce no change — nothing to correct.")
    undeclared = sorted(set(changed) - set(obligations))
    if undeclared:
        raise BadRequestException(f"The correction also changes {undeclared}, which affectedObligations does not "
                                  "declare — declare every affected obligation.")
    new_cols = {"gross_pay": result.gross, "total_deductions": result.total_deductions, "net_pay": result.net_pay}
    col_delta = {c: Decimal(str(new_cols[c])) - effective_cols[c] for c in _CH_DELTA_COLUMNS}
    new_acc = _ch_accumulators({"trace": new_trace})
    ytd_delta = {comp: {"wages": new_acc[comp]["wages"] - effective_acc.get(comp, {}).get("wages", ZERO_CHF),
                        "withheld": new_acc[comp]["withheld"] - effective_acc.get(comp, {}).get("withheld", ZERO_CHF)}
                 for comp in new_acc}
    ytd_delta = {c: v for c, v in ytd_delta.items() if v["wages"] or v["withheld"]}

    fmt = lambda d: {ob: {s: str(v) for s, v in sides.items()} for ob, sides in d.items()}  # noqa: E731
    correction = {
        "originalPayslipId": item.id, "originalRunId": run.id, "sequence": len(chain) + 1,
        "reason": reason.strip(), "obligations": obligations, "changedObligations": changed,
        "originalRuleHash": original_trace.get("rule_hash"), "newRuleHash": new_trace.get("rule_hash"),
        "originalInputHash": original_trace.get("input_hash"), "newInputHash": new_trace.get("input_hash"),
        "correctedInputs": _json_safe(corrected_inputs or {}),
        "before": fmt(effective), "after": fmt(after), "delta": fmt(delta),
        "columnDelta": {c: str(v) for c, v in col_delta.items()},
        "ytdDelta": {c: {"wages": str(v["wages"]), "withheld": str(v["withheld"])} for c, v in ytd_delta.items()},
        "actorId": actor_id, "idempotencyKey": idempotency_key, "correlationId": correlation_id,
        "at": datetime.utcnow().replace(microsecond=0).isoformat(),
    }
    delta_totals = {key: str(Decimal(str(new_r.get(key) or 0)) - Decimal(str(base_totals.get(key) or 0)))
                    for key in base_totals}
    corr_run = PayrollRun(organization_id=organization_id,
                          period_label=f"Correction {correction['sequence']} of {run.period_label}"[:50],
                          period_start=run.period_start, period_end=run.period_end, pay_date=run.pay_date,
                          notes=f"{CH_CORRECTION_MARKER} original run {run.id}, payslip {item.id}: {reason.strip()}"[:2000],
                          created_by=actor_id, calculation_mode=run.calculation_mode)
    db.add(corr_run)
    db.flush()
    delta_item = PayslipItem(
        payroll_run_id=corr_run.id, employee_id=item.employee_id, organization_id=organization_id,
        employee_name=item.employee_name, country_code="CH", status=PayslipStatus.PENDING,
        compliance_fields=item.compliance_fields, tax_policy_version=item.tax_policy_version,
        tax_rule_snapshot=item.tax_rule_snapshot, notes=f"Correction delta of payslip {item.id}",
        ch_calculation_snapshot=_json_safe({"correction": correction, "totals": delta_totals,
                                            "totalsAll": _ch_totals_all(new_r), "trace": new_trace,
                                            "frozenContext": new_frozen}),
        **col_delta,
    )
    pre = _ytd_capture_state(db, item.employee_id, organization_id)
    db.add(delta_item)
    db.flush()
    _post_ch_ytd_delta(db, item.employee_id, run.pay_date.year, ytd_delta, delta_item.id)
    _ytd_record_postings(db, delta_item, pre)

    # 4. ELM: a correction envelope for every submission of the affected domains
    domains = sorted({_CH_ELM_DOMAINS[ob] for ob in changed if ob in _CH_ELM_DOMAINS})
    period_key = run.period_start.strftime("%Y-%m") if run.period_start else None
    elm_links = []
    for original_sub in (db.query(ChElmSubmission).filter(
            ChElmSubmission.organization_id == organization_id, ChElmSubmission.period_key == period_key,
            ChElmSubmission.domain.in_(domains or ["-"]), ChElmSubmission.correction_of_id.is_(None))
            .order_by(ChElmSubmission.id)):
        sub = ChElmSubmission(
            organization_id=organization_id, domain=original_sub.domain, receiver_id=original_sub.receiver_id,
            canton=original_sub.canton, schema_version=original_sub.schema_version, period_key=period_key,
            transport_status="NOT_SENT", correction_of_id=original_sub.id,
            idempotency_key=hashlib.sha256(f"ch-correction:{delta_item.id}:{original_sub.id}".encode()).hexdigest(),
            actor_id=actor_id, correlation_id=correlation_id)
        db.add(sub)
        db.flush()
        elm_links.append({"submissionId": sub.id, "correctionOfId": original_sub.id, "domain": sub.domain})

    later = [p.id for p in db.query(PayslipItem).join(PayrollRun, PayrollRun.id == PayslipItem.payroll_run_id).filter(
        PayslipItem.employee_id == item.employee_id, PayslipItem.country_code == "CH",
        PayrollRun.pay_date > run.pay_date, PayrollRun.pay_date <= date(run.pay_date.year, 12, 31)).all()
        if not (p.ch_calculation_snapshot or {}).get("correction")]
    _ch_audit(db, actor_id, "create", "ch_payslip_correction", delta_item.id,
              old={"originalPayslipId": item.id, "before": correction["before"]},
              new={"after": correction["after"], "delta": correction["delta"], "elm": elm_links},
              reason=reason.strip(), correlation_id=correlation_id)
    return {"correctionRunId": corr_run.id, "deltaPayslipId": delta_item.id, "originalPayslipId": item.id,
            "sequence": correction["sequence"], "delta": correction["delta"], "changedObligations": changed,
            "columnDelta": correction["columnDelta"], "ytdDelta": correction["ytdDelta"],
            "originalRuleHash": correction["originalRuleHash"], "newRuleHash": correction["newRuleHash"],
            "elmCorrections": elm_links,
            # later payslips of the year built on the corrected YTD: listed, never auto-recalculated
            "laterPayslipsNotRecalculated": later}


def _ch_totals_all(r: dict) -> dict:
    keys = {k for keys in CH_CORRECTION_OBLIGATIONS.values() for k in keys if k} | {"ch_employee_total",
                                                                                      "ch_employer_total"}
    return {k: str(r.get(k) or 0) for k in sorted(keys)}


def _post_ch_ytd_delta(db: Session, employee_id: int, year: int, ytd_delta: dict, payslip_id: int) -> None:
    """ADDITIVE: a correction changes a period that later periods may already
    have built on, so the delta is added to today's totals (never an absolute
    overwrite). Recorded as this delta payslip's own postings."""
    key = ch_tax_year_key(year)
    for component, d in ytd_delta.items():
        row = (db.query(PayrollYtdAccumulator)
               .filter(PayrollYtdAccumulator.employee_id == employee_id, PayrollYtdAccumulator.tax_year == key,
                       PayrollYtdAccumulator.tax_component == component).first())
        if row is None:
            row = PayrollYtdAccumulator(employee_id=employee_id, tax_year=key, tax_component=component,
                                        ytd_taxable_wages=ZERO_CHF, ytd_tax_withheld=ZERO_CHF)
            db.add(row)
        row.ytd_taxable_wages = Decimal(str(row.ytd_taxable_wages or 0)) + d["wages"]
        row.ytd_tax_withheld = Decimal(str(row.ytd_tax_withheld or 0)) + d["withheld"]
        row.last_updated_payslip_id = payslip_id
    db.flush()


def list_ch_corrections(db: Session, organization_id: int, payslip_id: int) -> list:
    item = db.query(PayslipItem).filter(PayslipItem.id == payslip_id,
                                        PayslipItem.organization_id == organization_id).first()
    if item is None:
        raise NotFoundException("Payslip", payslip_id)
    return [{"deltaPayslipId": c.id, "correctionRunId": c.payroll_run_id,
             **{k: v for k, v in ((c.ch_calculation_snapshot or {}).get("correction") or {}).items()
                if k not in ("idempotencyKey",)}}
            for c in _ch_correction_chain(db, item)]


# ── QST tariff correction: list what it affects, never recalculate ───────

def qst_tariff_affected_payslips(db: Session, tariff_file_id: int) -> dict:
    """Every CH payslip calculated on this tariff file, grouped into the
    months a correction would concern. Read-only: nothing is recalculated —
    each affected payslip is corrected deliberately (create_ch_correction)."""
    from app.modules.payroll.models import PayrollRun

    tariff = _get(db, tariff_file_id)
    affected = []
    rows = (db.query(PayslipItem, PayrollRun).join(PayrollRun, PayrollRun.id == PayslipItem.payroll_run_id)
            .filter(PayslipItem.country_code == "CH").order_by(PayrollRun.pay_date, PayslipItem.id).all())
    for item, run in rows:
        qst = (((item.ch_calculation_snapshot or {}).get("trace") or {}).get("qst") or {})
        if qst.get("tariff_file_id") != tariff.id:
            continue
        affected.append({"organizationId": item.organization_id, "payrollRunId": run.id,
                         "month": run.period_start.strftime("%Y-%m") if run.period_start else None,
                         "payslipId": item.id, "employeeId": item.employee_id, "rowId": qst.get("row_id"),
                         "isCorrection": bool((item.ch_calculation_snapshot or {}).get("correction"))})
    return {"tariffFileId": tariff.id, "canton": tariff.canton, "status": tariff.status,
            "months": sorted({a["month"] for a in affected if a["month"]}), "payslipCount": len(affected),
            "affected": affected, "autoRecalculated": False}
