"""
modules/payroll/mexico_pilot_service.py
---------------------------------------
Mexico Phase 10e (docs/mexico/MEXICO_PHASE_10E_PLAN.md, approved 2026-10-22):
two-level activation.

  * GENERAL AVAILABILITY — the registry AVAILABLE; refused unless G1–G8 are
    SIGNED, Q9 is RECORDED and MX_IDENTITY_TOKEN_KEY is configured
    (ga_preconditions; enforced in mexico_service.transition_mx_service_registry).
  * PILOT — a grant for ONE named EVALUATION organisation: proposed by a Super
    Admin, approved by a different one, revocable, expiring (≤ 120 days). It
    needs G1, G2, G4, G5 and G7 SIGNED, Q9 and the hosting decision RECORDED,
    the identity key configured and the kill switch on (pilot_preconditions,
    D2). A pilot organisation's output is NON-BINDING: CFDI only through a
    SANDBOX PAC, no payments, no authority filings, watermarked payslips, a
    PILOT journal banner — enforced in the services with named refusals.
  * MASTER-DATA COPY (D5) — the pilot's employer profiles, IMSS and ISN
    registrations, establishments, labour policies, Mexican employees and their
    open statutory profiles, copied into a NEW live organisation: proposed by
    one Super Admin, approved by another, executed in one transaction, with a
    diff report. Payroll results, risk-premium approvals, credentials and
    evidence-backed rows are never copied (listed in the report).

Whether Mexico is open for an organisation is mexico_dormancy.onboarding_enabled.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import mexico_dormancy
from app.modules.payroll.engine.countries.mexico import MXRefuse

MAX_PILOT_DAYS = 120
PILOT_GATES = ("G1", "G2", "G4", "G5", "G7")                 # D2 (G3, G6, G8 are produced during the pilot)
PILOT_WATERMARK = "PILOT — PARALLEL RUN — NOT A PAYSLIP"
PILOT_JOURNAL_BANNER = "ZOIKO PAYROLL JOURNAL - PILOT - NOT FOR POSTING - parallel-run comparison only"


def _pilot_models():
    from app.modules.payroll import models as m

    return m


def _pilot_now() -> datetime:
    return datetime.now(timezone.utc)


def _pilot_audit(db, **kw):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, **kw)


def _identity_key_configured() -> bool:
    from app.config import settings

    return bool((getattr(settings, "MX_IDENTITY_TOKEN_KEY", "") or "").strip())


def _pilot_check(key: str, label: str, met: bool, detail: str) -> dict:
    return {"key": key, "label": label, "met": bool(met), "detail": detail}


def _decision_checks(db: Session, keys) -> list:
    from app.modules.payroll import mexico_service

    states = {d["key"]: d for d in mexico_service.owner_decisions(db)}
    return [_pilot_check(f"mx_decision_{k.lower()}", states[k]["label"], states[k]["state"] == "RECORDED",
                   f"{states[k]['evidenceTag']} is {states[k]['state']}") for k in keys]


def _gate_checks(db: Session, gates) -> list:
    from app.modules.payroll import mexico_service

    states = {g["gate"]: g for g in mexico_service.gate_states(db)}
    return [_pilot_check(f"mx_gate_{g.lower()}", f"Gate {g} — {states[g]['label']}", states[g]["state"] == "SIGNED",
                   f"gate {g} is {states[g]['state']}") for g in gates]


def _pause_check(db: Session) -> dict:
    paused = mexico_dormancy.onboarding_paused(db)
    return _pilot_check("mx_onboarding_not_paused", "New Mexican organisations not paused (runbook §6)", not paused,
                        "paused" if paused else "not paused")


def _key_check() -> dict:
    return _pilot_check("mx_identity_key", "MX_IDENTITY_TOKEN_KEY configured", _identity_key_configured(),
                  "configured" if _identity_key_configured() else "not configured (Secret Manager)")


def ga_preconditions(db: Session) -> list:
    """General availability: every gate, Q9, the identity key."""
    return (_gate_checks(db, [f"G{i}" for i in range(1, 9)]) + _decision_checks(db, ["MX-D-Q9"]) + [_key_check()]
            + [_pause_check(db)])                                                    # Phase 10g


def pilot_preconditions(db: Session) -> list:
    """A pilot grant (D2): the kill switch, G1 G2 G4 G5 G7, Q9, hosting, the key."""
    return ([_pilot_check("mx_flag", "MX_TENANT_ONBOARDING_ENABLED (kill switch) on", mexico_dormancy.flag_enabled(),
                    "on" if mexico_dormancy.flag_enabled() else "off")]
            + _gate_checks(db, PILOT_GATES) + _decision_checks(db, ["MX-D-Q9", "MX-D-HOSTING"]) + [_key_check()]
            + [_pause_check(db)])                                                    # Phase 10g: a pilot is a new org


# ── pilot grants ────────────────────────────────────────────────────────────

def _pilot_org(db: Session, org_id: int):
    from app.modules.organizations.models import Organization

    org = db.get(Organization, org_id)
    if org is None:
        raise NotFoundException(f"Organisation {org_id} not found")
    return org


def _pilot_grant(db: Session, grant_id: int):
    row = db.get(_pilot_models().PayrollMxPilotGrant, grant_id)
    if row is None:
        raise NotFoundException(f"Pilot grant {grant_id} not found")
    return row


def _pilot_expiry(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.combine(date.fromisoformat(str(value)), datetime.min.time())
        except (TypeError, ValueError):
            raise BadRequestException("expiresOn must be a date (YYYY-MM-DD)")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def propose_grant(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    G = _pilot_models().PayrollMxPilotGrant
    org = _pilot_org(db, org_id)
    if (org.workspace_type or "").upper() != "EVALUATION":
        raise MXRefuse("MX_PILOT_EVALUATION_ONLY", "a pilot is only for an EVALUATION workspace", org_id)
    reason = ((data or {}).get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A pilot grant needs a reason")
    expires = _pilot_expiry((data or {}).get("expiresOn"))
    now = _pilot_now()
    if expires <= now:
        raise BadRequestException("The pilot expiry must be in the future")
    if expires > now + timedelta(days=MAX_PILOT_DAYS):
        raise BadRequestException(f"A pilot grant lasts at most {MAX_PILOT_DAYS} days (renew with a new grant)")
    if db.query(G).filter(G.organization_id == org_id, G.status == "PROPOSED").first() is not None:
        raise BadRequestException("this organisation already has a proposed pilot grant")
    if mexico_dormancy.active_pilot_grant(db, org_id) is not None:
        raise BadRequestException("this organisation already has an active pilot grant")
    row = G(organization_id=org_id, status="PROPOSED", reason=reason[:300],
            scope_note=((data or {}).get("scopeNote") or "").strip()[:300] or None, expires_at=expires,
            proposed_by_id=actor_id)
    db.add(row)
    db.flush()
    _pilot_audit(db, actor_id=actor_id, action="propose_pilot_grant", entity_type="mx_pilot_grant", entity_id=row.id,
                 new={"organizationId": org_id, "expiresAt": expires.isoformat()}, reason=reason[:300])
    db.commit()
    return pilot_grant_view(row)


def approve_grant(db: Session, grant_id: int, actor_id: Optional[int]) -> dict:
    row = _pilot_grant(db, grant_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED grant can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.proposed_by_id:
        raise MXRefuse("MX_FOUR_EYES_REQUIRED", "a pilot grant must be approved by a Super Admin other than its proposer",
                      row.organization_id)
    unmet = [c for c in pilot_preconditions(db) if not c["met"]]
    if unmet:
        raise MXRefuse("MX_PILOT_PRECONDITIONS", "a pilot grant needs: " + "; ".join(f"{c['label']} ({c['detail']})"
                                                                                    for c in unmet), row.organization_id)
    if (_pilot_org(db, row.organization_id).workspace_type or "").upper() != "EVALUATION":
        raise MXRefuse("MX_PILOT_EVALUATION_ONLY", "a pilot is only for an EVALUATION workspace", row.organization_id)
    if mexico_dormancy._aware(row.expires_at) <= _pilot_now():
        raise BadRequestException("The proposed grant has already expired — propose a new one")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, _pilot_now()
    _pilot_audit(db, actor_id=actor_id, action="approve_pilot_grant", entity_type="mx_pilot_grant", entity_id=row.id,
                 new={"organizationId": row.organization_id, "status": "APPROVED"})
    db.commit()
    return pilot_grant_view(row)


def withdraw_grant(db: Session, grant_id: int, reason: str, actor_id: Optional[int]) -> dict:
    row = _pilot_grant(db, grant_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED grant can be withdrawn (this one is {row.status})")
    row.status, row.revoke_reason = "WITHDRAWN", ((reason or "").strip()[:300] or None)
    _pilot_audit(db, actor_id=actor_id, action="withdraw_pilot_grant", entity_type="mx_pilot_grant", entity_id=row.id,
                 reason=row.revoke_reason)
    db.commit()
    return pilot_grant_view(row)


def revoke_grant(db: Session, grant_id: int, reason: str, actor_id: Optional[int]) -> dict:
    row = _pilot_grant(db, grant_id)
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Revoking a pilot grant needs a reason")
    if row.status != "APPROVED":
        raise BadRequestException(f"Only an APPROVED grant can be revoked (this one is {row.status})")
    row.status, row.revoked_by_id, row.revoked_at, row.revoke_reason = "REVOKED", actor_id, _pilot_now(), text[:300]
    _pilot_audit(db, actor_id=actor_id, action="revoke_pilot_grant", entity_type="mx_pilot_grant", entity_id=row.id,
                 new={"organizationId": row.organization_id, "status": "REVOKED"}, reason=text[:300])
    db.commit()
    return pilot_grant_view(row)


def pilot_grant_view(row) -> dict:
    expires = mexico_dormancy._aware(row.expires_at)
    state = row.status
    if row.status == "APPROVED":
        state = "ACTIVE" if expires > _pilot_now() else "EXPIRED"
    return {"id": row.id, "organizationId": row.organization_id, "status": row.status, "state": state,
            "reason": row.reason, "scopeNote": row.scope_note, "expiresAt": expires.isoformat() if expires else None,
            "proposedById": row.proposed_by_id, "approvedById": row.approved_by_id,
            "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
            "revokedById": row.revoked_by_id, "revokeReason": row.revoke_reason}


def list_grants(db: Session, org_id: Optional[int] = None) -> list:
    G = _pilot_models().PayrollMxPilotGrant
    q = db.query(G)
    if org_id is not None:
        q = q.filter(G.organization_id == org_id)
    return [pilot_grant_view(g) for g in q.order_by(G.id.desc())]


def pilot_status(db: Session, org_id: int) -> dict:
    """What an organisation's screens show (its banner)."""
    grant = mexico_dormancy.active_pilot_grant(db, org_id)
    return {"pilot": mexico_dormancy.is_pilot_organization(db, org_id), "active": grant is not None,
            "expiresAt": mexico_dormancy._aware(grant.expires_at).isoformat() if grant is not None else None,
            "rules": ["CFDI only through the PAC sandbox", "no salary payments", "no authority filings",
                      "every payslip watermarked", "journal for comparison only"]}


# ── pilot rules (non-binding output) ────────────────────────────────────────

def refuse_payments(db: Session, org_id: int) -> None:
    if mexico_dormancy.is_pilot_organization(db, org_id):
        raise MXRefuse("MX_PILOT_NO_PAYMENTS", "a pilot organisation never pays salaries through Zoiko — the pilot runs "
                                              "alongside the current payroll provider", org_id)


def refuse_filings(db: Session, org_id: int) -> None:
    if mexico_dormancy.is_pilot_organization(db, org_id):
        raise MXRefuse("MX_PILOT_NO_FILINGS", "a pilot organisation never files with or pays an authority — "
                                             "reconciliation (e.g. SUA figures) stays available", org_id)


def refuse_non_sandbox_pac(db: Session, org_id: int, environment: Optional[str]) -> None:
    if mexico_dormancy.is_pilot_organization(db, org_id) and (environment or "").upper() != "SANDBOX":
        raise MXRefuse("MX_PILOT_SANDBOX_ONLY", f"a pilot organisation stamps only through a SANDBOX PAC "
                                               f"(the employer is set to {environment or 'none'})", org_id)


def run_is_pilot(run) -> bool:
    return bool((getattr(run, "mx_approval_fingerprint", None) or {}).get("pilot"))


# ── Phase 10g: the "no new Mexican organisations" switch (four-eyes) ───────────

def _onboarding_pause_row(db: Session, pause_id: int):
    row = db.get(_pilot_models().PayrollMxOnboardingPause, pause_id)
    if row is None:
        raise NotFoundException(f"Onboarding pause change {pause_id} not found")
    return row


def propose_onboarding_change(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    """PAUSE or RESUME new Mexican organisations; a different Super Admin approves."""
    P = _pilot_models().PayrollMxOnboardingPause
    action = str((data or {}).get("action") or "").upper()
    if action not in ("PAUSE", "RESUME"):
        raise BadRequestException("action must be PAUSE or RESUME")
    reason = ((data or {}).get("reason") or "").strip()
    if not reason:
        raise BadRequestException("Pausing or resuming new Mexican organisations needs a reason")
    paused = mexico_dormancy.onboarding_paused(db)
    if (action == "PAUSE") == paused:
        raise BadRequestException(f"new Mexican organisations are already {'paused' if paused else 'not paused'}")
    if db.query(P).filter(P.status == "PROPOSED").first() is not None:
        raise BadRequestException("a pause / resume change is already proposed — approve or withdraw it first")
    row = P(action=action, status="PROPOSED", reason=reason[:300], proposed_by_id=actor_id)
    db.add(row)
    db.flush()
    _pilot_audit(db, actor_id=actor_id, action="propose_mx_onboarding_change", entity_type="mx_onboarding_pause",
                 entity_id=row.id, new={"action": action}, reason=reason[:300])
    db.commit()
    return onboarding_pause_view(row)


def approve_onboarding_change(db: Session, pause_id: int, actor_id: Optional[int]) -> dict:
    row = _onboarding_pause_row(db, pause_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED change can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.proposed_by_id:
        raise MXRefuse("MX_FOUR_EYES_REQUIRED", "pausing or resuming new Mexican organisations needs a Super Admin "
                                               "other than its proposer")
    if (row.action == "PAUSE") == mexico_dormancy.onboarding_paused(db):
        raise BadRequestException("the switch is already in that state — withdraw this change")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, _pilot_now()
    _pilot_audit(db, actor_id=actor_id, action="approve_mx_onboarding_change", entity_type="mx_onboarding_pause",
                 entity_id=row.id, new={"action": row.action, "paused": row.action == "PAUSE"})
    db.commit()
    return onboarding_pause_view(row)


def withdraw_onboarding_change(db: Session, pause_id: int, actor_id: Optional[int]) -> dict:
    row = _onboarding_pause_row(db, pause_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED change can be withdrawn (this one is {row.status})")
    row.status = "WITHDRAWN"
    _pilot_audit(db, actor_id=actor_id, action="withdraw_mx_onboarding_change", entity_type="mx_onboarding_pause",
                 entity_id=row.id, new={"action": row.action})
    db.commit()
    return onboarding_pause_view(row)


def onboarding_pause_view(row) -> dict:
    return {"id": row.id, "action": row.action, "status": row.status, "reason": row.reason,
            "proposedById": row.proposed_by_id, "approvedById": row.approved_by_id,
            "approvedAt": row.approved_at.isoformat() if row.approved_at else None}


def onboarding_pause_state(db: Session) -> dict:
    P = _pilot_models().PayrollMxOnboardingPause
    return {"paused": mexico_dormancy.onboarding_paused(db),
            "changes": [onboarding_pause_view(r) for r in db.query(P).order_by(P.id.desc())]}


# ── master-data copy (D5) ───────────────────────────────────────────────────

_SKIP = {"id", "organization_id", "created_at", "updated_at", "created_by_id"}


def _mx_open_rows(rows):
    return [r for r in rows if getattr(r, "effective_to", None) is None]


def _copy_categories(db: Session, org_id: int) -> dict:
    """The source rows per category (the master data only)."""
    m = _pilot_models()
    prof = _mx_open_rows(db.query(m.PayrollMxEmployerProfile).filter(m.PayrollMxEmployerProfile.organization_id == org_id)
                 .order_by(m.PayrollMxEmployerProfile.id).all())
    pid = {p.id for p in prof}
    regs = [r for r in _mx_open_rows(db.query(m.PayrollMxImssRegistration)
                             .filter(m.PayrollMxImssRegistration.organization_id == org_id)
                             .order_by(m.PayrollMxImssRegistration.id).all()) if r.employer_profile_id in pid]
    rid = {r.id for r in regs}
    estab = [e for e in db.query(m.PayrollMxEstablishment).filter(m.PayrollMxEstablishment.organization_id == org_id)
             .order_by(m.PayrollMxEstablishment.id) if e.is_active and e.employer_profile_id in pid
             and (e.imss_registration_id is None or e.imss_registration_id in rid)]
    isn = [r for r in _mx_open_rows(db.query(m.PayrollMxIsnRegistration).filter(m.PayrollMxIsnRegistration.organization_id == org_id)
                            .order_by(m.PayrollMxIsnRegistration.id).all()) if r.employer_profile_id in pid]
    pol = [p for p in _mx_open_rows(db.query(m.PayrollMxLaborPolicy).filter(m.PayrollMxLaborPolicy.organization_id == org_id)
                            .order_by(m.PayrollMxLaborPolicy.id).all()) if p.employer_profile_id in pid]
    emps = (db.query(m.PayrollEmployee).filter(m.PayrollEmployee.organization_id == org_id,
                                                m.PayrollEmployee.country_code == "MX")
            .order_by(m.PayrollEmployee.id).all())
    eid = {e.id for e in emps}
    profiles = [p for p in db.query(m.EmployeeStatutoryProfile)
                .filter(m.EmployeeStatutoryProfile.organization_id == org_id,
                        m.EmployeeStatutoryProfile.country_code == "MX",
                        m.EmployeeStatutoryProfile.effective_to.is_(None))
                .order_by(m.EmployeeStatutoryProfile.id) if p.employee_id in eid]
    return {"employerProfiles": prof, "imssRegistrations": regs, "establishments": estab, "isnRegistrations": isn,
            "laborPolicies": pol, "employees": emps, "statutoryProfiles": profiles}


# Per category: columns reset in the copy (environment-bound or org-scoped), and the
# id columns remapped to the copies.
_RESET = {
    "employerProfiles": {"previous_version_id": None, "stamp_test_status": "NOT_TESTED", "stamp_test_uuid": None,
                         "stamp_tested_at": None},
    "employees": {"legal_entity_id": None, "pay_group_id": None},
}
_REMAP = {
    "imssRegistrations": {"employer_profile_id": "employerProfiles"},
    "establishments": {"employer_profile_id": "employerProfiles", "imss_registration_id": "imssRegistrations"},
    "isnRegistrations": {"employer_profile_id": "employerProfiles"},
    "laborPolicies": {"employer_profile_id": "employerProfiles"},
    "statutoryProfiles": {"employee_id": "employees", "mx_establishment_id": "establishments",
                          "mx_imss_registration_id": "imssRegistrations"},
}
_ORDER = ("employerProfiles", "imssRegistrations", "establishments", "isnRegistrations", "laborPolicies", "employees",
          "statutoryProfiles")


def _mx_copy_columns(row, category: str) -> list:
    skip = _SKIP | set(_RESET.get(category, {})) | set(_REMAP.get(category, {}))
    return [c.name for c in row.__table__.columns if c.name not in skip]


def _mx_copy_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def _mx_copy_snapshot(cats: dict) -> dict:
    """{category: [(model, source id, {column: value})]} — every value read ONCE,
    as plain data, while the caller holds the source's tenant context (10f)."""
    return {k: [(type(r), r.id, {c.name: getattr(r, c.name) for c in r.__table__.columns}) for r in rows]
            for k, rows in cats.items()}


def _mx_copy_fingerprint(snap: dict) -> str:
    data = {k: [{c: _mx_copy_value(vals[c]) for c in _mx_copy_columns(model, k)} for model, _, vals in rows]
            for k, rows in snap.items()}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _mx_execute_copy(db: Session, snap: dict, target_id: int, actor_id: Optional[int], not_copied=None,
                     profile_map: Optional[dict] = None) -> dict:
    """Create the target's rows from the snapshot, remapping every reference to
    the copies; with `profile_map` (10f, same-RFC employer) the target's OWN
    employer profiles stand in for the source's and none is created. Returns
    the diff report (every copied row compared column by column with its source)."""
    ids = {k: {} for k in _ORDER}
    if profile_map is not None:
        ids["employerProfiles"] = dict(profile_map)
    pairs = []
    for category in _ORDER:
        if category == "employerProfiles" and profile_map is not None:
            continue
        for model, src_id, vals in snap[category]:
            values = {c: vals[c] for c in _mx_copy_columns(model, category)}
            values.update(_RESET.get(category, {}))
            for col, ref in _REMAP.get(category, {}).items():
                old = vals[col]
                values[col] = ids[ref].get(old) if old is not None else None
                if old is not None and values[col] is None:
                    raise MXRefuse("MX_COPY_REFERENCE", f"{category} row {src_id}: {col} {old} was not copied", target_id)
            values["organization_id"] = target_id
            if "created_by_id" in model.__table__.columns:
                values["created_by_id"] = actor_id
            copy = model(**values)
            db.add(copy)
            db.flush()
            ids[category][src_id] = copy.id
            pairs.append((category, model, src_id, vals, copy))
    differences = [{"category": category, "sourceId": src_id, "targetId": dst.id, "column": col}
                   for category, model, src_id, vals, dst in pairs for col in _mx_copy_columns(model, category)
                   if _mx_copy_value(vals[col]) != _mx_copy_value(getattr(dst, col))]
    copied = {k: 0 for k in _ORDER}
    for category, *_ in pairs:
        copied[category] += 1
    report = {"copied": copied, "differences": differences, "reset": {k: sorted(v) for k, v in _RESET.items()},
              "notCopied": not_copied or {}}
    if profile_map is not None:
        report["employerProfilesMatchedByRfc"] = len(profile_map)
    return report


def _mx_not_copied(db: Session, org_id: int) -> dict:
    m = _pilot_models()
    count = lambda model, *f: db.query(model.id).filter(*f).count()          # noqa: E731
    regs = [r.id for r in db.query(m.PayrollMxImssRegistration.id).filter(
        m.PayrollMxImssRegistration.organization_id == org_id)]
    return {
        "payrollRuns": count(m.PayrollRun, m.PayrollRun.organization_id == org_id),
        "riskPremiums (re-approve in the live organisation)":
            db.query(m.PayrollMxRiskPremium.id).filter(m.PayrollMxRiskPremium.registration_id.in_(regs)).count() if regs else 0,
        "credentialReferences (register the live CSD / PAC credentials)":
            count(m.PayrollMxCredentialRef, m.PayrollMxCredentialRef.organization_id == org_id),
        "infonavitNotices (re-record with their evidence)":
            count(m.PayrollMxInfonavitNotice, m.PayrollMxInfonavitNotice.organization_id == org_id),
        "employer stamp tests (re-run against the production PAC)": "reset",
        "employee legal entity / pay group links (organisation-scoped)": "reset",
    }


def _copy_target_refusal(db: Session, source_id: int, target_id: int) -> Optional[str]:
    from app.modules.payroll import service

    m = _pilot_models()
    if source_id == target_id:
        return "the source and the target organisation must differ"
    if not mexico_dormancy.is_pilot_organization(db, source_id):
        return f"organisation {source_id} is not a pilot organisation"
    if mexico_dormancy.is_pilot_organization(db, target_id):
        return f"organisation {target_id} is itself a pilot organisation — the target must be a new live organisation"
    if (_pilot_org(db, target_id).workspace_type or "").upper() == "EVALUATION":
        return "the target must be a live (non-EVALUATION) organisation"
    if not mexico_dormancy.registry_available(db):
        return "general availability is not open (the registry is not AVAILABLE)"
    if not mexico_dormancy.is_mexico(service._resolve_org_country(db, target_id)):
        return "the target organisation's payroll jurisdiction is not Mexico"
    if db.query(m.PayrollMxEmployerProfile.id).filter(m.PayrollMxEmployerProfile.organization_id == target_id).first():
        return "the target already has Mexican employer data — the copy only fills an empty organisation"
    if db.query(m.PayrollEmployee.id).filter(m.PayrollEmployee.organization_id == target_id,
                                             m.PayrollEmployee.country_code == "MX").first():
        return "the target already has Mexican employees — the copy only fills an empty organisation"
    return None


def propose_copy(db: Session, source_id: int, target_id: int, reason: str, actor_id: Optional[int]) -> dict:
    C = _pilot_models().PayrollMxMasterCopy
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A master-data copy needs a reason")
    refusal = _copy_target_refusal(db, source_id, target_id)
    if refusal:
        raise MXRefuse("MX_COPY_REFUSED", refusal, target_id)
    cats = _copy_categories(db, source_id)
    for p in cats["laborPolicies"]:
        if p.collective_agreement_id is not None:
            raise MXRefuse("MX_COPY_COLLECTIVE_AGREEMENT", f"labour policy {p.id} references a collective agreement — "
                                                          f"record the agreement in the live organisation first", target_id)
    if not cats["employerProfiles"]:
        raise MXRefuse("MX_COPY_REFUSED", "the pilot organisation has no open employer profile to copy", target_id)
    plan = {"counts": {k: len(v) for k, v in cats.items()}, "notCopied": _mx_not_copied(db, source_id)}
    if db.query(C).filter(C.organization_id == target_id, C.status == "PROPOSED").first() is not None:
        raise BadRequestException("a copy into this organisation is already proposed")
    row = C(source_organization_id=source_id, organization_id=target_id, status="PROPOSED", reason=text[:300],
            plan=plan, plan_sha256=_mx_copy_fingerprint(_mx_copy_snapshot(cats)), proposed_by_id=actor_id)
    db.add(row)
    db.flush()
    _pilot_audit(db, actor_id=actor_id, action="propose_mx_master_copy", entity_type="mx_master_copy", entity_id=row.id,
                 new={"source": source_id, "target": target_id, "counts": plan["counts"]}, reason=text[:300])
    db.commit()
    return master_copy_view(row)


def _master_copy(db: Session, copy_id: int):
    row = db.get(_pilot_models().PayrollMxMasterCopy, copy_id)
    if row is None:
        raise NotFoundException(f"Master-data copy {copy_id} not found")
    return row


def approve_copy(db: Session, copy_id: int, actor_id: Optional[int]) -> dict:
    """A different Super Admin approves; the source must be unchanged since the
    proposal; the copy runs in ONE transaction, then the diff report is built."""
    row = _master_copy(db, copy_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED copy can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.proposed_by_id:
        raise MXRefuse("MX_FOUR_EYES_REQUIRED", "a master-data copy must be approved by a Super Admin other than its "
                                               "proposer", row.organization_id)
    refusal = _copy_target_refusal(db, row.source_organization_id, row.organization_id)
    if refusal:
        raise MXRefuse("MX_COPY_REFUSED", refusal, row.organization_id)
    snap = _mx_copy_snapshot(_copy_categories(db, row.source_organization_id))
    if _mx_copy_fingerprint(snap) != row.plan_sha256:
        raise MXRefuse("MX_COPY_SOURCE_CHANGED", "the pilot's master data changed after the copy was proposed — cancel "
                                                "and propose again", row.organization_id)
    try:
        report = _mx_execute_copy(db, snap, row.organization_id, actor_id,
                                  row.plan.get("notCopied") if isinstance(row.plan, dict) else None)
        row.status, row.approved_by_id, row.executed_at, row.report = "EXECUTED", actor_id, _pilot_now(), report
        _pilot_audit(db, actor_id=actor_id, action="execute_mx_master_copy", entity_type="mx_master_copy",
                     entity_id=row.id, new={"source": row.source_organization_id, "target": row.organization_id,
                                            "copied": report["copied"], "differences": len(report["differences"])})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return master_copy_view(row)


def cancel_copy(db: Session, copy_id: int, reason: str, actor_id: Optional[int]) -> dict:
    row = _master_copy(db, copy_id)
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED copy can be cancelled (this one is {row.status})")
    row.status, row.cancelled_reason = "CANCELLED", ((reason or "").strip()[:300] or None)
    _pilot_audit(db, actor_id=actor_id, action="cancel_mx_master_copy", entity_type="mx_master_copy", entity_id=row.id,
                 reason=row.cancelled_reason)
    db.commit()
    return master_copy_view(row)


def master_copy_view(row) -> dict:
    return {"id": row.id, "sourceOrganizationId": row.source_organization_id, "targetOrganizationId": row.organization_id,
            "status": row.status, "reason": row.reason, "plan": row.plan, "report": row.report,
            "proposedById": row.proposed_by_id, "approvedById": row.approved_by_id,
            "executedAt": row.executed_at.isoformat() if row.executed_at else None,
            "cancelledReason": row.cancelled_reason}


def list_copies(db: Session) -> list:
    C = _pilot_models().PayrollMxMasterCopy
    return [master_copy_view(c) for c in db.query(C).order_by(C.id.desc())]
