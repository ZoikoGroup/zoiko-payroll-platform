"""
core/authz/principal.py
-----------------------
The PDP's view of who is calling. Built from the already DB-revalidated
principal (core/dependencies._resolve_access_user / the assisted resolver),
never from anything the client sends in the URL, body, header or UI.

Platform roles never carry tenant payroll permission. Tenant roles carry
exactly one organization. Temporary support users are tenant users whose
permissions come from a live grant, re-read on every request (Part D).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Platform plane (organization_id is always NULL).
ROLE_SUPER_ADMIN = "super_admin"
ROLE_SUPPORT_OPERATOR = "support_operator"
ROLE_PLATFORM_SECURITY = "platform_security"
# Tenant plane.
ROLE_ORG_ADMIN = "org_admin"
ROLE_PAYROLL_ADMIN = "payroll_admin"
ROLE_EMPLOYEE = "employee"
# Temporary, grant-bound, read-only tenant user.
ROLE_SUPPORT_TEMP = "support_temp"
# Legacy SafeGuard assisted-access principal (retired in Part D).
ROLE_ASSISTED_ACCESS = "assisted_access"
# Tenant-pinned API client (ZP-PRIV D06): scope-bound, read-only.
ROLE_MACHINE_CLIENT = "machine_client"

PLATFORM_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_SUPPORT_OPERATOR, ROLE_PLATFORM_SECURITY})
TENANT_ROLES = frozenset({ROLE_ORG_ADMIN, ROLE_PAYROLL_ADMIN, ROLE_EMPLOYEE, ROLE_SUPPORT_TEMP,
                          ROLE_ASSISTED_ACCESS, ROLE_MACHINE_CLIENT})
ALL_ROLES = PLATFORM_ROLES | TENANT_ROLES


@dataclass(frozen=True)
class Principal:
    user_id: Optional[int]
    role: str
    organization_id: Optional[int]
    email: Optional[str] = None
    is_temporary: bool = False
    support_grant_id: Optional[int] = None
    # Employee self-service: the PayrollEmployee this login represents.
    payroll_employee_id: Optional[int] = None
    # Machine clients: the client id and the routes / field classes its
    # scopes grant.
    machine_client_id: Optional[int] = None
    machine_routes: frozenset = frozenset()
    machine_field_classes: frozenset = frozenset()

    @property
    def is_platform(self) -> bool:
        return self.role in PLATFORM_ROLES

    @property
    def is_tenant(self) -> bool:
        return self.role in TENANT_ROLES and self.organization_id is not None


def _role_value(obj) -> str:
    role = getattr(obj, "role", "") or ""
    return role.value if hasattr(role, "value") else str(role)


def principal_from_user(user) -> Principal:
    """Build a Principal from a resolved User row or AssistedAccessPrincipal.

    A platform role with an organization attached, or a tenant role without
    one, is ambiguous scope: it is passed through unchanged and the policy
    denies it (policy.authorize) rather than guessing which plane it means."""
    return Principal(
        user_id=getattr(user, "id", None),
        role=_role_value(user),
        organization_id=getattr(user, "organization_id", None),
        email=getattr(user, "email", None),
        is_temporary=bool(getattr(user, "is_temporary", False)),
        support_grant_id=getattr(user, "support_grant_id", None),
        payroll_employee_id=getattr(user, "self_service_employee_id", None),
        machine_client_id=getattr(user, "client_id", None),
        machine_routes=user.allowed_routes() if hasattr(user, "allowed_routes") else frozenset(),
        machine_field_classes=user.field_classes() if hasattr(user, "field_classes") else frozenset(),
    )
