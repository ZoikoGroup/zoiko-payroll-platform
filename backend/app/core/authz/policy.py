"""
core/authz/policy.py
--------------------
The policy decision point (PDP) for ZP-PRIV-VERIFY-001: default-deny
authorization for every route, evaluated BEFORE router-level gates.

Enforcement: install_route_policies(app) walks app.routes after every
include_router call and inserts a per-route policy dependency at index 0 of
route.dependant.dependencies (FastAPI 0.111 keeps the same dependant object
the request handler uses, so the insertion is live). The PDP therefore runs
before require_active_subscription and before the endpoint's own role gate.

Decision order (fail closed, evaluate()):
  public allow -> unregistered deny -> no principal 401 -> retired deny ->
  role-not-in-route-principals deny -> role matrix deny (exports specially) ->
  tenant scope (org binding) deny -> support_temp grant-required deny ->
  employee own-record deny -> object scope (employee_id belongs to org) 404
  -> allow. Any exception inside the PDP denies with PDP_ERROR.

Every denial writes an append-only authz_decision_events row on its own
session; a failed audit write is logged and the request STAYS denied.
"""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

from fastapi import Depends, Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.core.authz.decisions import (
    ACTION_NOT_PERMITTED,
    EXPORT_DENIED,
    GRANT_REQUIRED,
    NO_PRINCIPAL,
    OBJECT_NOT_IN_SCOPE,
    PDP_ERROR,
    PUBLIC_ROUTE,
    ROLE_NOT_PERMITTED,
    ROUTE_NOT_REGISTERED,
    ROUTE_RETIRED,
    SELF_ONLY,
    TENANT_SCOPE_MISSING,
    AccessDenied,
    Decision,
)
from app.core.authz.principal import (
    ROLE_MACHINE_CLIENT,
    ALL_ROLES,
    PLATFORM_ROLES,
    ROLE_EMPLOYEE,
    ROLE_SUPPORT_TEMP,
    TENANT_ROLES,
    Principal,
    principal_from_user,
)
from app.core.dependencies import get_current_org_scoped_principal
from app.database import get_db

logger = logging.getLogger("zoiko_payroll.authz")

# ── Data classes ─────────────────────────────────────────────────────────────
DC_PUBLIC = "public"
DC_SELF = "self"
DC_PLATFORM = "platform"
DC_AGGREGATE = "aggregate"
DC_TENANT_LIFECYCLE = "tenant_lifecycle"
DC_TENANT_CONFIG = "tenant_config"
DC_WORKER = "worker"
DC_SUPPORT = "support"
DC_SECURITY = "security"
# Registry-only marker for a route with no generated entry: deny all.
DC_UNREGISTERED = "unregistered"

DATA_CLASSES = frozenset({
    DC_PUBLIC, DC_SELF, DC_PLATFORM, DC_AGGREGATE, DC_TENANT_LIFECYCLE,
    DC_TENANT_CONFIG, DC_WORKER, DC_SUPPORT, DC_SECURITY,
})

# ── Actions ──────────────────────────────────────────────────────────────────
ACT_READ = "read"
ACT_EXPORT = "export"
ACT_CREATE = "create"
ACT_UPDATE = "update"
ACT_DELETE = "delete"
ACT_APPROVE = "approve"

ALL_ACTIONS = frozenset({ACT_READ, ACT_EXPORT, ACT_CREATE, ACT_UPDATE, ACT_DELETE, ACT_APPROVE})
READ_EXPORT = frozenset({ACT_READ, ACT_EXPORT})

# Tenant-plane data classes: require an exact org binding on a tenant role.
TENANT_SCOPED_CLASSES = frozenset({DC_WORKER, DC_TENANT_CONFIG, DC_SUPPORT})

# ── Role matrix ──────────────────────────────────────────────────────────────
# role -> data class -> allowed actions. A route can still deny a role by not
# listing it in its principals; the matrix is the second, coarser layer.
MATRIX: Dict[str, Dict[str, FrozenSet[str]]] = {
    "super_admin": {
        DC_PLATFORM: ALL_ACTIONS,
        DC_AGGREGATE: READ_EXPORT,
        DC_TENANT_LIFECYCLE: ALL_ACTIONS,
        # Super Admin keeps the platform security/audit surface (SOC views);
        # security operations are shared with platform_security below.
        DC_SECURITY: ALL_ACTIONS,
        # May request JIT support access (never approve it).
        DC_SUPPORT: frozenset({ACT_READ, ACT_CREATE, ACT_UPDATE}),
        DC_SELF: ALL_ACTIONS,
    },
    "platform_security": {
        DC_SECURITY: ALL_ACTIONS,
        DC_SUPPORT: frozenset({ACT_READ, ACT_CREATE, ACT_UPDATE, ACT_APPROVE}),
        DC_SELF: ALL_ACTIONS,
    },
    "support_operator": {
        DC_SUPPORT: frozenset({ACT_READ, ACT_CREATE, ACT_UPDATE}),
        DC_SELF: ALL_ACTIONS,
    },
    "org_admin": {
        DC_TENANT_CONFIG: ALL_ACTIONS,
        DC_WORKER: ALL_ACTIONS,
        DC_AGGREGATE: READ_EXPORT,
        DC_SUPPORT: ALL_ACTIONS,
        DC_SELF: ALL_ACTIONS,
    },
    "payroll_admin": {
        DC_TENANT_CONFIG: ALL_ACTIONS,
        DC_WORKER: ALL_ACTIONS,
        DC_AGGREGATE: READ_EXPORT,
        DC_SELF: ALL_ACTIONS,
    },
    # The legacy SafeGuard "assisted_access" principal is retired (Part D):
    # it has no row here, so it is denied everywhere by the matrix too.
    # Temporary support user (JIT grant): READ ONLY - never export, write,
    # approve or delete. The live grant is re-read on every request (step 8).
    "support_temp": {
        DC_WORKER: frozenset({ACT_READ}),
        DC_TENANT_CONFIG: frozenset({ACT_READ}),
        DC_SELF: frozenset({ACT_READ, ACT_CREATE}),
    },
    # Employee self-service: own record only (decision 2: policy + test
    # persona only, no login).
    "employee": {
        DC_WORKER: READ_EXPORT,
        DC_SELF: ALL_ACTIONS,
    },
}


@dataclass(frozen=True)
class RoutePolicy:
    """One (method, path) entry of the route policy registry."""

    method: str
    path: str
    data_class: str
    action: str
    resource: str
    principals: FrozenSet[str]
    scope_level: str  # public | self | tenant | platform
    field_classes: Tuple[str, ...] = ()
    retired_reason: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "path": self.path,
            "data_class": self.data_class,
            "action": self.action,
            "resource": self.resource,
            "principals": sorted(self.principals),
            "scope_level": self.scope_level,
            "field_classes": list(self.field_classes),
            "retired_reason": self.retired_reason,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RoutePolicy":
        return cls(
            method=d["method"],
            path=d["path"],
            data_class=d["data_class"],
            action=d["action"],
            resource=d["resource"],
            principals=frozenset(d["principals"]),
            scope_level=d["scope_level"],
            field_classes=tuple(d.get("field_classes", ())),
            retired_reason=d.get("retired_reason"),
            note=d.get("note"),
        )


def unregistered_policy(method: str, path: str) -> RoutePolicy:
    """Deny-all policy for a route missing from the registry (fail closed)."""
    return RoutePolicy(
        method=method,
        path=path,
        data_class=DC_UNREGISTERED,
        action="*",
        resource="unknown",
        principals=frozenset(),
        scope_level="platform",
    )


def _deny_for_action(action: str) -> Decision:
    if action == ACT_EXPORT:
        return Decision.deny(EXPORT_DENIED)
    return Decision.deny(ACTION_NOT_PERMITTED)


def evaluate(
    principal: Optional[Principal],
    policy: RoutePolicy,
    *,
    path_params: Optional[dict] = None,
    db: Optional[Session] = None,
) -> Decision:
    """The pure decision function. Never raises; returns allow/deny."""
    try:
        return _evaluate(principal, policy, path_params=path_params, db=db)
    except Exception:  # noqa: BLE001 - a PDP crash must deny, never allow
        logger.exception("[authz] PDP error on %s %s", policy.method, policy.path)
        return Decision.deny(PDP_ERROR, detail=traceback.format_exc()[-1500:])


def _evaluate(
    principal: Optional[Principal],
    policy: RoutePolicy,
    *,
    path_params: Optional[dict],
    db: Optional[Session],
) -> Decision:
    # 1. Public routes allow anyone (no principal is built for them at all).
    if policy.data_class == DC_PUBLIC:
        return Decision.allow(PUBLIC_ROUTE)

    # 2. A route with no registry entry is denied for everyone.
    if policy.data_class == DC_UNREGISTERED:
        return Decision.deny(ROUTE_NOT_REGISTERED)

    # 3. No authenticated principal -> 401 (kept at the auth layer).
    if principal is None:
        return Decision.deny(NO_PRINCIPAL, status_code=401)

    # 4. Retired routes (de-privileged in Part B) deny everyone.
    if policy.retired_reason:
        return Decision.deny(ROUTE_RETIRED)

    # 5. Machine clients: exactly the routes their scopes map to, read-only.
    if principal.role == ROLE_MACHINE_CLIENT:
        if policy.action != ACT_READ:
            return _deny_for_action(policy.action)
        if (policy.method, policy.path) not in principal.machine_routes:
            return Decision.deny(ROLE_NOT_PERMITTED, detail="route outside the client's scopes")
        if principal.organization_id is None:
            return Decision.deny(TENANT_SCOPE_MISSING)
        return Decision.allow()

    # 5b. Route-level principal list.
    if principal.role not in policy.principals:
        if policy.action == ACT_EXPORT:
            # Every refused export is recorded as an export attempt (D.4).
            return Decision.deny(EXPORT_DENIED,
                                 detail=f"role={principal.role} principals={sorted(policy.principals)}")
        return Decision.deny(ROLE_NOT_PERMITTED,
                             detail=f"role={principal.role} principals={sorted(policy.principals)}")

    # 6. Role matrix.
    allowed_actions = MATRIX.get(principal.role, {}).get(policy.data_class)
    if not allowed_actions or policy.action not in allowed_actions:
        return _deny_for_action(policy.action)

    # 7. Tenant scope: exact org binding.
    if policy.data_class in TENANT_SCOPED_CLASSES:
        if principal.role in TENANT_ROLES and principal.organization_id is None:
            return Decision.deny(TENANT_SCOPE_MISSING, detail="tenant role without organization")
        if principal.role in PLATFORM_ROLES and principal.organization_id is not None:
            return Decision.deny(TENANT_SCOPE_MISSING, detail="platform role carrying an organization")

    # 8. Temporary support users: the live grant decides, on every request.
    if principal.role == ROLE_SUPPORT_TEMP:
        denial = _support_temp_denial(principal, policy, db)
        if denial is not None:
            return denial

    # 9. Employee self-service: own record only.
    if principal.role == ROLE_EMPLOYEE:
        emp_id = (path_params or {}).get("employee_id")
        own = principal.payroll_employee_id
        if emp_id is None or own is None or str(emp_id) != str(own):
            return Decision.deny(SELF_ONLY)

    # 10. Object scope: an employee_id path param must belong to the org.
    if (
        db is not None
        and path_params
        and "employee_id" in path_params
        and policy.data_class == DC_WORKER
        and principal.organization_id is not None
        and principal.role in TENANT_ROLES
    ):
        from app.modules.payroll.models import PayrollEmployee

        row = (
            db.query(PayrollEmployee.organization_id)
            .filter(PayrollEmployee.id == path_params["employee_id"])
            .first()
        )
        if row is None or row[0] != principal.organization_id:
            return Decision.deny(OBJECT_NOT_IN_SCOPE, status_code=404,
                                 detail="employee_id outside principal organization")
        from app.core.authz.scopes import employee_scope

        allowed_ids = employee_scope(db, principal)
        try:
            emp_id = int(path_params["employee_id"])
        except (TypeError, ValueError):
            return Decision.deny(OBJECT_NOT_IN_SCOPE, status_code=404, detail="malformed employee_id")
        if allowed_ids is not None and emp_id not in allowed_ids:
            return Decision.deny(OBJECT_NOT_IN_SCOPE, status_code=404,
                                 detail="employee_id outside principal entity/pay-group scope")

    return Decision.allow()


# Worker data a temporary support user can reach at all: the employee record
# read routes, whose rows are then limited to the grant's employees by the
# data-layer scope and to the grant's field classes by the response
# projection (support_access/projection.py). Every other worker route -
# payslips, files, reports, bulk endpoints - is out of reach (fail closed).
SUPPORT_TEMP_WORKER_ROUTES = frozenset({
    ("GET", "/api/payroll/employees"),
    ("GET", "/api/payroll/employees/{employee_id}"),
})
# The temporary user's own account surface: who am I, and sign out.
SUPPORT_TEMP_SELF_ROUTES = frozenset({
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
})


def _support_temp_denial(principal: Principal, policy: RoutePolicy, db: Optional[Session]):
    if db is None:
        return Decision.deny(GRANT_REQUIRED)
    from app.modules.support_access import models as SM
    from app.modules.support_access.service import live_grant_for_principal

    grant = live_grant_for_principal(db, principal)
    if grant is None:
        return Decision.deny(GRANT_REQUIRED, status_code=401)
    from app.modules.security import governance

    try:  # ZP-PRIV F02: privileged retrieval only inside the tenant's region
        governance.assert_region_for_org_id(db, grant.organization_id, "Support access")
    except governance.RegionPolicyViolation:
        return Decision.deny("DATA_REGION_POLICY", detail="tenant data region differs from this deployment")
    if policy.data_class == DC_SELF:
        if (policy.method, policy.path) not in SUPPORT_TEMP_SELF_ROUTES:
            return Decision.deny(ACTION_NOT_PERMITTED, detail="temporary user self route")
        return None
    if policy.data_class == DC_WORKER:
        if grant.scope_type == SM.SCOPE_DIAGNOSTICS:
            return Decision.deny(OBJECT_NOT_IN_SCOPE, detail="diagnostics grant has no worker scope")
        if (policy.method, policy.path) not in SUPPORT_TEMP_WORKER_ROUTES:
            return Decision.deny(OBJECT_NOT_IN_SCOPE, detail="worker route outside the support allowlist")
    return None


# ── Audit ────────────────────────────────────────────────────────────────────

def _record_denial(request: Request, decision: Decision, policy: RoutePolicy,
                   principal: Optional[Principal], db: Session) -> None:
    """Append-only denial row on its own session. Failure is logged; the
    request stays denied either way (the raise happens after this returns)."""
    from sqlalchemy.orm import Session as _Session

    from app.modules.auth.models import AuthzDecisionEvent

    print(f"[DEBUG] _record_denial called: path={policy.path} method={request.method} reason={decision.reason} status={decision.status_code} principal_role={getattr(principal,'role',None)}", flush=True)
    try:
        audit_db = _Session(bind=db.get_bind())
    except Exception:  # noqa: BLE001
        logger.exception("[authz] denial audit session failed")
        return
    try:
        audit_db.add(AuthzDecisionEvent(
            decision_id=decision.decision_id,
            principal_user_id=getattr(principal, "user_id", None),
            principal_role=getattr(principal, "role", None) or "anonymous",
            organization_id=getattr(principal, "organization_id", None),
            method=request.method,
            route_template=policy.path[:300],
            action=policy.action,
            resource=policy.resource,
            data_class=policy.data_class,
            reason_code=decision.reason,
            status_code=404 if decision.status_code == 404 else (
                401 if decision.status_code == 401 else 403),
            client_address=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"),
            correlation_id=getattr(request.state, "correlation_id", None),
            path_params=json.dumps(request.path_params) if request.path_params else None,
        ))
        audit_db.commit()
    except Exception:  # noqa: BLE001
        audit_db.rollback()
        logger.exception("[authz] denial audit write failed (request stays denied)")
    finally:
        audit_db.close()
    _emit_security_event(request, db, "PDP_DENY", "deny", policy, principal, decision)


def _target(request: Request, policy: RoutePolicy):
    """Opaque target for a security event: the employee id when the route
    addresses one (counted by the enumeration rule), else the route."""
    emp = (request.path_params or {}).get("employee_id")
    if emp is not None:
        return f"employee:{policy.data_class}", f"employee:{emp}"
    return f"route:{policy.data_class}", f"{request.method} {policy.path}"


def _on_behalf_of(principal: Optional[Principal], db: Session):
    """For a temporary support login: (grant id, requester id, ticket)."""
    if principal is None or principal.role != ROLE_SUPPORT_TEMP or not principal.support_grant_id:
        return None, None, None
    from app.modules.support_access.models import SupportAccessGrant

    row = (db.query(SupportAccessGrant.requested_by_user_id, SupportAccessGrant.ticket_reference)
           .filter(SupportAccessGrant.id == principal.support_grant_id).first())
    return principal.support_grant_id, (row[0] if row else None), (row[1] if row else None)


def _emit_security_event(request: Request, db: Session, event_type: str, result: str, policy: RoutePolicy,
                         principal: Optional[Principal], decision: Optional[Decision] = None) -> None:
    from app.modules.security import events

    target_type, target_id = _target(request, policy)
    try:
        grant_id, requester, ticket = _on_behalf_of(principal, db)
    except Exception:  # noqa: BLE001
        grant_id, requester, ticket = getattr(principal, "support_grant_id", None), None, None
    events.emit(db, event_type, result=result,
                actor_user_id=getattr(principal, "user_id", None),
                actor_role=getattr(principal, "role", None) or "anonymous",
                on_behalf_of_user_id=requester, organization_id=getattr(principal, "organization_id", None),
                grant_id=grant_id, ticket_reference=ticket, target_type=target_type, target_id=target_id,
                action=policy.action, reason_code=decision.reason if decision else None,
                decision_trace_id=decision.decision_id if decision else None, request=request)


def _record_support_denial(request: Request, decision: Decision, policy: RoutePolicy,
                           principal: Principal) -> None:
    """A temporary support user's denial is also written to the grant's own
    append-only audit trail (support_access_audit_events), so the tenant
    sees ACCESS_DENIED_OUT_OF_SCOPE / EXPORT_ATTEMPT_DENIED on its audit tab."""
    from app.modules.support_access.service import record_pdp_denial

    try:
        record_pdp_denial(request, decision, policy, principal)
    except Exception:  # noqa: BLE001 - request stays denied either way
        logger.exception("[authz] support denial audit write failed")


# ── FastAPI dependencies ─────────────────────────────────────────────────────

def build_data_context(principal: Principal, policy: RoutePolicy, db: Session,
                       organization_id: Optional[int] = None):
    """The data-layer scope for an ALLOWED request (tenant_context.py).

    Platform principals get a platform context: any ORM statement touching a
    worker-level table raises, except on reviewed aggregate / lifecycle
    routes. Tenant principals get their organization plus object scope.

    A platform principal reading a *specific* organisation's data (the route
    supplies an explicit ``organization_id``) runs under a tenant context
    scoped to that organisation, so worker-table reads are org-scoped and
    allowed instead of being rejected as a cross-tenant platform access
    (ZP-PRIV B02). Platform reads without an explicit organisation stay on
    the platform plane (org-level tables or k-suppressed aggregates only).
    Fails closed: an error here propagates and the request is denied."""
    from app.core.authz import scopes, tenant_context as tc

    if principal.role in PLATFORM_ROLES:
        if organization_id is not None:
            return tc.TenantContext(tc.KIND_TENANT, organization_id=organization_id)
        return tc.TenantContext(
            tc.KIND_PLATFORM,
            allow_worker_aggregate=policy.data_class in (DC_AGGREGATE, DC_TENANT_LIFECYCLE),
        )
    return tc.TenantContext(
        tc.KIND_TENANT,
        organization_id=principal.organization_id,
        employee_ids=scopes.employee_scope(db, principal),
    )


async def _enforce(request: Request, policy: RoutePolicy, principal: Optional[Principal],
                   db: Session):
    """Shared body of the route and explicit policy dependencies: decide,
    audit a denial, and on allow bind the data-layer scope to the session
    for the duration of the request (always cleared afterwards)."""
    from app.core.authz import tenant_context as tc

    request.state.authz_db = db
    named_org = _named_other_tenant(request, principal)
    if named_org:
        decision = Decision.deny(OBJECT_NOT_IN_SCOPE, status_code=404,
                                 detail=f"request names another tenant ({named_org})")
    else:
        decision = evaluate(principal, policy, path_params=request.path_params, db=db)
    if decision.allowed:
        try:
            organization_id = None
            for name in _TENANT_PARAM_NAMES:
                value = request.query_params.get(name)
                if value not in (None, ""):
                    try:
                        organization_id = int(value)
                    except (TypeError, ValueError):
                        organization_id = None
                    break
            ctx = build_data_context(principal, policy, db, organization_id=organization_id)
        except Exception:  # noqa: BLE001 - scope we cannot compute = deny
            logger.exception("[authz] data scope error on %s %s", policy.method, policy.path)
            decision = Decision.deny(PDP_ERROR, detail="data scope computation failed")
    if not decision.allowed:
        _record_denial(request, decision, policy, principal, db)
        if principal is not None and principal.role == ROLE_SUPPORT_TEMP:
            _record_support_denial(request, decision, policy, principal)
        raise AccessDenied(decision)

    if principal is not None and principal.role == ROLE_MACHINE_CLIENT:
        request.state.support_field_classes = principal.machine_field_classes
        _emit_security_event(request, db, "MACHINE_CLIENT_READ", "allow", policy, principal, decision)
    if principal is not None and principal.role == ROLE_SUPPORT_TEMP:
        _support_temp_intent(request, policy, principal, db)
        _emit_security_event(request, db, "PRIVILEGED_READ", "allow", policy, principal, decision)
    elif policy.action == ACT_EXPORT:
        _emit_security_event(request, db, "EXPORT_STARTED", "allow", policy, principal, decision)

    previous = tc.get_context(db)
    tc.set_context(db, ctx)
    request.state.authz_decision = decision
    request.state.authz_principal = principal
    request.state.authz_policy = policy
    return decision, previous


def _support_temp_intent(request: Request, policy: RoutePolicy, principal: Principal, db: Session) -> None:
    """Fail-closed intent audit for temporary support users (kept from the
    retired assisted-access design): an ALLOWED request is recorded in the
    grant's append-only trail before the endpoint runs; if the record cannot
    be written the request is refused (503) and nothing happens."""
    from sqlalchemy.orm import Session as _Session

    from app.core.exceptions import ZoikoException
    from app.modules.support_access import service as support

    request.state.support_field_classes = support.allowed_field_classes(db, principal)
    audit_db = _Session(bind=db.get_bind())
    try:
        grant = support.live_grant_for_principal(audit_db, principal)
        support.audit(audit_db, "API_CALL", grant, actor_role="support_temp",
                      organization_id=principal.organization_id, request=request,
                      detail={"method": request.method, "route": policy.path,
                              "pathParams": dict(request.path_params or {}),
                              "supportUserId": principal.user_id})
    except Exception:  # noqa: BLE001
        audit_db.rollback()
        logger.exception("[authz] support intent audit failed - request refused")
        raise ZoikoException(503, "SUPPORT_AUDIT_UNAVAILABLE",
                             "Support access is unavailable: the audit record could not be written.")
    finally:
        audit_db.close()


_TENANT_PARAM_NAMES = ("organization_id", "organizationId", "org_id", "orgId", "tenant_id", "tenantId")
_TENANT_HEADER_NAMES = ("x-organization-id", "x-tenant-id")


def _named_other_tenant(request: Request, principal: Optional[Principal]) -> Optional[str]:
    """A tenant principal (and above all a machine client) can never steer a
    request at another tenant by naming it in the query string or a header:
    the tenant always comes from the authenticated principal. Naming a
    different one is refused (and audited) rather than silently ignored."""
    if principal is None or principal.organization_id is None or principal.role in PLATFORM_ROLES:
        return None
    named = [request.query_params.get(n) for n in _TENANT_PARAM_NAMES]
    named += [request.headers.get(n) for n in _TENANT_HEADER_NAMES]
    for value in named:
        if value not in (None, "") and str(value) != str(principal.organization_id):
            return str(value)
    return None


def _route_policy_dependency(path: str, by_method: Dict[str, RoutePolicy]):
    """One closure per route: picks the policy by request method at runtime
    (one route object can serve several methods with different policies)."""

    async def route_policy(
        request: Request,
        db: Session = Depends(get_db),
        resolved=Depends(get_current_org_scoped_principal),
    ):
        from app.core.authz import tenant_context as tc

        principal = principal_from_user(resolved)
        policy = by_method.get(request.method.upper()) or unregistered_policy(
            request.method, path)
        decision, previous = await _enforce(request, policy, principal, db)
        try:
            yield decision
        finally:
            tc.set_context(db, previous)

    route_policy.__name__ = "route_policy"
    route_policy.__route_policy_path__ = path  # introspection for tests
    return route_policy


def authorize(data_class: str, action: str, principals: Optional[FrozenSet[str]] = None):
    """Explicit dependency factory for endpoints that need an in-code policy
    (Depends(authorize("worker", "read"))). All roles are route-principals
    unless given; the role matrix still applies."""
    policy = RoutePolicy(
        method="*",
        path="<explicit>",
        data_class=data_class,
        action=action,
        resource=data_class,
        principals=frozenset(principals) if principals else frozenset(ALL_ROLES),
        scope_level="tenant" if data_class in TENANT_SCOPED_CLASSES else "platform",
    )

    async def explicit_policy(
        request: Request,
        db: Session = Depends(get_db),
        resolved=Depends(get_current_org_scoped_principal),
    ):
        from app.core.authz import tenant_context as tc

        principal = principal_from_user(resolved)
        decision, previous = await _enforce(request, policy, principal, db)
        try:
            yield decision
        finally:
            tc.set_context(db, previous)

    explicit_policy.__name__ = "explicit_policy"
    return explicit_policy


# ── Registry loading + installation ──────────────────────────────────────────

REGISTRY_PATH = __file__.replace("policy.py", "route_registry.json")

# The route-level auth gates a route can carry (must match generate.AUTH_DEPS).
_AUTH_DEP_NAMES = frozenset({
    "get_current_user", "get_current_super_admin", "get_current_org_admin",
    "get_current_payroll_operator", "get_organization_id",
    "get_current_org_scoped_principal", "get_current_support_requester",
    "get_current_platform_security", "get_current_security_reader", "get_current_machine_or_user",
})


def _structural_auth_deps(route) -> set:
    """The route's own auth dependencies, ignoring the injected PDP dep."""
    found: set = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            name = getattr(sub.call, "__name__", "")
            if name in ("route_policy", "explicit_policy"):
                continue
            if name in _AUTH_DEP_NAMES:
                found.add(name)
            walk(sub)

    walk(route.dependant)
    return found


def load_registry() -> Dict[Tuple[str, str], RoutePolicy]:
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        # First run before the registry is generated: deny everything and let
        # the generator produce the file (the registry CI test fails meanwhile).
        logger.error("[authz] route_registry.json missing - all routes deny")
        return {}
    return {(e["method"], e["path"]): RoutePolicy.from_dict(e) for e in raw["entries"]}


def install_route_policies(app) -> Dict[Tuple[str, str], RoutePolicy]:
    """Insert the PDP dependency into every non-public APIRoute. Idempotent
    per app instance; safe to call from tests after adding routes."""
    from fastapi.dependencies.utils import get_parameterless_sub_dependant

    if getattr(app.state, "authz_route_policies_installed", False):
        return getattr(app.state, "authz_route_policies", {})

    registry = load_registry()
    installed: Dict[Tuple[str, str], RoutePolicy] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        by_method: Dict[str, RoutePolicy] = {}
        for method in route.methods:
            m = method.upper()
            if m in ("HEAD", "OPTIONS"):
                continue
            by_method[m] = registry.get((m, route.path_format))
        if not by_method:
            continue
        if "GET" in by_method:
            by_method.setdefault("HEAD", by_method["GET"])
        # A structurally public route (no auth dependency of its own) gets no
        # PDP dependency. This is independent of the registry, so the very
        # first generation run - before the registry exists - is correct too.
        if not _structural_auth_deps(route):
            continue
        # A route whose every registered method is public also gets none.
        if all(p is not None and p.data_class == DC_PUBLIC for p in by_method.values()):
            continue
        # Fill gaps with the deny-all policy (drift is caught by the registry
        # test; at runtime it denies rather than allows).
        for m, p in list(by_method.items()):
            if p is None:
                by_method[m] = unregistered_policy(m, route.path_format)
        sub = get_parameterless_sub_dependant(
            depends=Depends(_route_policy_dependency(route.path_format, by_method)),
            path=route.path_format,
        )
        # The policy decision must be the first route dependency. Router-level
        # subscription, jurisdiction, and role guards can otherwise hide a
        # privacy denial and skip its audit/security event.
        route.dependant.dependencies.insert(0, sub)
        installed.update({(m, route.path_format): p for m, p in by_method.items()})

    app.state.authz_route_policies = installed
    app.state.authz_route_policies_installed = True
    return installed
