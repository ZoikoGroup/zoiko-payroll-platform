"""
core/authz/scopes.py
--------------------
Object scope inside a tenant (ZP-PRIV B02 / C.2): which PayrollEmployee
rows a tenant principal may touch. The answer feeds the data-layer context
(tenant_context.py), so it applies to get, list, search, count, export, bulk
and payslip queries alike — handlers cannot forget it.

  org_admin                 organization-wide (always)
  payroll_admin             organization-wide, unless the user has scope
                            assignments (user_scope_assignments): then only
                            workers whose legal entity or pay group is
                            assigned. An unassigned worker is invisible to a
                            scoped user (fail closed).
  employee                  their own record only (decision 2: policy +
                            test persona; self-service login stays off)
  support_temp              exactly the grant's resolved scope, re-read from
                            the live grant on every request (Part D)

``None`` means "every worker in the organization"; a frozenset restricts the
request to those ids (an empty set therefore sees nothing).
"""

from __future__ import annotations

from typing import FrozenSet, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.core.authz.principal import (
    ROLE_EMPLOYEE,
    ROLE_PAYROLL_ADMIN,
    ROLE_SUPPORT_TEMP,
    Principal,
)


class ScopeError(RuntimeError):
    """Raised when a worker query is attempted without tenant context."""


def require_tenant_org(principal: Optional[Principal]) -> int:
    """The one place that turns a principal into the org id a query MUST be
    filtered by."""
    org = getattr(principal, "organization_id", None)
    if org is None:
        raise ScopeError("tenant-scoped query attempted without an organization")
    return org


def tenant_scoped(db: Session, model, principal: Principal) -> Query:
    """A Query for ``model`` filtered to the principal's organization."""
    org = require_tenant_org(principal)
    return db.query(model).filter(model.organization_id == org)


def organization_scoped(db: Session, model, organization_id: int) -> Query:
    """System work for exactly one tenant (retention, sweeps): a Query for
    ``model`` filtered to that organization. Call it inside
    ``tenant_context.tenant_session(db, organization_id)`` so RLS and the
    session guard apply too."""
    if not organization_id:
        raise ValueError("organization_scoped needs an organization id")
    return db.query(model).filter(model.organization_id == organization_id)


def assigned_scope(db: Session, user_id: int, organization_id: int):
    """(legal_entity_ids, pay_group_ids) assigned to a user in their org.
    Both empty means the user is not scoped."""
    from app.modules.organizations.models import UserScopeAssignment

    rows = (
        db.query(UserScopeAssignment.legal_entity_id, UserScopeAssignment.pay_group_id)
        .filter(UserScopeAssignment.user_id == user_id,
                UserScopeAssignment.organization_id == organization_id)
        .all()
    )
    entities = frozenset(e for e, _ in rows if e is not None)
    groups = frozenset(g for _, g in rows if g is not None)
    return entities, groups


def employees_in_units(db: Session, organization_id: int, entities, groups) -> FrozenSet[int]:
    from app.modules.payroll.models import PayrollEmployee

    clauses = []
    if entities:
        clauses.append(PayrollEmployee.legal_entity_id.in_(sorted(entities)))
    if groups:
        clauses.append(PayrollEmployee.pay_group_id.in_(sorted(groups)))
    if not clauses:
        return frozenset()
    rows = (
        db.query(PayrollEmployee.id)
        .filter(PayrollEmployee.organization_id == organization_id, or_(*clauses))
        .all()
    )
    return frozenset(r[0] for r in rows)


def employee_scope(db: Session, principal: Principal) -> Optional[FrozenSet[int]]:
    """The worker ids this tenant principal may touch (None = whole org)."""
    org = require_tenant_org(principal)
    if principal.role == ROLE_EMPLOYEE:
        own = principal.payroll_employee_id
        return frozenset({own}) if own is not None else frozenset()
    if principal.role == ROLE_SUPPORT_TEMP:
        from app.modules.support_access.service import grant_employee_scope

        return grant_employee_scope(db, principal)
    if principal.role == ROLE_PAYROLL_ADMIN and principal.user_id is not None:
        entities, groups = assigned_scope(db, principal.user_id, org)
        if entities or groups:
            return employees_in_units(db, org, entities, groups)
    return None
