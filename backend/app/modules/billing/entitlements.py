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

from app.config import settings
from app.core.exceptions import BadRequestException, ForbiddenException
from app.database import get_db
from app.core.dependencies import get_current_user, get_organization_id
from app.modules.auth.models import UserRole
from app.modules.billing.models import (
    BillingAuthority,
    BillingCommercialAuditEvent,
    BillingEntitlementFlag,
    BillingEntitlementOverride,
    BillingSubscription,
)

# Three-state rollout switch (settings.BILLING_ENFORCEMENT_MODE) replacing
# the earlier Phase 0 ALLOW_ALL boolean:
#   "off"     - require_entitlement/require_scope_limit always pass (no
#               behavior change from before these were wired into any route).
#   "warn"    - run the real check, but on a would-be block only record a
#               BillingCommercialAuditEvent and let the request proceed.
#   "enforce" - raise ForbiddenException as coded.
# Read from settings at call time (not module import time) so tests can
# override it per-case without reimporting this module.
def _enforcement_mode() -> str:
    return getattr(settings, "BILLING_ENFORCEMENT_MODE", "off")


def _record_would_have_blocked(
    db: Session, organization_id: Optional[int], resource_or_feature: str, detail: dict
) -> None:
    db.add(
        BillingCommercialAuditEvent(
            organization_id=organization_id,
            actor_user_id=None,
            event_type="ENTITLEMENT_WOULD_HAVE_BLOCKED",
            payload={"feature_key": resource_or_feature, **detail},
        )
    )
    db.commit()


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

    # Part 12 — an Enterprise Order Form org has no plan version at all,
    # by design (Enterprise is never self-service). Its
    # negotiated_scale_limits dict uses the same feature_key vocabulary
    # (billing/feature_keys.py) as BillingEntitlementFlag, so this is a
    # drop-in substitute lookup, same 0-means-off semantics, checked before
    # ever touching BillingEntitlementFlag/subscription.plan_version_id.
    if subscription.billing_authority == BillingAuthority.ENTERPRISE_ORDER_FORM.value:
        from app.modules.billing.models import EnterpriseOrderForm

        order_form = (
            db.query(EnterpriseOrderForm)
            .filter(EnterpriseOrderForm.organization_id == subscription.organization_id)
            .first()
        )
        limits = (order_form.negotiated_scale_limits or {}) if order_form else {}
        if feature_key not in limits:
            return False, None
        limit_value = limits[feature_key]
        if limit_value == 0:
            return False, 0
        return True, limit_value

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


def _current_plan_code(db: Session, subscription: Optional[BillingSubscription]) -> Optional[str]:
    """Best-effort plan code for a 403's `trace` payload (frontend upgrade
    CTA) — never raises, returns None if it can't be resolved."""
    if subscription is None:
        return None
    from app.modules.billing.models import BillingPlan, BillingPlanVersion

    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == subscription.plan_version_id).first()
    if version is None:
        return None
    plan = db.query(BillingPlan).filter(BillingPlan.id == version.plan_id).first()
    return plan.code if plan else None


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


def has_in_flight_authorized_run(db: Session, organization_id: int) -> bool:
    """Part 9's critical guard: True if this org has a PayrollRun already
    APPROVED/AUTHORIZED with a pay_date that hasn't passed yet.

    This is deliberately narrower than is_run_in_flight above (which also
    bypasses entitlement/scope checks for ANY approved run regardless of
    pay_date) — dunning restriction must specifically never block *completing*
    an already-authorized, not-yet-paid cycle, which is exactly this
    condition. require_writeable_workspace-style dunning gating below calls
    this, not is_run_in_flight, so restriction still applies to starting new
    payroll activity even if some unrelated older approved run has already
    passed its pay date.
    """
    if organization_id is None:
        return False

    from datetime import date as date_cls

    from app.modules.payroll.models import PayrollRun, PayrollStatus

    return (
        db.query(PayrollRun)
        .filter(
            PayrollRun.organization_id == organization_id,
            PayrollRun.status.in_((PayrollStatus.APPROVED.value, PayrollStatus.AUTHORIZED.value)),
            PayrollRun.pay_date >= date_cls.today(),
        )
        .first()
        is not None
    )


_DUNNING_STAGE_ORDER = ["RETRY", "RESTRICT_EXPANSION", "RESTRICT_NEW_RUN", "READ_ONLY"]


def require_not_dunning_restricted(blocking_from_stage: str):
    """FastAPI dependency factory — Part 9. Blocks NEW payroll/growth
    activity once an org's BillingDunningState reaches `blocking_from_stage`
    or later in the RETRY -> RESTRICT_EXPANSION -> RESTRICT_NEW_RUN ->
    READ_ONLY sequence (billing/dunning.py owns advancing that state).

    Deliberately never gates the run-approve/advance endpoint — that
    endpoint is shared with completing an already-authorized run, and the
    Operating Standard's own requirement is explicit: dunning must never
    block an already-authorized in-flight cycle. Blocking only *creation*
    (new payroll runs, new legal entities, new jurisdictions), never
    *advancement*, is how that guarantee holds without needing to
    distinguish intent inside a shared polymorphic endpoint. Call with
    DunningStage.RESTRICT_EXPANSION for growth actions, RESTRICT_NEW_RUN
    for payroll run creation specifically (one stage later/more severe).
    """
    threshold_index = _DUNNING_STAGE_ORDER.index(blocking_from_stage)

    def _check(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        if current_user.role == UserRole.SUPER_ADMIN:
            return True

        organization_id = current_user.organization_id
        from app.modules.billing.models import BillingDunningState

        state = db.query(BillingDunningState).filter(BillingDunningState.organization_id == organization_id).first()
        if state is None:
            return True

        current_index = _DUNNING_STAGE_ORDER.index(state.stage) if state.stage in _DUNNING_STAGE_ORDER else 0
        if current_index >= threshold_index:
            raise ForbiddenException(
                "Your account has an overdue payment and this action is currently "
                "restricted. Existing authorized payroll runs are not affected. "
                "Please update your billing details to resume.",
                trace={"dunning_stage": state.stage},
            )
        return True

    return _check


_VALID_COMMERCIAL_ROUTES = (
    BillingAuthority.STANDALONE.value,
    BillingAuthority.ZOIKO_ONE_BUNDLE.value,
    BillingAuthority.ENTERPRISE_ORDER_FORM.value,
)


def resolve_commercial_route(db: Session, organization, route: str) -> None:
    """Commercial Billing & Subscription Operating Standard §12 — the ONE
    place Organization.commercial_route and BillingSubscription.
    billing_authority are ever set, together, so they can never disagree.
    Every entry point that establishes or changes an org's commercial
    route calls this instead of setting either field itself:

      - billing/router.py's create_checkout_session — route=STANDALONE
      - billing/enterprise_order_form.py's record_order_form —
        route=ENTERPRISE_ORDER_FORM
      - apply_zoiko_one_bundle_route() below — route=ZOIKO_ONE_BUNDLE,
        stubbed now with no caller yet, so that decision doesn't get
        invented ad hoc when Zoiko One integration actually lands

    Does NOT commit — callers are already inside their own transaction
    (checkout's auto-promotion, record_order_form's audit-first write) and
    decide when to commit alongside their own other changes.
    """
    if route not in _VALID_COMMERCIAL_ROUTES:
        raise ValueError(f"Unrecognized commercial_route: {route!r}")

    organization.commercial_route = route
    db.add(organization)

    sub = get_active_subscription(db, organization.id)
    if sub is not None:
        sub.billing_authority = route
        db.add(sub)


def apply_zoiko_one_bundle_route(db: Session, organization) -> None:
    """Stub — no caller exists yet. Reserved for the future Zoiko One
    bundle entry point (an org whose billing rides on a Zoiko One-level
    commercial relationship rather than its own Stripe subscription or an
    Enterprise Order Form). Exists now purely so that entry point calls
    resolve_commercial_route() the same way STANDALONE/ENTERPRISE_ORDER_FORM
    already do, instead of a future implementer inventing a fourth way to
    set these two fields."""
    resolve_commercial_route(db, organization, BillingAuthority.ZOIKO_ONE_BUNDLE.value)


def assert_no_overlapping_billable_ownership(db: Session, organization_id: int, incoming_route: str) -> None:
    """Commercial Billing & Subscription Operating Standard §12's core
    rule: an org may never have overlapping billable ownership — a
    BillingSubscription under one commercial route while something else
    (an EnterpriseOrderForm, or a different route's subscription) also
    claims to govern its billing. Application-level guard rather than a DB
    constraint: BillingSubscription.organization_id and
    EnterpriseOrderForm.organization_id are each already unique
    individually (preventing duplicates within their own table), but
    nothing at the schema level can express "these two tables must never
    both have a row for the same org" across tables without a trigger —
    checked here instead, at the two points that ever create either row
    (create_checkout_session, record_order_form).
    """
    from app.modules.billing.models import EnterpriseOrderForm

    existing_sub = get_active_subscription(db, organization_id)
    existing_order_form = db.query(EnterpriseOrderForm).filter(EnterpriseOrderForm.organization_id == organization_id).first()

    if incoming_route == BillingAuthority.ENTERPRISE_ORDER_FORM.value:
        if existing_sub is not None and existing_sub.billing_authority != BillingAuthority.ENTERPRISE_ORDER_FORM.value:
            raise ForbiddenException(
                f"This organization already has a {existing_sub.billing_authority} billing relationship. "
                "Recording an Enterprise Order Form for it would silently overlap two commercial routes — "
                "migrate it explicitly first."
            )
    else:
        if existing_order_form is not None:
            raise ForbiddenException(
                "This organization already has an Enterprise Order Form on file. "
                "Self-service checkout would silently overlap two commercial routes — "
                "this org must be managed through its Order Form, not self-service checkout."
            )


def is_billable(organization) -> bool:
    """Commercial Billing & Subscription Operating Standard §A1 — the one
    gate every invoice/charge/recurring-billing-event code path must check
    before doing anything, and refuse (fail closed) if it returns False.

    Deliberately takes the Organization object directly, not an
    organization_id + db lookup, since every call site (webhook handlers,
    invoice writers, the dunning sweep) already has the row in hand — this
    stays a pure, DB-free predicate so it's trivial to unit test.
    """
    if organization is None:
        return False
    return (
        getattr(organization, "billing_classification", None) == "COMMERCIAL_ACTIVE"
        and bool(getattr(organization, "charge_enabled", False))
    )


def is_service_commenced(organization) -> bool:
    """Part 2 — a subscription is only real-billable once
    service_commencement_at is set AND in the past. Existing (workspace
    created, checkout completed, admin account exists) is never sufficient
    on its own — see Organization.service_commencement_at's own docstring."""
    commenced_at = getattr(organization, "service_commencement_at", None)
    if commenced_at is None:
        return False
    return commenced_at <= datetime.utcnow()


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
    """Blocks access for PRODUCTION-workspace orgs with no real commercial
    relationship at all. EVALUATION-workspace orgs are exempt — their
    access comes from the trial subscription (SubscriptionStatus.TRIALING),
    not this gate. Ignores ALLOW_ALL for the same reason
    require_production_workspace does: this is about whether a commercial
    relationship exists at all, not about which plan-tier features are
    enabled.

    PAST_DUE is deliberately NOT blocked here (Commercial Billing &
    Subscription Operating Standard Part 9): a payment failure must run the
    graduated dunning sequence (billing/dunning.py — RETRY is fully
    permissive, matching Stripe's own smart-retry window) and must never
    terminate an already-authorized in-flight pay cycle immediately on the
    first failed charge. This router-level gate blocking PAST_DUE
    unconditionally would make the entire dunning system moot — the
    specific, narrower require_not_dunning_restricted() gates (wired into
    new-run/new-entity/new-jurisdiction creation only) are what actually
    enforce dunning restriction, scaled to how overdue the account is.
    Only a subscription with no real path back (SUSPENDED, CANCELLED, or
    simply missing) blocks here.
    """
    from app.modules.organizations.models import Organization
    from app.modules.billing.models import SubscriptionStatus

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        return

    if org.workspace_type == "EVALUATION":
        return

    subscription = get_active_subscription(db, organization_id)
    if subscription is None:
        raise ForbiddenException("An active commercial relationship is required for production workspaces.")

    if subscription.status in (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PAST_DUE.value):
        return

    raise ForbiddenException("An active commercial relationship is required for production workspaces.")


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
    _notify_entitlement_override_granted(db, override, organization_id)
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
    """FastAPI dependency factory — gates a route behind one feature_key.

    Can also be called directly as a plain function (bypassing FastAPI's
    Depends() injection) by passing current_user/db explicitly — useful from
    inside a route handler that needs to gate conditionally rather than for
    every request to that route (see organizations/router.py's currency-
    override check).
    """

    def _check(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        mode = _enforcement_mode()
        if mode == "off":
            return True

        if current_user.role == UserRole.SUPER_ADMIN:
            return True

        organization_id = current_user.organization_id
        if is_run_in_flight(db, organization_id):
            return True

        subscription = get_active_subscription(db, organization_id)
        if not entitlement_allows(db, subscription, feature_key):
            if mode == "warn":
                _record_would_have_blocked(
                    db, organization_id, feature_key, {"reason": "not_entitled"}
                )
                return True
            raise ForbiddenException(
                f"Your plan does not include access to '{feature_key}'. "
                f"Upgrade your plan to unlock this.",
                trace={"feature_key": feature_key, "plan_code": _current_plan_code(db, subscription)},
            )
        return True

    return _check


def require_scope_limit(resource: str, requested_qty: int = 1):
    """FastAPI dependency factory — gates a route behind a numeric scope
    limit (e.g. max_entities) for `resource`, checking that `requested_qty`
    fits within whatever limit_value the subscription's plan version/override
    resolves to. A limit_value of None means unlimited once the resource is
    entitled at all.

    `requested_qty` is normally data-dependent per request (e.g. "current
    count of legal entities + 1"), not a fixed value known when the route is
    defined — so call sites typically don't wire this via FastAPI's
    Depends() at all; they call `require_scope_limit(resource, qty)
    (current_user=current_user, db=db)` directly inside the handler body
    once `qty` has been computed, same pattern used for require_entitlement
    above.
    """

    def _check(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        mode = _enforcement_mode()
        if mode == "off":
            return True

        if current_user.role == UserRole.SUPER_ADMIN:
            return True

        organization_id = current_user.organization_id
        if is_run_in_flight(db, organization_id):
            return True

        subscription = get_active_subscription(db, organization_id)
        allowed, limit_value = _resolve_entitlement(db, subscription, resource)

        if not allowed:
            if mode == "warn":
                _record_would_have_blocked(
                    db, organization_id, resource, {"reason": "not_entitled", "requested_qty": requested_qty}
                )
                return True
            raise ForbiddenException(
                f"Your plan does not include '{resource}'.",
                trace={"resource": resource, "plan_code": _current_plan_code(db, subscription)},
            )

        if limit_value is not None and requested_qty > limit_value:
            if mode == "warn":
                _record_would_have_blocked(
                    db,
                    organization_id,
                    resource,
                    {"reason": "over_limit", "requested_qty": requested_qty, "limit_value": limit_value},
                )
                return True
            raise ForbiddenException(
                f"This action would exceed your plan's limit for '{resource}' ({limit_value}). "
                f"Upgrade your plan to raise this limit.",
                trace={
                    "resource": resource,
                    "limit_value": limit_value,
                    "requested_qty": requested_qty,
                    "plan_code": _current_plan_code(db, subscription),
                },
            )
        return True

    return _check


def _notify_entitlement_override_granted(db: Session, override, organization_id: int) -> None:
    import logging
    logger = logging.getLogger("zoiko")
    try:
        from app.services.email_service import _get_org_contact_email, send_entitlement_override_granted_email
        org_email = _get_org_contact_email(db, organization_id)
        if not org_email:
            return
        from app.modules.communications.service import idempotency_key, queue_email
        queue_email(
            "billing", "billing.entitlement_override_granted", None, org_email,
            idempotency_key(
                organization_id, "billing.entitlement_override_granted", org_email, None, f"override:{override.id}",
            ),
            send_entitlement_override_granted_email, org_email,
            send_kwargs=dict(
                feature_key=override.feature_key,
                limit_value=override.limit_value,
                reason=override.reason or "",
                expires_at=override.expires_at,
                organization_id=organization_id,
            ),
            organization_id=organization_id, actor_user_id=getattr(override, "granted_by_user_id", None), db=db,
        )
    except Exception as exc:
        logger.warning(f"[billing] entitlement-override email failed for org {organization_id}: {exc}")
