"""
payroll/netherlands_tables_service.py
--------------------------------------
NL wage-tax table file import, validation, approval, activation, supersede
(ZP-NL-ENG-001 NL-011..NL-014, gate G1).

State machine mirrors CH QST files (jurisdiction_hooks pattern):
  IMPORTED -> VALIDATED -> APPROVED -> ACTIVE
                    -> REJECTED (from any state)
  ACTIVE -> SUPERSEDED (when new file activated for same key)

Four-eyes approval at APPROVE and ACTIVATE steps (same as CH).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .models import (
    JurisdictionPack,
    PayrollNlTaxTableFile,
    PayrollNlTaxTableRow,
)
from .engine.jurisdictions.netherlands.wage_tax import (
    NlTableKey,
    TABLE_FILE_PERIOD,
    TableColor,
    TableKind,
    PeriodCode,
    AowCohort,
)
from app.core.exceptions import BadRequestException, NotFoundException


# ---- Import & Parse ----

REQUIRED_CSV_HEADERS = {
    "PERIOD": ["wage_from", "wage_to", "aow_cohort", "with_tax_credit", "withholding_amount"],
    "SPECIAL_REMUNERATION": ["wage_from", "wage_to", "aow_cohort", "with_tax_credit", "percentage"],
}

def _parse_bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "y", "t")


def _parse_decimal(v: str) -> Optional[Decimal]:
    v = v.strip()
    if v == "" or v.lower() in ("null", "none", "-"):
        return None
    return Decimal(v)


def _row_sha256(row: Dict[str, Any]) -> str:
    """Deterministic SHA256 of the row's logical content."""
    parts = [
        str(row.get("wage_from", "")),
        str(row.get("wage_to", "")),
        str(row.get("aow_cohort", "")),
        str(row.get("with_tax_credit", "")),
        str(row.get("withholding_amount", "")),
        str(row.get("percentage", "")),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def import_table_file(
    db: Session,
    *,
    jurisdiction_pack_id: int,
    tax_year: int,
    table_color: str,
    table_kind: str,
    period: Optional[str],
    residence_variant: str,
    source_url: Optional[str],
    source_filename: str,
    file_bytes: bytes,
    actor_id: int,
) -> PayrollNlTaxTableFile:
    """Parse a CSV/TSV Belastingdienst table file, validate structure, store as IMPORTED.
    Returns the created PayrollNlTaxTableFile row (not yet committed).
    """
    # Verify pack exists and is NL
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == jurisdiction_pack_id).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", jurisdiction_pack_id)
    if pack.jurisdiction_country != "NL":
        raise BadRequestException("NL wage-tax tables can only be imported for NL packs")

    # Validate enums
    try:
        TableColor(table_color)
        TableKind(table_kind)
    except ValueError as e:
        raise BadRequestException(f"Invalid enum value: {e}")
    # The file's period is stored in the CHECK-constrained file vocabulary
    # (DAY/WEEK/FOUR_WEEK/MONTH/QUARTER/YEAR), not the engine's PeriodCode.
    if period and period not in TABLE_FILE_PERIOD.values():
        raise BadRequestException(f"Invalid period {period!r}: use one of {', '.join(TABLE_FILE_PERIOD.values())}")

    if table_kind == "PERIOD" and not period:
        raise BadRequestException("PERIOD table_kind requires a period (DAY/WEEK/FOUR_WEEK/MONTH/QUARTER/YEAR)")
    if table_kind == "SPECIAL_REMUNERATION" and period:
        raise BadRequestException("SPECIAL_REMUNERATION table_kind must not have a period")

    # SHA256 of file content
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Check duplicate file_sha256
    existing = db.query(PayrollNlTaxTableFile).filter(PayrollNlTaxTableFile.file_sha256 == file_sha256).first()
    if existing:
        raise BadRequestException(f"File with identical content already imported (id={existing.id})")

    # Parse CSV/TSV (assume comma or tab separated, header row required)
    text = file_bytes.decode("utf-8-sig")  # handle BOM
    lines = text.strip().splitlines()
    if not lines:
        raise BadRequestException("Empty file")

    # Detect delimiter
    header = lines[0].strip()
    delimiter = "\t" if "\t" in header else ","
    headers = [h.strip().lower() for h in header.split(delimiter)]

    required = REQUIRED_CSV_HEADERS.get(table_kind, [])
    missing = [h for h in required if h not in headers]
    if missing:
        raise BadRequestException(f"Missing required columns for {table_kind}: {missing}")

    # Parse rows
    rows = []
    validation_errors = []
    for i, line in enumerate(lines[1:], start=1):
        if not line.strip():
            continue
        values = line.split(delimiter)
        if len(values) != len(headers):
            validation_errors.append(f"Row {i}: column count mismatch (expected {len(headers)}, got {len(values)})")
            continue
        row = dict(zip(headers, (v.strip() for v in values)))

        # Validate required fields
        wage_from = _parse_decimal(row["wage_from"])
        if wage_from is None:
            validation_errors.append(f"Row {i}: wage_from required")
            continue

        wage_to = _parse_decimal(row.get("wage_to", "")) if row.get("wage_to", "").strip() else None
        aow_cohort = row.get("aow_cohort", "").strip().upper()
        if aow_cohort not in ("BELOW_AOW", "AOW_AGE"):
            validation_errors.append(f"Row {i}: invalid aow_cohort '{aow_cohort}'")
            continue

        with_tax_credit = _parse_bool(row.get("with_tax_credit", "true"))

        if table_kind == "PERIOD":
            withholding = _parse_decimal(row.get("withholding_amount", ""))
            if withholding is None:
                validation_errors.append(f"Row {i}: withholding_amount required for PERIOD table")
                continue
            percentage = None
        else:
            percentage = _parse_decimal(row.get("percentage", ""))
            if percentage is None:
                validation_errors.append(f"Row {i}: percentage required for SPECIAL_REMUNERATION table")
                continue
            withholding = None

        rows.append({
            "wage_from": wage_from,
            "wage_to": wage_to,
            "aow_cohort": aow_cohort,
            "with_tax_credit": with_tax_credit,
            "withholding_amount": withholding,
            "percentage": percentage,
        })

    if validation_errors:
        raise BadRequestException("Validation errors: " + "; ".join(validation_errors[:10]) + (f" (+{len(validation_errors)-10} more)" if len(validation_errors) > 10 else ""))

    # Row ordering: wage_from ascending, then wage_to ascending (NULL last)
    rows.sort(key=lambda r: (r["wage_from"], r["wage_to"] if r["wage_to"] is not None else Decimal("999999999999")))

    # Create file row
    file_row = PayrollNlTaxTableFile(
        jurisdiction_pack_id=jurisdiction_pack_id,
        tax_year=tax_year,
        table_color=table_color,
        table_kind=table_kind,
        period=period,
        residence_variant=residence_variant,
        source_url=source_url,
        source_filename=source_filename,
        file_sha256=file_sha256,
        row_count=len(rows),
        status="IMPORTED",
        validation_report={"errors": validation_errors, "warnings": []} if validation_errors else None,
        imported_by=actor_id,
        effective_from=date(tax_year, 1, 1),
        effective_to=date(tax_year, 12, 31),
    )
    db.add(file_row)
    db.flush()

    # Create row entries
    for idx, row in enumerate(rows, start=1):
        row_data = dict(row)
        row_data["row_sha256"] = _row_sha256(row_data)
        db.add(PayrollNlTaxTableRow(
            file_id=file_row.id,
            row_no=idx,
            wage_from=row_data["wage_from"],
            wage_to=row_data["wage_to"],
            aow_cohort=row_data["aow_cohort"],
            with_tax_credit=row_data["with_tax_credit"],
            withholding_amount=row_data["withholding_amount"],
            percentage=row_data["percentage"],
            row_sha256=row_data["row_sha256"],
        ))

    return file_row


# ---- Validation ----

def validate_table_file(db: Session, file_id: int, actor_id: int) -> PayrollNlTaxTableFile:
    """Validate the parsed rows for consistency (no overlaps, full coverage, etc.).
    Sets status to VALIDATED.
    """
    file_row = db.query(PayrollNlTaxTableFile).filter(PayrollNlTaxTableFile.id == file_id).first()
    if not file_row:
        raise NotFoundException("PayrollNlTaxTableFile", file_id)
    if file_row.status != "IMPORTED":
        raise BadRequestException(f"Cannot validate file in status {file_row.status}")

    rows = db.query(PayrollNlTaxTableRow).filter(PayrollNlTaxTableRow.file_id == file_id).order_by(PayrollNlTaxTableRow.row_no).all()
    errors = []
    warnings = []

    # Check coverage and overlaps per (aow_cohort, with_tax_credit)
    for aow in ("BELOW_AOW", "AOW_AGE"):
        for wtc in (True, False):
            subset = [r for r in rows if r.aow_cohort == aow and r.with_tax_credit == wtc]
            if not subset:
                warnings.append(f"No rows for aow_cohort={aow}, with_tax_credit={wtc}")
                continue

            # Check contiguous coverage from 0
            prev_to = None
            for r in subset:
                if prev_to is None:
                    if r.wage_from > 0:
                        warnings.append(f"Gap at start for {aow}/{wtc}: 0 to {r.wage_from}")
                else:
                    if r.wage_from != prev_to:
                        errors.append(f"Gap/overlap at {prev_to} vs {r.wage_from} for {aow}/{wtc}")
                prev_to = r.wage_to if r.wage_to is not None else Decimal("Infinity")

    file_row.status = "VALIDATED"
    file_row.validation_report = {"errors": errors, "warnings": warnings}
    file_row.validated_by = actor_id
    db.flush()
    return file_row


# ---- Approval (four-eyes) ----

def approve_table_file(db: Session, file_id: int, actor_id: int) -> PayrollNlTaxTableFile:
    """Four-eyes approval: actor must not be the importer."""
    file_row = db.query(PayrollNlTaxTableFile).filter(PayrollNlTaxTableFile.id == file_id).first()
    if not file_row:
        raise NotFoundException("PayrollNlTaxTableFile", file_id)
    if file_row.status != "VALIDATED":
        raise BadRequestException(f"Cannot approve file in status {file_row.status}")
    if file_row.imported_by == actor_id:
        raise BadRequestException("Importer cannot also approve (four-eyes rule)")

    file_row.status = "APPROVED"
    file_row.approved_by = actor_id
    db.flush()
    return file_row


# ---- Activation (four-eyes + supersede) ----

def _find_active_conflict(db: Session, file_row: PayrollNlTaxTableFile) -> Optional[PayrollNlTaxTableFile]:
    """Find currently ACTIVE file with same table key."""
    return db.query(PayrollNlTaxTableFile).filter(
        PayrollNlTaxTableFile.id != file_row.id,
        PayrollNlTaxTableFile.status == "ACTIVE",
        PayrollNlTaxTableFile.tax_year == file_row.tax_year,
        PayrollNlTaxTableFile.table_color == file_row.table_color,
        PayrollNlTaxTableFile.table_kind == file_row.table_kind,
        PayrollNlTaxTableFile.period == file_row.period,
        PayrollNlTaxTableFile.residence_variant == file_row.residence_variant,
    ).first()


def activate_table_file(db: Session, file_id: int, actor_id: int) -> Tuple[PayrollNlTaxTableFile, Optional[PayrollNlTaxTableFile]]:
    """Activate file (four-eyes: actor != approver). Supersedes any existing ACTIVE file for same key.
    Returns (activated_file, superseded_file_or_None).
    """
    file_row = db.query(PayrollNlTaxTableFile).filter(PayrollNlTaxTableFile.id == file_id).first()
    if not file_row:
        raise NotFoundException("PayrollNlTaxTableFile", file_id)
    if file_row.status != "APPROVED":
        raise BadRequestException(f"Cannot activate file in status {file_row.status}")
    if file_row.approved_by == actor_id:
        raise BadRequestException("Approver cannot also activate (four-eyes rule)")

    # Supersede existing ACTIVE
    superseded = _find_active_conflict(db, file_row)
    if superseded:
        superseded.status = "SUPERSEDED"
        superseded.superseded_by_id = file_row.id
        # Inclusive windows: the old file ends the day before the new one starts.
        superseded.effective_to = file_row.effective_from - timedelta(days=1)

    file_row.status = "ACTIVE"
    file_row.activated_by = actor_id
    db.flush()

    # No process-local cache: the payroll path reads the ACTIVE rows from the
    # database for every calculation (active_table_rows), so a restart or a
    # second worker can never see a different table.
    return file_row, superseded


# ---- Reject ----

def reject_table_file(db: Session, file_id: int, actor_id: int, reason: str) -> PayrollNlTaxTableFile:
    file_row = db.query(PayrollNlTaxTableFile).filter(PayrollNlTaxTableFile.id == file_id).first()
    if not file_row:
        raise NotFoundException("PayrollNlTaxTableFile", file_id)
    if file_row.status in ("ACTIVE", "SUPERSEDED"):
        raise BadRequestException(f"Cannot reject file in status {file_row.status} — supersede instead")
    file_row.status = "REJECTED"
    file_row.validation_report = (file_row.validation_report or {})
    file_row.validation_report["rejection_reason"] = reason
    file_row.validation_report["rejected_by"] = actor_id
    db.flush()
    return file_row


# ---- Helpers ----

def get_active_table_file(db: Session, table_key: NlTableKey, on: Optional[date] = None) -> Optional[PayrollNlTaxTableFile]:
    """The ACTIVE file for this key whose legal window covers `on` (default:
    any). Period codes map onto the file's CHECK-constrained values (MONTHLY
    -> MONTH)."""
    q = db.query(PayrollNlTaxTableFile).filter(
        PayrollNlTaxTableFile.status == "ACTIVE",
        PayrollNlTaxTableFile.tax_year == table_key.tax_year,
        PayrollNlTaxTableFile.table_color == table_key.table_color.value,
        PayrollNlTaxTableFile.table_kind == table_key.table_kind.value,
        PayrollNlTaxTableFile.residence_variant == table_key.residence_variant,
    )
    if table_key.period is None:
        q = q.filter(PayrollNlTaxTableFile.period.is_(None))
    else:
        q = q.filter(PayrollNlTaxTableFile.period == TABLE_FILE_PERIOD[table_key.period])
    if on is not None:
        q = q.filter(PayrollNlTaxTableFile.effective_from <= on,
                     or_(PayrollNlTaxTableFile.effective_to.is_(None), PayrollNlTaxTableFile.effective_to >= on))
    return q.order_by(PayrollNlTaxTableFile.effective_from.desc()).first()


def table_rows(db: Session, file_id: int) -> List[Dict[str, Any]]:
    """All rows of one file as plain dicts (the shape wage_tax consumes)."""
    rows = (db.query(PayrollNlTaxTableRow).filter(PayrollNlTaxTableRow.file_id == file_id)
            .order_by(PayrollNlTaxTableRow.row_no).all())
    return [{"row_no": r.row_no, "wage_from": r.wage_from, "wage_to": r.wage_to, "aow_cohort": r.aow_cohort,
             "with_tax_credit": r.with_tax_credit, "withholding_amount": r.withholding_amount,
             "percentage": r.percentage, "row_sha256": r.row_sha256} for r in rows]


def list_table_files(db: Session, pack_id: Optional[int] = None, status: Optional[str] = None) -> List[PayrollNlTaxTableFile]:
    q = db.query(PayrollNlTaxTableFile)
    if pack_id:
        q = q.filter(PayrollNlTaxTableFile.jurisdiction_pack_id == pack_id)
    if status:
        q = q.filter(PayrollNlTaxTableFile.status == status)
    return q.order_by(PayrollNlTaxTableFile.created_at.desc()).all()