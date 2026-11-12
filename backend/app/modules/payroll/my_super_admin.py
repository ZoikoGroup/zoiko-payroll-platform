"""
modules/payroll/my_super_admin.py
---------------------------------
Malaysia governed statutory console (ZP-MY-ENG-001; spec §13 / §16 G1).

Phase 1 (this module's core): the ONLY write paths for canonical Malaysia
rows, shared by the Super Admin console (Phase 8) and the statutory workbook
import (my_workbook_adapter):

  * update_row — edit and/or sign one canonical row (ContributionRate
    parameter or TaxSlab table row). Every change needs a reason and an
    existing source document; SIGNING additionally needs that source stored,
    hashed and reviewed by a Super Admin other than its uploader. An unsigned
    change keeps / re-adds the "[PENDING G1]" marker.
  * replace_table — load a whole table (EPF / PERKESO / EIS / foreign-worker
    schedule, public holidays) into a Draft pack, all-or-nothing, every row
    UNSIGNED with its source document and page.
  * sign_rows — sign many rows at once; all or nothing.

Text values must come from the engine's vocabulary; a policy with no
vocabulary yet can only be signed NOT_SUPPORTED (the feature stays blocked).
Modelled on pl_super_admin.py.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import malaysia_service as mys

MY = "MY"
MARK = "[PENDING G1]"
NOT_SUPPORTED = "NOT_SUPPORTED"
_LEGAL = "MY statutory configuration (ZP-MY-ENG-001)"
TABLE_RULES = ("MY_EPF_SCHEDULE", "MY_SOCSO_SCHEDULE", "MY_EIS_SCHEDULE", "MY_FW_SOCSO_SCHEDULE",
               "MY_PUBLIC_HOLIDAY")


def _content():
    return mys._content()


def _vocabulary() -> dict:
    """text key -> validator(value) returning an error message or None."""
    content = _content()

    def one_of(*allowed):
        return lambda v: None if v in allowed else f"must be one of: {', '.join(allowed)}"

    def listed(allowed):
        def check(v):
            items = [p.strip() for p in v.split(",") if p.strip()]
            bad = [p for p in items if p not in allowed]
            return f"unknown value(s): {', '.join(bad)}" if bad or not items else None
        return check

    vocab = {key: one_of(*content.ROUNDING_RULES)
             for key in content.MALAYSIA_PARAMETER_KEYS if key.startswith("my_rounding_")}
    vocab.update({
        "my_supported_pay_frequencies": listed(content.PAY_FREQUENCIES_SUPPORTED),
        "my_supported_contract_types": listed(content.CONTRACT_TYPES_SUPPORTED),
        "my_pcb_spec_version": lambda v: None if re.fullmatch(r"[A-Z0-9][A-Z0-9 ._/-]{0,39}", v)
        else "must be the specification's version label (letters, digits, . _ / -)",
        "my_ea_due": one_of("END_FEBRUARY"),
        "my_form_e_due": one_of("END_MARCH"),
    })
    return vocab


def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or (pack.jurisdiction_country or "").upper() != MY or pack.pack_type != "tax":
        raise NotFoundException("Malaysia tax pack", pack_row_id)
    return pack


def _decimal(value, field: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal number.")


def _reason(data: dict) -> str:
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A statutory change needs a change reason.")
    return reason[:300]


def _source(db: Session, source_id, verify: bool):
    from app.modules.payroll.models import SourceArtifact

    try:
        source = db.get(SourceArtifact, int(source_id)) if source_id not in (None, "") else None
    except (TypeError, ValueError):
        source = None
    if source is None:
        raise BadRequestException("A statutory change needs the official source document (an existing SourceArtifact).")
    if source.superseded_by_id is not None:
        raise BadRequestException(f"Source document {source.id} has been superseded; use its replacement.")
    if verify and not (source.checksum_sha256 and source.file_path and source.reviewer_id
                       and source.reviewer_id != source.created_by_id and "[UNVERIFIED" not in (source.title or "")):
        raise BadRequestException("Signing needs a stored, hashed source document reviewed by a Super Admin other "
                                  "than its uploader (and not itself marked UNVERIFIED).")
    return source


def _marked(label: Optional[str], signed: bool, limit: int) -> str:
    base = " ".join((label or "").replace(MARK, " ").split())
    if signed:
        return base[:limit]
    return (base[:limit - len(MARK) - 1] + " " + MARK).strip()


def _audit(db: Session, pack, actor_id, entity_type: str, entity_id: int, old: dict, new: dict, reason: str):
    from app.modules.payroll.service import _invalidate_pack_approval_on_edit, record_tax_audit

    _invalidate_pack_approval_on_edit(pack)
    if actor_id is not None:
        pack.updated_by_id = actor_id
    db.flush()
    record_tax_audit(db, actor_id=actor_id, action="update", entity_type=entity_type, entity_id=entity_id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=_LEGAL,
                     old_value=old, new_value=new, reason=reason, auto_commit=False)


def _json(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return value


def rate_view(row) -> dict:
    kind = _content().ALL_PARAMETER_KINDS.get(row.component_key)
    return {"kind": "rate", "id": row.id, "componentKey": row.component_key, "territory": row.jurisdiction_state,
            "label": row.label, "valueKind": kind, "employeeRatePct": _json(row.employee_rate_pct),
            "employerRatePct": _json(row.employer_rate_pct), "flatAmount": _json(row.flat_amount),
            "textValue": row.text_value, "effectiveFrom": _json(row.effective_from),
            "effectiveTo": _json(row.effective_to), "sourceDocumentId": row.source_document_id,
            "signed": MARK not in (row.label or "")}


def slab_view(row) -> dict:
    return {"kind": "slab", "id": row.id, "ruleType": row.rule_type, "label": row.rate_label,
            "memberClass": row.filing_status, "component": row.filing_status, "obligation": row.tax_regime,
            "side": row.tax_regime, "treatment": row.assessment_basis, "state": row.jurisdiction_state,
            "minAmount": _json(row.min_amount), "maxAmount": _json(row.max_amount),
            "flatAmount": _json(row.flat_amount), "detail": row.tax_formula,
            "sourceDocumentId": row.source_document_id, "signed": MARK not in (row.rate_label or "")}


RATE_FIELDS = {"employeeRatePct": "employee_rate_pct", "employerRatePct": "employer_rate_pct",
               "flatAmount": "flat_amount", "textValue": "text_value", "effectiveFrom": "effective_from",
               "effectiveTo": "effective_to"}
_KIND_SLOTS = {"pct_employee": {"employee_rate_pct"}, "pct_employer": {"employer_rate_pct"},
               "pct_both": {"employee_rate_pct", "employer_rate_pct"}, "amount": {"flat_amount"},
               "text": {"text_value"}}


def check_rate_value(key: str, column: str, value) -> None:
    """The slot / range / vocabulary rules every parameter value obeys."""
    kind = _content().ALL_PARAMETER_KINDS.get(key)
    if kind is None:
        raise BadRequestException(f"{key} is not a Malaysia parameter.")
    if value is None or column.startswith("effective_"):
        return
    if column not in _KIND_SLOTS[kind]:
        raise BadRequestException(f"{key} holds a {kind} value, not {column}.")
    if column == "text_value":
        if value != NOT_SUPPORTED:
            check = _vocabulary().get(key)
            problem = check(value) if check else "has no signed vocabulary yet: sign it NOT_SUPPORTED"
            if problem:
                raise BadRequestException(f"{key} {problem}.")
        return
    if value < 0:
        raise BadRequestException(f"{key} cannot be negative.")
    if column.endswith("_rate_pct") and value > 100:
        raise BadRequestException(f"{key} is a percentage (0-100).")


def _rate_total(row) -> str:
    return mys.rate_total(row.employee_rate_pct, row.employer_rate_pct, row.flat_amount, row.text_value)


def update_row(db: Session, kind: str, row_id: int, data: dict, actor_id) -> dict:
    """Edit and/or sign one canonical MY row of an editable pack version."""
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
    if model is None:
        raise BadRequestException("kind must be 'rate' or 'slab'.")
    data = dict(data or {})
    row = db.get(model, row_id)
    if row is None or row.organization_id is not None or (row.jurisdiction_country or "").upper() != MY:
        raise NotFoundException("Malaysia statutory row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = _reason(data)
    verify = data.get("specialistVerified") is True
    source = _source(db, data.get("sourceDocumentId"), verify)
    if kind == "rate":
        allowed = dict(RATE_FIELDS)
    elif row.rule_type == content.MY_EARNING_CLASS_RULE:
        allowed = {"treatment": "assessment_basis"}
    elif row.rule_type in content.SCHEDULE_RULES:
        allowed = {"minAmount": "min_amount", "maxAmount": "max_amount", "flatAmount": "flat_amount"}
    else:
        allowed = {}
    unknown = set(data) - set(allowed) - {"reason", "sourceDocumentId", "specialistVerified", "page"}
    if unknown:
        raise BadRequestException(f"not editable here: {', '.join(sorted(unknown))}")

    old, new, changed = {}, {}, False
    for name, column in allowed.items():
        if name not in data:
            continue
        value = data[name]
        if column.startswith("effective_"):
            value = mys_date(value, name) if value else None
        elif column == "assessment_basis":
            value = str(value or "").strip().upper()
            if value not in content.TREATMENTS:
                raise BadRequestException(f"treatment must be one of: {', '.join(content.TREATMENTS)}.")
        elif column == "text_value":
            value = str(value).strip().upper() if value not in (None, "") else None
        else:
            value = _decimal(value, name)
            if value is not None and value < 0:
                raise BadRequestException(f"{name} cannot be negative.")
        if kind == "rate":
            check_rate_value(row.component_key, column, value)
        old[name], new[name] = _json(getattr(row, column)), _json(value)
        if getattr(row, column) != value:
            changed = True
        setattr(row, column, value)
    if kind == "slab" and row.rule_type in content.SCHEDULE_RULES and row.max_amount is not None \
            and row.max_amount <= (row.min_amount or 0):
        raise BadRequestException("a schedule band must end above where it starts.")
    start, end = row.effective_from or pack.effective_from, row.effective_to or pack.effective_to
    if kind == "rate" and start and end and end < start:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")
    if kind == "rate" and verify:
        if row.flat_amount is None and not row.text_value and row.employee_rate_pct is None \
                and row.employer_rate_pct is None:
            raise BadRequestException(f"{row.component_key} has no value: fill it before signing.")
        if (row.text_value or "") == content.PENDING:
            raise BadRequestException(f"{row.component_key} is still PENDING_G1: choose a value or NOT_SUPPORTED.")
    label_col = "label" if kind == "rate" else "rate_label"
    was_signed = MARK not in (getattr(row, label_col) or "")
    signed = verify or (was_signed and not changed)
    setattr(row, label_col, _marked(getattr(row, label_col), signed, 100 if kind == "rate" else 150))
    if kind == "rate":
        row.employee_share = (f"{row.employee_rate_pct}%" if row.employee_rate_pct is not None else "—")[:50]
        row.employer_share = (f"{row.employer_rate_pct}%" if row.employer_rate_pct is not None else "—")[:50]
        row.total = _rate_total(row)
    old["signed"], new["signed"] = was_signed, signed
    old["sourceDocumentId"], new["sourceDocumentId"] = row.source_document_id, source.id
    if data.get("page"):
        new["page"] = str(data["page"]).strip()[:60]
    row.source_document_id = source.id
    _audit(db, pack, actor_id, f"my_statutory_{kind}", row.id, old, new, reason)
    return rate_view(row) if kind == "rate" else slab_view(row)


def mys_date(value, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


# ── tables (schedules and public holidays) ───────────────────────────────────
def validate_schedule(rule_type: str, rows: list) -> list:
    """Problems in a schedule (empty list = valid). rows: dicts with
    member_class, wage_from, wage_to (None = open top band), employee_amount,
    employer_amount (Decimals). Per class: starts at 0, contiguous, no
    overlap, ascending, amounts >= 0, only the last band open."""
    content = _content()
    problems = []
    classes = content.SCHEDULE_CLASSES[rule_type]
    by_class = {}
    for n, row in enumerate(rows, start=1):
        cls = row.get("member_class")
        if cls not in classes:
            problems.append(f"row {n}: member class {cls!r} is not one of {', '.join(classes)}")
            continue
        lo, hi = row.get("wage_from"), row.get("wage_to")
        if lo is None or lo < 0 or (hi is not None and hi <= lo):
            problems.append(f"row {n}: band must start at or above 0 and end above where it starts")
        for side in ("employee_amount", "employer_amount"):
            if row.get(side) is None or row[side] < 0:
                problems.append(f"row {n}: {side} must be a number of at least 0")
        by_class.setdefault(cls, []).append((lo, hi, n))
    for cls, bands in by_class.items():
        bands = sorted(bands, key=lambda b: (b[0] if b[0] is not None else Decimal("-1")))
        if bands[0][0] != 0:
            problems.append(f"{cls}: the first band must start at 0")
        for (lo, hi, n), (next_lo, _next_hi, m) in zip(bands, bands[1:]):
            if hi is None:
                problems.append(f"{cls}: only the last band may be open (row {n})")
            elif next_lo != hi:
                problems.append(f"{cls}: bands must be contiguous — row {n} ends at {hi}, row {m} starts at {next_lo}")
    return problems


def validate_holidays(rows: list, pack) -> list:
    content = _content()
    problems, seen = [], set()
    for n, row in enumerate(rows, start=1):
        day, name, state = row.get("date"), (row.get("name") or "").strip(), row.get("holiday_state")
        if not isinstance(day, date):
            problems.append(f"row {n}: date must be an ISO date")
            continue
        if not (pack.effective_from <= day <= (pack.effective_to or day)):
            problems.append(f"row {n}: {day.isoformat()} is outside the pack window")
        if not name:
            problems.append(f"row {n}: a holiday needs its name")
        if state is not None and state not in content.HOLIDAY_STATES:
            problems.append(f"row {n}: state {state!r} is not one of {', '.join(content.HOLIDAY_STATES)}")
        if (day, state) in seen:
            problems.append(f"row {n}: {day.isoformat()} is listed twice for {state or 'national'}")
        seen.add((day, state))
    return problems


def replace_table(db: Session, pack_row_id: int, rule_type: str, rows: list, actor_id, reason: str) -> int:
    """Replace every canonical row of one table in a Draft pack — all or
    nothing, every row UNSIGNED with its source document. rows carry
    `source_document_id` and `page` per row. Returns the row count."""
    from app.modules.payroll.models import TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    if rule_type not in TABLE_RULES:
        raise BadRequestException(f"{rule_type} is not a loadable Malaysia table.")
    pack = _pack(db, pack_row_id)
    _require_editable_pack(pack)
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("A statutory change needs a change reason.")
    problems = (validate_holidays(rows, pack) if rule_type == content.MY_PUBLIC_HOLIDAY_RULE
                else validate_schedule(rule_type, rows))
    for n, row in enumerate(rows, start=1):
        try:
            _source(db, row.get("source_document_id"), verify=False)
        except BadRequestException as exc:
            problems.append(f"row {n}: {exc.detail if hasattr(exc, 'detail') else exc}")
    if problems:
        raise BadRequestException("; ".join(problems[:10]) + (f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""))
    old_count = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == rule_type,
                                          TaxSlab.organization_id.is_(None)).delete())
    order = 10000 + 1000 * TABLE_RULES.index(rule_type)
    written = 0
    for row in rows:
        page = str(row.get("page") or "").strip()[:40]
        source_id = int(row["source_document_id"])
        if rule_type == content.MY_PUBLIC_HOLIDAY_RULE:
            order += 1
            db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=MY,
                           rule_type=rule_type, min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"),
                           jurisdiction_state=row.get("holiday_state"),
                           rate_label=mys.pending_label(row["name"].strip(), 150),
                           tax_formula=f"{row['date'].isoformat()} p.{page}"[:150],
                           source_document_id=source_id, sort_order=order))
            written += 1
            continue
        for side, amount in (("EMPLOYEE", row["employee_amount"]), ("EMPLOYER", row["employer_amount"])):
            order += 1
            top = "open" if row["wage_to"] is None else format(row["wage_to"], "f")
            db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=MY,
                           rule_type=rule_type, filing_status=row["member_class"], tax_regime=side,
                           min_amount=row["wage_from"], max_amount=row["wage_to"], rate_pct=Decimal("0"),
                           flat_amount=amount,
                           rate_label=mys.pending_label(
                               f"{rule_type} {row['member_class']} {side} {format(row['wage_from'], 'f')}-{top}", 150),
                           tax_formula=f"{row['member_class']} {side} p.{page}"[:150],
                           source_document_id=source_id, sort_order=order))
            written += 1
    _audit(db, pack, actor_id, "my_statutory_table", pack.id, {"ruleType": rule_type, "rows": old_count},
           {"ruleType": rule_type, "rows": written, "signed": False}, reason)
    return written


def sign_rows(db: Session, refs: list, actor_id, reason: str, source_document_id=None) -> dict:
    """Sign many rows at once through update_row (specialistVerified). All or
    nothing: the first refusal raises, and the caller's transaction must be
    rolled back (the API layer commits only on success)."""
    if not refs:
        raise BadRequestException("Choose at least one row to sign.")
    signed = []
    for ref in refs:
        kind, row_id = ref.get("kind"), ref.get("id")
        source_id = ref.get("sourceDocumentId", source_document_id)
        if source_id is None:
            from app.modules.payroll.models import ContributionRate, TaxSlab

            model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
            row = db.get(model, row_id) if model is not None else None
            source_id = getattr(row, "source_document_id", None)
        signed.append(update_row(db, kind, row_id, {"reason": reason, "sourceDocumentId": source_id,
                                                    "specialistVerified": True}, actor_id))
    return {"signed": len(signed), "rows": signed}
