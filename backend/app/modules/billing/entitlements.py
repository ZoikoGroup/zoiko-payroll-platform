"""
modules/billing/entitlements.py
---------------------------------
The enforcement chokepoint from blueprint §3: every other module that wants
to gate a feature behind a plan calls require_entitlement()/require_scope_limit()
as a FastAPI dependency — none of them query billing_* tables directly.

Phase 0 permissive mode (see ALLOW_ALL below) means neither dependency
actually blocks anything yet. Wiring these dependencies into other modules'
routers is explicitly out of scope for this task (comes in a later prompt) —
this module only defines them.

This module reads (never writes or imports business logic from) other
modules for read-only lookups the blueprint's own §3 sketch requires:
  - app.modules.auth.models.UserRole       — to bypass entitlement checks
                                              for Super Admin
  - app.modules.payroll.models.PayrollRun  — to check whether an approved
                                              run is in flight (P4 guard)
  - app.modules.organizations.models.Organization — to check workspace_type
    for EVALUATION-vs-PRODUCTION execution safety (require_production_workspace)
Neither import writes to those modules, and nothing outside
app/modules/billing/ imports from this module yet.
"""

from datetime import datetime
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, ForbiddenException
from app.database import get_db
from app.core.dependencies import get_current_user, get_organization_id
from app.modules.auth.models import UserRole
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    BillingEntitlementFlag,
    BillingEntitlementOverride,
    BillingSubscription,
)

# Phase 0 permissive mode — no plan data exists yet; flip to False once
# Prompt 3's admin CRUD has been used to publish at least one real plan
# version, per blueprint Phase 0.
ALLOW_ALL = False


def get_active_subscription(db: Session, organization_id: int) -> Optional[BillingSubscription]:
    """The org's one commercial relationship row, or None.

    v1 assumption (per BillingSubscription's own unique organization_id
    constraint in models.py): at most one subscription ever exists per org,
    so there is no separate "most recent"/"active-status" filter to apply —
    whatever row exists for this org is the one to check.
    """
    if organization_id is None:
        return None
    return (
        db.query(BillingSubscription)
        .filter(BillingSubscription.organization_id == organization_id)
        .first()
    )


def _resolve_entitlement(
    db: Session, subscription: Optional[BillingSubscription], feature_key: str
) -> tuple[bool, Optional[int]]:
    """(allowed, limit_value) for one feature_key against one subscription.

    limit_value is None for a boolean/unlimited grant, an int for a
    numeric cap (e.g. max_entities). A live (non-expired)
    billing_entitlement_overrides row always wins over the plan version's
    own billing_entitlement_flags row — it's an explicit, time-boxed grant
    that may unlock a feature the base plan doesn't have, or raise a limit
    the base plan does. A base flag with limit_value == 0 is treated as
    "explicitly disabled", not "allowed with a zero cap".
    """
    if subscription is None:
        return False, None

    override = (
        db.query(BillingEntitlementOverride)
        .filter(
            BillingEntitlementOverride.organization_id == subscription.organization_id,
            BillingEntitlementOverride.feature_key == feature_key,
            BillingEntitlementOverride.expires_at > datetime.utcnow(),
        )
        .order_by(BillingEntitlementOverride.created_at.desc())
        .first()
    )
    if override is not None:
        return True, override.limit_value

    flag = (
        db.query(BillingEntitlementFlag)
        .filter(
            BillingEntitlementFlag.plan_version_id == subscription.plan_version_id,
            BillingEntitlementFlag.feature_key == feature_key,
        )
        .first()
    )
    if flag is None:
        return False, None
    if flag.limit_value == 0:
        return False, 0
    return True, flag.limit_value


def entitlement_allows(db: Session, subscription: Optional[BillingSubscription], feature_key: str) -> bool:
    """True if `subscription`'s plan version (or a live org override) grants
    `feature_key` at all. Does not check any numeric quantity — see
    require_scope_limit for that."""
    allowed, _ = _resolve_entitlement(db, subscription, feature_key)
    return allowed


def is_run_in_flight(db: Session, organization_id: int) -> bool:
    """True if this org has a payroll run that has been approved but not
    yet paid/closed. P4 guard: neither dependency below may abort or
    restrict access while a run is in this window, regardless of
    entitlement/dunning state — interrupting an approved run mid-flight is
    worse than temporarily over-serving a feature.
    """
    if organization_id is None:
        return False

    from app.modules.payroll.models import PayrollRun, PayrollStatus

    in_flight_statuses = (PayrollStatus.APPROVED.value, PayrollStatus.AUTHORIZED.value)
    return (
        db.query(PayrollRun)
        .filter(
            PayrollRun.organization_id == organization_id,
            PayrollRun.status.in_(in_flight_statuses),
        )
        .first()
        is not None
    )


def require_production_workspace(db: Session, organization_id: int) -> None:
    """Block execution-safety-sensitive operations (ELSTER transmission,
    future live bank disbursements) for EVALUATION workspaces.

    Unlike require_entitlement/require_scope_limit, this guard does NOT
    check ALLOW_ALL — it blocks regardless of that flag's state because
    ALLOW_ALL is about plan *features*, not about production-vs-simulation
    execution safety. Also unlike those guards, this is a plain function
    (not a FastAPI dependency factory) because it is called from service
    layer code, not from route handlers."""
    from app.modules.organizations.models import Organization

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is not None and org.workspace_type == "EVALUATION":
        raise ForbiddenException(
            "This action requires a production workspace. "
            "Evaluation workspaces are preview/simulation only."
        )


def require_active_subscription(
    organization_id: int = Depends(get_organization_id),
    db: Session = Depends(get_db)
) -> None:
    """Blocks access for PRODUCTION-workspace orgs with no ACTIVE subscription.
    EVALUATION-workspace orgs are exempt — their access comes from the trial
    subscription (SubscriptionStatus.TRIALING), not this gate. Ignores
    ALLOW_ALL for the same reason require_production_workspace does: this is
    about whether a commercial relationship exists at all, not about which
    plan-tier features are enabled."""
    from app.modules.organizations.models import Organization
    from app.modules.billing.models import SubscriptionStatus

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        return

    if org.workspace_type == "EVALUATION":
        return

    subscription = get_active_subscription(db, organization_id)
    if subscription is None or subscription.status != SubscriptionStatus.ACTIVE.value:
        raise ForbiddenException("An ACTIVE subscription is required for production workspaces.")


def list_entitlement_overrides(db: Session, organization_id: int) -> list:
    """Every override ever granted to this org (live or expired) — the
    super admin list view needs to see history, not just what's currently
    live; require_entitlement/require_scope_limit above are the ones that
    filter to non-expired via _resolve_entitlement."""
    return (
        db.query(BillingEntitlementOverride)
        .filter(BillingEntitlementOverride.organization_id == organization_id)
        .order_by(BillingEntitlementOverride.expires_at.desc())
        .all()
    )


def create_entitlement_override(
    db: Session,
    organization_id: int,
    feature_key: str,
    limit_value: Optional[int],
    granted_by_user_id: int,
    reason: str,
    expires_at: datetime,
) -> BillingEntitlementOverride:
    """Grant a temporary, time-boxed override. expires_at must be in the
    future — a request for a not-yet-expired grant that would be born
    already expired is rejected outright rather than silently accepted as
    a no-op."""
    if expires_at <= datetime.utcnow():
        raise BadRequestException("expires_at must be in the future.")

    override = BillingEntitlementOverride(
        organization_id=organization_id,
        feature_key=feature_key,
        limit_value=limit_value,
        granted_by_user_id=granted_by_user_id,
        reason=reason,
        expires_at=expires_at,
    )
    db.add(override)
    db.flush()

    db.add(
        BillingCommercialAuditEvent(
            organization_id=organization_id,
            actor_user_id=granted_by_user_id,
            event_type="ENTITLEMENT_OVERRIDE_GRANTED",
            payload={
                "override_id": override.id,
                "feature_key": feature_key,
                "limit_value": limit_value,
                "expires_at": expires_at.isoformat(),
            },
        )
    )
    db.commit()
    db.refresh(override)
    return override


def require_writeable_workspace():
    """FastAPI dependency — write-endpoint guard for the trial lifecycle.

    Blocks mutations for trial orgs whose derived stage is GRACE_READONLY
    or CLOSED (see trial_lifecycle.resolve_trial_stage). GET endpoints do
    NOT carry this dependency, so reads stay untouched during the grace
    window. EVALUATION orgs still inside their active trial pass through —
    only expired/closed trials return 403. Mirrors require_entitlement's
    signature (dependency factory returning bool) so it can be dropped into
    an existing `dependencies=[...]` list without changing route behavior.
    """
    from app.modules.billing.trial_lifecycle import (
        TRIAL_STAGE_CLOSED,
        TRIAL_STAGE_GRACE_READONLY,
        resolve_trial_stage,
    )

    def _check(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        if current_user.role == UserRole.SUPER_ADMIN:
            return True

        organization_id = current_user.organization_id
        if is_run_in_flight(db, organization_id):
            return True

        subscription = get_active_subscription(db, organization_id)
        stage = resolve_trial_stage(subscription)
        if stage in (TRIAL_STAGE_GRACE_READONLY, TRIAL_STAGE_CLOSED):
            raise ForbiddenException(
                "This workspace is read-only: your evaluation period has ended. "
                "Choose a plan to resume full access."
            )
        return True

    return _check


def require_entitlement(feature_key: str):
    """FastAPI dependency factory — gates a route behind one feature_key."""

    def _check(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        if ALLOW_ALL:
            return True

        if current_user.role == UserRole.SUPER_ADMIN:
            return True

        organization_id = current_user.organization_id
        if is_run_in_flight(db, organization_id):
            return True

        subscription = get_active_subscription(db, organization_id)
        if not entitlement_allows(db, subscription, feature_key):
            raise ForbiddenException(
                f"Your plan does not include access to '{feature_key}'."
            )
        return True

    return _check


def require_scope_limit(resource: str, requested_qty: int = 1):
    """FastAPI dependency factory — gates a route behind a numeric scope
    limit (e.g. max_entities) for `resource`, checking that `requested_qty`
    fits within whatever limit_value the subscription's plan version/override
    resolves to. A limit_value of None means unlimited once the resource is
    entitled at all.
    """

    def _check(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        if ALLOW_ALL:
            return True

        if current_user.role == UserRole.SUPER_ADMIN:
            return True

        organization_id = current_user.organization_id
        if is_run_in_flight(db, organization_id):
            return True

        subscription = get_active_subscription(db, organization_id)
        allowed, limit_value = _resolve_entitlement(db, subscription, resource)
        if not allowed:
            raise ForbiddenException(f"Your plan does not include '{resource}'.")
        if limit_value is not None and requested_qty > limit_value:
            raise ForbiddenException(
                f"This action would exceed your plan's limit for '{resource}' ({limit_value})."
            )
        return True

    return _check
