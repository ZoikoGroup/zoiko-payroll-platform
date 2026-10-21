"""
modules/support_access/router.py
--------------------------------
JIT Support Access API (ZP-PRIV D.5).

Operator side   /api/super-admin/support-access/...
Tenant side     /api/organization-admin/support-access/...

Responses are display-ready: organization name/code, requester and approver
emails looked up by id at response time, UTC timestamps with a trailing "Z",
approvalExpiresAt for pending grants and supportUsername for active ones.
The password is returned ONLY by GET /{id}/credentials (owner, active,
audited on every read). Operator and Platform Security views never carry an
employee name or code: resolved employees are shown to the tenant only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_org_admin,
    get_current_platform_security,
    get_current_support_requester,
    require_recent_mfa,
)
from app.core.exceptions import NotFoundException, UnauthorizedException
from app.database import get_db
from app.modules.support_access import models as M
from app.modules.support_access import service

operator_router = APIRouter(prefix="/super-admin/support-access", tags=["Support Access (platform)"])
tenant_router = APIRouter(prefix="/organization-admin/support-access", tags=["Support Access (organization)"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class SupportAccessRequest(_Camel):
    organization_id: Optional[int] = Field(None, alias="organizationId")
    organization_code: Optional[str] = Field(None, alias="organizationCode")
    reason: str
    # Optional: generated server-side (ZSA-YYYYMMDD-XXXXXX) when not supplied.
    ticket_reference: Optional[str] = Field(None, alias="ticketReference")
    minutes: int
    scope_type: str = Field("diagnostics", alias="scopeType")
    scope_entity_id: Optional[int] = Field(None, alias="scopeEntityId")
    scope_pay_group_id: Optional[int] = Field(None, alias="scopePayGroupId")
    employee_codes: Optional[List[str]] = Field(None, alias="employeeCodes")


class ReasonBody(_Camel):
    reason: str = ""


class ApproveBody(_Camel):
    note: Optional[str] = None
    field_classes: Optional[List[str]] = Field(None, alias="fieldClasses")
    employee_ids: Optional[List[int]] = Field(None, alias="employeeIds")


class BreakGlassBody(_Camel):
    organization_id: Optional[int] = Field(None, alias="organizationId")
    organization_code: Optional[str] = Field(None, alias="organizationCode")
    incident_reference: str = Field(..., alias="incidentReference")
    reason: str
    acknowledged: bool = False
    mfa_code: Optional[str] = Field(None, alias="mfaCode")


class ReviewBody(_Camel):
    outcome: str
    findings: str


# ── Serialisation ────────────────────────────────────────────────────────────

def _z(value: Optional[datetime]) -> Optional[str]:
    """Naive UTC -> ISO-8601 with Z, so every countdown is right everywhere."""
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def _email(db: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    from app.modules.auth.models import User

    row = db.query(User.email).filter(User.id == user_id).first()
    return row[0] if row else None


def _outcome(grant: M.SupportAccessGrant) -> str:
    """Plain-language history line (D.6)."""
    if grant.status == M.PENDING:
        waiting = []
        if grant.approved_by_user_id is None:
            waiting.append("the organization")
        if grant.zoiko_required and grant.zoiko_approved_by_user_id is None:
            waiting.append("Platform Security")
        return "Waiting for " + " and ".join(waiting) + " to approve"
    return {
        M.ACTIVE: "Active",
        M.DENIED: f"Declined: {grant.decline_reason or ''}".strip(),
        M.CANCELLED: "Cancelled by the requester",
        M.REVOKED: (f"Revoked by the tenant administrator: {grant.revoke_reason or ''}" if grant.revoked_by_tenant
                    else f"Revoked by Platform Security: {grant.revoke_reason or ''}"),
        M.EXITED: "Ended by the requester",
        M.EXPIRED: "Ended automatically when the time limit was reached",
        M.EXPIRED_UNUSED: "No one approved it within 60 minutes",
    }.get(grant.status, grant.status)


def grant_view(db: Session, grant: M.SupportAccessGrant, audience: str) -> Dict[str, Any]:
    org = service._organization(db, grant.organization_id)
    view: Dict[str, Any] = {
        "id": grant.id,
        "status": grant.status,
        "outcome": _outcome(grant),
        "organizationId": grant.organization_id,
        "organizationName": getattr(org, "organization_name", None),
        "organizationCode": getattr(org, "organization_code", None),
        "reason": grant.reason,
        "ticketReference": grant.ticket_reference,
        "requestedMinutes": grant.requested_minutes,
        "scopeType": grant.scope_type,
        "scopeLabel": service.scope_label(grant),
        "employeeCount": (len(grant.requested_employee_codes or [])
                          if grant.scope_type == M.SCOPE_EMPLOYEES else None),
        "allowedFieldClasses": grant.allowed_field_classes or list(service.DEFAULT_FIELD_CLASSES),
        "zoikoRequired": bool(grant.zoiko_required),
        "tenantApproved": grant.approved_by_user_id is not None,
        "zoikoApproved": grant.zoiko_approved_by_user_id is not None,
        "requestedAt": _z(grant.requested_at),
        "approvalExpiresAt": _z(grant.approval_expires_at) if grant.status == M.PENDING else None,
        "approvedAt": _z(grant.approved_at),
        "activatedAt": _z(grant.activated_at),
        "expiresAt": _z(grant.expires_at),
        "endedAt": _z(grant.ended_at),
        "requesterEmail": _email(db, grant.requested_by_user_id),
        "approverEmail": _email(db, grant.approved_by_user_id),
        "zoikoApproverEmail": _email(db, grant.zoiko_approved_by_user_id),
        "approvalNote": grant.approval_note,
        "declineReason": grant.decline_reason,
        "revokeReason": grant.revoke_reason,
        "revokedByTenant": grant.revoked_by_tenant,
        "isBreakGlass": bool(grant.is_break_glass),
        "incidentReference": grant.incident_reference,
        "reviewDueAt": _z(grant.review_due_at),
        "reviewedAt": _z(grant.reviewed_at),
        "reviewOutcome": grant.review_outcome,
        "reviewNote": grant.review_note,
        "reviewerEmail": _email(db, grant.reviewed_by_user_id),
        "reviewOverdue": bool(grant.is_break_glass and grant.reviewed_at is None and grant.review_due_at
                              and grant.review_due_at <= datetime.utcnow()),
        "supportUsername": grant.support_username if grant.status == M.ACTIVE else None,
    }
    if audience == "security":
        # Approvals / live sessions: no personal data, no ticket free text
        # beyond what the requester typed for the approver.
        view.pop("supportUsername", None)
    return view


def tenant_grant_view(db: Session, grant: M.SupportAccessGrant) -> Dict[str, Any]:
    """The tenant's view: everything in grant_view plus the employees the
    request names (resolved inside the tenant only) and scope unit names.
    Kept separate so no operator or Platform Security code path can reach
    employee records at all."""
    view = grant_view(db, grant, "tenant")
    if grant.scope_type == M.SCOPE_EMPLOYEES:
        if grant.status == M.PENDING:
            view["resolvedEmployees"] = service.resolve_codes(db, grant)
        else:
            from app.modules.payroll.models import PayrollEmployee

            rows = (db.query(PayrollEmployee.id, PayrollEmployee.employee_code, PayrollEmployee.name)
                    .join(M.SupportGrantEmployee, M.SupportGrantEmployee.employee_id == PayrollEmployee.id)
                    .filter(M.SupportGrantEmployee.grant_id == grant.id).all())
            view["grantedEmployees"] = [{"employeeId": i, "employeeCode": c, "name": n} for i, c, n in rows]
    if grant.scope_entity_id or grant.scope_pay_group_id:
        from app.modules.organizations.models import LegalEntity, PayGroup

        if grant.scope_entity_id:
            ent = db.query(LegalEntity.name).filter(LegalEntity.id == grant.scope_entity_id).first()
            view["scopeEntityName"] = ent[0] if ent else None
        if grant.scope_pay_group_id:
            grp = db.query(PayGroup.name).filter(PayGroup.id == grant.scope_pay_group_id).first()
            view["scopePayGroupName"] = grp[0] if grp else None
    return view


def _organization_id(db: Session, organization_id: Optional[int], organization_code: Optional[str]) -> int:
    from app.modules.organizations.models import Organization

    if organization_id:
        return organization_id
    if organization_code:
        org = (db.query(Organization.id)
               .filter(Organization.organization_code == organization_code.strip()).first())
        if org:
            return org[0]
    raise NotFoundException("Organization")


# ── Operator side ────────────────────────────────────────────────────────────

@operator_router.get("/config", summary="Allowed durations, scopes and field classes")
def support_access_config(current_user=Depends(get_current_support_requester)):
    from app.config import settings

    return {
        "allowedMinutes": service.allowed_minutes(),
        "maxMinutes": settings.SUPPORT_ACCESS_MAX_MINUTES,
        "approvalWindowMinutes": settings.SUPPORT_ACCESS_APPROVAL_WINDOW_MINUTES,
        "breakGlassMinutes": settings.SUPPORT_ACCESS_BREAK_GLASS_MINUTES,
        "maxEmployees": settings.SUPPORT_ACCESS_MAX_EMPLOYEES,
        "scopeTypes": list(M.SCOPE_TYPES),
        "reasons": list(service.REQUEST_REASONS),
        "role": service._role(current_user),
    }


@operator_router.get("/ticket-number", summary="A fresh ticket number to show on the request form")
def support_access_ticket_number(current_user=Depends(get_current_support_requester), db: Session = Depends(get_db)):
    return {"ticketReference": service.generate_ticket_reference(db)}


@operator_router.get("/tenants", summary="Tenant picker over registry metadata only")
def search_tenants(q: str = Query("", max_length=80), limit: int = Query(20, ge=1, le=50),
                   current_user=Depends(get_current_support_requester), db: Session = Depends(get_db)):
    from sqlalchemy import or_

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import CompanyComplianceDetails

    query = (db.query(Organization.id, Organization.organization_name, Organization.organization_code,
                      Organization.is_active, CompanyComplianceDetails.jurisdiction_country)
             .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(Organization.organization_name.ilike(like),
                                 Organization.organization_code.ilike(like)))
    rows = query.order_by(Organization.organization_name).limit(limit).all()
    return [{"id": i, "name": n, "code": c, "isActive": a, "jurisdiction": j} for i, n, c, a, j in rows]


@operator_router.get("/tenants/{organization_id}/scope-options",
                     summary="A tenant's legal entities and pay groups (names only) for the scope picker")
def tenant_scope_options(organization_id: int, current_user=Depends(get_current_support_requester),
                         db: Session = Depends(get_db)):
    from app.modules.organizations.models import LegalEntity, PayGroup

    entities = (db.query(LegalEntity.id, LegalEntity.name)
                .filter(LegalEntity.organization_id == organization_id, LegalEntity.is_active.is_(True)).all())
    groups = (db.query(PayGroup.id, PayGroup.name)
              .filter(PayGroup.organization_id == organization_id, PayGroup.is_active.is_(True)).all())
    return {"legalEntities": [{"id": i, "name": n} for i, n in entities],
            "payGroups": [{"id": i, "name": n} for i, n in groups]}


@operator_router.post("/request", summary="Request temporary, read-only access to one tenant")
def request_access(body: SupportAccessRequest, request: Request,
                   current_user=Depends(get_current_support_requester), db: Session = Depends(get_db)):
    org_id = _organization_id(db, body.organization_id, body.organization_code)
    grant = service.request_grant(
        db, current_user, organization_id=org_id, reason=body.reason, ticket_reference=body.ticket_reference,
        minutes=body.minutes, scope_type=body.scope_type, scope_entity_id=body.scope_entity_id,
        scope_pay_group_id=body.scope_pay_group_id, employee_codes=body.employee_codes, request=request)
    return grant_view(db, grant, "operator")


@operator_router.post("/{grant_id}/cancel", summary="Cancel your own pending request")
def cancel_request(grant_id: int, request: Request, current_user=Depends(get_current_support_requester),
                   db: Session = Depends(get_db)):
    return grant_view(db, service.cancel(db, current_user, grant_id, request=request), "operator")


@operator_router.post("/{grant_id}/exit", summary="End your own active session now")
def exit_session(grant_id: int, request: Request, current_user=Depends(get_current_support_requester),
                 db: Session = Depends(get_db)):
    return grant_view(db, service.exit_grant(db, current_user, grant_id, request=request), "operator")


@operator_router.get("/active", summary="Your live grant (null once it has ended or lapsed)")
def my_active(current_user=Depends(get_current_support_requester), db: Session = Depends(get_db)):
    grant = service.live_grant_for(db, current_user.id)
    return {"grant": grant_view(db, grant, "operator") if grant else None}


@operator_router.get("/mine", summary="Your requests, newest first")
def my_history(current_user=Depends(get_current_support_requester), db: Session = Depends(get_db)):
    return [grant_view(db, g, "operator") for g in service.my_grants(db, current_user)]


@operator_router.get("/{grant_id}/credentials", summary="Your temporary login (owner only, active only, audited)")
def my_credentials(grant_id: int, request: Request, current_user=Depends(get_current_support_requester),
                   db: Session = Depends(get_db)):
    creds = service.credentials(db, current_user, grant_id, request=request)
    return {"username": creds["username"], "password": creds["password"], "expiresAt": _z(creds["expiresAt"])}


@operator_router.get("/live", summary="Every pending or active grant (Platform Security)")
def live(current_user=Depends(get_current_platform_security), db: Session = Depends(get_db)):
    return [grant_view(db, g, "security") for g in service.live_sessions(db)]


@operator_router.post("/{grant_id}/revoke", summary="Revoke a pending or active grant (Platform Security)")
def security_revoke(grant_id: int, body: ReasonBody, request: Request,
                    current_user=Depends(get_current_platform_security), db: Session = Depends(get_db)):
    grant = service.security_revoke(db, current_user, grant_id, body.reason, request=request)
    return grant_view(db, grant, "security")


@operator_router.get("/approvals", summary="Requests waiting for the independent Zoiko approval")
def approvals(current_user=Depends(get_current_platform_security), db: Session = Depends(get_db)):
    return [grant_view(db, g, "security") for g in service.approvals_queue(db)]


@operator_router.post("/{grant_id}/zoiko-approve", summary="Independent Zoiko approval (never the requester)")
def zoiko_approve(grant_id: int, request: Request, current_user=Depends(get_current_platform_security),
                  _mfa=Depends(require_recent_mfa), db: Session = Depends(get_db)):
    return grant_view(db, service.zoiko_approve(db, current_user, grant_id, request=request), "security")


@operator_router.post("/break-glass", summary="Emergency access (Platform Security; fresh MFA code required)")
def break_glass(body: BreakGlassBody, request: Request, current_user=Depends(get_current_platform_security),
                db: Session = Depends(get_db)):
    from app.modules.auth import mfa

    org_id = _organization_id(db, body.organization_id, body.organization_code)
    if mfa.enforcement_on() and (
            not body.mfa_code or not mfa.verify_second_factor(db, current_user, code=body.mfa_code, request=request)):
        service.audit(db, service.EV_MFA_STEP_UP_FAILED, None, actor=current_user, organization_id=org_id,
                      request=request, reason="break-glass")
        raise UnauthorizedException("A fresh authentication code is required for emergency access.")
    grant = service.open_break_glass(db, current_user, organization_id=org_id,
                                     incident_reference=body.incident_reference, reason=body.reason,
                                     acknowledged=body.acknowledged, request=request)
    return grant_view(db, grant, "operator")


@operator_router.get("/pending-review", summary="Break-glass accesses waiting for their independent review")
def pending_review(current_user=Depends(get_current_platform_security), db: Session = Depends(get_db)):
    return [grant_view(db, g, "security") for g in service.pending_reviews(db)]


@operator_router.post("/{grant_id}/review", summary="Close a break-glass review (a different officer)")
def review(grant_id: int, body: ReviewBody, request: Request,
           current_user=Depends(get_current_platform_security), db: Session = Depends(get_db)):
    grant = service.review_break_glass(db, current_user, grant_id, body.outcome, body.findings, request=request)
    return grant_view(db, grant, "security")


# ── Tenant side ──────────────────────────────────────────────────────────────

def _tenant_admin(current_user=Depends(get_current_org_admin)):
    """A real org admin of the organization (never a support or assisted
    principal acting for it)."""
    if service._role(current_user) != "org_admin" or getattr(current_user, "is_temporary", False):
        raise NotFoundException("Support access")
    return current_user


@tenant_router.get("/", summary="Support access requests and sessions for your organization")
def tenant_list(current_user=Depends(_tenant_admin), db: Session = Depends(get_db)):
    grants = service.tenant_grants(db, current_user)
    return {
        "pending": [tenant_grant_view(db, g) for g in grants
                    if g.status == M.PENDING and g.approved_by_user_id is None],
        "awaitingZoiko": [tenant_grant_view(db, g) for g in grants
                          if g.status == M.PENDING and g.approved_by_user_id is not None],
        "active": [tenant_grant_view(db, g) for g in grants if g.status == M.ACTIVE],
        "history": [tenant_grant_view(db, g) for g in grants if g.status in M.ENDED_STATUSES],
        "fieldClassChoices": list(service.FIELD_CLASS_CHOICES),
        "defaultFieldClasses": list(service.DEFAULT_FIELD_CLASSES),
    }


@tenant_router.post("/{grant_id}/approve", summary="Approve (scope may be narrowed, never widened)")
def tenant_approve(grant_id: int, body: ApproveBody, request: Request, current_user=Depends(_tenant_admin),
                   _mfa=Depends(require_recent_mfa), db: Session = Depends(get_db)):
    grant = service.approve(db, current_user, grant_id, note=body.note, field_classes=body.field_classes,
                            employee_ids=body.employee_ids, request=request)
    return tenant_grant_view(db, grant)


@tenant_router.post("/{grant_id}/deny", summary="Decline with a reason (shown to the requester)")
def tenant_deny(grant_id: int, body: ReasonBody, request: Request, current_user=Depends(_tenant_admin),
                db: Session = Depends(get_db)):
    return tenant_grant_view(db, service.deny(db, current_user, grant_id, body.reason, request=request))


@tenant_router.post("/{grant_id}/revoke", summary="Revoke active access now (reason required)")
def tenant_revoke(grant_id: int, body: ReasonBody, request: Request, current_user=Depends(_tenant_admin),
                  db: Session = Depends(get_db)):
    grant = service.tenant_revoke(db, current_user, grant_id, body.reason, request=request)
    return tenant_grant_view(db, grant)


@tenant_router.get("/audit", summary="Your organization's support access audit trail (C07)")
def tenant_audit(current_user=Depends(_tenant_admin), db: Session = Depends(get_db)):
    events = service.tenant_audit(db, current_user)
    grant_ids = {e.grant_id for e in events if e.grant_id}
    tickets = {g.id: g.ticket_reference for g in db.query(M.SupportAccessGrant)
               .filter(M.SupportAccessGrant.id.in_(grant_ids)).all()} if grant_ids else {}
    return [{
        "id": e.id, "recordedAt": _z(e.recorded_at), "eventType": e.event_type, "grantId": e.grant_id,
        "ticketReference": tickets.get(e.grant_id),
        "actorRole": e.actor_role, "actorEmail": _email(db, e.actor_user_id),
        "requesterEmail": _email(db, e.requested_by_user_id),
        "supportUsername": _email(db, e.support_user_id), "reason": e.reason,
        "clientAddress": e.client_address, "detail": e.detail,
    } for e in events]
