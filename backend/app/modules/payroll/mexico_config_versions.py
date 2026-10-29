"""
payroll/mexico_config_versions.py
---------------------------------
Mexico statutory configuration versions for the Super Admin (Hong Kong parity):
every version of every Mexico pack (national and state ISN) with its state, the
rows of one version with their sources, a row-level comparison of two versions,
and "new version" — a Draft copy of ANY version, which is the only rollback path.

Mexico rows are never edited in the product (completion W5-2): a value changes
only through a code release that re-seeds from the transcribed, source-cited
content. A new version is therefore an exact copy of its source version (rows,
row sources, pack source) — it changes nothing by itself, and it goes live only
through the existing gates (four-eyes approval, activation checks, golden run).

Unlike the shared upsert_jurisdiction_pack (which pre-populates a new version
from the pack's LATEST version), the copy here is always from the version chosen.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

MX = "MX"
_ROW_SKIP = {"id", "jurisdiction_pack_id", "created_at", "updated_at"}
# Pack columns a new version takes from its source (identity, status, approval
# and bookkeeping are the new version's own).
_PACK_SKIP = {"id", "version", "status", "approved_by_id", "created_by_id", "updated_by_id", "created_at", "updated_at",
              "previous_version_id", "change_summary"}


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


def _plain(v) -> Optional[str]:
    if v is None:
        return None
    text = format(v, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or pack.jurisdiction_country != MX or pack.pack_type != "tax":
        raise NotFoundException("Mexico statutory pack", pack_row_id)
    return pack


def _rows(db: Session, pack) -> tuple:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.component_key, ContributionRate.effective_from, ContributionRate.id).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.rule_type, TaxSlab.filing_status, TaxSlab.tax_table_number, TaxSlab.min_amount,
                       TaxSlab.effective_from, TaxSlab.id).all())
    return rates, slabs


def mx_config_version_state(pack, on: date) -> str:
    starts, ends = pack.effective_from, pack.effective_to
    if pack.status == "Retired":
        return "RETIRED"
    if pack.status in ("Superseded", "Deprecated"):
        return "SUPERSEDED"
    if pack.status == "Active":
        if starts and starts > on:
            return "NEXT_ACTIVE"
        if ends and ends < on:
            return "PAST_ACTIVE"
        return "CURRENT_ACTIVE"
    if starts and starts > on:
        return "FUTURE_DRAFT"
    return "DRAFT"


def mx_config_versions(db: Session, on: Optional[date] = None) -> dict:
    """Every Mexico pack version, grouped by pack (national first, then states)."""
    from app.modules.payroll.models import JurisdictionPack

    on_source = "query" if on else "today"
    on = on or date.today()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == MX,
                                               JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.pack_id, JurisdictionPack.id).all())
    groups = {}
    for p in packs:
        rates, slabs = _rows(db, p)
        cited = sum(1 for r in list(rates) + list(slabs) if r.source_document_id)
        groups.setdefault(p.pack_id, {"packId": p.pack_id, "state": p.jurisdiction_state, "versions": []})["versions"].append({
            "id": p.id, "version": p.version, "status": p.status, "versionState": mx_config_version_state(p, on),
            "taxYear": p.tax_year, "effectiveFrom": _iso(p.effective_from), "effectiveTo": _iso(p.effective_to),
            "approvedById": p.approved_by_id, "createdById": p.created_by_id,
            "createdAt": p.created_at.isoformat() if p.created_at else None,
            "previousVersionId": p.previous_version_id, "changeSummary": p.change_summary,
            "rows": len(rates) + len(slabs), "rowsWithSource": cited,
            "packSourceId": p.source_document_id})
    ordered = sorted(groups.values(), key=lambda g: (g["state"] is not None, g["state"] or "", g["packId"]))
    return {"on": on.isoformat(), "onSource": on_source, "packs": ordered,
            "rule": "Rows are never edited in the product: a value changes through a code release that re-seeds "
                    "the pack from its transcribed source. A new version is a Draft copy of one version (the "
                    "rollback path) and goes live only through four-eyes approval and the activation checks."}


def _source(db: Session, source_document_id) -> Optional[dict]:
    from app.modules.payroll.models import SourceArtifact

    if not source_document_id:
        return None
    a = db.get(SourceArtifact, source_document_id)
    if a is None:
        return {"id": source_document_id, "missing": True}
    return {"id": a.id, "title": a.title, "sha256": a.checksum_sha256, "reviewed": a.reviewer_approved_at is not None}


def _rate_view(db, r) -> dict:
    return {"kind": "rate", "id": r.id, "key": r.component_key, "label": r.label,
            "value": {"employeePct": _plain(r.employee_rate_pct), "employerPct": _plain(r.employer_rate_pct),
                      "amount": _plain(r.flat_amount), "text": r.text_value},
            "effectiveFrom": _iso(r.effective_from), "effectiveTo": _iso(r.effective_to),
            "source": _source(db, r.source_document_id)}


def _slab_view(db, s) -> dict:
    return {"kind": "slab", "id": s.id, "key": s.rule_type, "label": s.rate_label,
            "value": {"filingStatus": s.filing_status, "table": s.tax_table_number, "min": _plain(s.min_amount),
                      "max": _plain(s.max_amount), "ratePct": _plain(s.rate_pct), "amount": _plain(s.flat_amount),
                      "formula": s.tax_formula},
            "effectiveFrom": _iso(s.effective_from), "effectiveTo": _iso(s.effective_to),
            "source": _source(db, s.source_document_id)}


def mx_config_pack_rows(db: Session, pack_row_id: int) -> dict:
    """One version's rows (read-only), each with its value, dates and source."""
    pack = _pack(db, pack_row_id)
    rates, slabs = _rows(db, pack)
    return {"pack": {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status,
                     "state": pack.jurisdiction_state, "effectiveFrom": _iso(pack.effective_from),
                     "effectiveTo": _iso(pack.effective_to), "source": _source(db, pack.source_document_id)},
            "rates": [_rate_view(db, r) for r in rates], "slabs": [_slab_view(db, s) for s in slabs],
            "editable": False}


def _match_key(row: dict) -> str:
    """Stable across versions: a rate by component and start date; a slab by its
    rule, key, table, lower bound and start date — never by a label."""
    v = row["value"]
    if row["kind"] == "rate":
        return f"rate|{row['key']}|{row['effectiveFrom']}"
    return f"slab|{row['key']}|{v['filingStatus']}|{v['table']}|{v['min']}|{row['effectiveFrom']}"


def mx_config_compare(db: Session, from_id: int, to_id: int) -> dict:
    """Row-level differences between two versions of the same Mexico pack scope
    (national with national, a state with the same state)."""
    a, b = _pack(db, from_id), _pack(db, to_id)
    if (a.jurisdiction_state or None) != (b.jurisdiction_state or None):
        raise BadRequestException("Compare two versions of the same scope: the national pack with a national pack, "
                                  "or a state ISN pack with the same state's")
    va, vb = mx_config_pack_rows(db, a.id), mx_config_pack_rows(db, b.id)
    ra = {_match_key(r): r for r in va["rates"] + va["slabs"]}
    rb = {_match_key(r): r for r in vb["rates"] + vb["slabs"]}
    changed, unchanged = [], 0
    for k in sorted(set(ra) & set(rb)):
        x, y = ra[k], rb[k]
        diffs = {f"value.{f}": {"from": x["value"][f], "to": y["value"][f]} for f in x["value"]
                 if x["value"][f] != y["value"][f]}
        for f in ("label", "effectiveTo"):
            if x[f] != y[f]:
                diffs[f] = {"from": x[f], "to": y[f]}
        sx, sy = (x["source"] or {}).get("sha256"), (y["source"] or {}).get("sha256")
        if sx != sy:
            diffs["sourceSha256"] = {"from": sx, "to": sy}
        if diffs:
            changed.append({"kind": y["kind"], "key": y["key"], "label": y["label"], "changes": diffs})
        else:
            unchanged += 1
    slim = lambda r: {"kind": r["kind"], "key": r["key"], "label": r["label"], "value": r["value"],  # noqa: E731
                      "effectiveFrom": r["effectiveFrom"]}
    side = lambda p: {"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,  # noqa: E731
                      "state": p.jurisdiction_state}
    return {"from": side(a), "to": side(b), "added": [slim(rb[k]) for k in sorted(set(rb) - set(ra))],
            "removed": [slim(ra[k]) for k in sorted(set(ra) - set(rb))], "changed": changed, "unchanged": unchanged,
            "identical": not changed and set(ra) == set(rb)}


def mx_config_new_version(db: Session, pack_row_id: int, version: str, reason: str, actor_id: Optional[int]) -> dict:
    """A Draft copy of one Mexico pack version — every row and source, exactly.
    The rollback path (copy an older version) and the start of any re-proving;
    it never edits a value and goes live only through the existing gates."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from app.modules.payroll.service import record_tax_audit

    src = _pack(db, pack_row_id)
    version, reason = (version or "").strip(), (reason or "").strip()
    if not version or len(version) > 20:
        raise BadRequestException("A new version needs a version number (at most 20 characters)")
    if not reason:
        raise BadRequestException("A new version needs a reason (the rollback or the change it starts)")
    if actor_id is None:
        raise BadRequestException("A new version needs an identified Super Admin")
    if db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == src.pack_id,
                                         JurisdictionPack.version == version).first():
        raise BadRequestException(f"{src.pack_id} v{version} already exists")
    cols = {c.name: getattr(src, c.name) for c in JurisdictionPack.__table__.columns if c.name not in _PACK_SKIP}
    new = JurisdictionPack(**cols, version=version, status="Draft", previous_version_id=src.id,
                           created_by_id=actor_id, updated_by_id=actor_id,
                           change_summary=f"Copy of v{src.version}: {reason}"[:500])
    db.add(new)
    db.flush()
    copied = 0
    for model in (ContributionRate, TaxSlab):
        columns = [c.name for c in model.__table__.columns if c.name not in _ROW_SKIP]
        for row in db.query(model).filter(model.jurisdiction_pack_id == src.id, model.organization_id.is_(None)):
            db.add(model(jurisdiction_pack_id=new.id, **{c: getattr(row, c) for c in columns}))
            copied += 1
    db.commit()
    db.refresh(new)
    record_tax_audit(db, actor_id=actor_id, action="new_version", entity_type="jurisdiction_pack", entity_id=new.id,
                     jurisdiction_pack_id=new.id, tax_version=new.version, legal_reference=new.source_references,
                     old_value={"copiedFrom": src.id, "version": src.version},
                     new_value={"version": new.version, "status": "Draft", "rows": copied}, reason=reason)
    return {"id": new.id, "packId": new.pack_id, "version": new.version, "status": new.status,
            "copiedFrom": {"id": src.id, "version": src.version}, "rows": copied}
