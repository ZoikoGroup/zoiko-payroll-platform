"""
modules/payroll/mexico_cfdi_preview.py
--------------------------------------
Phase 11c — validate-only CFDI preview (MEXICO_PHASE_11_PLAN.md §4.7, D3 + D5).

For a committed Mexican run, every payslip's CFDI 4.0 + Nómina 1.2 receipt is
assembled and built IN MEMORY with the real SAT builder, against the latest
Approved (or Active) release loaded from a verified pinned SAT set, and
validated against the pinned XSDs. Nothing is signed, stored, queued or sent.

Returned per payslip: valid / refused, the refusal code and its findings (rule
id + text, value-free by construction and scrubbed again here), and the
SHA-256 of the would-be payload. NEVER the XML (MX-061).

Stored: one audited summary per preview (counts, codes, payload hashes, the
release and set) — no names, no identifiers. The Super Admin reads those
summaries per organisation as G1 evidence.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.payroll.engine.countries.mexico import MXBlock

ENTITY = "mx_cfdi_validation"
PREVIEW_FOLIO = "PREVIEW"
G1_MARKER = "G1 decision"


def _models():
    from app.modules.payroll import models

    return models


def validation_release(db: Session):
    """The newest Approved or Active release whose pinned set still verifies (D3)."""
    from app.modules.payroll import mexico_cfdi_catalog_service as cat

    m = _models()
    rows = (db.query(m.PayrollMxCfdiSchemaRelease)
            .filter(m.PayrollMxCfdiSchemaRelease.status.in_(("Approved", "Active")))
            .order_by(m.PayrollMxCfdiSchemaRelease.id.desc()).all())
    return next((r for r in rows if cat.release_set_id(r) is not None), None)


def _findings(exc: MXBlock) -> list:
    from app.core.redaction import scrub_text

    reasons = list(getattr(exc, "reasons", None) or []) or [(exc.key, str(exc))]
    return [{"rule": rule, "message": scrub_text(text)} for rule, text in reasons]


def validate_run(db: Session, run, actor_id: Optional[int]) -> dict:
    from app.modules.payroll import mexico_cfdi_input, mexico_cfdi_service, mexico_cfdi_xml, mexico_run_service

    mexico_cfdi_service.run_guard(db, run)
    fp = run.mx_approval_fingerprint or {}
    if run.status != "Approved" or not fp.get("committedAt"):
        raise MXBlock("MX_CFDI_RUN_NOT_COMMITTED", "only a committed (Approved) Mexican run can be validated (MX-016)",
                      run.organization_id)
    release = validation_release(db)
    if release is None:
        raise MXBlock("MX_CFDI_NO_APPROVED_RELEASE",
                      "no Approved CFDI release loaded from a verified pinned SAT set (Super Admin → Mexico → CFDI "
                      "catalogs)", run.organization_id)
    from app.modules.payroll import mexico_cfdi_catalog_service as cat

    set_id = cat.release_set_id(release)
    now = datetime.now(timezone.utc)
    results = []
    for item in mexico_run_service._mx_items(db, run):
        base = {"payslipItemId": item.id, "folio": PREVIEW_FOLIO, "issuedAtUtc": now, "replacesUuid": None}
        entry = {"payslipItemId": item.id, "employeeName": item.employee_name}
        try:
            doc = mexico_cfdi_input.document_input(db, run, item, release, base)
            payload = mexico_cfdi_xml.build(doc)
            del doc                                   # MX-061: identifiers never outlive the build
            entry.update(valid=True, code=None, findings=[], payloadSha256=hashlib.sha256(payload).hexdigest())
            del payload                               # the XML is never returned or stored
        except MXBlock as exc:
            entry.update(valid=False, code=exc.key, findings=_findings(exc), payloadSha256=None)
        results.append(entry)
    awaiting = sorted({f["message"] for r in results for f in r["findings"] if G1_MARKER in f["message"]})
    summary = {"runId": run.id, "releaseId": release.id, "setId": set_id, "releaseStatus": release.status,
               "payslips": len(results), "valid": sum(r["valid"] for r in results),
               "refused": sum(not r["valid"] for r in results),
               "codes": dict(Counter(r["code"] for r in results if r["code"])),
               "rules": dict(Counter(f["rule"] for r in results for f in r["findings"])),
               "payloadHashes": [r["payloadSha256"] for r in results if r["payloadSha256"]],
               "awaitingG1Decision": bool(awaiting), "validatedAt": now.isoformat()}
    _audit(db, run, actor_id, summary)
    db.commit()
    return {**summary, "awaitingDecisions": awaiting, "results": results,
            "note": "Validate-only: nothing was signed, stored or sent. The XML is never shown."}


def _audit(db: Session, run, actor_id, summary: dict):
    from app.modules.payroll import service

    service.record_tax_audit(db, actor_id=actor_id, action="validate", entity_type=ENTITY, entity_id=run.id,
                             old_value=None, new_value={**summary, "organizationId": run.organization_id},
                             reason="CFDI validate-only preview (Phase 11c)", legal_reference="ZP-MX-ENG-001 §4.7",
                             auto_commit=False)


def validation_summaries(db: Session, organization_id: Optional[int] = None, limit: int = 50) -> list:
    """Super Admin: the audited preview summaries (counts, codes, hashes — no worker data)."""
    m = _models()
    A = m.TaxConfigurationAudit
    rows = db.query(A).filter(A.entity_type == ENTITY, A.action == "validate").order_by(A.id.desc()).limit(500).all()
    out = []
    for r in rows:
        value = r.new_value or {}
        if organization_id is not None and value.get("organizationId") != organization_id:
            continue
        out.append({"id": r.id, "at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                    **{k: value.get(k) for k in ("organizationId", "runId", "releaseId", "setId", "releaseStatus",
                                                 "payslips", "valid", "refused", "codes", "rules", "payloadHashes",
                                                 "awaitingG1Decision")}})
        if len(out) >= limit:
            break
    return out
