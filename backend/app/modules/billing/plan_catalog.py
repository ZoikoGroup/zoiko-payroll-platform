"""
modules/billing/plan_catalog.py
--------------------------------
Read-mostly service functions over the plan catalog (billing_plans /
billing_plan_versions / billing_entitlement_flags) — blueprint §2/§3's
"what does a plan version grant" side, as opposed to entitlements.py's
"does this org's subscription grant it right now" enforcement side.

This module does not import from or modify payroll, organizations, auth, or
super_admin models — it only references their primary keys via ForeignKey
(inherited from models.py; this module itself has no such references).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import AlreadyExistsException, BadRequestException, NotFoundException
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    BillingEntitlementFlag,
    BillingPlan,
    BillingPlanVersion,
    PlanVersionStatus,
)


def get_published_plan_version(db: Session, plan_code: str) -> Optional[BillingPlanVersion]:
    """Latest PUBLISHED version for a plan code (e.g. "PROFESSIONAL").

    "Latest" is by version number, not published_at — a higher version
    number is always the intended successor of a lower one for the same
    plan_id, per the version's own immutable-once-PUBLISHED contract.
    """
    code = plan_code.value if hasattr(plan_code, "value") else plan_code
    return (
        db.query(BillingPlanVersion)
        .join(BillingPlan, BillingPlanVersion.plan_id == BillingPlan.id)
        .filter(
            BillingPlan.code == code,
            BillingPlanVersion.status == PlanVersionStatus.PUBLISHED.value,
        )
        .order_by(BillingPlanVersion.version.desc())
        .first()
    )


def list_entitlement_flags(db: Session, plan_version_id: int) -> dict:
    """dict[feature_key, limit_value] for one plan version. limit_value is
    None for a boolean/unlimited flag (see BillingEntitlementFlag docstring)."""
    rows = (
        db.query(BillingEntitlementFlag)
        .filter(BillingEntitlementFlag.plan_version_id == plan_version_id)
        .all()
    )
    return {row.feature_key: row.limit_value for row in rows}


def publish_plan_version(
    db: Session, plan_version_id: int, published_by_user_id: int
) -> BillingPlanVersion:
    """Transition APPROVED -> PUBLISHED. One-way: there is no "unpublish" or
    edit-after-publish path anywhere in this module — a PUBLISHED version is
    immutable at the application layer for the rest of its life (see
    BillingPlanVersion's own docstring in models.py). Raises BadRequestException
    if the version is not currently APPROVED.
    """
    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == plan_version_id).first()
    if version is None:
        raise NotFoundException("Plan version", plan_version_id)

    if version.status != PlanVersionStatus.APPROVED.value:
        raise BadRequestException(
            f"Plan version {plan_version_id} must be APPROVED before it can be "
            f"published (current status: {version.status})."
        )

    version.status = PlanVersionStatus.PUBLISHED.value
    version.published_at = datetime.utcnow()
    db.add(version)

    db.add(
        BillingCommercialAuditEvent(
            organization_id=None,  # plan versions are platform-level, not org-scoped
            actor_user_id=published_by_user_id,
            event_type="PLAN_VERSION_PUBLISHED",
            payload={
                "plan_version_id": version.id,
                "plan_id": version.plan_id,
                "version": version.version,
            },
        )
    )

    db.commit()
    db.refresh(version)
    return version


# ── Super Admin CRUD (Prompt 3 — billing/admin_router.py) ────────────────
# Every write below records its own billing_commercial_audit_events row
# before committing, same audit-first discipline publish_plan_version above
# already follows, and the same modules/assist audit convention this task
# was asked to mirror.

def create_plan(db: Session, code: str, name: str, actor_user_id: int) -> BillingPlan:
    code_value = code.value if hasattr(code, "value") else code
    if db.query(BillingPlan).filter(BillingPlan.code == code_value).first() is not None:
        raise AlreadyExistsException("Billing plan", "code")

    plan = BillingPlan(code=code_value, name=name)
    db.add(plan)
    db.flush()

    db.add(
        BillingCommercialAuditEvent(
            organization_id=None,
            actor_user_id=actor_user_id,
            event_type="PLAN_CREATED",
            payload={"plan_id": plan.id, "code": code_value, "name": name},
        )
    )
    db.commit()
    db.refresh(plan)
    return plan


def create_plan_version(
    db: Session,
    plan_id: int,
    feature_set: Optional[dict],
    scale_limits: Optional[dict],
    actor_user_id: int,
) -> BillingPlanVersion:
    """Create a new DRAFT version for `plan_id`. The version number is
    always server-assigned (latest existing + 1, or 1 for the first
    version) — see BillingPlanVersionCreateRequest's own docstring for why
    the client never supplies it."""
    plan = db.query(BillingPlan).filter(BillingPlan.id == plan_id).first()
    if plan is None:
        raise NotFoundException("Billing plan", plan_id)

    latest = (
        db.query(BillingPlanVersion)
        .filter(BillingPlanVersion.plan_id == plan_id)
        .order_by(BillingPlanVersion.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1

    version = BillingPlanVersion(
        plan_id=plan_id,
        version=next_version,
        status=PlanVersionStatus.DRAFT.value,
        feature_set=feature_set,
        scale_limits=scale_limits,
    )
    db.add(version)
    db.flush()

    db.add(
        BillingCommercialAuditEvent(
            organization_id=None,
            actor_user_id=actor_user_id,
            event_type="PLAN_VERSION_CREATED",
            payload={"plan_version_id": version.id, "plan_id": plan_id, "version": next_version},
        )
    )
    db.commit()
    db.refresh(version)
    return version


def approve_plan_version(db: Session, plan_version_id: int, actor_user_id: int) -> BillingPlanVersion:
    """Transition DRAFT -> APPROVED. The other half of the lifecycle
    publish_plan_version doesn't cover — APPROVED is still editable at the
    application layer (only PUBLISHED is immutable), but no edit path is
    implemented anywhere in this task, so this function only flips status."""
    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == plan_version_id).first()
    if version is None:
        raise NotFoundException("Plan version", plan_version_id)

    if version.status != PlanVersionStatus.DRAFT.value:
        raise BadRequestException(
            f"Plan version {plan_version_id} must be DRAFT before it can be "
            f"approved (current status: {version.status})."
        )

    version.status = PlanVersionStatus.APPROVED.value
    db.add(version)

    db.add(
        BillingCommercialAuditEvent(
            organization_id=None,
            actor_user_id=actor_user_id,
            event_type="PLAN_VERSION_APPROVED",
            payload={
                "plan_version_id": version.id,
                "plan_id": version.plan_id,
                "version": version.version,
            },
        )
    )
    db.commit()
    db.refresh(version)
    return version


def add_entitlement_flag(
    db: Session,
    plan_version_id: int,
    feature_key: str,
    limit_value: Optional[int],
    actor_user_id: int,
) -> BillingEntitlementFlag:
    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == plan_version_id).first()
    if version is None:
        raise NotFoundException("Plan version", plan_version_id)

    if version.status == PlanVersionStatus.PUBLISHED.value:
        raise BadRequestException(
            "This plan version is PUBLISHED and immutable — create a new "
            "version instead of adding flags to it."
        )

    exists = (
        db.query(BillingEntitlementFlag)
        .filter(
            BillingEntitlementFlag.plan_version_id == plan_version_id,
            BillingEntitlementFlag.feature_key == feature_key,
        )
        .first()
    )
    if exists is not None:
        raise AlreadyExistsException("Entitlement flag", "feature_key")

    flag = BillingEntitlementFlag(
        plan_version_id=plan_version_id, feature_key=feature_key, limit_value=limit_value
    )
    db.add(flag)
    db.flush()

    db.add(
        BillingCommercialAuditEvent(
            organization_id=None,
            actor_user_id=actor_user_id,
            event_type="ENTITLEMENT_FLAG_ADDED",
            payload={
                "plan_version_id": plan_version_id,
                "feature_key": feature_key,
                "limit_value": limit_value,
            },
        )
    )
    db.commit()
    db.refresh(flag)
    return flag
