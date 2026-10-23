"""
modules/payroll/mexico_transfer_service.py
------------------------------------------
Mexico Phase 10f — option B for the D5 master-data copy: a TENANT-RUN handshake
between the pilot organisation and the new live organisation of the SAME
employer (ZP-PRIV decision 3: statutory actions on worker data are tenant-run;
no platform role handles worker data). The Super Admin copy routes stay retired.

The four safeguards:

  1. SAME EMPLOYER — the live organisation has recorded its own employer
     profile(s) first, and their RFCs equal the pilot's exactly. The pilot's
     profiles are never copied: the live organisation's own profiles stand in
     for them (matched by RFC); everything under them is copied.
  2. ONE-TIME RELEASE — the pilot's release names ONE target, expires 7 days
     after it is released, is revocable until it is used, and is used at most
     once (USED).
  3. FOUR EYES ON BOTH SIDES — one pilot-org admin proposes the release and a
     DIFFERENT pilot-org admin releases it; one live-org admin proposes the
     import AFTER reviewing the diff preview (its hash is bound to the
     proposal) and a DIFFERENT live-org admin approves and executes it.
  4. AUDITED ON BOTH SIDES, IDENTIFIERS MASKED — every step writes one audit
     row for each organisation; RFCs are masked; no CURP / NSS / CLABE value,
     no name, ever reaches an audit row.

Each side reads the other's rows ONLY inside an explicit tenant_session of
that organisation (core/authz/tenant_context.py), authorised by the release.

Needs the ZP-PRIV owner's (Rugvedh's) sign-off before production use.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import mexico_dormancy
from app.modules.payroll import mexico_pilot_service as pilot
from app.modules.payroll.engine.countries.mexico import MXBlock

RELEASE_DAYS = 7


def _xfer_models():
    from app.modules.payroll import models as m

    return m


def _xfer_now() -> datetime:
    return datetime.now(timezone.utc)


def _xfer_scope(db: Session, org_id: int):
    from app.core.authz.tenant_context import tenant_session

    return tenant_session(db, org_id)


def _xfer_mask(value) -> Optional[str]:
    from app.modules.payroll.employee_validation import mask_identifier

    return mask_identifier(value)


def _xfer_audit_both(db: Session, actor_id, action: str, entity_type: str, entity_id: int, source_id: int,
                     target_id: int, new: dict, reason: Optional[str] = None) -> None:
    """One audit row per organisation (masked identifiers only)."""
    for side, org in (("pilot", source_id), ("live", target_id)):
        pilot._pilot_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                           new={**new, "organizationId": org, "side": side, "sourceOrganizationId": source_id,
                                "targetOrganizationId": target_id}, reason=reason)


def _xfer_rfcs(db: Session, org_id: int) -> dict:
    """{RFC: profile id} of the organisation's OPEN employer profiles, read in its own tenant scope."""
    m = _xfer_models()
    with _xfer_scope(db, org_id):
        rows = (db.query(m.PayrollMxEmployerProfile)
                .filter(m.PayrollMxEmployerProfile.organization_id == org_id,
                        m.PayrollMxEmployerProfile.effective_to.is_(None)).all())
        return {(r.rfc or "").upper(): r.id for r in rows}


def _xfer_target_refusal(db: Session, source_id: int, target_id: int) -> Optional[tuple]:
    """(code, message) when the target cannot receive this pilot's master data."""
    from app.modules.payroll import service

    m = _xfer_models()
    if source_id == target_id:
        return "MX_TRANSFER_REFUSED", "the pilot and the live organisation must differ"
    if not mexico_dormancy.is_pilot_organization(db, source_id):
        return "MX_TRANSFER_NOT_PILOT", f"organisation {source_id} is not a pilot organisation"
    if mexico_dormancy.is_pilot_organization(db, target_id):
        return "MX_TRANSFER_REFUSED", "the target is itself a pilot organisation — it must be a new live organisation"
    if (pilot._pilot_org(db, target_id).workspace_type or "").upper() == "EVALUATION":
        return "MX_TRANSFER_REFUSED", "the target must be a live (non-EVALUATION) organisation"
    if not mexico_dormancy.is_mexico(service._resolve_org_country(db, target_id)):
        return "MX_TRANSFER_REFUSED", "the target organisation's payroll jurisdiction is not Mexico"
    source_rfcs, target_rfcs = _xfer_rfcs(db, source_id), _xfer_rfcs(db, target_id)
    if not source_rfcs:
        return "MX_TRANSFER_REFUSED", "the pilot organisation has no open employer profile"
    if set(source_rfcs) != set(target_rfcs):
        return ("MX_TRANSFER_RFC_MISMATCH", "the live organisation must first record the SAME employer: its open "
                f"employer profiles {sorted(_xfer_mask(r) for r in target_rfcs) or 'none'} do not match the pilot's "
                f"{sorted(_xfer_mask(r) for r in source_rfcs)}")
    with _xfer_scope(db, target_id):
        for model, label in ((m.PayrollMxImssRegistration, "IMSS registrations"),
                             (m.PayrollMxEstablishment, "establishments"),
                             (m.PayrollMxIsnRegistration, "ISN registrations"),
                             (m.PayrollMxLaborPolicy, "labour policies")):
            if db.query(model.id).filter(model.organization_id == target_id).first():
                return "MX_TRANSFER_TARGET_NOT_EMPTY", f"the live organisation already has {label} — the copy only fills an empty employer"
        if db.query(m.PayrollEmployee.id).filter(m.PayrollEmployee.organization_id == target_id,
                                                 m.PayrollEmployee.country_code == "MX").first():
            return "MX_TRANSFER_TARGET_NOT_EMPTY", "the live organisation already has Mexican employees"
    return None


def _xfer_source_snapshot(db: Session, source_id: int) -> tuple:
    """(snapshot, categories counts, fingerprint) of the pilot's master data, read in its tenant scope."""
    with _xfer_scope(db, source_id):
        cats = pilot._copy_categories(db, source_id)
        for p in cats["laborPolicies"]:
            if p.collective_agreement_id is not None:
                raise MXBlock("MX_COPY_COLLECTIVE_AGREEMENT", f"labour policy {p.id} references a collective agreement "
                                                              "— record the agreement in the live organisation first",
                              source_id)
        snap = pilot._mx_copy_snapshot(cats)
        not_copied = pilot._mx_not_copied(db, source_id)
    counts = {k: len(v) for k, v in snap.items()}
    return snap, counts, pilot._mx_copy_fingerprint(snap), not_copied


# ── guards ──────────────────────────────────────────────────────────────────

def release_guard(db: Session, org_id: int) -> None:
    """The pilot side: kill switch on, general availability open, a pilot organisation
    (its own grant may have ended — releasing is its last act)."""
    if not mexico_dormancy.flag_enabled():
        raise MXBlock("MX_DORMANT", mexico_dormancy.DORMANT_MESSAGE, org_id)
    if not mexico_dormancy.registry_available(db):
        raise MXBlock("MX_TRANSFER_REQUIRES_GA", "a release needs general availability (the registry AVAILABLE)", org_id)
    if not mexico_dormancy.is_pilot_organization(db, org_id):
        raise MXBlock("MX_TRANSFER_NOT_PILOT", "only a pilot organisation releases its master data", org_id)


def import_guard(db: Session, org_id: int) -> None:
    """The live side: open by general availability, a Mexican, non-pilot organisation."""
    from app.modules.payroll import service

    if mexico_dormancy.is_pilot_organization(db, org_id) or not mexico_dormancy.onboarding_enabled(db, org_id):
        raise MXBlock("MX_TRANSFER_NOT_LIVE", "only an open, live (non-pilot) Mexican organisation imports", org_id)
    if not mexico_dormancy.is_mexico(service._resolve_org_country(db, org_id)):
        raise MXBlock("MX_TRANSFER_NOT_LIVE", "the organisation's payroll jurisdiction is not Mexico", org_id)


# ── the release (pilot organisation) ────────────────────────────────────────

def _xfer_release(db: Session, release_id: int):
    row = db.get(_xfer_models().PayrollMxMasterRelease, release_id)
    if row is None:
        raise NotFoundException(f"Release {release_id} not found")
    return row


def _xfer_owned_release(db: Session, org_id: int, release_id: int):
    row = _xfer_release(db, release_id)
    if row.organization_id != org_id:
        raise NotFoundException(f"Release {release_id} not found")
    return row


def release_state(row) -> str:
    if row.status == "RELEASED":
        return "AVAILABLE" if mexico_dormancy._aware(row.expires_at) > _xfer_now() else "EXPIRED"
    return row.status


def propose_release(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    R = _xfer_models().PayrollMxMasterRelease
    release_guard(db, org_id)
    target_id = (data or {}).get("targetOrganizationId")
    if not isinstance(target_id, int):
        raise BadRequestException("targetOrganizationId is required")
    reason = ((data or {}).get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A release needs a reason")
    refusal = _xfer_target_refusal(db, org_id, target_id)
    if refusal:
        raise MXBlock(refusal[0], refusal[1], org_id)
    for r in db.query(R).filter(R.organization_id == org_id, R.target_organization_id == target_id,
                                R.status.in_(("PROPOSED", "RELEASED"))):
        if release_state(r) in ("PROPOSED", "AVAILABLE"):
            raise BadRequestException(f"release {r.id} to this organisation is already {release_state(r)}")
    _, counts, fingerprint, not_copied = _xfer_source_snapshot(db, org_id)
    plan = {"counts": counts, "employerRfcs": sorted(_xfer_mask(r) for r in _xfer_rfcs(db, org_id)),
            "notCopied": not_copied, "employerProfiles": "matched by RFC in the live organisation, never copied"}
    row = R(organization_id=org_id, target_organization_id=target_id, status="PROPOSED", reason=reason[:300],
            plan=plan, plan_sha256=fingerprint, proposed_by_id=actor_id)
    db.add(row)
    db.flush()
    _xfer_audit_both(db, actor_id, "propose_mx_master_release", "mx_master_release", row.id, org_id, target_id,
                     {"counts": counts, "employerRfcs": plan["employerRfcs"]}, reason[:300])
    db.commit()
    return master_release_view(row)


def approve_release(db: Session, org_id: int, release_id: int, actor_id: Optional[int]) -> dict:
    release_guard(db, org_id)
    row = _xfer_owned_release(db, org_id, release_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED release can be released (this one is {row.status})")
    if actor_id is not None and actor_id == row.proposed_by_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", "a release must be released by a pilot-org admin other than its proposer",
                      org_id)
    refusal = _xfer_target_refusal(db, org_id, row.target_organization_id)
    if refusal:
        raise MXBlock(refusal[0], refusal[1], org_id)
    if _xfer_source_snapshot(db, org_id)[2] != row.plan_sha256:
        raise MXBlock("MX_COPY_SOURCE_CHANGED", "the pilot's master data changed after the release was proposed — "
                                                "revoke it and propose again", org_id)
    now = _xfer_now()
    row.status, row.released_by_id, row.released_at = "RELEASED", actor_id, now
    row.expires_at = now + timedelta(days=RELEASE_DAYS)
    _xfer_audit_both(db, actor_id, "release_mx_master_data", "mx_master_release", row.id, org_id,
                     row.target_organization_id, {"expiresAt": row.expires_at.isoformat()})
    db.commit()
    return master_release_view(row)


def revoke_release(db: Session, org_id: int, release_id: int, reason: str, actor_id: Optional[int]) -> dict:
    row = _xfer_owned_release(db, org_id, release_id)
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Revoking a release needs a reason")
    if row.status not in ("PROPOSED", "RELEASED"):
        raise BadRequestException(f"the release is already {row.status} (a used release cannot be revoked)")
    row.status, row.revoked_by_id, row.revoked_at, row.revoke_reason = "REVOKED", actor_id, _xfer_now(), text[:300]
    _xfer_audit_both(db, actor_id, "revoke_mx_master_release", "mx_master_release", row.id, org_id,
                     row.target_organization_id, {"status": "REVOKED"}, text[:300])
    db.commit()
    return master_release_view(row)


def master_release_view(row) -> dict:
    return {"id": row.id, "sourceOrganizationId": row.organization_id,
            "targetOrganizationId": row.target_organization_id, "status": row.status, "state": release_state(row),
            "reason": row.reason, "plan": row.plan, "proposedById": row.proposed_by_id,
            "releasedById": row.released_by_id,
            "releasedAt": row.released_at.isoformat() if row.released_at else None,
            "expiresAt": mexico_dormancy._aware(row.expires_at).isoformat() if row.expires_at else None,
            "usedAt": row.used_at.isoformat() if row.used_at else None, "revokeReason": row.revoke_reason}


# ── the import (live organisation) ──────────────────────────────────────────

def _xfer_usable_release(db: Session, org_id: int, release_id: int):
    row = _xfer_release(db, release_id)
    if row.target_organization_id != org_id:
        raise NotFoundException(f"Release {release_id} not found")
    if release_state(row) != "AVAILABLE":
        raise MXBlock("MX_TRANSFER_RELEASE_UNAVAILABLE", f"release {row.id} is {release_state(row)} — only an "
                                                         "unexpired, unused release can be imported", org_id)
    return row


def _xfer_masked_compliance(fields: dict) -> dict:
    fields = fields or {}
    clabe = str(fields.get("clabe") or "")
    return {"rfc": _xfer_mask(fields.get("rfc")), "curp": _xfer_mask(fields.get("curp")),
            "nss": _xfer_mask(fields.get("nss")), "clabeLast4": clabe[-4:] if clabe else None}


def preview_import(db: Session, org_id: int, release_id: int) -> dict:
    """The diff the live organisation's admins review before importing: what
    will be created (identifiers masked), the RFC match, and the hash the
    import proposal must carry."""
    import_guard(db, org_id)
    rel = _xfer_usable_release(db, org_id, release_id)
    refusal = _xfer_target_refusal(db, rel.organization_id, org_id)
    if refusal:
        raise MXBlock(refusal[0], refusal[1], org_id)
    snap, counts, fingerprint, not_copied = _xfer_source_snapshot(db, rel.organization_id)
    if fingerprint != rel.plan_sha256:
        raise MXBlock("MX_COPY_SOURCE_CHANGED", "the pilot's master data changed after it was released — ask the "
                                                "pilot to revoke and release again", org_id)
    rows = {
        "imssRegistrations": [{"sourceId": i, "registroPatronal": v["registro_patronal"], "riskClass": v["risk_class"]}
                              for _, i, v in snap["imssRegistrations"]],
        "establishments": [{"sourceId": i, "name": v["name"], "state": v["state_code"]} for _, i, v in snap["establishments"]],
        "isnRegistrations": [{"sourceId": i, "state": v["state_code"]} for _, i, v in snap["isnRegistrations"]],
        "laborPolicies": [{"sourceId": i, "version": v["version"],
                           "effectiveFrom": v["effective_from"].isoformat() if v["effective_from"] else None}
                          for _, i, v in snap["laborPolicies"]],
        "employees": [{"sourceId": i, "employeeCode": v["employee_code"], "name": v["name"],
                       **_xfer_masked_compliance(v.get("compliance_fields"))} for _, i, v in snap["employees"]],
        "statutoryProfiles": [{"sourceId": i, "employeeSourceId": v["employee_id"]} for _, i, v in snap["statutoryProfiles"]],
    }
    return {"releaseId": rel.id, "sourceOrganizationId": rel.organization_id, "targetOrganizationId": org_id,
            "previewSha256": fingerprint, "employerRfcs": rel.plan.get("employerRfcs"),
            "employerProfiles": "matched by RFC to this organisation's own profiles — not copied",
            "willCreate": {k: v for k, v in counts.items() if k != "employerProfiles"}, "rows": rows,
            "notCopied": not_copied, "releaseExpiresAt": mexico_dormancy._aware(rel.expires_at).isoformat()}


def propose_import(db: Session, org_id: int, release_id: int, data: dict, actor_id: Optional[int]) -> dict:
    C = _xfer_models().PayrollMxMasterCopy
    preview = preview_import(db, org_id, release_id)
    reviewed = ((data or {}).get("previewSha256") or "").strip()
    if reviewed != preview["previewSha256"]:
        raise MXBlock("MX_TRANSFER_DIFF_NOT_REVIEWED", "propose the import with the hash of the diff preview you "
                                                       "reviewed (it changed, or none was given)", org_id)
    reason = ((data or {}).get("reason") or "").strip()
    if not reason:
        raise BadRequestException("An import needs a reason")
    if db.query(C).filter(C.organization_id == org_id, C.status == "PROPOSED").first() is not None:
        raise BadRequestException("an import into this organisation is already proposed")
    rel = _xfer_release(db, release_id)
    row = C(source_organization_id=rel.organization_id, organization_id=org_id, status="PROPOSED", reason=reason[:300],
            plan={**(rel.plan or {}), "reviewedPreviewSha256": reviewed}, plan_sha256=rel.plan_sha256,
            proposed_by_id=actor_id, release_id=rel.id)
    db.add(row)
    db.flush()
    _xfer_audit_both(db, actor_id, "propose_mx_master_import", "mx_master_import", row.id, rel.organization_id, org_id,
                     {"releaseId": rel.id, "willCreate": preview["willCreate"]}, reason[:300])
    db.commit()
    return pilot.master_copy_view(row)


def _xfer_owned_import(db: Session, org_id: int, copy_id: int):
    row = db.get(_xfer_models().PayrollMxMasterCopy, copy_id)
    if row is None or row.organization_id != org_id or row.release_id is None:
        raise NotFoundException(f"Import {copy_id} not found")
    return row


def approve_import(db: Session, org_id: int, copy_id: int, actor_id: Optional[int]) -> dict:
    """A DIFFERENT live-org admin approves; everything is re-checked; the copy
    runs in one transaction; the release is marked USED in the pilot's scope."""
    import_guard(db, org_id)
    row = _xfer_owned_import(db, org_id, copy_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED import can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.proposed_by_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", "an import must be approved by a live-org admin other than its proposer",
                      org_id)
    rel = _xfer_usable_release(db, org_id, row.release_id)
    refusal = _xfer_target_refusal(db, rel.organization_id, org_id)
    if refusal:
        raise MXBlock(refusal[0], refusal[1], org_id)
    snap, _, fingerprint, not_copied = _xfer_source_snapshot(db, rel.organization_id)
    if fingerprint != row.plan_sha256:
        raise MXBlock("MX_COPY_SOURCE_CHANGED", "the pilot's master data changed after it was released", org_id)
    source_rfcs, target_rfcs = _xfer_rfcs(db, rel.organization_id), _xfer_rfcs(db, org_id)
    profile_map = {source_rfcs[rfc]: target_rfcs[rfc] for rfc in source_rfcs}
    try:
        report = pilot._mx_execute_copy(db, snap, org_id, actor_id, not_copied, profile_map=profile_map)
        now = _xfer_now()
        with _xfer_scope(db, rel.organization_id):              # the release row belongs to the pilot
            rel.status, rel.used_at = "USED", now
            db.flush()
        row.status, row.approved_by_id, row.executed_at, row.report = "EXECUTED", actor_id, now, report
        _xfer_audit_both(db, actor_id, "execute_mx_master_import", "mx_master_import", row.id, rel.organization_id,
                         org_id, {"releaseId": rel.id, "copied": report["copied"],
                                  "differences": len(report["differences"]),
                                  "employerRfcs": sorted(_xfer_mask(r) for r in source_rfcs)})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return pilot.master_copy_view(row)


def cancel_import(db: Session, org_id: int, copy_id: int, reason: str, actor_id: Optional[int]) -> dict:
    row = _xfer_owned_import(db, org_id, copy_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED import can be cancelled (this one is {row.status})")
    row.status, row.cancelled_reason = "CANCELLED", ((reason or "").strip()[:300] or None)
    _xfer_audit_both(db, actor_id, "cancel_mx_master_import", "mx_master_import", row.id, row.source_organization_id,
                     org_id, {"status": "CANCELLED"}, row.cancelled_reason)
    db.commit()
    return pilot.master_copy_view(row)


def transfer_status(db: Session, org_id: int) -> dict:
    """What this organisation's transfer panel shows."""
    m = _xfer_models()
    R, C = m.PayrollMxMasterRelease, m.PayrollMxMasterCopy
    is_pilot = mexico_dormancy.is_pilot_organization(db, org_id)
    outgoing = [master_release_view(r) for r in db.query(R).filter(R.organization_id == org_id).order_by(R.id.desc())]
    incoming = [master_release_view(r) for r in
                db.query(R).filter(R.target_organization_id == org_id).order_by(R.id.desc())]
    imports = [pilot.master_copy_view(c) for c in
               db.query(C).filter(C.organization_id == org_id, C.release_id.isnot(None)).order_by(C.id.desc())]
    return {"isPilot": is_pilot, "outgoing": outgoing, "incoming": incoming, "imports": imports,
            "releaseDays": RELEASE_DAYS}
