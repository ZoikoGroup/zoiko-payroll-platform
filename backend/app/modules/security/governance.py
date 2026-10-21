"""
modules/security/governance.py
------------------------------
Privacy governance controls with code behind them (ZP-PRIV F02, F03).

Data region (F02, decision 9). Every organization has a data_region (EU, UK,
US, IN, ME, APAC); a deployment runs in one home region
(settings.DATA_REGION). Privileged retrieval (support access, break-glass),
processing jobs, replication and backups of a tenant are refused outside the
tenant's region - ``assert_region(...)`` is called by the support-access
service, the PDP for temporary logins, and the backup / restore scripts.

Retention, legal hold and data-access requests (F03, decision 10). The HK
retention_service legal-hold table is used platform-wide: a hold with
jurisdiction "XX" covers every jurisdiction of the organization (or of one
worker). While a hold is ACTIVE no deletion path may remove the covered
records (employee delete, bulk delete, organization hard-delete, retention
purge). Placing is audited; releasing needs a different user (four-eyes).
Worker records are kept WORKER_DATA_RETENTION_YEARS (7) after termination,
then become eligible for the explicit, logged retention purge - never while
held. Data-access requests (DSAR) are tracked per tenant with a 30-day due
date and fulfilled tenant-side; no platform role ever sees the subject's data.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException, ZoikoException

SUPPORTED_REGIONS = ("EU", "UK", "US", "IN", "ME", "APAC")
PLATFORM_WIDE = "XX"
DSAR_DUE_DAYS = 30
DSAR_TYPES = ("access", "erasure", "rectification")


class RegionPolicyViolation(ZoikoException):
    def __init__(self, operation: str, tenant_region: str, here: str):
        super().__init__(403, "DATA_REGION_POLICY",
                         f"{operation} is refused: this organization's data region is {tenant_region} and "
                         f"this deployment runs in {here}.")


def home_region() -> str:
    region = (settings.DATA_REGION or "EU").upper()
    if region not in SUPPORTED_REGIONS:
        raise RuntimeError(f"DATA_REGION must be one of {SUPPORTED_REGIONS}")
    return region


def assert_region(org, operation: str, target_region: Optional[str] = None) -> None:
    """Refuse a privileged retrieval / processing / replication / backup of a
    tenant outside its data region."""
    tenant_region = (getattr(org, "data_region", None) or "EU").upper()
    here = (target_region or home_region()).upper()
    if tenant_region != here:
        raise RegionPolicyViolation(operation, tenant_region, here)


def assert_region_for_org_id(db: Session, organization_id: int, operation: str) -> None:
    from app.modules.organizations.models import Organization

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization")
    assert_region(org, operation)


# ── Legal holds (platform-wide) ─────────────────────────────────────────────

def active_holds(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    from app.modules.payroll.models import LegalHold

    q = db.query(LegalHold).filter(LegalHold.organization_id == organization_id, LegalHold.status == "ACTIVE")
    rows = q.all()
    if employee_id is None:
        return rows
    return [h for h in rows if h.employee_id in (None, employee_id)]


def assert_not_on_hold(db: Session, organization_id: int, employee_id: Optional[int] = None) -> None:
    if active_holds(db, organization_id, employee_id):
        raise ZoikoException(409, "LEGAL_HOLD",
                             "These records are under a legal hold and cannot be deleted until it is released.")


def place_hold(db: Session, actor, *, employee_id: Optional[int], reason: str, reference: Optional[str]):
    from app.modules.payroll.models import LegalHold
    from app.modules.security import events as security_events

    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("A reason is required.")
    hold = LegalHold(organization_id=actor.organization_id, jurisdiction_country=PLATFORM_WIDE,
                     employee_id=employee_id, status="ACTIVE", reason=reason, reference=reference,
                     placed_by_id=actor.id, placed_at=datetime.now(timezone.utc))
    db.add(hold)
    db.commit()
    db.refresh(hold)
    security_events.emit(db, "LEGAL_HOLD_PLACED", result="allow", actor_user_id=actor.id, actor_role="org_admin",
                         organization_id=actor.organization_id, target_type="legal_hold", target_id=f"hold:{hold.id}")
    return hold


def release_hold(db: Session, actor, hold_id: int, reason: str):
    from app.modules.payroll.models import LegalHold
    from app.modules.security import events as security_events

    hold = db.query(LegalHold).filter(LegalHold.id == hold_id).first()
    if hold is None or hold.organization_id != actor.organization_id:
        raise NotFoundException("Legal hold")
    if hold.status != "ACTIVE":
        raise BadRequestException("This hold is not active.")
    if hold.placed_by_id == actor.id:
        raise ForbiddenException("A different administrator must release a legal hold (four-eyes).")
    if not (reason or "").strip():
        raise BadRequestException("A reason is required.")
    hold.status = "RELEASED"
    hold.released_by_id = actor.id
    hold.released_at = datetime.now(timezone.utc)
    hold.release_reason = reason.strip()
    db.commit()
    security_events.emit(db, "LEGAL_HOLD_RELEASED", result="allow", actor_user_id=actor.id, actor_role="org_admin",
                         organization_id=actor.organization_id, target_type="legal_hold", target_id=f"hold:{hold.id}")
    return hold


# ── Retention ───────────────────────────────────────────────────────────────

def retention_cutoff(today: Optional[date] = None) -> date:
    today = today or datetime.now(timezone.utc).date()
    try:
        return today.replace(year=today.year - settings.WORKER_DATA_RETENTION_YEARS)
    except ValueError:  # 29 February
        return today.replace(year=today.year - settings.WORKER_DATA_RETENTION_YEARS, day=28)


def retention_candidates(db: Session, today: Optional[date] = None) -> List[dict]:
    """Workers who left before the cutoff and are not under any hold. The
    purge itself is explicit (scripts/audit_retention.py --apply)."""
    from app.core.authz.scopes import organization_scoped
    from app.core.authz.tenant_context import tenant_session
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    cutoff = retention_cutoff(today)
    out: List[dict] = []
    for (org_id,) in db.query(Organization.id).order_by(Organization.id).all():
        with tenant_session(db, org_id):  # one tenant at a time, under RLS
            rows = (organization_scoped(db, PayrollEmployee, org_id)
                    .with_entities(PayrollEmployee.id, PayrollEmployee.date_of_leaving)
                    .filter(PayrollEmployee.date_of_leaving.isnot(None),
                            PayrollEmployee.date_of_leaving < cutoff).all())
            out += [{"employeeId": i, "organizationId": org_id, "leftOn": d.isoformat()}
                    for i, d in rows if not active_holds(db, org_id, i)]
    return out


# ── Data-access requests ────────────────────────────────────────────────────

def create_request(db: Session, actor, *, request_type: str, employee_id: Optional[int]):
    from app.core.authz.principal import principal_from_user
    from app.core.authz.scopes import tenant_scoped
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.security.models import DataAccessRequest

    if request_type not in DSAR_TYPES:
        raise BadRequestException(f"Request type must be one of {DSAR_TYPES}.")
    if employee_id is not None and tenant_scoped(db, PayrollEmployee, principal_from_user(actor)).filter(
            PayrollEmployee.id == employee_id).first() is None:
        raise NotFoundException("Employee")
    now = datetime.now(timezone.utc)
    row = DataAccessRequest(organization_id=actor.organization_id, employee_id=employee_id,
                            request_type=request_type, status="received", requested_by_user_id=actor.id,
                            received_at=now, due_at=now + timedelta(days=DSAR_DUE_DAYS))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def complete_request(db: Session, actor, request_id: int, outcome: str):
    from app.modules.security.models import DataAccessRequest

    row = db.query(DataAccessRequest).filter(DataAccessRequest.id == request_id).first()
    if row is None or row.organization_id != actor.organization_id:
        raise NotFoundException("Data access request")
    if row.request_type == "erasure" and row.employee_id is not None:
        assert_not_on_hold(db, actor.organization_id, row.employee_id)
    row.status = "completed"
    row.completed_at = datetime.now(timezone.utc)
    row.outcome = (outcome or "").strip() or None
    db.commit()
    return row
