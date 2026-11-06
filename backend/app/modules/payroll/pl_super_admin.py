"""Poland Super Admin signing console (ZP-PL-ENG-001 Phase 7a; spec §12
"Statutory content console", gate G1). Same governance as the New Zealand
console (nz_super_admin.py):

  1. A Super Admin edits a canonical PL row on an editable pack version with a
     change reason and an existing source document. Text rows must use the
     engine's own vocabulary, so a value the engine cannot read is refused
     here, not at payroll time. A policy the specification does not define
     (night supplement, leave-pay reference, fund exemptions, PIT remittance
     due date, ...) can be signed as NOT_SUPPORTED: the decision is recorded
     and the engine keeps blocking that feature.
  2. "Specialist verified" needs a stored, hashed source reviewed by a Super
     Admin other than its uploader; only then is the "[PENDING G1]" marker
     removed. A value changed without verification is (re)marked pending.
  3. Every editor of the version is recorded (statutory_editors), so the
     platform's pack approval refuses all of them; activation still refuses
     while any row is pending or empty (pl_pack_activation_refusal).

No migration: rows are the existing ContributionRate / TaxSlab rows of the PL
pack, audited through record_tax_audit.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import poland_service as pls

PL = "PL"
MARK = "[PENDING G1]"
NOT_SUPPORTED = "NOT_SUPPORTED"
AUDIT_TYPES = ("pl_statutory_rate", "pl_statutory_slab")
_LEGAL = "PL statutory configuration (ZP-PL-ENG-001)"
TREATMENTS = ("INCLUDED", "EXCLUDED", "REVIEW")


def _content():
    return pls._content()


def _vocabulary() -> dict:
    """text key -> validator(value) returning an error message or None."""
    from app.modules.payroll.engine.jurisdictions.poland.pack import ROUNDING_RULES

    content = _content()

    def one_of(*allowed):
        return lambda v: None if v in allowed else f"must be one of: {', '.join(allowed)}"

    def listed(allowed):
        def check(v):
            items = [p.strip() for p in v.split(",") if p.strip()]
            bad = [p for p in items if p not in allowed]
            return f"unknown value(s): {', '.join(bad)}" if bad or not items else None
        return check

    def premium_map(v):
        kinds = set()
        for part in [p.strip() for p in v.split(",") if p.strip()]:
            kind, _, pct = part.partition("=")
            if kind not in content.OVERTIME_EVENT_KINDS or pct not in ("50", "100"):
                return "must be KIND=50|100 pairs for " + ", ".join(content.OVERTIME_EVENT_KINDS)
            kinds.add(kind)
        return None if kinds == set(content.OVERTIME_EVENT_KINDS) else "must map every overtime event kind once"

    vocab = {key: one_of(*ROUNDING_RULES) for key in content.POLAND_PARAMETER_KEYS if key.startswith("pl_rounding_")}
    vocab.update({
        "pl_supported_pay_frequencies": listed(content.PAY_FREQUENCIES_SUPPORTED),
        "pl_supported_contract_types": listed(content.CONTRACT_TYPES_SUPPORTED),
        "pl_pit_social_deduction_rule": one_of("EMPLOYEE_SOCIAL_ONLY"),
        "pl_health_base_rule": one_of("GROSS_LESS_EMPLOYEE_SOCIAL"),
        "pl_health_limitation_rule": one_of(*content.HEALTH_LIMITATION_RULES),
        "pl_zus_contribution_year_start": lambda v: None if re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", v)
        else "must be MM-DD",
        "pl_fp_fs_min_base_rule": one_of(*content.FP_FS_MIN_BASE_RULES),
        "pl_fund_cap_rule": one_of(*content.FUND_CAP_RULES),
        "pl_ppk_employer_pit_treatment": one_of(*content.PPK_EMPLOYER_PIT_TREATMENTS),
        "pl_overtime_premium_map": premium_map,
        "pl_leave_part_time_rounding": one_of(*content.LEAVE_PART_TIME_ROUNDING),
        "pl_sick_full_rate_cases": listed(content.INCAPACITY_CATEGORIES),
        "pl_sick_age_rule": one_of(*content.SICK_AGE_RULES),
        "pl_zus_due_day_classes": one_of("5,15,20"),
        "pl_pit11_authority_due": one_of("END_JANUARY"),
        "pl_pit11_employee_due": one_of("END_FEBRUARY"),
        "pl_pit4r_due": one_of("END_JANUARY"),
        "pl_pit8ar_due": one_of("END_JANUARY"),
    })
    return vocab


def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or (pack.jurisdiction_country or "").upper() != PL or pack.pack_type != "tax":
        raise NotFoundException("Poland tax pack", pack_row_id)
    return pack


def _decimal(value, field: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal number.")


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


def _marked(label: Optional[str], signed: bool, limit: int) -> str:
    base = " ".join((label or "").replace(MARK, " ").split())
    if signed:
        return base[:limit]
    return (base[:limit - len(MARK) - 1] + " " + MARK).strip()


def _finish(db: Session, pack, actor_id, entity_type: str, entity_id: int, old: dict, new: dict, reason: str):
    from app.modules.payroll.service import _invalidate_pack_approval_on_edit, record_tax_audit

    _invalidate_pack_approval_on_edit(pack)
    if actor_id is not None:
        pack.updated_by_id = actor_id
    db.flush()
    record_tax_audit(db, actor_id=actor_id, action="update", entity_type=entity_type, entity_id=entity_id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=_LEGAL,
                     old_value=old, new_value=new, reason=reason, auto_commit=False)


def rate_view(row) -> dict:
    kind = _content().POLAND_PARAMETER_KEYS.get(row.component_key)
    return {"kind": "rate", "id": row.id, "componentKey": row.component_key, "label": row.label, "valueKind": kind,
            "employeeRatePct": pls._json_safe(row.employee_rate_pct), "employerRatePct": pls._json_safe(row.employer_rate_pct),
            "flatAmount": pls._json_safe(row.flat_amount), "textValue": row.text_value,
            "effectiveFrom": pls._json_safe(row.effective_from), "effectiveTo": pls._json_safe(row.effective_to),
            "sourceDocumentId": row.source_document_id, "signed": MARK not in (row.label or "")}


def slab_view(row) -> dict:
    return {"kind": "slab", "id": row.id, "ruleType": row.rule_type, "label": row.rate_label,
            "component": row.filing_status, "obligation": row.tax_regime, "treatment": row.assessment_basis,
            "minAmount": pls._json_safe(row.min_amount), "maxAmount": pls._json_safe(row.max_amount),
            "ratePct": pls._json_safe(row.rate_pct), "flatAmount": pls._json_safe(row.flat_amount),
            "sourceDocumentId": row.source_document_id, "signed": MARK not in (row.rate_label or "")}


RATE_FIELDS = {"employeeRatePct": "employee_rate_pct", "employerRatePct": "employer_rate_pct",
               "flatAmount": "flat_amount", "textValue": "text_value", "effectiveFrom": "effective_from",
               "effectiveTo": "effective_to"}
SLAB_FIELDS = {"minAmount": "min_amount", "maxAmount": "max_amount", "ratePct": "rate_pct", "flatAmount": "flat_amount"}


def _check_rate_kind(row, column: str, value) -> None:
    kind = _content().POLAND_PARAMETER_KEYS.get(row.component_key)
    slots = {"employee_pct": {"employee_rate_pct"}, "employer_pct": {"employer_rate_pct"},
             "pct_pair": {"employee_rate_pct", "employer_rate_pct"}, "amount": {"flat_amount"},
             "text": {"text_value"}}.get(kind, set())
    if value is not None and column not in slots | {"effective_from", "effective_to"}:
        raise BadRequestException(f"{row.component_key} holds a {kind} value, not {column}.")


def update_row(db: Session, kind: str, row_id: int, data: dict, actor_id) -> dict:
    """Edit and/or sign one canonical PL row of an editable pack version."""
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
    if model is None:
        raise BadRequestException("kind must be 'rate' or 'slab'.")
    data = dict(data or {})
    row = db.get(model, row_id)
    if row is None or row.organization_id is not None or (row.jurisdiction_country or "").upper() != PL:
        raise NotFoundException("Poland statutory row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = _reason(data)
    verify = data.get("specialistVerified") is True
    source = _source(db, data, verify)
    allowed = dict(RATE_FIELDS if kind == "rate" else SLAB_FIELDS)
    if kind == "slab" and row.rule_type == content.PL_EARNING_CLASS_RULE:
        allowed = {"treatment": "assessment_basis"}
    unknown = set(data) - set(allowed) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not editable here: {', '.join(sorted(unknown))}")

    old, new, changed = {}, {}, False
    for name, column in allowed.items():
        if name not in data:
            continue
        value = data[name]
        if column.startswith("effective_"):
            value = pls._as_date(value, name) if value else None
        elif column == "assessment_basis":
            value = str(value or "").strip().upper()
            if value not in TREATMENTS:
                raise BadRequestException(f"treatment must be one of: {', '.join(TREATMENTS)}.")
        elif column == "text_value":
            value = str(value).strip().upper() if value not in (None, "") else None
        else:
            value = _decimal(value, name)
            if value is not None and value < 0:
                raise BadRequestException(f"{name} cannot be negative.")
        if kind == "rate":
            _check_rate_kind(row, column, value)
            if column == "text_value" and value is not None and value != NOT_SUPPORTED:
                check = _vocabulary().get(row.component_key)
                problem = check(value) if check else "has no signed vocabulary yet: sign it NOT_SUPPORTED"
                if problem:
                    raise BadRequestException(f"{row.component_key} {problem}.")
        old[name], new[name] = pls._json_safe(getattr(row, column)), pls._json_safe(value)
        if getattr(row, column) != value:
            changed = True
        setattr(row, column, value)
    if kind == "slab" and row.rule_type == content.PL_PIT_BAND_RULE and row.max_amount is not None \
            and row.max_amount <= row.min_amount:
        raise BadRequestException("a PIT band must end above where it starts.")
    start, end = row.effective_from or pack.effective_from, row.effective_to or pack.effective_to
    if start and end and end < start:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")
    if kind == "rate" and verify and row.flat_amount is None and not row.text_value \
            and row.employee_rate_pct is None and row.employer_rate_pct is None:
        raise BadRequestException(f"{row.component_key} has no value: fill it before signing.")
    if kind == "rate" and verify and (row.text_value or "") == "PENDING_G1":
        raise BadRequestException(f"{row.component_key} is still PENDING_G1: choose a value or NOT_SUPPORTED.")
    label_col = "label" if kind == "rate" else "rate_label"
    was_signed = MARK not in (getattr(row, label_col) or "")
    signed = verify or (was_signed and not changed)
    setattr(row, label_col, _marked(getattr(row, label_col), signed, 100 if kind == "rate" else 150))
    if kind == "rate":
        ee = f"{row.employee_rate_pct}%" if row.employee_rate_pct is not None else "—"
        er = f"{row.employer_rate_pct}%" if row.employer_rate_pct is not None else "—"
        row.employee_share, row.employer_share = ee[:50], er[:50]
        if row.employee_rate_pct is not None or row.employer_rate_pct is not None:
            total = " / ".join(s for s in (ee, er) if s != "—")
        elif row.text_value:
            total = row.text_value
        elif row.flat_amount is None:
            total = pls.NOT_CONFIGURED
        else:
            total = str(row.flat_amount)
        row.total = total[:50]
    old["signed"], new["signed"] = was_signed, signed
    old["sourceDocumentId"], new["sourceDocumentId"] = row.source_document_id, source.id
    row.source_document_id = source.id
    _finish(db, pack, actor_id, f"pl_statutory_{kind}", row.id, old, new, reason)
    return rate_view(row) if kind == "rate" else slab_view(row)


def configuration(db: Session, pack_row_id: int) -> dict:
    """Every canonical row of a PL pack for the console (grouped by the UI)."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = _pack(db, pack_row_id)
    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.sort_order, ContributionRate.id).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.sort_order, TaxSlab.id).all())
    content = _content()
    basis = {row[0]: row[10] for row in content.POLAND_SCALAR_CONTENT}
    return {"packRowId": pack.id, "packId": pack.pack_id, "status": pack.status,
            "rates": [{**rate_view(r), "dateBasis": basis.get(r.component_key),
                       "vocabulary": r.component_key in _vocabulary()} for r in rates],
            "pitBands": [slab_view(s) for s in slabs if s.rule_type == content.PL_PIT_BAND_RULE],
            "earningClasses": [slab_view(s) for s in slabs if s.rule_type == content.PL_EARNING_CLASS_RULE]}


def signing_status(db: Session, pack_row_id: int) -> dict:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = _pack(db, pack_row_id)
    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None)).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    pending_slabs = {}
    for s in slabs:
        if MARK in (s.rate_label or ""):
            pending_slabs[s.rule_type] = pending_slabs.get(s.rule_type, 0) + 1
    return {"packId": pack.pack_id, "packRowId": pack.id, "version": pack.version, "status": pack.status,
            "pendingRates": sorted(r.component_key for r in rates if MARK in (r.label or "")),
            "emptyValues": sorted(r.component_key for r in rates if r.flat_amount is None and not r.text_value
                                  and r.employee_rate_pct is None and r.employer_rate_pct is None),
            "pendingPolicies": sorted(r.component_key for r in rates if (r.text_value or "") == "PENDING_G1"),
            "notSupported": sorted(r.component_key for r in rates if (r.text_value or "") == NOT_SUPPORTED),
            "reviewClasses": sum(1 for s in slabs if s.rule_type == _content().PL_EARNING_CLASS_RULE
                                 and s.assessment_basis == "REVIEW"),
            "pendingSlabsByRuleType": pending_slabs, "editors": sorted(statutory_editors(db, pack)),
            "activationRefusal": pls.pl_pack_activation_refusal(db, pack)}


def statutory_editors(db: Session, pack) -> set:
    from app.modules.payroll.models import TaxConfigurationAudit as A

    rows = (db.query(A.actor_id).filter(A.jurisdiction_pack_id == pack.id, A.entity_type.in_(AUDIT_TYPES),
                                        A.actor_id.isnot(None)).distinct().all())
    return {r[0] for r in rows}


def list_packs(db: Session) -> list:
    from app.modules.payroll.models import JurisdictionPack

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == PL)
             .order_by(JurisdictionPack.effective_from, JurisdictionPack.id).all())
    return [{"id": p.id, "packId": p.pack_id, "version": p.version, "packType": p.pack_type, "status": p.status,
             "effectiveFrom": pls._json_safe(p.effective_from), "effectiveTo": pls._json_safe(p.effective_to),
             "approvedById": p.approved_by_id, "updatedById": p.updated_by_id} for p in packs]


def seed_draft(db: Session, data: dict, actor_id) -> dict:
    """Create the Draft PL-PAYROLL-2026 pack and the PLANNED registry row from
    poland_content.py inside the deployed app (no shell, no environment
    file) — only while no Poland pack exists. Audited."""
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.service import record_tax_audit

    reason = _reason(data)
    existing = [p.pack_id for p in db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == PL)]
    if existing:
        raise BadRequestException(f"Poland content is already seeded ({', '.join(existing)}); change it through "
                                  "the signing console instead.")
    pack = pls.seed_poland_pack(db)
    availability = pls.ensure_pl_service_registry_row(db)
    record_tax_audit(db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=pls.SPEC,
                     old_value=None, new_value={"status": pack.status, "availability": availability},
                     reason=f"{reason} — canonical {pack.pack_id} seeded as Draft from {pls.SPEC} (Super Admin console).",
                     auto_commit=False)
    db.flush()
    return {"pack": list_packs(db), "availability": availability}
