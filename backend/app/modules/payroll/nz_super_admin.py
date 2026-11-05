"""New Zealand Super Admin signing console (ZP-NZ-ENG-001 Phase 7a; decision
2026-11-04: Option 1).

Super Admin-configured values drive the calculation only through governance:

  1. A Super Admin edits a canonical NZ row (or adds a row to an empty
     authority table) on an editable pack version, with a change reason and
     an existing source document. Text rows must use the engine's own
     vocabulary, so a value the engine cannot read is refused here, not at
     payroll time.
  2. Marking the change "specialist verified" needs a stored, hashed source
     reviewed by a Super Admin other than its uploader (the Hong Kong rule);
     only then is the "[PENDING G1]" marker removed: the row is SIGNED. A
     value changed without verification is (re)marked pending.
  3. Every editor of the version is recorded (statutory_editors), so the
     platform's pack approval refuses all of them; activation needs that
     distinct approver and nz_pack_activation_refusal still refuses while any
     row is pending or any authority table is empty.

No migration: rows are the existing ContributionRate / TaxSlab rows of the
NZ pack, audited through record_tax_audit.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs

NZ = "NZ"
MARK = "[PENDING G1]"
AUDIT_TYPES = ("nz_statutory_rate", "nz_statutory_slab", "nz_statutory_table_row")
_LEGAL = "NZ statutory configuration (ZP-NZ-ENG-001)"


def _content():
    return nzs._content()


def _mm_dd(value: str) -> bool:
    return bool(re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", value))


def _vocabulary() -> dict:
    """text key -> validator(value) returning an error message or None."""
    from app.modules.payroll.engine.jurisdictions.new_zealand import deduction_precedence as prec
    from app.modules.payroll.engine.jurisdictions.new_zealand import extra_pay, leave_pay
    from app.modules.payroll.engine.jurisdictions.new_zealand.pack import ROUNDING_RULES
    from app.modules.payroll.nz_lifecycle import CORRECTION_POLICY

    content = _content()

    def one_of(*allowed):
        return lambda v: None if v in allowed else f"must be one of: {', '.join(allowed)}"

    def frequencies(v):
        items = [p.strip() for p in v.split(",") if p.strip()]
        bad = [p for p in items if p not in content.PAY_FREQUENCIES]
        return f"unknown pay frequency: {', '.join(bad)}" if bad or not items else None

    def precedence(v):
        order = [p.strip() for p in v.split(",") if p.strip()]
        if sorted(order) != sorted(prec.STATUTORY):
            return f"must name each of {', '.join(prec.STATUTORY)} exactly once"
        if any(order.index("CHILD_SUPPORT") < order.index(t) for t in prec.TAX_LIKE):
            return "CHILD_SUPPORT must come after PAYE and ACC_LEVY"
        return None

    def rates(v):
        try:
            values = [Decimal(p.strip()) for p in v.split(",") if p.strip()]
        except InvalidOperation:
            return "must be comma-separated percentages"
        return None if values and all(0 < x <= 100 for x in values) else "must be percentages above 0"

    vocab = {key: one_of(*ROUNDING_RULES) for key in content.NZ_PARAMETER_KEYS if key.endswith("_rounding")}
    vocab.update({
        "nz_supported_pay_frequencies": frequencies,
        "nz_correction_policy": one_of(CORRECTION_POLICY),
        "nz_deduction_precedence": precedence,
        "nz_ks_employee_rates": rates,
        "nz_ks_rate_selection_basis": one_of("PAYDAY"),
        "nz_sl_secondary_basis": one_of("WHOLE_PAYMENT"),
        "nz_remit_december_second_half_due": lambda v: None if _mm_dd(v) else "must be MM-DD",
        "nz_hol_owp_method": one_of(leave_pay.OWP_METHOD),
        "nz_hol_rdp_method": one_of(leave_pay.RDP_METHOD),
        "nz_hol_adp_use_rule": one_of(leave_pay.ADP_RULE),
        "nz_hol_final_pay_unvested_method": one_of(leave_pay.UNVESTED_METHOD),
        "nz_out_of_cycle_paye_method": one_of("EXTRA_PAY", "PERIOD_MAIN"),
        "nz_lump_sum_paye_method": one_of(extra_pay.FOUR_WEEK_ANNUALISE),
        "nz_working_day_rule": one_of("WEEKDAYS_EXCL_PUBLIC_HOLIDAYS_AND_25DEC_15JAN"),
    })
    return vocab


# ── shared ──────────────────────────────────────────────────────────────────
def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or (pack.jurisdiction_country or "").upper() != NZ or pack.pack_type != "tax":
        raise NotFoundException("New Zealand tax pack", pack_row_id)
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
    return (base if signed else f"{base} {MARK}".strip())[:limit]


def _finish(db: Session, pack, actor_id, entity_type: str, entity_id: int, old: dict, new: dict, reason: str):
    from app.modules.payroll.service import _invalidate_pack_approval_on_edit, record_tax_audit

    _invalidate_pack_approval_on_edit(pack)
    if actor_id is not None:
        pack.updated_by_id = actor_id
    db.flush()
    record_tax_audit(db, actor_id=actor_id, action="update", entity_type=entity_type, entity_id=entity_id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=_LEGAL,
                     old_value=old, new_value=new, reason=reason, auto_commit=False)


def _rate_view(row) -> dict:
    return {"kind": "rate", "id": row.id, "componentKey": row.component_key, "label": row.label,
            "flatAmount": None if row.flat_amount is None else str(row.flat_amount), "textValue": row.text_value,
            "effectiveFrom": nzs._json_safe(row.effective_from), "effectiveTo": nzs._json_safe(row.effective_to),
            "sourceDocumentId": row.source_document_id, "signed": MARK not in (row.label or "")}


def _slab_view(row) -> dict:
    return {"kind": "slab", "id": row.id, "ruleType": row.rule_type, "label": row.rate_label,
            "filingStatus": row.filing_status, "taxRegime": row.tax_regime, "treatment": row.assessment_basis,
            "jurisdictionState": row.jurisdiction_state, "taxFormula": row.tax_formula,
            "minAmount": nzs._json_safe(row.min_amount), "maxAmount": nzs._json_safe(row.max_amount),
            "ratePct": nzs._json_safe(row.rate_pct), "flatAmount": nzs._json_safe(row.flat_amount),
            "effectiveFrom": nzs._json_safe(row.effective_from), "effectiveTo": nzs._json_safe(row.effective_to),
            "sourceDocumentId": row.source_document_id, "signed": MARK not in (row.rate_label or "")}


# ── governed edit / sign of one canonical row ───────────────────────────────
RATE_FIELDS = {"flatAmount": "flat_amount", "textValue": "text_value", "effectiveFrom": "effective_from",
               "effectiveTo": "effective_to"}
SLAB_FIELDS = {"minAmount": "min_amount", "maxAmount": "max_amount", "ratePct": "rate_pct",
               "flatAmount": "flat_amount", "taxFormula": "tax_formula", "effectiveFrom": "effective_from",
               "effectiveTo": "effective_to"}
TREATMENTS = ("INCLUDED", "EXCLUDED", "LUMP_SUM_PATH", "REVIEW")


def update_row(db: Session, kind: str, row_id: int, data: dict, actor_id) -> dict:
    """Edit and/or sign one canonical NZ row of an editable pack version."""
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
    if model is None:
        raise BadRequestException("kind must be 'rate' or 'slab'.")
    data = dict(data or {})
    row = db.get(model, row_id)
    if row is None or row.organization_id is not None or (row.jurisdiction_country or "").upper() != NZ:
        raise NotFoundException("New Zealand statutory row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = _reason(data)
    verify = data.get("specialistVerified") is True
    source = _source(db, data, verify)
    allowed = dict(RATE_FIELDS if kind == "rate" else SLAB_FIELDS)
    if kind == "slab" and row.rule_type == content.NZ_EARNING_CLASS_RULE:
        allowed["treatment"] = "assessment_basis"
    if kind == "slab" and row.rule_type == content.NZ_PUBLIC_HOLIDAY_RULE:
        allowed.update(name="rate_label", region="jurisdiction_state")
    unknown = set(data) - set(allowed) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not editable here: {', '.join(sorted(unknown))}")

    old, new, changed = {}, {}, False
    for name, column in allowed.items():
        if name not in data:
            continue
        value = data[name]
        if column.startswith("effective_"):
            value = nzs._as_date(value, name) if value else None
        elif column == "assessment_basis":
            value = str(value or "").strip().upper()
            if value not in TREATMENTS:
                raise BadRequestException(f"treatment must be one of: {', '.join(TREATMENTS)}.")
        elif column == "jurisdiction_state":
            value = _region(value)
        elif column in ("text_value", "tax_formula", "rate_label"):
            value = str(value).strip() if value not in (None, "") else None
        else:
            value = _decimal(value, name)
            if value is not None and value < 0:
                raise BadRequestException(f"{name} cannot be negative.")
        if kind == "rate" and column == "text_value" and value is not None:
            value = value.upper()
            check = _vocabulary().get(row.component_key)
            problem = check(value) if check else "this row holds a number, not text"
            if problem:
                raise BadRequestException(f"{row.component_key} {problem}.")
        if kind == "rate" and column == "flat_amount" and value is not None \
                and content.NZ_PARAMETER_KEYS.get(row.component_key) == "text":
            raise BadRequestException(f"{row.component_key} holds text, not a number.")
        if column == "rate_label":
            value = _marked(value, MARK not in (row.rate_label or ""), 150)
        old[name], new[name] = nzs._json_safe(getattr(row, column)), nzs._json_safe(value)
        if getattr(row, column) != value:
            changed = True
        setattr(row, column, value)
    start, end = row.effective_from or pack.effective_from, row.effective_to or pack.effective_to
    if start and end and end < start:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")
    if kind == "rate" and verify and row.flat_amount is None and not row.text_value:
        raise BadRequestException(f"{row.component_key} has no value: fill it before signing.")
    label_col = "label" if kind == "rate" else "rate_label"
    was_signed = MARK not in (getattr(row, label_col) or "")
    signed = verify or (was_signed and not changed)
    setattr(row, label_col, _marked(getattr(row, label_col), signed, 100 if kind == "rate" else 150))
    if kind == "rate":
        if row.text_value:
            total = row.text_value
        elif row.flat_amount is None:
            total = "NOT CONFIGURED"
        else:
            pct = content.NZ_PARAMETER_KEYS.get(row.component_key) == "pct_total"
            total = f"{row.flat_amount}%" if pct else str(row.flat_amount)
        row.total = total[:50]
    old["signed"], new["signed"] = was_signed, signed
    old["sourceDocumentId"], new["sourceDocumentId"] = row.source_document_id, source.id
    row.source_document_id = source.id
    _finish(db, pack, actor_id, f"nz_statutory_{kind}", row.id, old, new, reason)
    return _rate_view(row) if kind == "rate" else _slab_view(row)


# ── authority-table rows (the tables the specification does not reproduce) ──
def _region(value) -> Optional[str]:
    text = str(value or "").strip().upper()
    if not text:
        return None
    codes = {code for code, _name in _content().NZ_REGIONS}
    text = text[3:] if text.startswith("NZ-") else text
    if text not in codes:
        raise BadRequestException(f"region must be an ISO 3166-2:NZ code ({', '.join(sorted(codes))}) or empty.")
    return text


def _table_specs() -> dict:
    """rule_type -> (allowed filingStatus values or None, required fields)."""
    from app.modules.payroll.engine.jurisdictions.new_zealand import paye

    content = _content()
    return {
        content.NZ_PAYE_METHOD_RULE: (content.PAY_FREQUENCIES, ("filingStatus", "flatAmount", "taxFormula")),
        content.NZ_SECONDARY_RATE_RULE: (("SB", "S", "SH", "ST", "SA"), ("filingStatus", "ratePct")),
        content.NZ_ND_RATE_RULE: (None, ("ratePct",)),
        content.NZ_IETC_RULE: (None, ("minAmount", "flatAmount", "ratePct")),
        content.NZ_CS_VARIATION_RULE: (None, ("filingStatus", "taxFormula", "name")),
        content.NZ_LUMP_SUM_RULE: (("ANNUALISATION_FACTOR", "SL_ON_EXTRA_PAY", "IETC_ON_EXTRA_PAY"), ("filingStatus",)),
        content.NZ_HOLIDAY_ADVANCE_RULE: (("STANDARD", "ALTERNATIVE"), ("filingStatus",)),
        content.NZ_IRD_EXAMPLE_RULE: (None, ("filingStatus", "taxFormula", "name")),
        content.NZ_PUBLIC_HOLIDAY_RULE: (None, ("date", "name")),
        content.NZ_ACC_CLASSIFICATION_RULE: (None, ("filingStatus", "ratePct", "name")),
        "_paye_formula": paye.ANNUALISE_BANDS,
    }


TABLE_FIELDS = ("filingStatus", "minAmount", "maxAmount", "ratePct", "flatAmount", "taxFormula", "name", "region",
                "date", "effectiveTo")


def add_table_row(db: Session, pack_row_id: int, rule_type: str, data: dict, actor_id) -> dict:
    from app.modules.payroll.models import TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    content = _content()
    specs = _table_specs()
    rule_type = str(rule_type or "").strip().upper()
    if rule_type not in specs or rule_type.startswith("_"):
        raise BadRequestException("Rows can be added only to New Zealand authority tables.")
    pack = _pack(db, pack_row_id)
    _require_editable_pack(pack)
    data = dict(data or {})
    reason = _reason(data)
    verify = data.get("specialistVerified") is True
    source = _source(db, data, verify)
    unknown = set(data) - set(TABLE_FIELDS) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not a field of an authority-table row: {', '.join(sorted(unknown))}")
    allowed_codes, required = specs[rule_type]
    missing = [f for f in required if data.get(f) in (None, "")]
    if missing:
        raise BadRequestException(f"{rule_type} needs: {', '.join(missing)}")
    code = str(data.get("filingStatus") or "").strip().upper() or None
    if allowed_codes is not None and code not in allowed_codes:
        raise BadRequestException(f"filingStatus must be one of: {', '.join(allowed_codes)}.")
    formula = str(data.get("taxFormula") or "").strip() or None
    if rule_type == content.NZ_IRD_EXAMPLE_RULE:
        from app.modules.payroll import nz_golden

        try:
            nz_golden.parse_example(formula)
        except ValueError as exc:
            raise BadRequestException(f"NZ_IRD_EXAMPLE taxFormula: {exc}.")
    if rule_type == content.NZ_PAYE_METHOD_RULE and formula != specs["_paye_formula"]:
        raise BadRequestException(f"taxFormula must be {specs['_paye_formula']}.")
    if rule_type == content.NZ_LUMP_SUM_RULE:
        need = {"ANNUALISATION_FACTOR": ("flatAmount", None), "SL_ON_EXTRA_PAY": ("taxFormula", "WHOLE"),
                "IETC_ON_EXTRA_PAY": ("taxFormula", "NONE")}[code]
        if data.get(need[0]) in (None, "") or (need[1] and (formula or "").upper() != need[1]):
            raise BadRequestException(f"{code} needs {need[0]}" + (f" = {need[1]}" if need[1] else "") + ".")
        formula = formula.upper() if formula else None
    day = nzs._as_date(data["date"], "date") if data.get("date") else None
    end = nzs._as_date(data["effectiveTo"], "effectiveTo") if data.get("effectiveTo") else None
    numbers = {name: _decimal(data.get(name), name) for name in ("minAmount", "maxAmount", "ratePct", "flatAmount")}
    if any(v is not None and v < 0 for v in numbers.values()):
        raise BadRequestException("Amounts and rates cannot be negative.")
    name = str(data.get("name") or f"{rule_type} {code or ''}").strip()
    row = TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ, rule_type=rule_type,
                  filing_status=code, min_amount=numbers["minAmount"] if numbers["minAmount"] is not None else Decimal(0),
                  max_amount=numbers["maxAmount"], rate_pct=numbers["ratePct"] if numbers["ratePct"] is not None
                  else Decimal(0), flat_amount=numbers["flatAmount"],
                  tax_formula=(formula or name)[:150],          # descriptive when the table has no formula
                  jurisdiction_state=_region(data.get("region")) if rule_type == content.NZ_PUBLIC_HOLIDAY_RULE else None,
                  rate_label=_marked(name, verify, 150),
                  effective_from=day if rule_type == content.NZ_PUBLIC_HOLIDAY_RULE else None,
                  effective_to=end, source_document_id=source.id, sort_order=0)
    db.add(row)
    db.flush()
    _finish(db, pack, actor_id, "nz_statutory_table_row", row.id, {}, {**_slab_view(row), "action": "added"}, reason)
    return _slab_view(row)


def delete_table_row(db: Session, row_id: int, data: dict, actor_id) -> dict:
    from app.modules.payroll.models import TaxSlab
    from app.modules.payroll.service import _require_editable_pack

    row = db.get(TaxSlab, row_id)
    tables = {rt for rt in _table_specs() if not rt.startswith("_")}
    if row is None or row.organization_id is not None or (row.jurisdiction_country or "").upper() != NZ \
            or row.rule_type not in tables:
        raise NotFoundException("New Zealand authority-table row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = _reason(dict(data or {}))
    old = _slab_view(row)
    db.delete(row)
    _finish(db, pack, actor_id, "nz_statutory_table_row", row_id, old, {"action": "deleted"}, reason)
    return {"id": row_id, "deleted": True}


# ── status, editors, packs ──────────────────────────────────────────────────
def signing_status(db: Session, pack_row_id: int) -> dict:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    content = _content()
    pack = _pack(db, pack_row_id)
    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None)).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    pending_rates = sorted(r.component_key for r in rates if MARK in (r.label or ""))
    empty_values = sorted(r.component_key for r in rates if r.flat_amount is None and not r.text_value)
    pending_slabs = {}
    for s in slabs:
        if MARK in (s.rate_label or ""):
            pending_slabs[s.rule_type] = pending_slabs.get(s.rule_type, 0) + 1
    tables = []
    for name, table in content.NZ_EMPTY_TABLES.items():
        count = sum(1 for s in slabs if s.rule_type == table["rule_type"])
        tables.append({"table": name, "ruleType": table["rule_type"], "gate": table["gate"], "rows": count,
                       "employerContent": bool(table.get("employer_content"))})
    return {"packId": pack.pack_id, "packRowId": pack.id, "version": pack.version, "status": pack.status,
            "pendingRates": pending_rates, "emptyValues": empty_values, "pendingSlabsByRuleType": pending_slabs,
            "authorityTables": tables, "editors": sorted(statutory_editors(db, pack)),
            "activationRefusal": nzs.nz_pack_activation_refusal(db, pack)}


def statutory_editors(db: Session, pack) -> set:
    """Every Super Admin who changed a statutory row of this pack version (from
    the audit trail written above): none of them may approve it."""
    from app.modules.payroll.models import TaxConfigurationAudit as A

    rows = (db.query(A.actor_id).filter(A.jurisdiction_pack_id == pack.id, A.entity_type.in_(AUDIT_TYPES),
                                        A.actor_id.isnot(None)).distinct().all())
    return {r[0] for r in rows}


def list_packs(db: Session) -> list:
    from app.modules.payroll.models import JurisdictionPack

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == NZ)
             .order_by(JurisdictionPack.effective_from, JurisdictionPack.id).all())
    return [{"id": p.id, "packId": p.pack_id, "version": p.version, "packType": p.pack_type, "status": p.status,
             "effectiveFrom": nzs._json_safe(p.effective_from), "effectiveTo": nzs._json_safe(p.effective_to),
             "approvedById": p.approved_by_id, "updatedById": p.updated_by_id} for p in packs]


def decisions(db: Session) -> list:
    return nzs.owner_decisions(db)


def golden_check(db: Session, pack_row_id: int) -> dict:
    """Replay the pack's Inland Revenue examples through the engine (read-only)."""
    from app.modules.payroll import nz_golden

    return nz_golden.nz_golden_check(db, _pack(db, pack_row_id))


def seed_draft(db: Session, data: dict, actor_id) -> dict:
    """Create the Draft NZ-PAYROLL-2026-27 pack (every row PENDING G1), the
    empty NZ-ELA-2028 staging pack and the PLANNED service-registry row from
    new_zealand_content.py, inside the deployed app — no shell access and no
    environment file. Only while no New Zealand pack exists: once one does,
    every change goes through the governed edit / sign above. Audited."""
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.service import record_tax_audit

    reason = _reason(data)
    existing = [p.pack_id for p in nzs._nz_seeded_packs(db)]
    if existing:
        raise BadRequestException(f"New Zealand content is already seeded ({', '.join(existing)}); change it "
                                  "through the signing console instead.")
    pack = nzs.seed_nz_pack(db)
    availability = nzs.ensure_nz_service_registry_row(db)
    record_tax_audit(db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=nzs.SPEC,
                     old_value=None, new_value={"status": pack.status, "availability": availability},
                     reason=f"{reason} — canonical {content.NZ_2026_27[0]} seeded as Draft from {nzs.SPEC} "
                            "(Super Admin console).", auto_commit=False)
    db.flush()
    return nzs.nz_seed_summary(db)
