"""
modules/payroll/mexico_cfdi_catalog_service.py
----------------------------------------------
Phase 11a (MEXICO_PHASE_11_PLAN.md §4.1, §4.3; decisions D2, D4):

* Loading a pinned SAT schema set (mexico_cfdi_schema) into a Draft CFDI schema
  release: the release records the set's XSD checksum, and every catalog row of
  the set becomes a frozen-on-approval catalog entry. Nothing is typed by hand.
* System concepts: the SAT code for each amount the engine produces itself
  (no earning classification carries one), per release, maker-checker, each row
  citing its S28 / S4 location.

Super Admin only; platform data (no organisation). Every change is audited.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, insert
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import mexico_cfdi_schema

# Engine-produced amounts that need a SAT code (§4.3). The key names the engine
# field; the SAT code itself is never chosen here.
SYSTEM_CONCEPTS = {
    "ISR_WITHHELD": "ISR withheld in the period (result.isr_withheld)",
    "IMSS_EMPLOYEE": "IMSS employee quotas (result.imss_employee)",
    "INFONAVIT_CREDIT": "INFONAVIT housing-credit repayment (result.infonavit_credit)",
    "SUBSIDY_APPLIED": "Employment subsidy applied (result.subsidy.applied)",
    "AGUINALDO": "Special payment: aguinaldo (special-pay kind AGUINALDO)",
    "VACATION_PREMIUM": "Special payment: vacation premium (special-pay kind VACATION_PREMIUM)",
    "PTU": "Special payment: profit sharing (special-pay kind PTU)",
    "SEPARATION": "Special payment: separation (special-pay kind SEPARATION)",
    "ANNUAL_ADJUSTMENT_REFUND": "Annual ISR adjustment in the employee's favour (result.annual_adjustment)",
    "ANNUAL_ADJUSTMENT_CHARGE": "Annual ISR adjustment charged to the employee (result.annual_adjustment)",
}
# The SAT catalog that holds the codes of each node type (S28).
NODE_CATALOG = {"PERCEPCION": "c_TipoPercepcion", "DEDUCCION": "c_TipoDeduccion", "OTRO_PAGO": "c_TipoOtroPago"}
_SOURCE_PREFIXES = ("S28", "S4")
_CHUNK = 5000
_ET_RELEASE, _ET_CONCEPT = "mx_cfdi_schema_release", "mx_cfdi_system_concept"


def _svc():
    from app.modules.payroll import mexico_service

    return mexico_service


def _models():
    from app.modules.payroll import models

    return models


def _iso(value):
    return value.isoformat() if value else None


def _date(value: Optional[str]):
    return date.fromisoformat(value) if value else None


# ── pinned sets ──────────────────────────────────────────────────────────────

def pinned_sets() -> list:
    return [mexico_cfdi_schema.set_view(s) for s in mexico_cfdi_schema.available_sets()]


def catalog_counts(db: Session, release_id: int) -> dict:
    m = _models()
    rows = (db.query(m.PayrollMxCfdiCatalogEntry.catalog_name, func.count(m.PayrollMxCfdiCatalogEntry.id))
            .filter(m.PayrollMxCfdiCatalogEntry.schema_release_id == release_id)
            .group_by(m.PayrollMxCfdiCatalogEntry.catalog_name).all())
    return {name: count for name, count in sorted(rows)}


def load_pinned_set(db: Session, release_id: int, set_id: str, actor_id: Optional[int]) -> dict:
    """Fill an EMPTY Draft release from a verified pinned set (one transaction)."""
    m, svc = _models(), _svc()
    release = db.get(m.PayrollMxCfdiSchemaRelease, release_id)
    if release is None:
        raise NotFoundException("CFDI schema release", release_id)
    if actor_id is None:
        raise BadRequestException("Loading a schema set needs an identified Super Admin.")
    if release.status != "Draft":
        svc._refuse(db, _ET_RELEASE, release.id, "load_pinned_set", actor_id,
                    f"a pinned set is loaded only into a Draft release (this one is {release.status})")
    existing = db.query(m.PayrollMxCfdiCatalogEntry.id).filter(
        m.PayrollMxCfdiCatalogEntry.schema_release_id == release.id).first()
    if existing is not None:
        svc._refuse(db, _ET_RELEASE, release.id, "load_pinned_set", actor_id,
                    "this release already has catalog entries — register a new release for a new set")
    try:
        manifest = mexico_cfdi_schema.verify(set_id)
    except mexico_cfdi_schema.SchemaSetError as exc:
        svc._refuse(db, _ET_RELEASE, release.id, "load_pinned_set", actor_id, str(exc))
    if (release.cfdi_version, release.complement_version) != (manifest["cfdiVersion"], manifest["complementVersion"]):
        svc._refuse(db, _ET_RELEASE, release.id, "load_pinned_set", actor_id,
                    f"the release is CFDI {release.cfdi_version} / Nómina {release.complement_version} but the set is "
                    f"CFDI {manifest['cfdiVersion']} / Nómina {manifest['complementVersion']}")
    table = m.PayrollMxCfdiCatalogEntry.__table__
    batch, total = [], 0
    for name, code, description, valid_from, valid_to, attributes in mexico_cfdi_schema.catalog_rows(set_id):
        batch.append({"schema_release_id": release.id, "catalog_name": name, "code": code,
                      "description": description, "valid_from": _date(valid_from), "valid_to": _date(valid_to),
                      "attributes": attributes})
        if len(batch) >= _CHUNK:
            db.execute(insert(table), batch)
            total += len(batch)
            batch = []
    if batch:
        db.execute(insert(table), batch)
        total += len(batch)
    expected = sum(manifest["catalogCounts"].values())
    if total != expected:
        db.rollback()
        raise BadRequestException(f"loaded {total} entries but the set's manifest lists {expected} — nothing saved")
    old = {"revision": release.revision, "xsdChecksum": release.xsd_checksum, "catalogRelease": release.catalog_release}
    release.revision = set_id
    release.xsd_checksum = manifest["xsdChecksum"]
    release.catalog_release = manifest["catalogRelease"][:40]
    svc._audit(db, actor_id=actor_id, action="load_pinned_set", entity_type=_ET_RELEASE, entity_id=release.id,
               old=old, new={"setId": set_id, "xsdChecksum": manifest["xsdChecksum"], "entries": total,
                             "catalogCounts": manifest["catalogCounts"]})
    db.commit()
    db.refresh(release)
    return {**svc.release_view(db, release), "catalogCounts": catalog_counts(db, release.id)}


def release_set_id(release) -> Optional[str]:
    """The pinned set a release was loaded from, only if its checksum still matches."""
    set_id = getattr(release, "revision", None)
    if not set_id or set_id not in mexico_cfdi_schema.available_sets():
        return None
    try:
        manifest = mexico_cfdi_schema.verify(set_id)
    except mexico_cfdi_schema.SchemaSetError:
        return None
    return set_id if manifest["xsdChecksum"] == release.xsd_checksum else None


# ── catalog look-ups ─────────────────────────────────────────────────────────

def catalog_has_code(db: Session, catalog_name: str, code: str, release_statuses=("Approved", "Active"),
                     release_id: Optional[int] = None) -> bool:
    """Is `code` in the named SAT catalog of an approved (or the given) release?"""
    m = _models()
    q = (db.query(m.PayrollMxCfdiCatalogEntry.id)
         .join(m.PayrollMxCfdiSchemaRelease,
               m.PayrollMxCfdiCatalogEntry.schema_release_id == m.PayrollMxCfdiSchemaRelease.id)
         .filter(m.PayrollMxCfdiCatalogEntry.catalog_name == catalog_name, m.PayrollMxCfdiCatalogEntry.code == code))
    if release_id is not None:
        q = q.filter(m.PayrollMxCfdiSchemaRelease.id == release_id)
    else:
        q = q.filter(m.PayrollMxCfdiSchemaRelease.status.in_(release_statuses))
    return q.first() is not None


def list_entries(db: Session, release_id: int, catalog: Optional[str] = None, q: Optional[str] = None,
                 limit: int = 200) -> dict:
    m = _models()
    if db.get(m.PayrollMxCfdiSchemaRelease, release_id) is None:
        raise NotFoundException("CFDI schema release", release_id)
    limit = max(1, min(int(limit or 200), 1000))
    E = m.PayrollMxCfdiCatalogEntry
    query = db.query(E).filter(E.schema_release_id == release_id)
    if catalog:
        query = query.filter(E.catalog_name == catalog)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter((E.code.ilike(like)) | (E.description.ilike(like)))
    total = query.count()
    rows = query.order_by(E.catalog_name, E.code, E.valid_from).limit(limit).all()
    return {"total": total, "limit": limit, "counts": catalog_counts(db, release_id),
            "entries": [{"id": e.id, "releaseId": e.schema_release_id, "catalogName": e.catalog_name, "code": e.code,
                         "description": e.description, "validFrom": _iso(e.valid_from), "validTo": _iso(e.valid_to),
                         "attributes": e.attributes} for e in rows]}


# ── system concepts (§4.3, D4) ───────────────────────────────────────────────

def concept_view(row) -> dict:
    return {"id": row.id, "releaseId": row.schema_release_id, "conceptKey": row.concept_key,
            "conceptLabel": SYSTEM_CONCEPTS.get(row.concept_key, row.concept_key), "nodeType": row.node_type,
            "satCode": row.sat_code, "sourceRef": row.source_ref, "status": row.status,
            "proposedById": row.proposed_by_id, "approvedById": row.approved_by_id,
            "approvedAt": row.approved_at.isoformat() if row.approved_at else None}


def list_system_concepts(db: Session, release_id: Optional[int] = None) -> dict:
    m = _models()
    C = m.PayrollMxCfdiSystemConcept
    query = db.query(C)
    if release_id is not None:
        query = query.filter(C.schema_release_id == release_id)
    rows = query.order_by(C.schema_release_id, C.concept_key, C.id).all()
    return {"concepts": [{"key": k, "label": v} for k, v in SYSTEM_CONCEPTS.items()],
            "nodeTypes": dict(NODE_CATALOG), "rows": [concept_view(r) for r in rows]}


def _concept(db: Session, concept_id: int):
    row = db.get(_models().PayrollMxCfdiSystemConcept, concept_id)
    if row is None:
        raise NotFoundException("CFDI system concept", concept_id)
    return row


def propose_system_concept(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    m, svc = _models(), _svc()
    if actor_id is None:
        raise BadRequestException("A system concept needs an identified Super Admin.")
    release_id = data.get("release_id")
    release = db.get(m.PayrollMxCfdiSchemaRelease, release_id) if release_id else None
    if release is None:
        raise NotFoundException("CFDI schema release", release_id)
    key = (data.get("concept_key") or "").strip().upper()
    node = (data.get("node_type") or "").strip().upper()
    code = (data.get("sat_code") or "").strip()
    source = " ".join((data.get("source_ref") or "").split())
    if key not in SYSTEM_CONCEPTS:
        raise BadRequestException(f"conceptKey must be one of {', '.join(SYSTEM_CONCEPTS)}")
    if node not in NODE_CATALOG:
        raise BadRequestException(f"nodeType must be one of {', '.join(NODE_CATALOG)}")
    if not code:
        raise BadRequestException("satCode is required")
    if len(source) < 8 or not source.upper().startswith(_SOURCE_PREFIXES) or len(source) > 300:
        raise BadRequestException("sourceRef must cite the S28 catalog row or the S4 guide page it comes from "
                                  "(starting 'S28' or 'S4', at most 300 characters)")
    if release.status == "Superseded":
        svc._refuse(db, _ET_CONCEPT, None, "propose", actor_id, "the release is Superseded")
    if not catalog_has_code(db, NODE_CATALOG[node], code, release_id=release.id):
        svc._refuse(db, _ET_CONCEPT, None, "propose", actor_id,
                    f"{code} is not in {NODE_CATALOG[node]} of release #{release.id} — load the pinned SAT set first, "
                    f"and use a code of the node's own catalog")
    C = m.PayrollMxCfdiSystemConcept
    pending = db.query(C).filter(C.schema_release_id == release.id, C.concept_key == key,
                                 C.status == "PROPOSED").first()
    if pending is not None:
        svc._refuse(db, _ET_CONCEPT, pending.id, "propose", actor_id,
                    f"{key} already has a proposal waiting (#{pending.id}) — approve or withdraw it first")
    row = C(schema_release_id=release.id, concept_key=key, node_type=node, sat_code=code, source_ref=source,
            status="PROPOSED", proposed_by_id=actor_id)
    db.add(row)
    db.flush()
    svc._audit(db, actor_id=actor_id, action="propose", entity_type=_ET_CONCEPT, entity_id=row.id,
               new={"release": release.id, "conceptKey": key, "nodeType": node, "satCode": code, "sourceRef": source})
    db.commit()
    db.refresh(row)
    return concept_view(row)


def approve_system_concept(db: Session, concept_id: int, actor_id: Optional[int]) -> dict:
    m, svc = _models(), _svc()
    row = _concept(db, concept_id)
    if actor_id is None:
        svc._refuse(db, _ET_CONCEPT, row.id, "approve", actor_id, "Approval needs an identified Super Admin.")
    if row.status != "PROPOSED":
        svc._refuse(db, _ET_CONCEPT, row.id, "approve", actor_id,
                    f"only a PROPOSED concept can be approved (this one is {row.status})")
    if row.proposed_by_id == actor_id:
        svc._refuse(db, _ET_CONCEPT, row.id, "approve", actor_id,
                    "You proposed this mapping — a different Super Admin must approve it (maker-checker).")
    C = m.PayrollMxCfdiSystemConcept
    for prior in db.query(C).filter(C.schema_release_id == row.schema_release_id, C.concept_key == row.concept_key,
                                    C.status == "APPROVED").all():
        prior.status = "SUPERSEDED"
        svc._audit(db, actor_id=actor_id, action="supersede", entity_type=_ET_CONCEPT, entity_id=prior.id,
                   new={"status": "SUPERSEDED", "by": row.id})
    db.flush()
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = datetime.now(timezone.utc)
    svc._audit(db, actor_id=actor_id, action="approve", entity_type=_ET_CONCEPT, entity_id=row.id,
               new={"status": "APPROVED", "conceptKey": row.concept_key, "satCode": row.sat_code})
    db.commit()
    db.refresh(row)
    return concept_view(row)


def withdraw_system_concept(db: Session, concept_id: int, actor_id: Optional[int]) -> dict:
    svc = _svc()
    row = _concept(db, concept_id)
    if actor_id is None:
        svc._refuse(db, _ET_CONCEPT, row.id, "withdraw", actor_id, "Withdrawal needs an identified Super Admin.")
    if row.status != "PROPOSED":
        svc._refuse(db, _ET_CONCEPT, row.id, "withdraw", actor_id,
                    f"only a PROPOSED concept can be withdrawn (this one is {row.status})")
    row.status = "WITHDRAWN"
    svc._audit(db, actor_id=actor_id, action="withdraw", entity_type=_ET_CONCEPT, entity_id=row.id,
               new={"status": "WITHDRAWN"})
    db.commit()
    db.refresh(row)
    return concept_view(row)


def approved_concept(db: Session, release_id: int, concept_key: str):
    """The APPROVED mapping of one engine concept in a release (None = unmapped)."""
    C = _models().PayrollMxCfdiSystemConcept
    return db.query(C).filter(C.schema_release_id == release_id, C.concept_key == concept_key,
                              C.status == "APPROVED").first()
