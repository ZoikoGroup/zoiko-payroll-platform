"""Belgium Super Admin signing console (ZP-BE-ENG-001 Phase 3A; spec §14
"Content control": no single-person production publication of statutory
content). Same governance as the Poland and New Zealand consoles:

  1. A Super Admin edits a canonical BE row of an EDITABLE pack version
     (shared service._require_editable_pack) with a change reason and an
     existing source document. Text rows must use the key's own vocabulary
     (belgium_content); a key with no vocabulary yet can only be signed
     NOT_SUPPORTED, which records the decision while the engine keeps blocking.
  2. "Specialist verified" needs a stored, hashed source reviewed by a Super
     Admin other than its uploader (and not itself marked UNVERIFIED); only
     then is "[PENDING G1]" removed. A value changed without verification is
     re-marked pending.
  3. Every edit invalidates the pack's approval (shared
     service._invalidate_pack_approval_on_edit) and is audited (shared
     service.record_tax_audit) as be_statutory_rate / be_statutory_slab; every
     editor is returned by statutory_editors, so the SHARED pack approval
     (statutory_editors hook + _SELF_APPROVAL_REFUSED / _APPROVER_NOT_ACTIVATOR
     lists) refuses all of them, and the approver can never activate.
     Activation still refuses while any row is empty, unsourced or unsigned
     (belgium_service.be_pack_activation_refusal).

onss_employer rate / band rows are REFERENCE ONLY (BE-015 / BE-019): every view
carries `referenceOnly` and `referenceNote`; no view presents an all-in rate.
No migration: rows are the existing ContributionRate / TaxSlab rows.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as bes

BE = "BE"
AUDIT_TYPES = ("be_statutory_rate", "be_statutory_slab")
_LEGAL = "BE statutory configuration (ZP-BE-ENG-001)"


def _content():
    from app.modules.payroll.engine.countries import belgium_content as content

    return content


def _safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


# ── shared building blocks ────────────────────────────────────────────────
def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or (pack.jurisdiction_country or "").upper() != BE or pack.pack_type != "tax":
        raise NotFoundException("Belgium tax pack", pack_row_id)
    return pack


def _reason(data: dict) -> str:
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A statutory change needs a change reason.")
    return reason[:300]


def _source(db: Session, data: dict, verify: bool):
    from app.modules.payroll.models import SourceArtifact

    source_id = data.get("sourceDocumentId")
    source = db.get(SourceArtifact, int(source_id)) if source_id not in (None, "") else None
    if source is None:
        raise BadRequestException("A statutory change needs the official source document (an existing SourceArtifact).")
    if verify and not (source.checksum_sha256 and source.file_path and source.reviewer_id
                       and source.reviewer_id != source.created_by_id and "[UNVERIFIED" not in (source.title or "")):
        raise BadRequestException("Signing needs a stored, hashed source document reviewed by a Super Admin other "
                                  "than its uploader (and not itself marked UNVERIFIED).")
    return source


def _decimal(value, name: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{name} must be a decimal number.")


def _marked(label: Optional[str], signed: bool, limit: int) -> str:
    mark = _content().PENDING_MARK
    base = " ".join((label or "").replace(mark, " ").split())
    if signed:
        return base[:limit]
    return (base[:limit - len(mark) - 1] + " " + mark).strip()


def _finish(db: Session, pack, actor_id, entity_type: str, entity_id: int, old: dict, new: dict, reason: str):
    """Shared governance: approval invalidated on edit, editor recorded, audited."""
    from app.modules.payroll.service import _invalidate_pack_approval_on_edit, record_tax_audit

    _invalidate_pack_approval_on_edit(pack)
    if actor_id is not None:
        pack.updated_by_id = actor_id
    db.flush()
    record_tax_audit(db, actor_id=actor_id, action="update", entity_type=entity_type, entity_id=entity_id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=_LEGAL,
                     old_value=old, new_value=new, reason=reason, auto_commit=False)


# ── views ─────────────────────────────────────────────────────────────────
def rate_view(row) -> dict:
    content = _content()
    group, kind, ref, _label = content.KEYS.get(row.component_key, (None, None, None, None))
    view = {"kind": "rate", "id": row.id, "componentKey": row.component_key, "label": row.label, "group": group,
            "valueKind": kind, "specReference": ref,
            "employeeRatePct": _safe(row.employee_rate_pct), "employerRatePct": _safe(row.employer_rate_pct),
            "flatAmount": _safe(row.flat_amount), "textValue": row.text_value,
            "effectiveFrom": _safe(row.effective_from), "effectiveTo": _safe(row.effective_to),
            "sourceDocumentId": row.source_document_id, "signed": content.PENDING_MARK not in (row.label or ""),
            "referenceOnly": False}
    if row.component_key in content.KEYS and content.is_reference_only(row.component_key):
        view.update({"referenceOnly": True, "referenceNote": content.REFERENCE_NOTE})
    return view


def slab_view(row) -> dict:
    return {"kind": "slab", "id": row.id, "ruleType": row.rule_type, "label": row.rate_label,
            "component": row.filing_status, "obligation": row.tax_regime, "treatment": row.assessment_basis,
            "minAmount": _safe(row.min_amount), "maxAmount": _safe(row.max_amount), "ratePct": _safe(row.rate_pct),
            "flatAmount": _safe(row.flat_amount), "taxFormula": row.tax_formula,
            "effectiveFrom": _safe(row.effective_from), "effectiveTo": _safe(row.effective_to),
            "sourceDocumentId": row.source_document_id,
            "signed": _content().PENDING_MARK not in (row.rate_label or "")}


# ── vocabulary ────────────────────────────────────────────────────────────
def _text_problem(key: str, kind: str, value: str) -> Optional[str]:
    """None when `value` is a valid signed text for `key`, else the reason."""
    content = _content()
    if value == content.NOT_SUPPORTED:
        return None
    if kind in content.SLAB_KINDS:
        return None if value == content.SLAB_ROWS else f"must be {content.SLAB_ROWS} or {content.NOT_SUPPORTED}"
    if kind == content.KIND_DATE:
        try:
            date.fromisoformat(value)
            return None
        except ValueError:
            return f"must be an ISO date (YYYY-MM-DD) or {content.NOT_SUPPORTED}"
    if key in content.CODE_LIST_KEYS:
        items = [p.strip() for p in value.split(",") if p.strip()]
        bad = [p for p in items if not content.CODE_PATTERN.fullmatch(p)]
        return f"must be a comma-separated list of codes (letters / digits); bad: {', '.join(bad) or '(none)'}" \
            if bad or not items or len(set(items)) != len(items) else None
    if key in content.LIST_VOCABULARIES:
        allowed = content.LIST_VOCABULARIES[key]
        items = [p.strip() for p in value.split(",") if p.strip()]
        bad = [p for p in items if p not in allowed]
        return f"unknown value(s): {', '.join(bad) or '(none)'}; allowed: {', '.join(allowed)}" \
            if bad or not items else None
    if key in content.CHOICE_VOCABULARIES:
        allowed = content.CHOICE_VOCABULARIES[key]
        return None if value in allowed else f"must be one of: {', '.join(allowed)}"
    return f"has no signed vocabulary yet: sign it {content.NOT_SUPPORTED}"


RATE_FIELDS = {"employeeRatePct": "employee_rate_pct", "employerRatePct": "employer_rate_pct",
               "flatAmount": "flat_amount", "textValue": "text_value", "effectiveFrom": "effective_from",
               "effectiveTo": "effective_to"}
SLAB_FIELDS = {"minAmount": "min_amount", "maxAmount": "max_amount", "ratePct": "rate_pct",
               "flatAmount": "flat_amount", "taxFormula": "tax_formula", "effectiveFrom": "effective_from",
               "effectiveTo": "effective_to"}
_KIND_SLOTS = {"rate": {"employee_rate_pct", "employer_rate_pct"}, "amount": {"flat_amount"},
               "text-choice": {"text_value"}, "date": {"text_value"}, "band": {"text_value"},
               "formula": {"text_value"}, "table": {"text_value"}}


def _parse(column: str, value, name: str):
    if column.startswith("effective_"):
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            raise BadRequestException(f"{name} must be an ISO date.")
    if column in ("text_value", "assessment_basis"):
        return str(value).strip().upper() if value not in (None, "") else None
    if column == "tax_formula":
        return str(value or "").strip()[:150]
    parsed = _decimal(value, name)
    if parsed is not None and parsed < 0:
        raise BadRequestException(f"{name} cannot be negative.")
    return parsed


def update_row(db: Session, kind: str, row_id: int, data: dict, actor_id) -> dict:
    """Edit and/or sign one canonical BE row of an editable pack version."""
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
    if model is None:
        raise BadRequestException("kind must be 'rate' or 'slab'.")
    data = dict(data or {})
    row = db.get(model, row_id)
    if row is None or row.organization_id is not None or (row.jurisdiction_country or "").upper() != BE:
        raise NotFoundException("Belgium statutory row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = _reason(data)
    verify = data.get("specialistVerified") is True
    source = _source(db, data, verify)
    if kind == "slab" and row.rule_type == content.AUTHORITY_EXAMPLE_RULE:
        raise BadRequestException("Authority examples are registered, never edited in place.")
    allowed = dict(RATE_FIELDS if kind == "rate" else SLAB_FIELDS)
    if kind == "slab" and row.rule_type == content.EARNING_CLASS_RULE:
        allowed = {"treatment": "assessment_basis"}
    unknown = set(data) - set(allowed) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not editable here: {', '.join(sorted(unknown))}")
    key_kind = content.KEYS.get(row.component_key, (None, None))[1] if kind == "rate" else None

    old, new, changed = {}, {}, False
    for name, column in allowed.items():
        if name not in data:
            continue
        value = _parse(column, data[name], name)
        if column == "assessment_basis" and value not in content.TREATMENTS:
            raise BadRequestException(f"treatment must be one of: {', '.join(content.TREATMENTS)}.")
        not_supported = column == "text_value" and value == content.NOT_SUPPORTED
        if kind == "rate" and value is not None and not column.startswith("effective_") and not not_supported \
                and column not in _KIND_SLOTS.get(key_kind, set()):
            raise BadRequestException(f"{row.component_key} holds a {key_kind} value, not {column}.")
        if kind == "rate" and column == "text_value" and value is not None:
            problem = _text_problem(row.component_key, key_kind, value)
            if problem:
                raise BadRequestException(f"{row.component_key} {problem}.")
        old[name], new[name] = _safe(getattr(row, column)), _safe(value)
        if getattr(row, column) != value:
            changed = True
        setattr(row, column, value)
    start, end = row.effective_from or pack.effective_from, row.effective_to or pack.effective_to
    if start and end and end < start:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")
    if kind == "rate" and verify and bes._row_empty(row, key_kind):
        raise BadRequestException(f"{row.component_key} has no value: fill it (or sign NOT_SUPPORTED) before signing.")
    label_col = "label" if kind == "rate" else "rate_label"
    was_signed = content.PENDING_MARK not in (getattr(row, label_col) or "")
    signed = verify or (was_signed and not changed)
    setattr(row, label_col, _marked(getattr(row, label_col), signed, 100 if kind == "rate" else 150))
    if kind == "rate":
        # Display columns only; an onss_employer row never shows a total rate.
        row.total = ("REFERENCE ONLY" if content.is_reference_only(row.component_key)
                     else (row.text_value or (str(row.flat_amount) if row.flat_amount is not None else "—")))[:50]
    old["signed"], new["signed"] = was_signed, signed
    old["sourceDocumentId"], new["sourceDocumentId"] = row.source_document_id, source.id
    row.source_document_id = source.id
    _finish(db, pack, actor_id, f"be_statutory_{kind}", row.id, old, new, reason)
    return rate_view(row) if kind == "rate" else slab_view(row)


# ── read models ───────────────────────────────────────────────────────────
def _rows(db: Session, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.sort_order, ContributionRate.id).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.sort_order, TaxSlab.id).all())
    return rates, slabs


def configuration(db: Session, pack_row_id: int) -> dict:
    """Every canonical row of a BE pack, grouped by catalogue group."""
    content = _content()
    pack = _pack(db, pack_row_id)
    rates, slabs = _rows(db, pack)
    groups = {g: {"label": content.CATEGORY_LABELS[g], "rows": []} for g in content.GROUPS}
    for r in rates:
        view = rate_view(r)
        if view["group"] in groups:
            groups[view["group"]]["rows"].append(view)
    return {"packRowId": pack.id, "packId": pack.pack_id, "status": pack.status, "groups": groups,
            "groupOrder": list(content.GROUPS), "vocabulary": vocabulary(), "slabSpecs": slab_specs(),
            "earningClass": {"treatments": list(content.TREATMENTS), "obligations": list(content.OBLIGATIONS),
                             "components": list(content.COMPONENTS), "ruleType": content.EARNING_CLASS_RULE},
            "sourcePrefix": "ZP-BE-ENG-001 ",
            "slabRows": {rule: [slab_view(s) for s in slabs if s.rule_type == rule]
                         for rule in sorted(set(content.RULE_TYPES.values()))},
            "earningClasses": [slab_view(s) for s in slabs if s.rule_type == content.EARNING_CLASS_RULE],
            "authorityExamples": [slab_view(s) for s in slabs if s.rule_type == content.AUTHORITY_EXAMPLE_RULE]}


def vocabulary() -> dict:
    """key -> how a signed text value is chosen, for the console UI (no value
    lists live in the frontend). NOT_SUPPORTED is always offered."""
    content = _content()
    out = {}
    for key, (_group, kind, _ref, _label) in content.KEYS.items():
        if key in content.LIST_VOCABULARIES:
            out[key] = {"mode": "list", "choices": list(content.LIST_VOCABULARIES[key])}
        elif key in content.CHOICE_VOCABULARIES:
            out[key] = {"mode": "choice", "choices": list(content.CHOICE_VOCABULARIES[key])}
        elif key in content.CODE_LIST_KEYS:
            out[key] = {"mode": "codes", "choices": []}
        elif kind in content.SLAB_KINDS:
            out[key] = {"mode": "choice", "choices": [content.SLAB_ROWS]}
        elif kind == content.KIND_DATE:
            out[key] = {"mode": "date", "choices": []}
        elif kind == content.KIND_TEXT:
            out[key] = {"mode": "choice", "choices": []}
        else:
            out[key] = {"mode": "value", "choices": []}
        out[key]["notSupported"] = content.NOT_SUPPORTED
    return out


def slab_specs() -> dict:
    content = _content()
    return {key: {"kind": spec["kind"], "ruleType": content.RULE_TYPES[key], "fields": list(spec["fields"]),
                  "dimensions": list(spec["dimensions"])} for key, spec in content.SLAB_SPECS.items()}


def signing_status(db: Session, pack_row_id: int) -> dict:
    content = _content()
    pack = _pack(db, pack_row_id)
    rates, slabs = _rows(db, pack)
    kinds = {k: v[1] for k, v in content.KEYS.items()}
    return {"packId": pack.pack_id, "packRowId": pack.id, "version": pack.version, "status": pack.status,
            "pendingRates": sorted(r.component_key for r in rates if content.PENDING_MARK in (r.label or "")),
            "emptyValues": sorted(r.component_key for r in rates
                                  if bes._row_empty(r, kinds.get(r.component_key, "text-choice"))),
            "unsourced": sorted(r.component_key for r in rates if r.source_document_id is None),
            "notSupported": sorted(r.component_key for r in rates if (r.text_value or "") == content.NOT_SUPPORTED),
            "reviewClasses": sum(1 for s in slabs if s.rule_type == content.EARNING_CLASS_RULE
                                 and s.assessment_basis == "REVIEW"),
            "editors": sorted(statutory_editors(db, pack)),
            "activationRefusal": bes.be_pack_activation_refusal(db, pack)}


def statutory_editors(db: Session, pack) -> set:
    from app.modules.payroll.models import TaxConfigurationAudit as A

    rows = (db.query(A.actor_id).filter(A.jurisdiction_pack_id == pack.id, A.entity_type.in_(AUDIT_TYPES),
                                        A.actor_id.isnot(None)).distinct().all())
    return {r[0] for r in rows}


def list_packs(db: Session) -> list:
    from app.modules.payroll.models import JurisdictionPack

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == BE)
             .order_by(JurisdictionPack.effective_from, JurisdictionPack.id).all())
    return [{"id": p.id, "packId": p.pack_id, "version": p.version, "packType": p.pack_type, "status": p.status,
             "effectiveFrom": _safe(p.effective_from), "effectiveTo": _safe(p.effective_to),
             "approvedById": p.approved_by_id, "updatedById": p.updated_by_id} for p in packs]


def seed_draft(db: Session, data: dict, actor_id) -> dict:
    """Create the Draft BE-PAYROLL-2026 pack and the PLANNED registry row from
    belgium_content.py inside the deployed app — only while no Belgian pack
    exists. Reason required; audited."""
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.service import record_tax_audit

    reason = _reason(data or {})
    existing = [p.pack_id for p in db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == BE)]
    if existing:
        raise BadRequestException(f"Belgium content is already seeded ({', '.join(existing)}); change it through "
                                  "the signing console instead.")
    pack = bes.seed_belgium_pack(db)
    availability = bes.ensure_be_service_registry_row(db)
    record_tax_audit(db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=bes.SPEC,
                     old_value=None, new_value={"status": pack.status, "availability": availability},
                     reason=f"{reason} — canonical {pack.pack_id} seeded as Draft from {bes.SPEC} (Super Admin console).",
                     auto_commit=False)
    db.flush()
    return {"pack": list_packs(db), "availability": availability}


_EXAMPLE_NAME = re.compile(r"^[A-Za-z0-9 _.-]{1,20}$")


# ── Phase 3B: governed slab rows of band / formula / table keys ───────────
SLAB_ROW_FIELDS = ("minAmount", "maxAmount", "ratePct", "flatAmount", "formulaText", "name", "date", "dimension",
                   "effectiveFrom", "effectiveTo")


def _signed_codes(db: Session, pack, key: str) -> set:
    """The signed code list of `key` in `pack` (refuses when not signed)."""
    content = _content()
    row = _rate_row(db, pack, key)
    text = (row.text_value or "").strip().upper() if row is not None else ""
    if row is None or content.PENDING_MARK in (row.label or "") or not text or text == content.NOT_SUPPORTED:
        raise BadRequestException(f"{key} is not signed yet: sign the supported code list before adding rows "
                                  "that reference it.")
    return {p.strip() for p in text.split(",") if p.strip()}


def _rate_row(db: Session, pack, key: str):
    from app.modules.payroll.models import ContributionRate

    return (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.organization_id.is_(None),
                                              ContributionRate.component_key == key).first())


def add_slab_row(db: Session, pack_row_id: int, key: str, data: dict, actor_id) -> dict:
    """Create one slab row of a band / formula / table key (rule_type BE_<KEY>)
    on an editable pack version. Reason + source required; the row starts
    "[PENDING G1]" unless signed with a reviewed archived source (same rule as
    scalar rows); approval invalidated, editor recorded, audited."""
    from app.modules.payroll.models import TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    spec = content.SLAB_SPECS.get(str(key or "").strip().lower())
    if spec is None:
        raise BadRequestException("Slab rows can be added only to Belgian band / formula / table keys.")
    key = str(key).strip().lower()
    pack = _pack(db, pack_row_id)
    _require_editable_pack(pack)
    data = dict(data or {})
    reason = _reason(data)
    verify = data.get("specialistVerified") is True
    source = _source(db, data, verify)
    unknown = set(data) - set(SLAB_ROW_FIELDS) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not a field of a {key} row: {', '.join(sorted(unknown))}")
    missing = [f for f in spec["fields"] if data.get(f) in (None, "")]
    if spec["kind"] == content.KIND_BAND and data.get("ratePct") in (None, "") and data.get("flatAmount") in (None, ""):
        missing.append("ratePct or flatAmount")
    if missing:
        raise BadRequestException(f"{key} needs: {', '.join(missing)}")

    dimension = None
    if spec["dimensions"] or data.get("dimension"):
        try:
            parts = content.parse_dimension(data.get("dimension"))
        except ValueError as exc:
            raise BadRequestException(f"{key} dimension: {exc}.")
        if set(parts) != set(spec["dimensions"]):
            raise BadRequestException(f"{key} rows need exactly the dimensions "
                                      f"{', '.join(spec['dimensions']) or '(none)'}.")
        for name, value in parts.items():
            if name in content.DIMENSION_LISTS:
                codes = _signed_codes(db, pack, content.DIMENSION_LISTS[name])
                if value not in codes:
                    raise BadRequestException(f"{name}={value} is not in the signed "
                                              f"{content.DIMENSION_LISTS[name]} list.")
        dimension = content.format_dimension(**parts) or None

    numbers = {name: _decimal(data.get(name), name) for name in ("minAmount", "maxAmount", "ratePct", "flatAmount")}
    if any(v is not None and v < 0 for v in numbers.values()):
        raise BadRequestException("Amounts and rates cannot be negative.")
    if numbers["maxAmount"] is not None and numbers["minAmount"] is not None and numbers["maxAmount"] <= numbers["minAmount"]:
        raise BadRequestException("maxAmount must be above minAmount.")
    start = _parse("effective_from", data.get("effectiveFrom"), "effectiveFrom")
    end = _parse("effective_to", data.get("effectiveTo"), "effectiveTo")
    name = " ".join(str(data.get("name") or key).split())
    if spec["kind"] == content.KIND_TABLE:
        day = _parse("effective_from", data.get("date"), "date")
        if (pack.effective_from and day < pack.effective_from) or (pack.effective_to and day > pack.effective_to):
            raise BadRequestException(f"{day.isoformat()} is outside the pack window "
                                      f"({_safe(pack.effective_from)} to {_safe(pack.effective_to)}).")
        start, end = day, day
    if start and end and end < start:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")
    formula = " ".join(str(data.get("formulaText") or "").split()) or None

    row = TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=BE,
                  rule_type=content.RULE_TYPES[key], filing_status=dimension,
                  min_amount=numbers["minAmount"] if numbers["minAmount"] is not None else Decimal("0"),
                  max_amount=numbers["maxAmount"],
                  rate_pct=numbers["ratePct"] if numbers["ratePct"] is not None else Decimal("0"),
                  flat_amount=numbers["flatAmount"], formula_expression=formula,
                  tax_formula=name[:150], rate_label=_marked(f"{key}: {name}", verify, 150),
                  effective_from=start, effective_to=end, source_document_id=source.id, sort_order=0)
    db.add(row)
    db.flush()
    _finish(db, pack, actor_id, "be_statutory_slab", row.id, {}, {**slab_view(row), "action": "added",
                                                                   "signed": verify}, reason)
    return slab_view(row)


def _signer(db: Session, row_id: int):
    """The Super Admin whose audited edit last signed this slab row, or None."""
    from app.modules.payroll.models import TaxConfigurationAudit as A

    rows = (db.query(A).filter(A.entity_type == "be_statutory_slab", A.entity_id == row_id)
            .order_by(A.id.desc()).all())
    for audit in rows:
        new = audit.new_value if isinstance(audit.new_value, dict) else {}
        if new.get("signed") is True:
            return audit.actor_id
    return None


def retire_slab_row(db: Session, row_id: int, data: dict, actor_id) -> dict:
    """Hard-delete one band / formula / table slab row of a DRAFT pack (a Draft
    row was never in force). Reason required; the audit row keeps the full
    before-image (values, dates, source, signed state and signer). Refused on
    any non-Draft pack."""
    from app.modules.payroll.models import TaxSlab

    content = _content()
    row = db.get(TaxSlab, row_id)
    if row is None or row.organization_id is not None or (row.jurisdiction_country or "").upper() != BE \
            or row.rule_type not in set(content.RULE_TYPES.values()):
        raise NotFoundException("Belgium band / formula / table row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    if pack.status != "Draft":
        raise BadRequestException(f"Belgium pack {pack.pack_id} is {pack.status}: rows can be retired only from a "
                                  "Draft version.")
    reason = _reason(dict(data or {}))
    before = {**slab_view(row), "formulaExpression": row.formula_expression, "signedBy": _signer(db, row.id)}
    db.delete(row)
    _finish(db, pack, actor_id, "be_statutory_slab", row_id, before, {"action": "retired"}, reason)
    return {"id": row_id, "retired": True}


def joint_committees(db: Session) -> list:
    """Belgian Joint Committee CBA packs (payroll_collective_agreements, D3) with
    the committee / sub-committee parsed from agreement_code by the backend
    (the frontend never parses codes). Platform definitions only."""
    from app.modules.payroll.models import CollectiveAgreement

    content = _content()
    out = []
    rows = (db.query(CollectiveAgreement).filter(CollectiveAgreement.jurisdiction_country == BE,
                                                 CollectiveAgreement.organization_id.is_(None))
            .order_by(CollectiveAgreement.agreement_code, CollectiveAgreement.version).all())
    for r in rows:
        try:
            committee, sub, code_version = content.parse_be_agreement_code(r.agreement_code)
            valid = True
        except ValueError:
            committee, sub, code_version, valid = None, None, None, False
        out.append({"id": r.id, "agreementCode": r.agreement_code, "name": r.name, "version": r.version,
                    "status": r.status, "agreementType": r.agreement_type, "jointCommittee": committee,
                    "subCommittee": sub, "codeVersion": code_version, "codeValid": valid,
                    "effectiveFrom": _safe(r.effective_from), "effectiveTo": _safe(r.effective_to),
                    "sourceDocumentId": r.source_document_id, "approvedById": r.approved_by_id})
    return out


def add_authority_example(db: Session, pack_row_id: int, data: dict, actor_id) -> dict:
    """Register one official / independently prepared worked example (gate G1).
    REGISTER ONLY in Phase 3A: no engine exists to replay it (Phase 10 golden
    checks). Needs its reviewed source (the signing rule) and a reason."""
    from app.modules.payroll.models import TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    pack = _pack(db, pack_row_id)
    _require_editable_pack(pack)
    data = dict(data or {})
    unknown = set(data) - {"name", "description", "sourceDocumentId", "reason"}
    if unknown:
        raise BadRequestException(f"not a field of an authority example: {', '.join(sorted(unknown))}")
    reason = _reason(data)
    source = _source(db, data, verify=True)
    name = " ".join(str(data.get("name") or "").split())
    if not _EXAMPLE_NAME.fullmatch(name):
        raise BadRequestException("An authority example needs a short name (1-20 letters, digits, space, _ . -).")
    description = " ".join(str(data.get("description") or "").split())
    if not description:
        raise BadRequestException("An authority example needs a description of the worked case.")
    if db.query(TaxSlab.id).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                   TaxSlab.rule_type == content.AUTHORITY_EXAMPLE_RULE,
                                   TaxSlab.filing_status == name).first():
        raise BadRequestException(f"The pack already has an authority example named {name!r}.")
    row = TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=BE,
                  rule_type=content.AUTHORITY_EXAMPLE_RULE, min_amount=Decimal("0"), max_amount=None,
                  rate_pct=Decimal("0"), filing_status=name, rate_label=f"Authority example {name}"[:150],
                  tax_formula=description[:150], source_document_id=source.id, sort_order=9000)
    db.add(row)
    db.flush()
    _finish(db, pack, actor_id, "be_statutory_slab", row.id, {},
            {"ruleType": content.AUTHORITY_EXAMPLE_RULE, "name": name}, reason)
    return slab_view(row)
