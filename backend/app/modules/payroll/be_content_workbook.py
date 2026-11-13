"""Belgium content intake workbook (ZP-BE-ENG-001 Block D3).

Export: one XLSX per Belgian pack for the Belgian payroll specialist — every
catalogue key (scalar), every band / formula / table key with its required
fields and dimension format and existing rows, the earning-classification
matrix, the filing schema versions, the parallel-run tolerances, the authority
calendar (rows + a template), the owner decisions and the evidence register
S1-S24 with its archive status, plus an Instructions sheet. Content only: no
personal data. Every cell is written as text (no float rounding).

Import (Draft packs only): the same workbook back. dry_run (the default)
validates every changed row through the SAME governed writers the console uses
(be_super_admin.update_row / add_slab_row) and rolls everything back, returning
a report per changed cell (sheet!cell, OK / ERROR + reason). A real import is
all-or-nothing (any ERROR -> nothing written), needs a source reference per
changed row, records the importer as the editor (audited before / after
images), NEVER signs (a changed row is "[PENDING G1]" again) and never
activates anything. Calendar rows are created Draft (inactive) with their
source; a Super Admin activates them.

Bulk signing: a signer who is neither the importer nor any editor of the
selected rows signs them in one action; each row is signed (and audited)
individually through update_row with its own reviewed, archived source.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

BE = "BE"
SHEET_INSTRUCTIONS = "Instructions"
SHEET_SCALAR = "Scalar keys"
SHEET_SLAB = "Slab keys"
SHEET_CLASS = "Earning classification"
SHEET_SCHEMA = "Filing schema versions"
SHEET_TOLERANCE = "Parallel tolerances"
SHEET_CALENDAR = "Calendar rows"
SHEET_DECISIONS = "Owner decisions"
SHEET_SOURCES = "Sources"
CALENDAR_REPORT_TYPES = ("BE_DMFA", "BE_FINPROF", "BE_BELCOTAX", "BE_ONSS_ADVANCE", "BE_HOLIDAY_FUND")

SCALAR_COLS = ("rowId", "key", "group", "kind", "specReference", "specProposed", "vocabulary", "state",
               "employeeRatePct", "employerRatePct", "flatAmount", "textValue", "effectiveFrom", "effectiveTo",
               "sourceDocumentId")
SCALAR_EDIT = ("employeeRatePct", "employerRatePct", "flatAmount", "textValue", "effectiveFrom", "effectiveTo")
SLAB_COLS = ("rowId", "key", "ruleType", "kind", "requiredFields", "dimensionFormat", "minAmount", "maxAmount",
             "ratePct", "flatAmount", "formulaText", "name", "date", "dimension", "effectiveFrom", "effectiveTo",
             "state", "sourceDocumentId")
SLAB_EDIT_EXISTING = ("minAmount", "maxAmount", "ratePct", "flatAmount", "name", "effectiveFrom", "effectiveTo")
SLAB_NEW = ("minAmount", "maxAmount", "ratePct", "flatAmount", "formulaText", "name", "date", "dimension",
            "effectiveFrom", "effectiveTo")
CLASS_COLS = ("rowId", "component", "obligation", "treatment", "state", "sourceDocumentId")
SCHEMA_COLS = ("rowId", "form", "key", "version", "effectiveFrom", "effectiveTo", "state", "sourceDocumentId")
TOLERANCE_COLS = ("rowId", "key", "concept", "flatAmount", "state", "sourceDocumentId")
CALENDAR_COLS = ("id", "reportType", "reportingYear", "periodKey", "periodLabel", "dueDate", "paymentDueDate",
                 "status", "sourceDocumentId")
DECISION_COLS = ("key", "label", "blocksLaunch", "evidenceTag", "state")
SOURCE_COLS = ("code", "agency", "title", "url", "sourceDocumentId", "archived", "reviewed")
SHEET_DRAFT_SOURCES = "Draft sources"               # optional: references a drafted workbook relies on
DRAFT_SOURCE_COLS = ("reference", "agency", "title", "url")

INSTRUCTIONS = (
    "Belgium content workbook (ZP-BE-ENG-001). Content only — no personal data.",
    "Edit only the value columns; never rowId / key / kind columns. Leave a cell unchanged to keep the value.",
    "Every changed row needs sourceDocumentId: an existing source document id, or its reference (form number, "
    "e.g. ZP-BE-ENG-001 S3) so the workbook works in every environment.",
    "Importing never signs: every changed row becomes PENDING again; a second Super Admin who did not import or "
    "edit it signs it (bulk sign) with a reviewed, archived source.",
    "Text-choice keys: use one of the listed vocabulary values, or NOT_SUPPORTED. Band / formula / table / "
    "schema-version keys: textValue SLAB_ROWS (or NOT_SUPPORTED) and their rows on the sheets below.",
    "Slab keys: a blank rowId adds a new row (fill the required fields); an existing row's formula / dimension "
    "cannot change (retire it in the console and add a new one).",
    "Filing schema versions: one row per version and window of SUBMISSION dates (effectiveFrom / effectiveTo).",
    "Calendar rows: a blank id adds a Draft (inactive) row; a Super Admin activates it. Dates YYYY-MM-DD; "
    "periodKey YYYYQn, YYYY-MM or YYYY.",
    "Amounts and rates are plain decimals with a dot as separator; a rate is the percentage number itself. "
    "Dates are YYYY-MM-DD.",
    "Import with the dry run first: it lists every changed cell as OK or ERROR with the reason.",
)


def _sa():
    from app.modules.payroll import be_super_admin

    return be_super_admin


def _content():
    from app.modules.payroll.engine.countries import belgium_content as content

    return content


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value == value.to_integral() else format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _norm(value) -> Optional[str]:
    """A cell or a stored value as a comparable string (None when empty)."""
    if value is None:
        return None
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()[:10]
    text = str(value).strip()
    if text == "":
        return None
    try:
        number = Decimal(text)
        if number.is_finite() and not any(c.isalpha() for c in text.replace("E", "").replace("e", "")):
            return format(number.normalize(), "f")
    except InvalidOperation:
        pass
    return text


def _pack_rows(db: Session, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.id).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.rule_type, TaxSlab.id).all())
    return rates, slabs


def _state(label: Optional[str], empty: bool = False) -> str:
    if _content().PENDING_MARK in (label or ""):
        return "EMPTY" if empty else "PENDING"
    return "SIGNED"


def _schema_keys() -> dict:
    content = _content()
    return {k: v for k, v in content.RULE_TYPES.items() if content.KEYS[k][1] == content.KIND_VERSION}


def _tolerance_keys() -> tuple:
    return tuple(k for k, v in _content().KEYS.items() if v[0] == "parallel")


# ── export ──────────────────────────────────────────────────────────────────
def be_content_workbook_sheets(db: Session, pack_row_id: int) -> dict:
    """{sheet name: [header, *rows]} — the workbook's content, as text."""
    from app.modules.payroll import belgium_service as bes
    from app.modules.payroll.models import SourceArtifact, StatutoryFilingCalendar

    sa, content = _sa(), _content()
    pack = sa._pack(db, pack_row_id)
    rates, slabs = _pack_rows(db, pack)
    vocab = sa.vocabulary()
    schema_rules = set(_schema_keys().values())
    tolerance = set(_tolerance_keys())
    rule_to_key = {v: k for k, v in content.RULE_TYPES.items()}
    sheets = {SHEET_INSTRUCTIONS: [("instruction",)] + [(line,) for line in INSTRUCTIONS]
              + [(f"Pack: {pack.pack_id} v{pack.version} ({pack.status}), "
                  f"{_text(pack.effective_from)} to {_text(pack.effective_to)}",)]}

    scalar = [SCALAR_COLS]
    tol = [TOLERANCE_COLS]
    for r in rates:
        group, kind, ref, _label = content.KEYS.get(r.component_key, (None, None, None, None))
        if group is None:
            continue
        if r.component_key in tolerance:
            tol.append((_text(r.id), r.component_key, r.component_key.replace("be_parallel_tolerance_", ""),
                        _text(r.flat_amount), _state(r.label), _text(r.source_document_id)))
            continue
        v = vocab.get(r.component_key, {})
        choices = ", ".join(v.get("choices") or []) or v.get("mode", "")
        scalar.append((_text(r.id), r.component_key, group, kind, ref, content.SPEC_PROPOSED.get(r.component_key, ""),
                       f"{choices}; or {content.NOT_SUPPORTED}" if kind in (content.KIND_TEXT,) or kind in
                       content.SLAB_KINDS else choices, _state(r.label, bes._row_empty(r, kind)),
                       _text(r.employee_rate_pct), _text(r.employer_rate_pct), _text(r.flat_amount),
                       r.text_value or "", _text(r.effective_from), _text(r.effective_to),
                       _text(r.source_document_id)))
    sheets[SHEET_SCALAR], sheets[SHEET_TOLERANCE] = scalar, tol

    slab = [SLAB_COLS]
    schema = [SCHEMA_COLS]
    classes = [CLASS_COLS]
    specs = content.SLAB_SPECS
    seen = set()
    for s in slabs:
        if s.rule_type == content.EARNING_CLASS_RULE:
            classes.append((_text(s.id), s.filing_status, s.tax_regime, s.assessment_basis or "", _state(s.rate_label),
                            _text(s.source_document_id)))
            continue
        key = rule_to_key.get(s.rule_type)
        if key is None:
            continue                                      # authority examples: registered in the console
        seen.add(key)
        if s.rule_type in schema_rules:
            schema.append((_text(s.id), key.split("_")[2].upper(), key, s.tax_formula or "",
                           _text(s.effective_from), _text(s.effective_to), _state(s.rate_label),
                           _text(s.source_document_id)))
            continue
        spec = specs[key]
        slab.append((_text(s.id), key, s.rule_type, spec["kind"], ",".join(spec["fields"]),
                     ";".join(f"{d}=..." for d in spec["dimensions"]), _text(s.min_amount), _text(s.max_amount),
                     _text(s.rate_pct), _text(s.flat_amount), s.formula_expression or "", s.tax_formula or "",
                     _text(s.effective_from) if spec["kind"] == content.KIND_TABLE else "", s.filing_status or "",
                     "" if spec["kind"] == content.KIND_TABLE else _text(s.effective_from),
                     "" if spec["kind"] == content.KIND_TABLE else _text(s.effective_to), _state(s.rate_label),
                     _text(s.source_document_id)))
    for key, spec in specs.items():                       # one blank template line per key
        if content.RULE_TYPES[key] in schema_rules:
            schema.append(("", key.split("_")[2].upper(), key, "", "", "", "TEMPLATE", ""))
        else:
            slab.append(("", key, content.RULE_TYPES[key], spec["kind"], ",".join(spec["fields"]),
                         ";".join(f"{d}=..." for d in spec["dimensions"]), "", "", "", "", "", "", "", "", "", "",
                         "TEMPLATE", ""))
    sheets[SHEET_SLAB], sheets[SHEET_SCHEMA], sheets[SHEET_CLASS] = slab, schema, classes

    cal = [CALENDAR_COLS]
    for c in (db.query(StatutoryFilingCalendar).filter(StatutoryFilingCalendar.jurisdiction_country == BE)
              .order_by(StatutoryFilingCalendar.reporting_year, StatutoryFilingCalendar.report_type,
                        StatutoryFilingCalendar.period_key, StatutoryFilingCalendar.id)):
        cal.append((_text(c.id), c.report_type, c.reporting_year, c.period_key, c.period_label, _text(c.due_date),
                    _text(c.payment_due_date), c.status, _text(c.source_document_id)))
    cal.append(("", "|".join(CALENDAR_REPORT_TYPES), "", "", "", "", "", "TEMPLATE", ""))
    sheets[SHEET_CALENDAR] = cal

    sheets[SHEET_DECISIONS] = [DECISION_COLS] + [
        (d["key"], d["label"], "yes" if d["blocksLaunch"] else "no", d["evidenceTag"], d["state"])
        for d in bes.owner_decisions(db)]
    src = [SOURCE_COLS]
    for code, agency, title, url in content.SOURCE_REFERENCES:
        a = (db.query(SourceArtifact).filter(SourceArtifact.form_number == f"ZP-BE-ENG-001 {code}")
             .order_by(SourceArtifact.id.desc()).first())
        src.append((code, agency, title, url, _text(getattr(a, "id", None)),
                    "yes" if a is not None and a.checksum_sha256 and a.file_path else "no",
                    "yes" if a is not None and a.reviewer_id else "no"))
    sheets[SHEET_SOURCES] = src
    return sheets


def be_content_workbook_export(db: Session, pack_row_id: int) -> tuple:
    """(filename, xlsx bytes)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    sheets = be_content_workbook_sheets(db, pack_row_id)
    pack = _sa()._pack(db, pack_row_id)
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r, values in enumerate(rows, start=1):
            for c, value in enumerate(values, start=1):
                cell = ws.cell(row=r, column=c, value=_text(value))
                cell.number_format = "@"
                if r == 1:
                    cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return f"belgium-content-{pack.pack_id}-v{pack.version}.xlsx", out.getvalue()


# ── import ──────────────────────────────────────────────────────────────────
def _col(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index)


def _read(data: bytes) -> dict:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise BadRequestException("The file is not a readable XLSX workbook.")
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        out[ws.title] = (header, [(i + 2, dict(zip(header, r))) for i, r in enumerate(rows[1:])])
    return out


class _Report:
    def __init__(self):
        self.items = []

    def add(self, sheet, row, column, header, status, reason, key=None):
        cell = f"{sheet}!{_col(header.index(column) + 1)}{row}" if column in header else f"{sheet}!row {row}"
        self.items.append({"sheet": sheet, "cell": cell, "key": key, "status": status, "reason": reason})

    @property
    def errors(self):
        return [i for i in self.items if i["status"] == "ERROR"]


def _changed(row: dict, current: dict, columns) -> dict:
    return {c: row.get(c) for c in columns if c in row and _norm(row.get(c)) != _norm(current.get(c))}


def _apply(report, sheet, n, header, key, changed, fn, payload_cols):
    """Run one governed writer; on refusal report the first changed cell."""
    try:
        fn()
        for column in changed:
            report.add(sheet, n, column, header, "OK", f"{column} -> {_norm(changed[column])}", key)
    except (BadRequestException, NotFoundException) as error:
        text = str(getattr(error, "detail", error))
        column = next((c for c in payload_cols if c in text), next(iter(changed), None))
        report.add(sheet, n, column, header, "ERROR", text, key)


def _src(row: dict) -> Optional[str]:
    return _norm(row.get("sourceDocumentId"))


def _source_id(db: Session, raw: Optional[str]) -> Optional[int]:
    """A source document by id, or by its reference (SourceArtifact.form_number,
    e.g. "ZP-BE-ENG-001 S3"), so a workbook is portable between environments."""
    from app.modules.payroll.models import SourceArtifact

    if raw is None:
        return None
    if raw.isdigit():
        return int(raw) if db.get(SourceArtifact, int(raw)) is not None else None
    row = (db.query(SourceArtifact).filter(SourceArtifact.form_number == raw,
                                           SourceArtifact.superseded_by_id.is_(None))
           .order_by(SourceArtifact.id.desc()).first())
    return row.id if row is not None else None


def be_content_workbook_import(db: Session, pack_row_id: int, data: bytes, actor_id, *, reason=None,
                               dry_run: bool = True) -> dict:
    from app.modules.payroll.models import ContributionRate, SourceArtifact, StatutoryFilingCalendar, TaxSlab

    sa, content = _sa(), _content()
    pack = sa._pack(db, pack_row_id)
    if pack.status != "Draft":
        raise BadRequestException(f"Belgium pack {pack.pack_id} is {pack.status}: the workbook imports into a Draft "
                                  "pack only (never into an Active or approved one).")
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("A reason is required for a workbook import.")
    sheets = _read(data)
    report = _Report()
    # Draft sources first (optional sheet): every listed reference that does not
    # exist yet becomes an UNVERIFIED, unarchived SourceArtifact (it can never be
    # used to sign); existing references are left untouched.
    header, rows = sheets.get(SHEET_DRAFT_SOURCES, ([], []))
    for n, row in rows:
        ref_ = _norm(row.get("reference"))
        if ref_ is None:
            continue
        title = _norm(row.get("title"))
        if not title or ref_.isdigit():
            report.add(SHEET_DRAFT_SOURCES, n, "title" if not title else "reference", header, "ERROR",
                       "a draft source needs a non-numeric reference and a title")
            continue
        if _source_id(db, ref_) is None:
            db.add(SourceArtifact(agency=(_norm(row.get("agency")) or "unknown")[:200],
                                  title=f"{title} [UNVERIFIED: not archived]"[:300], form_number=ref_[:50],
                                  source_url=(_norm(row.get("url")) or None), created_by_id=actor_id))
            db.flush()
            report.add(SHEET_DRAFT_SOURCES, n, "reference", header, "OK", f"new unverified source {ref_}")
    rates = {r.id: r for r in _pack_rows(db, pack)[0]}
    slabs = {s.id: s for s in _pack_rows(db, pack)[1]}

    def ref(sheet, n, header, row, key):
        source = _source_id(db, _src(row))
        if source is None:
            report.add(sheet, n, "sourceDocumentId", header, "ERROR",
                       "a changed row needs an existing source document (id or reference)", key)
            return None
        return source

    def row_id(sheet, n, header, row, pool, key):
        raw = _norm(row.get("rowId"))
        if raw is None or not raw.isdigit() or int(raw) not in pool:
            report.add(sheet, n, "rowId", header, "ERROR", "rowId is not a row of this pack", key)
            return None
        return int(raw)

    # scalar keys + tolerances (ContributionRate rows)
    for sheet, edit in ((SHEET_SCALAR, SCALAR_EDIT), (SHEET_TOLERANCE, ("flatAmount",))):
        header, rows = sheets.get(sheet, ([], []))
        for n, row in rows:
            if not any(_norm(v) for v in row.values()):
                continue
            key = row.get("key")
            rid = row_id(sheet, n, header, row, rates, key)
            if rid is None:
                continue
            r = rates[rid]
            current = {"employeeRatePct": r.employee_rate_pct, "employerRatePct": r.employer_rate_pct,
                       "flatAmount": r.flat_amount, "textValue": r.text_value, "effectiveFrom": r.effective_from,
                       "effectiveTo": r.effective_to}
            changed = _changed(row, current, edit)
            if not changed:
                continue
            source = ref(sheet, n, header, row, key)
            if source is None:
                continue
            payload = {k: ("" if _norm(v) is None else _norm(v)) for k, v in changed.items()}
            _apply(report, sheet, n, header, key, changed,
                   lambda: sa.update_row(db, "rate", rid, {**payload, "sourceDocumentId": source, "reason": reason},
                                         actor_id), tuple(changed))

    # slab keys (bands / formulas / tables)
    header, rows = sheets.get(SHEET_SLAB, ([], []))
    for n, row in rows:
        key = row.get("key")
        values = {c: row.get(c) for c in SLAB_NEW}
        if _norm(row.get("rowId")) is None:
            if not any(_norm(v) for v in values.values()):
                continue                                    # untouched template line
            if key not in content.SLAB_SPECS:
                report.add(SHEET_SLAB, n, "key", header, "ERROR", "not a band / formula / table key", key)
                continue
            source = ref(SHEET_SLAB, n, header, row, key)
            if source is None:
                continue
            payload = {c: _norm(v) for c, v in values.items() if _norm(v) is not None}
            _apply(report, SHEET_SLAB, n, header, key, payload,
                   lambda: sa.add_slab_row(db, pack.id, key, {**payload, "sourceDocumentId": source,
                                                              "reason": reason}, actor_id), tuple(payload))
            continue
        rid = row_id(SHEET_SLAB, n, header, row, slabs, key)
        if rid is None:
            continue
        s = slabs[rid]
        spec = content.SLAB_SPECS.get(key) or {}
        table = spec.get("kind") == content.KIND_TABLE
        current = {"minAmount": s.min_amount, "maxAmount": s.max_amount, "ratePct": s.rate_pct,
                   "flatAmount": s.flat_amount, "name": s.tax_formula, "formulaText": s.formula_expression,
                   "dimension": s.filing_status, "date": s.effective_from if table else None,
                   "effectiveFrom": None if table else s.effective_from,
                   "effectiveTo": None if table else s.effective_to}
        frozen = _changed(row, current, ("formulaText", "dimension", "date"))
        if frozen:
            for column in frozen:
                report.add(SHEET_SLAB, n, column, header, "ERROR",
                           "an existing row's formula / dimension / date cannot change: retire it and add a new row",
                           key)
            continue
        changed = _changed(row, current, SLAB_EDIT_EXISTING)
        if not changed:
            continue
        source = ref(SHEET_SLAB, n, header, row, key)
        if source is None:
            continue
        payload = {("taxFormula" if k == "name" else k): ("" if _norm(v) is None else _norm(v))
                   for k, v in changed.items()}
        _apply(report, SHEET_SLAB, n, header, key, changed,
               lambda: sa.update_row(db, "slab", rid, {**payload, "sourceDocumentId": source, "reason": reason},
                                     actor_id), tuple(changed))

    # earning classification
    header, rows = sheets.get(SHEET_CLASS, ([], []))
    for n, row in rows:
        rid = row_id(SHEET_CLASS, n, header, row, slabs, row.get("component"))
        if rid is None:
            continue
        changed = _changed(row, {"treatment": slabs[rid].assessment_basis}, ("treatment",))
        if not changed:
            continue
        key = f"{row.get('component')} x {row.get('obligation')}"
        source = ref(SHEET_CLASS, n, header, row, key)
        if source is None:
            continue
        value = (_norm(changed["treatment"]) or "").upper()
        _apply(report, SHEET_CLASS, n, header, key, changed,
               lambda: sa.update_row(db, "slab", rid, {"treatment": value, "sourceDocumentId": source,
                                                       "reason": reason}, actor_id), ("treatment",))

    # filing schema versions
    schema_keys = _schema_keys()
    header, rows = sheets.get(SHEET_SCHEMA, ([], []))
    for n, row in rows:
        key = row.get("key")
        cols = {"name": row.get("version"), "effectiveFrom": row.get("effectiveFrom"),
                "effectiveTo": row.get("effectiveTo")}
        if _norm(row.get("rowId")) is None:
            if not any(_norm(v) for v in cols.values()):
                continue
            if key not in schema_keys:
                report.add(SHEET_SCHEMA, n, "key", header, "ERROR", "not a filing schema-version key", key)
                continue
            source = ref(SHEET_SCHEMA, n, header, row, key)
            if source is None:
                continue
            payload = {k: _norm(v) for k, v in cols.items() if _norm(v) is not None}
            _apply(report, SHEET_SCHEMA, n, header, key, {"version": row.get("version"), **{
                       k: v for k, v in cols.items() if k != "name"}},
                   lambda: sa.add_slab_row(db, pack.id, key, {**payload, "sourceDocumentId": source,
                                                              "reason": reason}, actor_id), ("name", "effective"))
            continue
        rid = row_id(SHEET_SCHEMA, n, header, row, slabs, key)
        if rid is None:
            continue
        s = slabs[rid]
        changed = _changed(row, {"version": s.tax_formula, "effectiveFrom": s.effective_from,
                                 "effectiveTo": s.effective_to}, ("version", "effectiveFrom", "effectiveTo"))
        if not changed:
            continue
        source = ref(SHEET_SCHEMA, n, header, row, key)
        if source is None:
            continue
        payload = {("taxFormula" if k == "version" else k): ("" if _norm(v) is None else _norm(v))
                   for k, v in changed.items()}
        _apply(report, SHEET_SCHEMA, n, header, key, changed,
               lambda: sa.update_row(db, "slab", rid, {**payload, "sourceDocumentId": source, "reason": reason},
                                     actor_id), tuple(changed))

    # calendar rows: new rows only, created Draft (inactive until a Super Admin activates them)
    header, rows = sheets.get(SHEET_CALENDAR, ([], []))
    for n, row in rows:
        if _norm(row.get("status")) == "TEMPLATE" or not any(_norm(v) for k, v in row.items() if k != "id"):
            continue
        existing = _norm(row.get("id"))
        if existing is not None:
            c = db.get(StatutoryFilingCalendar, int(existing)) if existing.isdigit() else None
            if c is None or c.jurisdiction_country != BE:
                report.add(SHEET_CALENDAR, n, "id", header, "ERROR", "id is not a Belgian calendar row")
                continue
            now = {"reportType": c.report_type, "reportingYear": c.reporting_year, "periodKey": c.period_key,
                   "periodLabel": c.period_label, "dueDate": c.due_date, "paymentDueDate": c.payment_due_date,
                   "sourceDocumentId": c.source_document_id}
            for column in _changed(row, now, tuple(now)):
                report.add(SHEET_CALENDAR, n, column, header, "ERROR",
                           "a calendar row is never edited: add a corrected row (blank id)")
            continue
        problems = []
        report_type = (_norm(row.get("reportType")) or "").upper()
        if report_type not in CALENDAR_REPORT_TYPES:
            problems.append(("reportType", f"must be one of {', '.join(CALENDAR_REPORT_TYPES)}"))
        period = _norm(row.get("periodKey")) or ""
        year = _norm(row.get("reportingYear")) or ""
        if not (year.isdigit() and len(year) == 4):
            problems.append(("reportingYear", "must be YYYY"))
        import re as _re
        if not _re.fullmatch(r"\d{4}(Q[1-4]|-(0[1-9]|1[0-2]))?", period) or not period.startswith(year):
            problems.append(("periodKey", "must be YYYYQn, YYYY-MM or YYYY within reportingYear"))
        dates = {}
        for column in ("dueDate", "paymentDueDate"):
            raw = _norm(row.get(column))
            if raw is None:
                if column == "dueDate":
                    problems.append((column, "is required (YYYY-MM-DD)"))
                continue
            try:
                dates[column] = date.fromisoformat(raw[:10])
            except ValueError:
                problems.append((column, "must be a date YYYY-MM-DD"))
        source = _source_id(db, _src(row))
        if source is None:
            problems.append(("sourceDocumentId", "a calendar row needs an existing source document (id or reference)"))
        if problems:
            for column, why in problems:
                report.add(SHEET_CALENDAR, n, column, header, "ERROR", f"{column} {why}")
            continue
        db.add(StatutoryFilingCalendar(jurisdiction_country=BE, report_type=report_type, reporting_year=year,
                                       period_key=period, period_label=(_norm(row.get("periodLabel")) or period)[:100],
                                       due_date=dates["dueDate"], payment_due_date=dates.get("paymentDueDate"),
                                       status="Draft", source_document_id=source, created_by_id=actor_id,
                                       updated_by_id=actor_id))
        db.flush()
        report.add(SHEET_CALENDAR, n, "dueDate", header, "OK", f"new Draft {report_type} {period} row")

    errors = report.errors
    written = not dry_run and not errors
    if written:
        db.flush()
    else:
        db.rollback()
    return {"packRowId": pack_row_id, "dryRun": dry_run, "written": written,
            "changes": sum(1 for i in report.items if i["status"] == "OK"), "errors": len(errors),
            "items": report.items}


# ── bulk signing ────────────────────────────────────────────────────────────
def _row_editors(db: Session, kind: str, row_id: int) -> set:
    from app.modules.payroll.models import TaxConfigurationAudit as A

    return {a for (a,) in db.query(A.actor_id).filter(A.entity_type == f"be_statutory_{kind}",
                                                      A.entity_id == row_id) if a is not None}


def be_bulk_sign_rows(db: Session, pack_row_id: int, data: dict, actor_id) -> dict:
    """Sign the selected rows ([{kind: rate|slab, id}]) in one action. Refused
    as a whole when the signer imported or edited any of them; each row is then
    signed individually (own reviewed, archived source; own audit row)."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    sa = _sa()
    pack = sa._pack(db, pack_row_id)
    data = dict(data or {})
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A reason is required to sign.")
    selected = [(str(r.get("kind")), int(r.get("id"))) for r in (data.get("rows") or [])
                if str(r.get("kind")) in ("rate", "slab") and str(r.get("id") or "").isdigit()]
    if not selected:
        raise BadRequestException("Select at least one row to sign.")
    refused = []
    rows = []
    for kind, row_id in selected:
        model = ContributionRate if kind == "rate" else TaxSlab
        row = db.get(model, row_id)
        if row is None or row.jurisdiction_pack_id != pack.id or row.organization_id is not None:
            raise NotFoundException("Belgium statutory row", row_id)
        if actor_id in _row_editors(db, kind, row_id):
            refused.append(f"{kind} #{row_id}")
        rows.append((kind, row))
    if refused:
        raise BadRequestException("Four-eyes: you imported or edited " + ", ".join(refused[:10])
                                  + (" (+more)" if len(refused) > 10 else "")
                                  + "; another Super Admin must sign them.")
    signed = []
    for kind, row in rows:
        if row.source_document_id is None:
            raise BadRequestException(f"{kind} #{row.id} has no source document; set one before signing.")
        sa.update_row(db, kind, row.id, {"specialistVerified": True, "sourceDocumentId": row.source_document_id,
                                         "reason": reason}, actor_id)
        signed.append({"kind": kind, "id": row.id})
    return {"packRowId": pack.id, "signed": signed}
