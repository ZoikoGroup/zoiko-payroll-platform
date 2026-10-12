"""
modules/payroll/retention_service.py
------------------------------------
Shared platform records-governance capability, jurisdiction-aware:

* PERSONAL-DATA ACCESS LOG (payroll_personal_data_access_events) — append-only
  record of report / certificate / payslip / bank-file downloads and views of
  statutory profile data, with actor, organisation, resource, employee,
  purpose, result, client address, user agent and, under a SafeGuard
  assisted-access session, that session id;
* LEGAL HOLDS (payroll_legal_holds) — organisation-wide or per employee; while
  one is ACTIVE no record of its jurisdiction in scope can be deleted;
  releasing needs a different user from the one who placed it (four-eyes);
* RETENTION POLICIES (payroll_retention_policies) — per (jurisdiction, record
  category): BLOCKED_UNDECIDED (no purge) until the jurisdiction's owner
  decisions are recorded and a period is approved by a second Super Admin;
* the DELETION GUARD a jurisdiction's employee-delete path calls.

The platform never chooses a retention period, never purges on a schedule and
never claims privacy-law compliance — those are owner / counsel decisions.

A jurisdiction opts in by registering its settings (jurisdiction_hooks hook
"retention_settings" returning ``RetentionJurisdiction``): its record
categories, the owner-decision keys that unblock retention, how to read their
state, how to validate an employee in its scope and which statutory records
count as retained evidence. Hong Kong is the first (hong_kong_service; D-2 /
D-3 / D-19). A country without settings has none of these controls, so no
other country's behaviour changes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Tuple

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import jurisdiction_hooks
from app.modules.payroll.models import LegalHold, PersonalDataAccessEvent, RetentionPolicy

ACCESS_ACTIONS = ("VIEW_REPORT", "DOWNLOAD_CERTIFICATE", "DOWNLOAD_CERTIFICATES_ZIP", "VIEW_STATUTORY_PROFILE",
                  "DOWNLOAD_PAYSLIP", "DOWNLOAD_PAYSLIPS_ZIP", "DOWNLOAD_BANK_FILE")


@dataclass(frozen=True)
class RetentionJurisdiction:
    country: str
    label: str                                          # "Hong Kong" — used in operator messages
    categories: Tuple[Tuple[str, str], ...]             # (record category, description)
    period_decision: str                                # owner decision that fixes the period (HK: D-2)
    end_decision: str                                   # owner decision delete vs anonymise (HK: D-3)
    decision_reference: str                             # evidence tag recorded on a proposed policy
    decision_state: Callable[[Session, str], str]       # -> "RECORDED" / "SUBMITTED" / "OPEN"
    validate_employee: Callable[[Session, int, int], None]                 # 404 outside the tenant / scope
    retained_record_label: Callable[[Session, int, int], Optional[str]]    # label of retained statutory records, or None
    has_statutory_profile: Callable[[Session, int], bool]                  # retained profile versions (by employee)
    report_matches: Callable[[object], bool]            # is this GeneratedReport one of the jurisdiction's
    audit_spec: str = "Records governance"


def settings(country: str) -> RetentionJurisdiction:
    return jurisdiction_hooks.call(country, "retention_settings")


def enabled(country: str) -> bool:
    return jurisdiction_hooks.has_module(country)


def _iso(value):
    return value.isoformat() if value else None


def _audit(db, cfg: RetentionJurisdiction, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     legal_reference=cfg.audit_spec, old_value=old,
                     new_value={**(new or {}), "jurisdiction": cfg.country}, reason=reason, auto_commit=False)


# ── personal-data access log ────────────────────────────────────────────

def _request_meta(request) -> dict:
    if request is None:
        return {}
    meta = {"client_address": (getattr(getattr(request, "client", None), "host", None) or None),
            "user_agent": (request.headers.get("user-agent") or "")[:300] or None}
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            from app.core.security import decode_assisted_access_token

            payload = decode_assisted_access_token(auth.split(" ", 1)[1].strip())
            if payload and payload.get("assisted_access_session_id"):
                meta["assisted_access_session_id"] = int(payload["assisted_access_session_id"])
        except Exception:   # an access log never breaks the request it records
            pass
    return meta


def record_access(db: Session, country: str, organization_id: int, actor_id: Optional[int], action: str,
                  resource_type: str, resource_id: Optional[int] = None, employee_id: Optional[int] = None,
                  report_type: Optional[str] = None, purpose: Optional[str] = None, result: str = "SUCCESS",
                  request=None) -> PersonalDataAccessEvent:
    cfg = settings(country)
    if action not in ACCESS_ACTIONS:
        raise ValueError(f"unknown {cfg.country} access action {action!r}")
    event = PersonalDataAccessEvent(organization_id=organization_id, jurisdiction_country=cfg.country,
                                    actor_id=actor_id, action=action, resource_type=resource_type,
                                    resource_id=resource_id, employee_id=employee_id, report_type=report_type,
                                    purpose=(purpose or None) and purpose[:200], result=result,
                                    **_request_meta(request))
    db.add(event)
    db.commit()
    return event


def _report_country(report) -> Optional[str]:
    if report is None:
        return None
    for country in jurisdiction_hooks._MODULES:
        if settings(country).report_matches(report):
            return country
    return None


def log_report_download(db: Session, organization_id: int, actor_id: Optional[int], report_id: int, action: str,
                        employee_id: Optional[int] = None, request=None, purpose: Optional[str] = None) -> None:
    """Called by the SHARED download routes after the file was produced; a
    no-op for a report of a jurisdiction without access logging."""
    from app.modules.payroll.models import GeneratedReport

    report = (db.query(GeneratedReport)
              .filter(GeneratedReport.id == report_id, GeneratedReport.organization_id == organization_id).first())
    country = _report_country(report)
    if country is None:
        return
    record_access(db, country, organization_id, actor_id, action, "generated_report", resource_id=report.id,
                  employee_id=employee_id if employee_id is not None else report.employee_id,
                  report_type=report.report_type, purpose=purpose, request=request)


def log_payslip_access(db: Session, organization_id: int, actor_id: Optional[int], payslip_ids: list, action: str,
                       request=None, run_id: Optional[int] = None) -> None:
    """Called by the SHARED payslip / payslip-ZIP / bank-file download routes
    after the file was produced: one event per payslip of a jurisdiction with
    access logging (with its employee); a no-op for every other payslip."""
    from app.modules.payroll.models import PayslipItem

    if not payslip_ids:
        return
    rows = (db.query(PayslipItem.id, PayslipItem.employee_id, PayslipItem.country_code)
            .filter(PayslipItem.organization_id == organization_id, PayslipItem.id.in_(list(payslip_ids))).all())
    logged = [r for r in rows if enabled((r.country_code or "").upper())]
    if not logged:
        return
    meta = _request_meta(request)
    for r in logged:
        db.add(PersonalDataAccessEvent(organization_id=organization_id, jurisdiction_country=r.country_code.upper(),
                                       actor_id=actor_id, action=action, resource_type="payslip_item",
                                       resource_id=r.id, employee_id=r.employee_id,
                                       purpose=f"payroll run {run_id}" if run_id else None, result="SUCCESS", **meta))
    db.commit()


def list_access_events(db: Session, country: str, organization_id: int, employee_id: Optional[int] = None,
                       limit: int = 200) -> list:
    q = db.query(PersonalDataAccessEvent).filter(PersonalDataAccessEvent.organization_id == organization_id,
                                                 PersonalDataAccessEvent.jurisdiction_country == settings(country).country)
    if employee_id is not None:
        q = q.filter(PersonalDataAccessEvent.employee_id == employee_id)
    rows = q.order_by(PersonalDataAccessEvent.id.desc()).limit(max(1, min(int(limit), 1000))).all()
    return [{"id": e.id, "actorId": e.actor_id, "action": e.action, "resourceType": e.resource_type,
             "resourceId": e.resource_id, "employeeId": e.employee_id, "reportType": e.report_type,
             "purpose": e.purpose, "result": e.result, "clientAddress": e.client_address,
             "assistedAccessSessionId": e.assisted_access_session_id,
             "occurredAt": _iso(e.occurred_at)} for e in rows]


# ── legal holds ─────────────────────────────────────────────────────────

def place_legal_hold(db: Session, country: str, organization_id: int, employee_id: Optional[int], reason: str,
                     reference: Optional[str], actor_id: Optional[int]) -> LegalHold:
    cfg = settings(country)
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("a legal hold needs a reason")
    if employee_id is not None:
        cfg.validate_employee(db, employee_id, organization_id)     # 404 outside the tenant / jurisdiction
    hold = LegalHold(organization_id=organization_id, jurisdiction_country=cfg.country, employee_id=employee_id,
                     status="ACTIVE", reason=reason, reference=(reference or None), placed_by_id=actor_id,
                     placed_at=datetime.utcnow().replace(microsecond=0))
    db.add(hold)
    db.flush()
    _audit(db, cfg, actor_id, "create", "legal_hold", hold.id,
           new={"employeeId": employee_id, "reference": reference, "scope": "EMPLOYEE" if employee_id else "ORGANISATION"},
           reason=reason)
    db.commit()
    return hold


def release_legal_hold(db: Session, country: str, organization_id: int, hold_id: int, reason: str,
                       actor_id: Optional[int]) -> LegalHold:
    from app.modules.payroll.service import require_four_eyes

    cfg = settings(country)
    hold = (db.query(LegalHold)
            .filter(LegalHold.id == hold_id, LegalHold.organization_id == organization_id,
                    LegalHold.jurisdiction_country == cfg.country).first())
    if hold is None:
        raise NotFoundException(f"{cfg.label} legal hold", hold_id)
    if hold.status != "ACTIVE":
        raise BadRequestException(f"legal hold #{hold.id} is {hold.status}")
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("releasing a legal hold needs a reason")
    require_four_eyes(hold.placed_by_id, actor_id, "Releasing a legal hold")
    hold.status, hold.released_by_id, hold.release_reason = "RELEASED", actor_id, reason
    hold.released_at = datetime.utcnow().replace(microsecond=0)
    _audit(db, cfg, actor_id, "status_change", "legal_hold", hold.id, old={"status": "ACTIVE"},
           new={"status": "RELEASED"}, reason=reason)
    db.commit()
    return hold


def active_legal_holds(db: Session, country: str, organization_id: int, employee_id: Optional[int] = None) -> list:
    rows = (db.query(LegalHold).filter(LegalHold.organization_id == organization_id,
                                       LegalHold.jurisdiction_country == settings(country).country,
                                       LegalHold.status == "ACTIVE").all())
    if employee_id is None:
        return rows
    return [h for h in rows if h.employee_id is None or h.employee_id == employee_id]


def list_legal_holds(db: Session, country: str, organization_id: int) -> list:
    rows = (db.query(LegalHold).filter(LegalHold.organization_id == organization_id,
                                       LegalHold.jurisdiction_country == settings(country).country)
            .order_by(LegalHold.id.desc()).all())
    return [{"id": h.id, "employeeId": h.employee_id, "scope": "EMPLOYEE" if h.employee_id else "ORGANISATION",
             "status": h.status, "reason": h.reason, "reference": h.reference, "placedById": h.placed_by_id,
             "placedAt": _iso(h.placed_at), "releasedById": h.released_by_id,
             "releasedAt": _iso(h.released_at), "releaseReason": h.release_reason} for h in rows]


def assert_employee_deletable(db: Session, country: str, organization_id: int, employee_id: int) -> None:
    """Refuses to hard-delete an employee of an opted-in jurisdiction under a
    legal hold, or one with retained statutory records (the jurisdiction says
    which). Deactivate the employee instead — the retention period is an
    owner decision."""
    cfg = settings(country)
    holds = active_legal_holds(db, country, organization_id, employee_id)
    if holds:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            f"legal hold #{holds[0].id} is in force — {cfg.label} records in its scope cannot be deleted"))
    retained = cfg.retained_record_label(db, organization_id, employee_id)
    if retained is None and (db.query(LegalHold.id).filter(LegalHold.organization_id == organization_id,
                                                           LegalHold.jurisdiction_country == cfg.country,
                                                           LegalHold.employee_id == employee_id).first()):
        retained = "legal-hold history"                     # a released hold is retained evidence too
    if retained is not None:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            f"this {cfg.label} employee has retained statutory records ({retained}) — set the status to Inactive "
            "instead; the retention period is an owner / privacy-counsel decision"))
    if cfg.has_statutory_profile(db, employee_id):
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            f"this {cfg.label} employee has statutory profile versions (retained evidence) — set the status to "
            "Inactive instead"))


# ── retention policies ──────────────────────────────────────────────────

def retention_policies(db: Session, country: str) -> dict:
    cfg = settings(country)
    period, end = cfg.decision_state(db, cfg.period_decision), cfg.decision_state(db, cfg.end_decision)
    out = []
    for key, label in cfg.categories:
        rows = (db.query(RetentionPolicy).filter(RetentionPolicy.jurisdiction_country == cfg.country,
                                                 RetentionPolicy.record_category == key)
                .order_by(RetentionPolicy.id.desc()).all())
        approved = next((r for r in rows if r.status == "APPROVED"), None)
        draft = next((r for r in rows if r.status == "DRAFT"), None)
        out.append({"category": key, "label": label, "state": "APPROVED" if approved else "BLOCKED_UNDECIDED",
                    "purgePermitted": approved is not None,
                    "retentionYears": approved.retention_years if approved else None,
                    "endOfRetention": approved.end_of_retention if approved else None,
                    "legalBasis": approved.legal_basis if approved else None,
                    "approved": _policy_view(approved) if approved else None,
                    "draft": _policy_view(draft) if draft else None,
                    "blocker": None if approved else (
                        f"owner decision {cfg.period_decision} (retention period) is not recorded" if period != "RECORDED"
                        else "no approved retention period for this category")})
    return {"decisions": {cfg.period_decision: period, cfg.end_decision: end}, "categories": out,
            "notice": ("No retention period is chosen by the platform. Until a period is approved for a category, "
                       "nothing in it may be purged; legal holds always prevail.")}


def _policy_view(r) -> dict:
    return {"id": r.id, "status": r.status, "retentionYears": r.retention_years, "endOfRetention": r.end_of_retention,
            "legalBasis": r.legal_basis, "decisionReference": r.decision_reference, "reason": r.reason,
            "createdById": r.created_by_id, "approvedById": r.approved_by_id, "approvedAt": _iso(r.approved_at)}


def propose_retention_policy(db: Session, country: str, data: dict, actor_id: Optional[int]) -> dict:
    cfg = settings(country)
    category = data.get("recordCategory")
    if category not in dict(cfg.categories):
        raise BadRequestException("unknown record category")
    if cfg.decision_state(db, cfg.period_decision) != "RECORDED":
        raise BadRequestException(f"blocked: owner decision {cfg.period_decision} (retention period per data category) "
                                  "is not recorded — the period is a legal decision, never guessed by the platform")
    years = data.get("retentionYears")
    if not isinstance(years, int) or years < 1:
        raise BadRequestException(f"retentionYears must be a whole number of years taken from the "
                                  f"{cfg.period_decision} decision")
    end = data.get("endOfRetention")
    if end not in ("DELETE", "ANONYMISE"):
        raise BadRequestException(f"endOfRetention must be DELETE or ANONYMISE (owner decision {cfg.end_decision})")
    if cfg.decision_state(db, cfg.end_decision) != "RECORDED":
        raise BadRequestException(f"blocked: owner decision {cfg.end_decision} (deletion vs anonymisation) is not recorded")
    if not (data.get("legalBasis") or "").strip() or not (data.get("reason") or "").strip():
        raise BadRequestException("legalBasis and reason are required")
    row = RetentionPolicy(jurisdiction_country=cfg.country, record_category=category, status="DRAFT",
                          retention_years=years, end_of_retention=end, legal_basis=data["legalBasis"].strip(),
                          decision_reference=cfg.decision_reference, reason=data["reason"].strip(),
                          created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, cfg, actor_id, "create", "retention_policy", row.id, new=_policy_view(row), reason=row.reason)
    db.commit()
    return _policy_view(row)


def approve_retention_policy(db: Session, country: str, policy_id: int, actor_id: Optional[int]) -> dict:
    cfg = settings(country)
    row = db.get(RetentionPolicy, policy_id)
    if row is None or row.jurisdiction_country != cfg.country:
        raise NotFoundException("retention policy not found")
    # lock the category's policies so two concurrent approvals cannot both end APPROVED
    (db.query(RetentionPolicy).filter(RetentionPolicy.jurisdiction_country == cfg.country,
                                      RetentionPolicy.record_category == row.record_category)
     .order_by(RetentionPolicy.id).with_for_update().all())
    db.refresh(row)
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT policy can be approved (this one is {row.status})")
    if actor_id is None or actor_id == row.created_by_id:
        raise BadRequestException("a retention policy must be approved by a Super Admin other than its maker")
    for prev in db.query(RetentionPolicy).filter(RetentionPolicy.jurisdiction_country == cfg.country,
                                                 RetentionPolicy.record_category == row.record_category,
                                                 RetentionPolicy.status == "APPROVED"):
        prev.status = "SUPERSEDED"
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    _audit(db, cfg, actor_id, "approve", "retention_policy", row.id, old={"status": "DRAFT"},
           new={"status": "APPROVED", "category": row.record_category, "years": row.retention_years}, reason=row.reason)
    db.commit()
    return _policy_view(row)


def purge_refusal(db: Session, country: str, category: str) -> Optional[str]:
    """The guard any purge must call first: None only when the category has an
    approved retention period."""
    entry = next((c for c in retention_policies(db, country)["categories"] if c["category"] == category), None)
    if entry is None:
        return "unknown record category"
    return None if entry["purgePermitted"] else f"purge refused: {entry['blocker']}"
