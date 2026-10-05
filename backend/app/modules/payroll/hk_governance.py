"""
modules/payroll/hk_governance.py
--------------------------------
Hong Kong Super Admin governance (final jurisdiction completion program).
HK-only; reuses the shared pack / template / source-artifact lifecycles.

* ``activation_readiness`` — every requirement for HK onboarding to open,
  re-derived from the database (never taken from a caller).
* ``transition_hk_service_registry`` — the ONLY governed path for the HK
  registry: PLANNED → AVAILABLE refused unless every requirement is met;
  AVAILABLE → PLANNED (suspension / rollback) always allowed. Reason required,
  identified Super Admin required, every outcome audited (refusals too).
* ``template_activation_refusal`` — an HK report template may go Active only
  with linked source evidence reviewed by someone other than its uploader, and
  an activator different from its approver (called from the shared template
  status transition for HK templates only).
* ``template_coverage`` — HK report types × year keys and their template status.
* ``compare_report_templates`` — a read-only diff of two HK templates, with a
  computed content hash per version (integrity evidence; read-only).
* ``owner_decisions`` — D-1…D-14 and their recorded state: a decision is
  RECORDED only when an uploaded ``HK-DECISION-D-n`` document was reviewed by a
  Super Admin other than its uploader (the same evidence rule as the gates).
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

HK = "HK"
REGISTRY_OPEN, REGISTRY_CLOSED = "AVAILABLE", "PLANNED"
GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
# Report type → year-key kind: IRD forms by year of assessment, MPF / termination by calendar year.
REPORT_TYPES = {
    "HK_BIR56A": "YA", "HK_IR56B": "YA", "HK_IR56E": "YA", "HK_IR56F": "YA", "HK_IR56G": "YA",
    "HK_EMPF_REMITTANCE": "CALENDAR", "HK_MPF_CONTRIBUTION_RECORD": "CALENDAR", "HK_TERMINATION_STATEMENT": "CALENDAR",
}


PRODUCTION_EVIDENCE_TAG = "HK-PRODUCTION-VERIFICATION"
# Owner decisions (HK_OWNER_DECISION_REGISTER.md). blocksLaunch = the G7 form §C requires it recorded.
DECISIONS = {
    "D-1": ("eMPF submission interface at launch", True), "D-2": ("Retention period per data category", True),
    "D-3": ("Deletion vs anonymisation at end of retention", True), "D-4": ("Encryption at rest", True),
    "D-5": ("Production HK identity-token secret", True), "D-6": ("Bilingual output a launch requirement", True),
    "D-7": ("Launch-scope exclusions", True), "D-8": ("HK payroll-run approval four-eyes", True),
    "D-9": ("Legal-hold policy", True), "D-10": ("Privileged (assisted) access policy", True),
    "D-11": ("Future-year template publication owner", True),
    "D-12": ("Per-value reviewer columns (shared platform)", False),
    "D-13": ("Platform-wide template compare (shared platform)", False),
    "D-14": ("Audit correlation id (shared platform)", False),
}
EXTERNAL_DEPENDENCIES = (
    ("X-1", "HK payroll / statutory specialist certification", "G1"), ("X-2", "IRD schemas, samples, test submission", "G2"),
    ("X-3", "eMPF onboarding and certification", "G2"), ("X-4", "Parallel payroll cycles (real data)", "G3"),
    ("X-5", "Independent penetration test", "G5"), ("X-6", "Privacy counsel review", "G5"),
    ("X-7", "Runbook approval", "G6"), ("X-8", "Approved production snapshot (restore rehearsal)", "G7"),
    ("X-9", "Read-only production facts", "G7"), ("X-10", "Launch approvals", "G7"),
)


def _evidence(db: Session, tag: str):
    """The current (not superseded) artifact with this tag that counts as evidence, if any."""
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag, SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    return next((r for r in rows if _reviewed_by_other(r)), None), bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in DECISIONS.items():
        accepted, submitted = _evidence(db, f"HK-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"HK-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def external_dependencies(db: Session) -> list:
    from app.modules.payroll import hk_service

    return [{"key": k, "label": label, "gate": gate, "gateState": hk_service.gate_state(db, gate)}
            for k, label, gate in EXTERNAL_DEPENDENCIES]


def template_content_hash(db: Session, template) -> str:
    """SHA-256 of the template's field structure + identifying metadata (computed; never stored)."""
    import hashlib
    import json

    from app.modules.payroll.models import ReportTemplateComponent, ReportTemplateComponentField

    fields = []
    for c in db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == template.id):
        for f in db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == c.id):
            fields.append([c.component_key, f.field_key, f.label, f.field_type, f.data_source_kind, f.source_column,
                           f.aggregation, bool(f.is_required), f.format_hint, f.enum_values])
    body = {"key": template.template_key, "type": template.report_type, "year": str(template.reporting_year),
            "version": template.version, "scope": template.document_scope, "fields": sorted(fields, key=str)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def year_key(kind: str, on: date) -> str:
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment

    return year_of_assessment(on) if kind == "YA" else str(on.year)


def _next_year_key(kind: str, on: date) -> str:
    return year_key(kind, date(on.year + 1, on.month, min(on.day, 28)))


def _reviewed_by_other(artifact) -> bool:
    return bool(artifact is not None and artifact.reviewer_id and artifact.file_path is not None
                and artifact.reviewer_id != artifact.created_by_id)


# ── report templates ────────────────────────────────────────────────────

def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    from app.modules.payroll.models import SourceArtifact

    if template.jurisdiction_country != HK:
        return None
    if not template.source_document_id:
        return (f"Hong Kong template {template.template_key} v{template.version} has no source evidence — link the "
                "official source document (a SourceArtifact) before activation.")
    artifact = db.get(SourceArtifact, template.source_document_id)
    if not _reviewed_by_other(artifact):
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} has not been "
                "reviewed by a Super Admin other than its uploader (an uploaded document is required).")
    # Same source rule as statutory values: hashed, current, and not itself flagged unverified.
    if not artifact.checksum_sha256:
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} has no SHA-256 "
                "— re-upload the official document so its hash is recorded.")
    if artifact.superseded_by_id:
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} has been "
                "superseded — link the current version of the document.")
    if "[UNVERIFIED" in (artifact.title or ""):
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} is marked "
                "UNVERIFIED — link a verified official source.")
    if not template.approved_by_id:
        return (f"Hong Kong template {template.template_key} v{template.version} has no recorded approval — "
                "approve it (four-eyes) before activation.")
    if actor_id is not None and actor_id == template.approved_by_id:
        return (f"Hong Kong template {template.template_key} v{template.version} must be activated by a Super Admin "
                "other than its approver.")
    return None


def template_coverage(db: Session, on: Optional[date] = None) -> list:
    from app.modules.payroll.models import ReportTemplate

    on = on or date.today()
    rows = db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == HK).all()
    out = []
    for report_type, kind in REPORT_TYPES.items():
        for label, key in (("current", year_key(kind, on)), ("next", _next_year_key(kind, on))):
            versions = [t for t in rows if t.report_type == report_type and str(t.reporting_year) == key]
            active = [t for t in versions if t.status == "Active"]
            out.append({"reportType": report_type, "yearKind": kind, "period": label, "yearKey": key,
                        "versions": [{"id": t.id, "version": t.version, "status": t.status,
                                      "sourceDocumentId": t.source_document_id,
                                      "approvedById": t.approved_by_id,
                                      "contentHash": template_content_hash(db, t)} for t in versions],
                        "active": active[0].id if active else None,
                        "state": "ACTIVE" if active else ("DRAFT" if versions else "MISSING")})
    return out


def compare_report_templates(db: Session, from_id: int, to_id: int) -> dict:
    """Read-only diff of two Hong Kong templates (any statuses / years)."""
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent, ReportTemplateComponentField

    a, b = db.get(ReportTemplate, from_id), db.get(ReportTemplate, to_id)
    for tid, t in ((from_id, a), (to_id, b)):
        if t is None:
            raise NotFoundException("ReportTemplate", tid)
        if t.jurisdiction_country != HK:
            raise BadRequestException(f"template #{tid} is not a Hong Kong template")

    def fields(t):
        out = {}
        for c in db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == t.id):
            for f in db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == c.id):
                out[f"{c.component_key}.{f.field_key}"] = {
                    "component": c.component_key, "label": f.label, "type": f.field_type, "sourceKind": f.data_source_kind,
                    "sourceColumn": f.source_column, "aggregation": f.aggregation, "required": bool(f.is_required),
                    "format": f.format_hint, "enum": f.enum_values}
        return out

    fa, fb = fields(a), fields(b)
    changed = []
    for k in sorted(set(fa) & set(fb)):
        diffs = {attr: {"from": fa[k][attr], "to": fb[k][attr]} for attr in fa[k] if fa[k][attr] != fb[k][attr]}
        if diffs:
            changed.append({"field": k, "changes": diffs})
    meta_attrs = ("template_key", "report_type", "reporting_year", "version", "status", "effective_from", "effective_to",
                  "source_document_id", "source_references", "regulatory_authority", "document_scope")
    meta = {m: {"from": str(getattr(a, m)), "to": str(getattr(b, m))} for m in meta_attrs if getattr(a, m) != getattr(b, m)}
    return {"from": {"id": a.id, "key": a.template_key, "version": a.version, "year": a.reporting_year, "status": a.status,
                     "contentHash": template_content_hash(db, a)},
            "to": {"id": b.id, "key": b.template_key, "version": b.version, "year": b.reporting_year, "status": b.status,
                   "contentHash": template_content_hash(db, b)},
            "sameReportType": a.report_type == b.report_type,
            "added": sorted(set(fb) - set(fa)), "removed": sorted(set(fa) - set(fb)), "changed": changed,
            "metadata": meta, "identical": not (set(fa) ^ set(fb)) and not changed}


# ── activation readiness + registry ─────────────────────────────────────

def activation_readiness(db: Session, as_of: Optional[date] = None) -> dict:
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import ReportTemplate, SourceArtifact
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    as_of = as_of or date.today()
    reqs = []
    for g in GATES:
        state = hk_service.gate_state(db, g)
        reqs.append({"key": f"GATE_{g}", "label": f"{g} evidence accepted (HK-GATE-{g})", "met": state == "PASS",
                     "detail": state})
    _rates, _slabs, pack = resolve_tax_configuration(db, HK, payroll_date=as_of)
    reqs.append({"key": "ACTIVE_PACK", "label": "an Active HK rule pack in force today", "met": pack is not None,
                 "detail": f"{pack.pack_id} v{pack.version}" if pack else f"none in force on {as_of}"})
    if pack is not None:
        check = hk_service.pack_golden_check(db, pack)
        ok = bool(check["casesInWindow"]) and not check["failures"]
        reqs.append({"key": "GOLDEN", "label": "the in-force pack reproduces its golden vectors", "met": ok,
                     "detail": f"{check['casesInWindow'] - len(check['failures'])}/{check['casesInWindow']} pass"})
    else:
        reqs.append({"key": "GOLDEN", "label": "the in-force pack reproduces its golden vectors", "met": False,
                     "detail": "no pack in force"})
    prod, prod_submitted = _evidence(db, PRODUCTION_EVIDENCE_TAG)
    reqs.append({"key": "PRODUCTION_VERIFICATION",
                 "label": f"production read-only verification and restore rehearsal recorded ({PRODUCTION_EVIDENCE_TAG})",
                 "met": prod is not None,
                 "detail": "PASS" if prod else ("SUBMITTED" if prod_submitted else "EVIDENCE_REQUIRED")})
    for cov in template_coverage(db, as_of):
        if cov["period"] != "current":
            continue
        tid = cov["active"]
        sourced = approved = False
        if tid:
            t = db.get(ReportTemplate, tid)
            sourced = _reviewed_by_other(db.get(SourceArtifact, t.source_document_id) if t.source_document_id else None)
            # defence in depth: an Active template must carry an independent approval even if
            # its status was set outside the governed transition
            approved = bool(t.approved_by_id) and t.approved_by_id != t.updated_by_id
        met = bool(tid) and sourced and approved
        detail = ("ACTIVE + sourced + independently approved" if met else
                  "no Active template" if not tid else
                  "source evidence missing" if not sourced else "independent approval missing")
        reqs.append({"key": f"TEMPLATE_{cov['reportType']}",
                     "label": f"{cov['reportType'][3:].replace('_', ' ')} {cov['yearKey']}: an Active template with "
                              "reviewed source evidence and an independent approval",
                     "met": met, "detail": detail})
    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == HK).first()
    unmet = [r for r in reqs if not r["met"]]
    return {"asOf": as_of.isoformat(), "registry": registry.availability if registry else None,
            "requirements": reqs, "met": len(reqs) - len(unmet), "total": len(reqs),
            "canOpen": not unmet and registry is not None and registry.availability == REGISTRY_CLOSED}


def _refused(db: Session, row, attempted: str, actor_id: Optional[int], message: str, unmet=None):
    from app.modules.payroll.service import record_tax_audit

    row_id, current = (row.id if row is not None else 0), (row.availability if row is not None else None)
    db.rollback()
    record_tax_audit(db, actor_id=actor_id, action="refused", entity_type="jurisdiction_service_registry",
                     entity_id=row_id, old_value={"country": HK, "availability": current},
                     new_value={"attempted": attempted, "result": "REFUSED", "unmet": unmet or []}, reason=message)
    raise BadRequestException(message)


def transition_hk_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.service import record_tax_audit

    target = (target or "").strip().upper()
    reason = (reason or "").strip()
    query = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == HK)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    attempted = f"availability:{target or '?'}"
    if actor_id is None:
        raise BadRequestException("A registry change needs an identified Super Admin.")
    if target not in (REGISTRY_OPEN, REGISTRY_CLOSED):
        _refused(db, row, attempted, actor_id, f"Hong Kong availability can only be {REGISTRY_OPEN} or {REGISTRY_CLOSED}.")
    if not reason:
        raise BadRequestException("A registry change needs the owner's reason (it is the change record).")
    if row is None:
        _refused(db, row, attempted, actor_id, "There is no Hong Kong registry row — seed it (PLANNED); it is never "
                                               "created here.")
    if row.availability == target:
        _refused(db, row, attempted, actor_id, f"Hong Kong is already {target}.")
    snapshot = None
    if target == REGISTRY_OPEN:
        if row.availability != REGISTRY_CLOSED:
            _refused(db, row, attempted, actor_id, f"Hong Kong is {row.availability}; only PLANNED moves to AVAILABLE.")
        readiness = activation_readiness(db, as_of)
        unmet = [r for r in readiness["requirements"] if not r["met"]]
        if unmet:
            _refused(db, row, attempted, actor_id,
                     f"Hong Kong cannot be made AVAILABLE — {len(unmet)} requirement(s) unmet: "
                     + "; ".join(f"{r['label']} ({r['detail']})" for r in unmet), unmet=[r["key"] for r in unmet])
        snapshot = {r["key"]: r["detail"] for r in readiness["requirements"]}
    old = row.availability
    row.availability = target
    db.commit()
    db.refresh(row)
    record_tax_audit(db, actor_id=actor_id, action="status_change", entity_type="jurisdiction_service_registry",
                     entity_id=row.id, old_value={"country": HK, "availability": old},
                     new_value={"country": HK, "availability": target, "evidence": snapshot}, reason=reason)
    return row
