"""
modules/payroll/statutory_workbook.py
-------------------------------------
Country-neutral statutory configuration workbook (ZP-MY-ENG-001 decision:
"workbook import from day 1"; reusable by any country through an adapter).

A Super Admin downloads an Excel template generated from a Draft pack, fills
it from the official documents (each changed row naming the uploaded source
document and page) and uploads it:

  * preview (apply=False): every row is classified CHANGED / UNCHANGED /
    MISSING / INVALID with a reason; NOTHING is written;
  * apply (apply=True): refused unless the whole workbook is valid — right
    pack and version (fingerprint), Draft pack, no INVALID row. Changes are
    written UNSIGNED ("extracted") through the country's own governed write
    path; signing is a separate, second-person step. All or nothing: the
    caller commits only on success.

This module knows nothing about any country. An adapter supplies:
  country, fingerprint(pack), sheets(db, pack) -> [SheetSpec],
  plan(db, pack, rows_by_sheet) -> [RowResult], apply(db, pack, plan, actor_id, reason) -> dict.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

INSTRUCTIONS = "Instructions"
MAX_BYTES = 2 * 1024 * 1024
STATUSES = ("CHANGED", "UNCHANGED", "MISSING", "INVALID")


@dataclass
class SheetSpec:
    name: str
    headers: List[str]
    rows: List[list]
    editable: List[str] = field(default_factory=list)
    note: str = ""


@dataclass
class RowResult:
    sheet: str
    ref: str
    status: str
    detail: str = ""
    change: Any = None

    def view(self) -> dict:
        return {"sheet": self.sheet, "ref": self.ref, "status": self.status, "detail": self.detail}


def pack_fingerprint(country: str, pack) -> str:
    raw = f"{country}|{pack.id}|{pack.pack_id}|{pack.version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cell(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def export_workbook(db: Session, pack, adapter) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = INSTRUCTIONS
    lines = [
        ("country", adapter.country), ("pack_id", pack.pack_id), ("version", pack.version),
        ("pack_row_id", pack.id), ("fingerprint", adapter.fingerprint(pack)),
        ("effective_from", pack.effective_from.isoformat() if pack.effective_from else ""),
        ("effective_to", pack.effective_to.isoformat() if pack.effective_to else ""),
        ("how_to", "Fill only the editable columns from the official documents. Every changed row needs the "
                   "source_document_id of an uploaded document and the page. Leave a value blank when the "
                   "document does not give it - it stays MISSING and blocks; never estimate."),
        ("signing", "Imported values are EXTRACTED, not verified: a second Super Admin signs them afterwards."),
    ]
    for key, value in lines:
        ws.append([key, value])
    for spec in adapter.sheets(db, pack):
        sheet = wb.create_sheet(spec.name[:31])
        sheet.append(spec.headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in spec.rows:
            sheet.append([value.isoformat() if isinstance(value, date) else value for value in row])
        if spec.note:
            sheet.cell(row=1, column=len(spec.headers) + 2, value=spec.note)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def read_workbook(data: bytes, adapter, db: Session, pack) -> tuple:
    """(instructions, rows_by_sheet, fatal problems). Structure only."""
    from openpyxl import load_workbook

    if not data:
        return {}, {}, ["the file is empty"]
    if len(data) > MAX_BYTES:
        return {}, {}, [f"the file is larger than {MAX_BYTES} bytes"]
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # openpyxl raises several unrelated types for a non-xlsx file
        return {}, {}, ["the file is not an Excel workbook (.xlsx)"]
    fatal = []
    if INSTRUCTIONS not in wb.sheetnames:
        return {}, {}, ["the Instructions sheet is missing - download a fresh template"]
    instructions = {}
    for row in wb[INSTRUCTIONS].iter_rows(values_only=True):
        if row and row[0]:
            instructions[str(row[0]).strip()] = row[1] if len(row) > 1 else None
    if str(instructions.get("fingerprint") or "") != adapter.fingerprint(pack):
        fatal.append("this workbook was made for a different pack or version - download a fresh template")
    rows_by_sheet = {}
    for spec in adapter.sheets(db, pack):
        name = spec.name[:31]
        if name not in wb.sheetnames:
            fatal.append(f"sheet {name!r} is missing")
            continue
        rows = list(wb[name].iter_rows(values_only=True))
        headers = [str(h).strip() if h is not None else "" for h in (rows[0] if rows else ())][:len(spec.headers)]
        if headers != spec.headers:
            fatal.append(f"sheet {name!r} columns changed - expected {', '.join(spec.headers)}")
            continue
        parsed = []
        for values in rows[1:]:
            values = list(values)[:len(spec.headers)] + [None] * (len(spec.headers) - len(values))
            if all(v in (None, "") for v in values):
                continue
            parsed.append({h: _cell(v) for h, v in zip(spec.headers, values)})
        rows_by_sheet[spec.name] = parsed
    extra = [n for n in wb.sheetnames if n != INSTRUCTIONS and n not in {s.name[:31] for s in adapter.sheets(db, pack)}]
    if extra:
        fatal.append(f"unexpected sheet(s): {', '.join(extra)}")
    return instructions, rows_by_sheet, fatal


def import_workbook(db: Session, pack, data: bytes, adapter, actor_id, reason: Optional[str] = None,
                    apply: bool = False, filename: str = "workbook.xlsx") -> dict:
    """Preview (apply=False) or apply (apply=True) a filled workbook."""
    _instructions, rows_by_sheet, fatal = read_workbook(data, adapter, db, pack)
    results = [] if fatal else adapter.plan(db, pack, rows_by_sheet)
    summary = {status: sum(1 for r in results if r.status == status) for status in STATUSES}
    out = {"packRowId": pack.id, "fingerprint": adapter.fingerprint(pack), "fatal": fatal, "summary": summary,
           "rows": [r.view() for r in results], "applied": False}
    if not apply:
        return out
    if pack.status != "Draft":
        raise BadRequestException(f"Pack {pack.pack_id} v{pack.version} is {pack.status}: only a Draft pack "
                                  "can take a workbook.")
    if fatal or summary["INVALID"]:
        raise BadRequestException("The workbook is not applied: fix every INVALID row and structural problem "
                                  "first (nothing was written).")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Applying a workbook needs a change reason.")
    artifact = record_workbook_evidence(db, adapter.country, pack, data, filename, actor_id)
    written = adapter.apply(db, pack, [r for r in results if r.status == "CHANGED"], actor_id,
                            f"{text} (workbook {artifact.checksum_sha256[:12]})")
    out.update(applied=True, written=written, workbookArtifactId=artifact.id)
    return out


def record_workbook_evidence(db: Session, country: str, pack, data: bytes, filename: str, actor_id):
    """The uploaded workbook itself, kept as evidence (checksum; the file body
    is stored by the upload route through the platform's artifact storage)."""
    from app.modules.payroll.models import SourceArtifact

    artifact = SourceArtifact(agency="Zoiko statutory workbook", title=f"{country} {pack.pack_id} v{pack.version} "
                              f"workbook import: {filename}"[:300], form_number=f"{country}-WORKBOOK",
                              checksum_sha256=hashlib.sha256(data).hexdigest(), created_by_id=actor_id)
    db.add(artifact)
    db.flush()
    return artifact
