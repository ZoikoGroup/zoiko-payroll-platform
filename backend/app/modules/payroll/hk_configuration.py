"""
modules/payroll/hk_configuration.py
-----------------------------------
Hong Kong statutory configuration administration (Super Admin control plane).
HK-only; built on the shared pack / row / source-artifact model.

* ``domains`` — every row of an HK pack grouped into governed domains (MPF,
  SMW, continuous contract, average wage, EO entitlements, leave & holidays,
  SP / LSP, IRD timing, Salaries Tax — informational, earning classification),
  each with value, unit, effective dates, source (agency, URL, sha256,
  reviewed), G1 flag, code consumer and editability.
* ``versions`` / ``explain_resolution`` — which pack is CURRENT ACTIVE, NEXT
  PUBLISHED (Active, starts later), FUTURE DRAFT, PAST, SUPERSEDED, RETIRED;
  and "why is this version selected" for a payroll date (pack + templates).
* ``compare`` — a row-level diff of two HK pack versions (rates and slabs).
* ``update_row`` — the governed edit: only while the pack is editable, a reason
  and a source artifact are required, the approval is invalidated, audited.
* ``new_version`` — a Draft copy of a pack (also the rollback mechanism: a
  rollback is always a new version, never an in-place edit).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

HK = "HK"
_ENG = "app/modules/payroll/engine/jurisdictions/hong_kong/"
# (domain key, label, matcher on a row key, consumer)
DOMAINS = [
    ("mpf", "MPF", lambda k: k.startswith("mpf_") and k != "mpf_offset_transition_date", _ENG + "mpf.py"),
    ("smw", "Minimum Wage", lambda k: k.startswith("smw_"), _ENG + "minimum_wage.py"),
    ("continuous_contract", "Continuous Contract", lambda k: k.startswith("eo_cc_") or k == "eo_week_start_day",
     _ENG + "continuous_contract.py"),
    ("average_wage", "Average Wage", lambda k: k.startswith(("eo_average_wage_", "eo_overtime_aw_")) or k == "eo_four_fifths_factor",
     _ENG + "average_wage.py"),
    ("eo_entitlements", "Employment Ordinance Entitlements",
     lambda k: k.startswith(("eo_sickness_", "eo_maternity_", "eo_paternity_", "eo_holiday_pay_", "eo_wage_payment_")),
     _ENG + "entitlements.py"),
    ("leave_holidays", "Leave & Holidays", lambda k: k in ("HK_ANNUAL_LEAVE_SCALE", "HK_STATUTORY_HOLIDAY"),
     _ENG + "entitlements.py"),
    ("sp_lsp", "SP / LSP", lambda k: k.startswith(("sp_", "lsp_")) or k in ("mpf_offset_transition_date", "eo_days_per_year"),
     _ENG + "termination.py"),
    ("ird", "IRD timing", lambda k: k.startswith("ird_"), _ENG + "ird.py"),
    ("salaries_tax", "Salaries Tax — informational",
     lambda k: k.startswith(("hk_allowance_", "hk_deduction_", "hk_tax_")) or k.startswith("HK_SALARIES_TAX"),
     _ENG + "salaries_tax.py"),
    ("earning_classification", "Earning Classification", lambda k: k == "HK_EARNING_CLASS",
     "app/modules/payroll/hk_service.py; report generators (IR56B)"),
]
SALARIES_TAX_NOTICE = "Informational calculation only — Salaries Tax is not withheld from monthly HK payroll."
EDITABLE = ("Draft", "In Review", "QA", "Approved")


def _domain_of(key: str):
    for dkey, label, match, consumer in DOMAINS:
        if match(key):
            return dkey, label, consumer
    return None, None, None


def _iso(d):
    return d.isoformat() if d else None


def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or pack.jurisdiction_country != HK or pack.pack_type != "tax":
        raise NotFoundException("Hong Kong statutory pack", pack_row_id)
    return pack


def _source(db: Session, source_id):
    from app.modules.payroll.models import SourceArtifact

    if not source_id:
        return None
    s = db.get(SourceArtifact, source_id)
    if s is None:
        return None
    return {"id": s.id, "agency": s.agency, "title": s.title, "url": s.source_url, "sha256": s.checksum_sha256,
            "reviewed": bool(s.reviewer_id) and s.reviewer_id != s.created_by_id,
            "unverified": "[UNVERIFIED" in (s.title or ""), "publicationDate": _iso(s.publication_date)}


def _unit(key: str, r) -> str:
    if r.text_value is not None:
        return "date" if len(r.text_value) == 10 and r.text_value[4] == "-" else "text"
    if r.employee_rate_pct is not None or r.employer_rate_pct is not None:
        return "percent"
    if key.endswith("_hourly_rate"):
        return "HKD per hour"
    if "days" in key or key.endswith("_day"):
        return "days" if "days" in key else "day of month"
    if "months" in key:
        return "months"
    if "weeks" in key:
        return "weeks"
    if key.endswith("_age") or "_age" in key:
        return "years of age"
    if key.endswith(("_pct",)) or "factor" in key or key.endswith("_rate"):
        return "ratio"
    return "HKD"


def _pct(v) -> str:
    return f"{(Decimal(str(v)) * 100).normalize():f}%"


def _rate_row(db: Session, pack, r) -> dict:
    dkey, dlabel, consumer = _domain_of(r.component_key)
    unit = _unit(r.component_key, r)
    if r.text_value is not None:
        display = r.text_value
    elif r.employee_rate_pct is not None or r.employer_rate_pct is not None:
        parts = []
        if r.employee_rate_pct is not None:
            parts.append(f"employee {_pct(r.employee_rate_pct)}")
        if r.employer_rate_pct is not None:
            parts.append(f"employer {_pct(r.employer_rate_pct)}")
        display = " · ".join(parts)
    elif unit == "ratio" and r.flat_amount is not None and Decimal(str(r.flat_amount)) <= 1 and "pct" not in r.component_key:
        display = f"{Decimal(str(r.flat_amount)).normalize():f}"
    elif r.flat_amount is not None:
        display = f"{Decimal(str(r.flat_amount)):,.2f}" if unit in ("HKD", "HKD per hour") else f"{Decimal(str(r.flat_amount)).normalize():f}"
    else:
        display = "—"
    src = _source(db, r.source_document_id)
    g1 = "[G1]" in (r.label or "") or bool(src and src["unverified"])
    status = ("SOURCE_HASH_REQUIRED" if not (src and src["sha256"]) else
              "UNVERIFIED — G1" if g1 else "SOURCED")
    return {"kind": "rate", "id": r.id, "key": r.component_key, "label": r.label, "domain": dkey, "domainLabel": dlabel,
            "value": display, "unit": unit,
            "raw": {"employeeRatePct": str(r.employee_rate_pct) if r.employee_rate_pct is not None else None,
                    "employerRatePct": str(r.employer_rate_pct) if r.employer_rate_pct is not None else None,
                    "flatAmount": str(r.flat_amount) if r.flat_amount is not None else None, "textValue": r.text_value},
            "effectiveFrom": _iso(r.effective_from or pack.effective_from), "effectiveTo": _iso(r.effective_to or pack.effective_to),
            "source": src, "g1": g1, "status": status, "consumer": consumer,
            "editable": pack.status in EDITABLE}


def _slab_row(db: Session, pack, s) -> dict:
    dkey, dlabel, consumer = _domain_of(s.rule_type)
    if s.rule_type == "HK_STATUTORY_HOLIDAY":
        display, unit, label = s.tax_formula, "date", f"{s.rate_label} ({s.filing_status})"
    elif s.rule_type == "HK_ANNUAL_LEAVE_SCALE":
        hi = f"–{s.max_amount.normalize():f}" if s.max_amount is not None else "+"
        display, unit, label = f"{s.flat_amount.normalize():f} days", "days", f"service year {s.min_amount.normalize():f}{hi}"
    elif s.rule_type.startswith("HK_SALARIES_TAX"):
        hi = f"{s.max_amount:,.0f}" if s.max_amount is not None else "∞"
        display, unit, label = f"{s.rate_pct.normalize():f}%", "percent of band", f"HK$ {s.min_amount:,.0f} – {hi} ({s.rate_label})"
    elif s.rule_type == "HK_EARNING_CLASS":
        display, unit = (s.tax_formula or "").split(": ")[-1] if s.tax_regime != "IRD" else (s.tax_formula or ""), "treatment"
        label = f"{s.filing_status} → {s.tax_regime}"
    else:
        display, unit, label = s.tax_formula or s.rate_label, "", s.rate_label
    src = _source(db, s.source_document_id)
    g1 = "[G1]" in (s.rate_label or "") or bool(src and src["unverified"])
    status = ("SOURCE_HASH_REQUIRED" if not (src and src["sha256"]) else "UNVERIFIED — G1" if g1 else "SOURCED")
    return {"kind": "slab", "id": s.id, "key": s.rule_type, "label": label, "domain": dkey, "domainLabel": dlabel,
            "value": display, "unit": unit,
            "raw": {"minAmount": str(s.min_amount) if s.min_amount is not None else None,
                    "maxAmount": str(s.max_amount) if s.max_amount is not None else None,
                    "ratePct": str(s.rate_pct) if s.rate_pct is not None else None,
                    "flatAmount": str(s.flat_amount) if s.flat_amount is not None else None,
                    "taxFormula": s.tax_formula, "rateLabel": s.rate_label},
            "effectiveFrom": _iso(s.effective_from or pack.effective_from), "effectiveTo": _iso(s.effective_to or pack.effective_to),
            "source": src, "g1": g1, "status": status, "consumer": consumer, "editable": pack.status in EDITABLE}


def _rows(db: Session, pack) -> list:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.component_key, ContributionRate.effective_from).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.rule_type, TaxSlab.sort_order).all())
    return [_rate_row(db, pack, r) for r in rates] + [_slab_row(db, pack, s) for s in slabs]


def domains(db: Session, pack_row_id: int) -> dict:
    pack = _pack(db, pack_row_id)
    rows = _rows(db, pack)
    out = []
    for dkey, label, _m, consumer in DOMAINS:
        items = [r for r in rows if r["domain"] == dkey]
        out.append({"key": dkey, "label": label, "consumer": consumer, "rows": items, "count": len(items),
                    "unverified": sum(1 for r in items if r["status"] != "SOURCED"),
                    "notice": SALARIES_TAX_NOTICE if dkey == "salaries_tax" else None})
    unmapped = [r["key"] for r in rows if r["domain"] is None]
    return {"pack": {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status,
                     "yearOfAssessment": pack.tax_year, "effectiveFrom": _iso(pack.effective_from),
                     "effectiveTo": _iso(pack.effective_to), "approvedById": pack.approved_by_id,
                     "editable": pack.status in EDITABLE, "versionState": _version_state(pack, date.today())},
            "domains": out, "total": len(rows), "unmapped": unmapped}


def _version_state(pack, today: date) -> str:
    starts, ends = pack.effective_from, pack.effective_to
    if pack.status == "Retired":
        return "RETIRED"
    if pack.status in ("Superseded", "Deprecated"):
        return "SUPERSEDED"
    if pack.status == "Active":
        if starts and starts > today:
            return "NEXT_PUBLISHED"            # approved and live-capable, but not yet in force
        if ends and ends < today:
            return "PAST_ACTIVE"               # still pinned by its period's payroll
        return "CURRENT_ACTIVE"
    if starts and starts > today:
        return "FUTURE_DRAFT"
    return "DRAFT"


def versions(db: Session, on: Optional[date] = None) -> list:
    from app.modules.payroll.models import JurisdictionPack

    on = on or date.today()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == HK, JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.effective_from, JurisdictionPack.version).all())
    return [{"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status, "yearOfAssessment": p.tax_year,
             "effectiveFrom": _iso(p.effective_from), "effectiveTo": _iso(p.effective_to),
             "approvedById": p.approved_by_id, "versionState": _version_state(p, on)} for p in packs]


def explain_resolution(db: Session, on: date) -> dict:
    """Why payroll on `on` uses what it uses (pack + exact-year templates)."""
    from app.modules.payroll import hk_governance
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll.models import ReportTemplate

    _rates, _slabs, pack = resolve_tax_configuration(db, HK, payroll_date=on)
    templates = []
    for report_type, kind in hk_governance.REPORT_TYPES.items():
        key = hk_governance.year_key(kind, on)
        active = (db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == HK, ReportTemplate.report_type == report_type,
                                                  ReportTemplate.reporting_year == key, ReportTemplate.status == "Active").first())
        templates.append({"reportType": report_type, "yearKey": key, "yearBasis": "year of assessment" if kind == "YA" else "calendar year",
                          "template": None if active is None else {"id": active.id, "version": active.version},
                          "rule": "exact year only — no fallback to another year's template"})
    return {"payrollDate": on.isoformat(), "yearOfAssessment": year_of_assessment(on),
            "pack": None if pack is None else {"id": pack.id, "packId": pack.pack_id, "version": pack.version,
                                               "effectiveFrom": _iso(pack.effective_from), "effectiveTo": _iso(pack.effective_to)},
            "rule": ("the Active Hong Kong statutory pack whose effective window contains the payroll date; Draft / "
                     "In Review / Approved packs are never selected; rows inside it apply by their own effective dates"),
            "outcome": "SELECTED" if pack else "NO ACTIVE PACK — HK payroll is blocked for this date (fail-closed)",
            "templates": templates}


def _match_key(r: dict) -> str:
    """A key stable across years: rates by component (+ start date for dated SMW rows);
    slabs by their structural identity, never by a label that embeds the year."""
    raw = r["raw"]
    if r["kind"] == "rate":
        return f"rate|{r['key']}|" + (r["effectiveFrom"] if r["key"].startswith("smw_") else "")
    if r["key"] == "HK_STATUTORY_HOLIDAY":
        return f"slab|{r['key']}|{raw['taxFormula']}|{raw['rateLabel']}"
    if r["key"] in ("HK_ANNUAL_LEAVE_SCALE",) or r["key"].startswith("HK_SALARIES_TAX"):
        return f"slab|{r['key']}|{raw['minAmount']}|{raw['maxAmount']}"
    return f"slab|{r['key']}|{r['label']}"


def compare(db: Session, from_id: int, to_id: int) -> dict:
    a, b = _pack(db, from_id), _pack(db, to_id)
    ra = {_match_key(r): r for r in _rows(db, a)}
    rb = {_match_key(r): r for r in _rows(db, b)}
    added = [rb[k] for k in sorted(set(rb) - set(ra))]
    removed = [ra[k] for k in sorted(set(ra) - set(rb))]
    changed, unchanged = [], 0
    for k in sorted(set(ra) & set(rb)):
        x, y = ra[k], rb[k]
        diffs = {f: {"from": x[f], "to": y[f]} for f in ("value", "unit", "effectiveFrom", "effectiveTo") if x[f] != y[f]}
        if x["kind"] == "rate" and a.pack_id != b.pack_id:     # a new year's window is expected, not a change
            if not x["key"].startswith("smw_"):
                diffs.pop("effectiveFrom", None)
            diffs.pop("effectiveTo", None)
        elif a.pack_id != b.pack_id and (x["effectiveFrom"], x["effectiveTo"]) == (_iso(a.effective_from), _iso(a.effective_to))                 and (y["effectiveFrom"], y["effectiveTo"]) == (_iso(b.effective_from), _iso(b.effective_to)):
            diffs.pop("effectiveFrom", None)                    # a slab spanning its own pack's year: not a change
            diffs.pop("effectiveTo", None)
        if (x["source"] or {}).get("sha256") != (y["source"] or {}).get("sha256"):
            diffs["sourceSha256"] = {"from": (x["source"] or {}).get("sha256"), "to": (y["source"] or {}).get("sha256")}
        if diffs:
            changed.append({"domain": y["domainLabel"], "key": y["key"], "label": y["label"], "changes": diffs})
        else:
            unchanged += 1
    slim = lambda r: {"domain": r["domainLabel"], "key": r["key"], "label": r["label"], "value": r["value"]}  # noqa: E731
    return {"from": {"id": a.id, "packId": a.pack_id, "version": a.version, "status": a.status, "yearOfAssessment": a.tax_year},
            "to": {"id": b.id, "packId": b.pack_id, "version": b.version, "status": b.status, "yearOfAssessment": b.tax_year},
            "added": [slim(r) for r in added], "removed": [slim(r) for r in removed], "changed": changed, "unchanged": unchanged}


def update_row(db: Session, kind: str, row_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """Governed edit of one HK statutory row (Draft-family packs only)."""
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab
    from app.modules.payroll.service import _invalidate_pack_approval_on_edit, _require_editable_pack, record_tax_audit

    model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
    if model is None:
        raise BadRequestException("kind must be 'rate' or 'slab'")
    row = db.get(model, row_id)
    if row is None or row.organization_id is not None or row.jurisdiction_country != HK:
        raise NotFoundException("Hong Kong statutory row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A statutory change needs a change reason.")
    source_id = data.get("sourceDocumentId")
    source = db.get(SourceArtifact, int(source_id)) if source_id else None
    if source is None:
        raise BadRequestException("A statutory change needs the official source document (an existing SourceArtifact).")
    verify = data.get("specialistVerified") is True
    if verify and not (source.checksum_sha256 and source.file_path and source.reviewer_id
                       and source.reviewer_id != source.created_by_id and "[UNVERIFIED" not in (source.title or "")):
        raise BadRequestException("Recording the specialist's verification needs a stored, hashed source document reviewed "
                                  "by a Super Admin other than its uploader (and not itself marked UNVERIFIED).")
    allowed = ({"employeeRatePct": "employee_rate_pct", "employerRatePct": "employer_rate_pct", "flatAmount": "flat_amount",
                "textValue": "text_value", "effectiveFrom": "effective_from", "effectiveTo": "effective_to"} if kind == "rate" else
               {"minAmount": "min_amount", "maxAmount": "max_amount", "ratePct": "rate_pct", "flatAmount": "flat_amount",
                "taxFormula": "tax_formula", "effectiveFrom": "effective_from", "effectiveTo": "effective_to"})
    unknown = set(data) - set(allowed) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not editable here: {', '.join(sorted(unknown))}")
    old, new = {}, {}
    for field, column in allowed.items():
        if field not in data:
            continue
        value = data[field]
        if column.startswith("effective_"):
            value = date.fromisoformat(value) if value else None
        elif column in ("text_value", "tax_formula"):
            value = value if value not in ("",) else None
        else:
            value = Decimal(str(value)) if value not in (None, "") else None
        old[field], new[field] = str(getattr(row, column)), str(value)
        setattr(row, column, value)
    ef, et = row.effective_from or pack.effective_from, row.effective_to or pack.effective_to
    if ef and et and et < ef:
        db.rollback()
        raise BadRequestException("effective_to cannot be before effective_from")
    old["sourceDocumentId"], new["sourceDocumentId"] = row.source_document_id, int(source_id)
    row.source_document_id = int(source_id)
    # The HK specialist's confirmation (G1) of a value seeded "[G1]": the marker is
    # removed only together with a reviewed, hashed source (checked above), so the
    # row reads SOURCED and may then pass the activation guard.
    label_col = "label" if kind == "rate" else "rate_label"
    if verify and "[G1]" in (getattr(row, label_col) or ""):
        old["label"] = getattr(row, label_col)
        setattr(row, label_col, " ".join(getattr(row, label_col).replace("[G1]", " ").split()))
        new["label"], new["specialistVerified"] = getattr(row, label_col), True
    _invalidate_pack_approval_on_edit(pack)
    db.flush()
    record_tax_audit(db, actor_id=actor_id, action="update", entity_type=f"hk_statutory_{kind}", entity_id=row.id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference="HK statutory configuration",
                     old_value=old, new_value=new, reason=reason, auto_commit=False)
    db.commit()
    return (_rate_row if kind == "rate" else _slab_row)(db, pack, row)


def new_version(db: Session, pack_row_id: int, version: str, reason: str, actor_id: Optional[int]):
    """A Draft copy of an HK pack (all rows cloned). Also the only rollback path."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    src = _pack(db, pack_row_id)
    version, reason = (version or "").strip(), (reason or "").strip()
    if not version or not reason:
        raise BadRequestException("A new version needs a version number and a reason (e.g. the change or rollback reason).")
    if db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == src.pack_id, JurisdictionPack.version == version).first():
        raise BadRequestException(f"{src.pack_id} v{version} already exists")
    new = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId=src.pack_id, jurisdictionCountry=HK, packType="tax", version=version, status="Draft",
        effectiveFrom=src.effective_from, effectiveTo=src.effective_to, sourceReferences=src.source_references,
        regulatoryAuthority=src.regulatory_authority, complianceCategory=src.compliance_category), actor_id=actor_id)
    new.tax_year = src.tax_year
    # the pack-level source evidence carries over (activation requires it — without
    # it a new version, including a rollback, could never go Active; found by the
    # whole-lifecycle test). Per-row sources come with the copied rows.
    new.source_document_id = src.source_document_id
    # the shared clone copies rates; slabs (holidays, earning classes, bands, leave scale) are copied here
    if not db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == new.id).first():
        cols = [c.name for c in TaxSlab.__table__.columns if c.name not in ("id", "jurisdiction_pack_id", "created_at", "updated_at")]
        for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == src.id, TaxSlab.organization_id.is_(None)).all():
            db.add(TaxSlab(jurisdiction_pack_id=new.id, **{c: getattr(s, c) for c in cols}))
    if not db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == new.id).first():
        cols = [c.name for c in ContributionRate.__table__.columns if c.name not in ("id", "jurisdiction_pack_id", "created_at", "updated_at")]
        for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == src.id,
                                                   ContributionRate.organization_id.is_(None)).all():
            db.add(ContributionRate(jurisdiction_pack_id=new.id, **{c: getattr(r, c) for c in cols}))
    db.flush()
    service.record_tax_audit(db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=new.id,
                             jurisdiction_pack_id=new.id, tax_version=version, legal_reference="HK statutory configuration",
                             old_value={"copiedFrom": f"{src.pack_id} v{src.version}"},
                             new_value={"status": "Draft", "version": version}, reason=reason, auto_commit=False)
    db.commit()
    return new
