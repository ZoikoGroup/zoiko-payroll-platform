"""
modules/security/router.py
--------------------------
Security plane API (ZP-PRIV E01-E05, D06 inventory). Metadata only: no
payload, no personal data beyond the actor's own platform account.

Platform (super_admin + platform_security; get_current_security_reader):
  GET  /api/super-admin/security-events            Audit Explorer
  GET  /api/super-admin/security-events/verify     hash-chain verification
  GET  /api/super-admin/alert-rules                rules + thresholds
  GET  /api/super-admin/alert-events               deduplicated alerts
  POST /api/super-admin/alert-events/{id}/acknowledge
  POST /api/super-admin/alert-rules/{key}/test-fire (platform_security; drill)
  GET  /api/super-admin/privileged-inventory
  GET  /api/super-admin/machine-clients            inventory (no secrets, no scopes' data)
  GET  /api/super-admin/privacy-assurance/controls  control register + reviews + verdict
  POST /api/super-admin/privacy-assurance/controls/{id}/reviews (platform_security, step-up)

Tenant (org admins, own organization only):
  GET  /api/organization-admin/security-events     Security Activity
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_org_admin,
    get_current_platform_security,
    get_current_security_reader,
    require_recent_mfa,
)
from app.core.exceptions import NotFoundException
from app.database import get_db
from app.modules.security import alerts as alert_engine
from app.modules.security import events as security_events
from app.modules.security.models import AlertEvent, AlertRule, MachineClient, SecurityEvent

platform_router = APIRouter(prefix="/super-admin", tags=["Security (platform)"])
tenant_router = APIRouter(prefix="/organization-admin", tags=["Security (organization)"])


def _z(value) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def event_view(e: SecurityEvent) -> dict:
    return {
        "id": e.id, "occurredAt": _z(e.occurred_at), "correlationId": e.correlation_id, "eventType": e.event_type,
        "actorUserId": e.actor_user_id, "actorRole": e.actor_role, "onBehalfOfUserId": e.on_behalf_of_user_id,
        "organizationId": e.organization_id, "grantId": e.grant_id, "ticketReference": e.ticket_reference,
        "targetType": e.target_type, "targetId": e.target_id, "action": e.action, "result": e.result,
        "reasonCode": e.reason_code, "decisionTraceId": e.decision_trace_id, "ip": e.ip,
    }


def _filtered(db: Session, organization_id, actor_user_id, grant_id, correlation_id, result, event_type,
              start_date, end_date):
    q = db.query(SecurityEvent)
    if organization_id is not None:
        q = q.filter(SecurityEvent.organization_id == organization_id)
    if actor_user_id is not None:
        q = q.filter((SecurityEvent.actor_user_id == actor_user_id)
                     | (SecurityEvent.on_behalf_of_user_id == actor_user_id))
    if grant_id is not None:
        q = q.filter(SecurityEvent.grant_id == grant_id)
    if correlation_id:
        q = q.filter(SecurityEvent.correlation_id == correlation_id)
    if result:
        q = q.filter(SecurityEvent.result == result)
    if event_type:
        q = q.filter(SecurityEvent.event_type == event_type)
    if start_date:
        q = q.filter(SecurityEvent.occurred_at >= datetime.combine(start_date, datetime.min.time(), timezone.utc))
    if end_date:
        q = q.filter(SecurityEvent.occurred_at
                     < datetime.combine(end_date + timedelta(days=1), datetime.min.time(), timezone.utc))
    return q


@platform_router.get("/security-events", summary="Audit Explorer: unified security events (metadata only)")
def list_security_events(
    organization_id: Optional[int] = Query(None, alias="organizationId"),
    actor_user_id: Optional[int] = Query(None, alias="actorUserId"),
    grant_id: Optional[int] = Query(None, alias="grantId"),
    correlation_id: Optional[str] = Query(None, alias="correlationId"),
    result: Optional[str] = Query(None, pattern="^(allow|deny|error)$"),
    event_type: Optional[str] = Query(None, alias="eventType"),
    start_date: Optional[date] = Query(None, alias="startDate"),
    end_date: Optional[date] = Query(None, alias="endDate"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user=Depends(get_current_security_reader),
    db: Session = Depends(get_db),
):
    q = _filtered(db, organization_id, actor_user_id, grant_id, correlation_id, result, event_type,
                  start_date, end_date)
    rows = q.order_by(SecurityEvent.id.desc()).offset(skip).limit(limit).all()
    return {"items": [event_view(e) for e in rows], "total": q.count()}


@platform_router.get("/security-events/verify", summary="Verify the security event hash chain")
def verify_security_events(current_user=Depends(get_current_security_reader), db: Session = Depends(get_db)):
    return security_events.verify_chain(db)


@platform_router.get("/alert-rules", summary="Security alert rules and thresholds")
def list_alert_rules(current_user=Depends(get_current_security_reader), db: Session = Depends(get_db)):
    alert_engine.ensure_rules(db)
    return [{"key": r.key, "description": r.description, "windowSeconds": r.window_seconds,
             "threshold": r.threshold, "severity": r.severity, "channel": r.channel, "enabled": r.enabled}
            for r in db.query(AlertRule).order_by(AlertRule.key).all()]


@platform_router.get("/alert-events", summary="Deduplicated security alerts")
def list_alert_events(
    status: Optional[str] = Query(None, pattern="^(open|acknowledged|resolved)$"),
    limit: int = Query(200, ge=1, le=500),
    current_user=Depends(get_current_security_reader),
    db: Session = Depends(get_db),
):
    q = db.query(AlertEvent)
    if status:
        q = q.filter(AlertEvent.status == status)
    return [{"id": a.id, "ruleKey": a.rule_key, "severity": a.severity, "summary": a.summary,
             "organizationId": a.organization_id, "firstSeen": _z(a.first_seen), "lastSeen": _z(a.last_seen),
             "count": a.count, "status": a.status, "acknowledgedBy": a.acknowledged_by,
             "acknowledgedAt": _z(a.acknowledged_at), "deliveryReceipt": a.delivery_receipt, "isDrill": a.is_drill}
            for a in q.order_by(AlertEvent.last_seen.desc()).limit(limit).all()]


@platform_router.post("/alert-events/{alert_id}/acknowledge", summary="Acknowledge an alert")
def acknowledge_alert(alert_id: int, current_user=Depends(get_current_security_reader), db: Session = Depends(get_db)):
    row = db.query(AlertEvent).filter(AlertEvent.id == alert_id).first()
    if row is None:
        raise NotFoundException("Alert")
    row.status = "acknowledged"
    row.acknowledged_by = current_user.id
    row.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    security_events.emit(db, "ALERT_ACKNOWLEDGED", result="allow", actor_user_id=current_user.id,
                         actor_role="platform", target_type="alert", target_id=f"alert:{alert_id}")
    return {"id": row.id, "status": row.status}


@platform_router.post("/alert-rules/{rule_key}/test-fire", summary="Fire a drill alert for one rule")
def test_fire_alert(rule_key: str, current_user=Depends(get_current_platform_security), db: Session = Depends(get_db)):
    if rule_key not in alert_engine.RULES_BY_KEY:
        raise NotFoundException("Alert rule")
    row = alert_engine.raise_alert(db, rule_key, dedupe_key=f"drill:{current_user.id}:{datetime.now(timezone.utc).timestamp()}",
                                   summary=f"DRILL: test-fire of {rule_key} by user #{current_user.id}", is_drill=True)
    return {"id": row.id, "ruleKey": row.rule_key, "deliveryReceipt": row.delivery_receipt}


@platform_router.get("/privileged-inventory", summary="Privileged humans, machine accounts and live grants")
def privileged_inventory(current_user=Depends(get_current_security_reader), db: Session = Depends(get_db)):
    from app.modules.security.inventory import build_inventory

    return build_inventory(db)


@platform_router.get("/machine-clients", summary="Machine client inventory (metadata only)")
def machine_client_inventory(current_user=Depends(get_current_security_reader), db: Session = Depends(get_db)):
    from app.modules.organizations.models import Organization

    names = dict(db.query(Organization.id, Organization.organization_code).all())
    return [{"id": c.id, "organizationId": c.organization_id, "organizationCode": names.get(c.organization_id),
             "name": c.name, "scopeCount": len(c.scopes or []), "createdAt": _z(c.created_at),
             "expiresAt": _z(c.expires_at), "lastUsedAt": _z(c.last_used_at), "rotatedAt": _z(c.rotated_at),
             "revokedAt": _z(c.revoked_at), "status": "revoked" if c.revoked_at else (
                 "expired" if c.expires_at and _aware(c.expires_at) <= datetime.now(timezone.utc) else "active")}
            for c in db.query(MachineClient).order_by(MachineClient.id).all()]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── Privacy assurance (ZP-PRIV Part 12) ─────────────────────────────────────


class ControlReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(accepted|rejected)$")
    proofReference: str = Field(..., min_length=3, max_length=200)


@platform_router.get("/privacy-assurance/controls", summary="The 46 privacy controls, reviews and the verdict")
def privacy_assurance_controls(current_user=Depends(get_current_security_reader), db: Session = Depends(get_db)):
    from app.modules.security import assurance

    return assurance.assurance_report(db)


@platform_router.post("/privacy-assurance/controls/{control_id}/reviews",
                      summary="Record an independent review of one control (platform_security, step-up)")
def record_control_review(control_id: str, body: ControlReviewRequest, request: Request,
                          current_user=Depends(get_current_platform_security), _mfa=Depends(require_recent_mfa),
                          db: Session = Depends(get_db)):
    from app.modules.security import assurance

    return assurance.record_review(db, current_user, control_id, body.decision, body.proofReference, request=request)


@tenant_router.get("/security-events", summary="Your organization's security activity")
def tenant_security_events(
    actor_user_id: Optional[int] = Query(None, alias="actorUserId"),
    result: Optional[str] = Query(None, pattern="^(allow|deny|error)$"),
    event_type: Optional[str] = Query(None, alias="eventType"),
    start_date: Optional[date] = Query(None, alias="startDate"),
    end_date: Optional[date] = Query(None, alias="endDate"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user=Depends(get_current_org_admin),
    db: Session = Depends(get_db),
):
    q = _filtered(db, current_user.organization_id, actor_user_id, None, None, result, event_type,
                  start_date, end_date)
    rows = q.order_by(SecurityEvent.id.desc()).offset(skip).limit(limit).all()
    counts = dict(q.with_entities(SecurityEvent.result, func.count(SecurityEvent.id))
                  .group_by(SecurityEvent.result).all())
    return {"items": [event_view(e) for e in rows], "total": q.count(), "byResult": counts}


# ── Machine clients and webhooks (organization admins; ZP-PRIV D06) ─────────


from app.modules.security import machine_clients as mc  # noqa: E402


class ApiClientBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    scopes: list[str]
    expires_in_days: int = Field(90, alias="expiresInDays")


class WebhookBody(BaseModel):
    url: str
    events: list[str]


def _client_view(c) -> dict:
    return {"id": c.id, "name": c.name, "scopes": list(c.scopes or []), "createdAt": _z(c.created_at),
            "expiresAt": _z(c.expires_at), "lastUsedAt": _z(c.last_used_at), "rotatedAt": _z(c.rotated_at),
            "revokedAt": _z(c.revoked_at),
            "status": "revoked" if c.revoked_at else (
                "expired" if _aware(c.expires_at) <= datetime.now(timezone.utc) else "active")}


@tenant_router.get("/api-clients/scopes", summary="Scopes an API client may be given")
def api_client_scopes(current_user=Depends(get_current_org_admin)):
    return [{"scope": k, "routes": sorted(f"{m} {p}" for m, p in v[0]), "fieldClasses": sorted(v[1])}
            for k, v in sorted(mc.SCOPES.items())]


@tenant_router.get("/api-clients", summary="Your organization's API clients")
def list_api_clients(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    rows = (db.query(MachineClient).filter(MachineClient.organization_id == current_user.organization_id)
            .order_by(MachineClient.id.desc()).all())
    return [_client_view(c) for c in rows]


@tenant_router.post("/api-clients", summary="Create an API client (the secret is shown once)")
def create_api_client(body: ApiClientBody, current_user=Depends(get_current_org_admin),
                      _mfa=Depends(require_recent_mfa), db: Session = Depends(get_db)):
    out = mc.create_client(db, current_user, name=body.name, scopes=body.scopes,
                           expires_in_days=body.expires_in_days)
    security_events.emit(db, "MACHINE_CLIENT_CREATED", result="allow", actor_user_id=current_user.id,
                         actor_role="org_admin", organization_id=current_user.organization_id,
                         target_type="machine_client", target_id=f"client:{out['client'].id}", action="create")
    return {**_client_view(out["client"]), "credential": out["credential"]}


@tenant_router.post("/api-clients/{client_id}/rotate", summary="Rotate an API client secret (shown once)")
def rotate_api_client(client_id: int, current_user=Depends(get_current_org_admin),
                      _mfa=Depends(require_recent_mfa), db: Session = Depends(get_db)):
    out = mc.rotate_client(db, current_user, client_id)
    security_events.emit(db, "MACHINE_CLIENT_ROTATED", result="allow", actor_user_id=current_user.id,
                         actor_role="org_admin", organization_id=current_user.organization_id,
                         target_type="machine_client", target_id=f"client:{client_id}", action="update")
    return {**_client_view(out["client"]), "credential": out["credential"]}


@tenant_router.post("/api-clients/{client_id}/revoke", summary="Revoke an API client now")
def revoke_api_client(client_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = mc.revoke_client(db, current_user, client_id)
    security_events.emit(db, "MACHINE_CLIENT_REVOKED", result="allow", actor_user_id=current_user.id,
                         actor_role="org_admin", organization_id=current_user.organization_id,
                         target_type="machine_client", target_id=f"client:{client_id}", action="update")
    return _client_view(row)


@tenant_router.get("/webhooks", summary="Your organization's outbound webhooks")
def list_webhooks(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.security.models import WebhookEndpoint

    rows = db.query(WebhookEndpoint).filter(WebhookEndpoint.organization_id == current_user.organization_id).all()
    return [{"id": w.id, "url": w.url, "events": w.events, "status": w.status, "createdAt": _z(w.created_at)}
            for w in rows]


@tenant_router.post("/webhooks", summary="Register an outbound webhook (signing secret shown once)")
def create_webhook(body: WebhookBody, current_user=Depends(get_current_org_admin),
                   _mfa=Depends(require_recent_mfa), db: Session = Depends(get_db)):
    out = mc.create_webhook(db, current_user, url=body.url, events=body.events)
    w = out["endpoint"]
    return {"id": w.id, "url": w.url, "events": w.events, "status": w.status, "signingSecret": out["signingSecret"]}


@tenant_router.post("/webhooks/{webhook_id}/disable", summary="Disable an outbound webhook")
def disable_webhook(webhook_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.security.models import WebhookEndpoint

    w = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == webhook_id).first()
    if w is None or w.organization_id != current_user.organization_id:
        raise NotFoundException("Webhook")
    w.status = "disabled"
    db.commit()
    return {"id": w.id, "status": w.status}


# ── Data region, retention, legal hold, data-access requests (F02/F03) ─────

from app.modules.security import governance  # noqa: E402


class HoldBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    employee_id: Optional[int] = Field(None, alias="employeeId")
    reason: str
    reference: Optional[str] = None


class ReasonBody(BaseModel):
    reason: str


class RequestBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    request_type: str = Field(..., alias="requestType")
    employee_id: Optional[int] = Field(None, alias="employeeId")


class OutcomeBody(BaseModel):
    outcome: str = ""


@tenant_router.get("/data-governance", summary="Your data region, retention policy, legal holds and requests")
def data_governance(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.config import settings
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import LegalHold
    from app.modules.security.models import DataAccessRequest

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    holds = (db.query(LegalHold).filter(LegalHold.organization_id == current_user.organization_id)
             .order_by(LegalHold.id.desc()).all())
    requests = (db.query(DataAccessRequest).filter(DataAccessRequest.organization_id == current_user.organization_id)
                .order_by(DataAccessRequest.id.desc()).all())
    return {
        "dataRegion": org.data_region, "deploymentRegion": governance.home_region(),
        "supportedRegions": list(governance.SUPPORTED_REGIONS),
        "regionPolicy": "Privileged access, processing, replication and backups of your data stay in your region; "
                        "Zoiko support access from another region is refused.",
        "retention": {"workerDataYearsAfterLeaving": settings.WORKER_DATA_RETENTION_YEARS,
                      "auditYears": settings.AUDIT_RETENTION_YEARS},
        "legalHolds": [{"id": h.id, "employeeId": h.employee_id, "scope": "platform-wide"
                        if h.jurisdiction_country == governance.PLATFORM_WIDE else h.jurisdiction_country,
                        "status": h.status, "reason": h.reason, "reference": h.reference,
                        "placedBy": h.placed_by_id, "placedAt": _z(h.placed_at), "releasedAt": _z(h.released_at)}
                       for h in holds],
        "requests": [{"id": r.id, "employeeId": r.employee_id, "requestType": r.request_type, "status": r.status,
                      "receivedAt": _z(r.received_at), "dueAt": _z(r.due_at), "completedAt": _z(r.completed_at),
                      "outcome": r.outcome} for r in requests],
    }


@tenant_router.post("/legal-holds", summary="Place a legal hold (organization-wide or one worker)")
def place_legal_hold(body: HoldBody, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    hold = governance.place_hold(db, current_user, employee_id=body.employee_id, reason=body.reason,
                                 reference=body.reference)
    return {"id": hold.id, "status": hold.status}


@tenant_router.post("/legal-holds/{hold_id}/release", summary="Release a legal hold (a different administrator)")
def release_legal_hold(hold_id: int, body: ReasonBody, current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    hold = governance.release_hold(db, current_user, hold_id, body.reason)
    return {"id": hold.id, "status": hold.status}


@tenant_router.post("/data-access-requests", summary="Record a data-access / erasure / rectification request")
def create_data_access_request(body: RequestBody, current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    row = governance.create_request(db, current_user, request_type=body.request_type, employee_id=body.employee_id)
    return {"id": row.id, "status": row.status, "dueAt": _z(row.due_at)}


@tenant_router.post("/data-access-requests/{request_id}/complete", summary="Mark a data-access request complete")
def complete_data_access_request(request_id: int, body: OutcomeBody, current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    row = governance.complete_request(db, current_user, request_id, body.outcome)
    return {"id": row.id, "status": row.status}
