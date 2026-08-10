"""
core/dependencies.py
--------------------
Auth dependencies for the standalone Payroll Platform.

Role hierarchy (lowest = highest privilege):
    super_admin      → platform-level, organization_id is None
    org_admin        → full control inside their own org
    payroll_admin    → day-to-day payroll operations inside their own org
    employee         → self-service only, inside their own org

Every payroll query for a non-super-admin role MUST be scoped by
organization_id. Super Admin never reads through the org-scoped helpers;
it must explicitly pass an organization_id (get_super_admin_organization_id
or require_organization_access), or it is blocked.
"""

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import decode_access_token
from app.core.exceptions import ForbiddenException, UnauthorizedException

# Tokens are issued by this platform only (see core/security.py).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ORG_ADMIN = "org_admin"
ROLE_PAYROLL_ADMIN = "payroll_admin"
ROLE_EMPLOYEE = "employee"

VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_PAYROLL_ADMIN, ROLE_EMPLOYEE}

# What each role may create (org admin manages org users; super admin
# manages org admins platform-wide).
ROLE_CREATION_RULES = {
    ROLE_SUPER_ADMIN: [ROLE_ORG_ADMIN],
    ROLE_ORG_ADMIN: [ROLE_PAYROLL_ADMIN, ROLE_EMPLOYEE],
    ROLE_PAYROLL_ADMIN: [],
    ROLE_EMPLOYEE: [],
}

# Default landing route per role (mirrored in the frontend roles.js).
ROLE_DEFAULT_REDIRECT = {
    ROLE_SUPER_ADMIN: "/super-admin/dashboard",
    ROLE_ORG_ADMIN: "/organization-admin/dashboard",
    ROLE_PAYROLL_ADMIN: "/payroll-admin/dashboard",
    ROLE_EMPLOYEE: "/employee/ess",
}


def can_create_role(creator_role, target_role) -> bool:
    return target_role in ROLE_CREATION_RULES.get(creator_role, [])


def _role_value(user) -> str:
    role = getattr(user, "role", "") or ""
    return role.value if hasattr(role, "value") else str(role)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Any authenticated, active user. Returns the User ORM row."""
    payload = decode_access_token(token)
    if payload is None:
        raise UnauthorizedException("Invalid or expired token. Please log in again.")

    user_id = payload.get("user_id")
    if user_id is None:
        raise UnauthorizedException("Token is missing user information.")

    from app.modules.auth.models import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise UnauthorizedException("User account not found. Please log in again.")
    if not user.is_active:
        raise UnauthorizedException("Your account is disabled. Contact your administrator.")

    # Reject tokens issued for a different role/org than the DB currently
    # holds — a role demotion or org transfer must invalidate stale sessions.
    jwt_role = payload.get("role")
    if jwt_role != _role_value(user):
        raise UnauthorizedException("Your role changed. Please log in again.")

    jwt_org_id = payload.get("organization_id")
    if jwt_org_id != user.organization_id:
        raise UnauthorizedException("Your organization assignment changed. Please log in again.")

    # A super_admin token must not carry an organization_id.
    if _role_value(user) == ROLE_SUPER_ADMIN and user.organization_id is not None:
        raise UnauthorizedException("Super Admin token is invalid.")

    return user


def get_current_super_admin(current_user=Depends(get_current_user)):
    """Only platform-level Super Admin. Bypasses all org scoping."""
    if _role_value(current_user) != ROLE_SUPER_ADMIN:
        raise ForbiddenException("This action requires Super Admin privileges.")
    if current_user.organization_id is not None:
        raise ForbiddenException("Super Admin must not belong to an organization.")
    return current_user


def get_current_org_admin(current_user=Depends(get_current_user)):
    """Org-scoped admin: org_admin (or super_admin, who may act cross-org)."""
    role = _role_value(current_user)
    if role not in (ROLE_ORG_ADMIN, ROLE_SUPER_ADMIN):
        raise ForbiddenException(
            f"This action requires organization admin privileges. Your role: {role}"
        )
    return current_user


def get_current_payroll_operator(current_user=Depends(get_current_user)):
    """Org-scoped payroll operator: org_admin or payroll_admin (or super_admin
    acting cross-org). This is the gate used by the copied payroll routers —
    it replaces the old platform's get_current_org_admin for payroll ops."""
    role = _role_value(current_user)
    if role not in (ROLE_ORG_ADMIN, ROLE_PAYROLL_ADMIN, ROLE_SUPER_ADMIN):
        raise ForbiddenException(
            f"This action requires payroll operator privileges. Your role: {role}"
        )
    return current_user


def get_current_employee(current_user=Depends(get_current_user)):
    """Employee self-service only."""
    role = _role_value(current_user)
    if role not in (ROLE_EMPLOYEE, ROLE_SUPER_ADMIN):
        raise ForbiddenException(
            f"This action requires an employee account. Your role: {role}"
        )
    return current_user


def get_organization_id(current_user=Depends(get_current_user)) -> int:
    """Return the current user's organization_id.

    Super Admin MUST use get_super_admin_organization_id instead — using
    this helper with a super_admin token is blocked, because a Super Admin
    belongs to no single org.
    """
    role = _role_value(current_user)
    if role == ROLE_SUPER_ADMIN:
        raise ForbiddenException(
            "Super Admin must use get_super_admin_organization_id() to explicitly select an organization."
        )
    if current_user.organization_id is None:
        raise ForbiddenException("User is not associated with any organization.")
    return current_user.organization_id


def get_super_admin_organization_id(
    organization_id: int = None,
    current_user=Depends(get_current_user),
) -> int:
    """Super Admin must explicitly provide organization_id; non-super admins
    cannot use this helper."""
    role = _role_value(current_user)
    if role != ROLE_SUPER_ADMIN:
        raise ForbiddenException("Only Super Admin can use this dependency.")
    if organization_id is None:
        raise ForbiddenException(
            "Super Admin must provide an organization_id query parameter to access organization data."
        )
    return organization_id


def require_organization_access(
    target_organization_id: int,
    current_user=Depends(get_current_user),
) -> bool:
    """Super Admin may access any org; every other role is confined to its own
    organization_id. Cross-org attempts are rejected."""
    role = _role_value(current_user)
    if role == ROLE_SUPER_ADMIN:
        return True
    if current_user.organization_id != target_organization_id:
        raise ForbiddenException(
            f"Access denied: you can only access data from your own organization "
            f"(ID: {current_user.organization_id})."
        )
    return True


def require_active_subscription(product_code: str):
    """Dependency factory kept for parity with the copied payroll routers.

    The old platform checked a billing subscription + product entitlement.
    The standalone platform has no billing module — every onboarded
    organization is entitled. This gate now simply verifies the
    organization exists and is not suspended. Super Admin bypasses it.
    """
    async def _check_subscription(
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        role = _role_value(current_user)
        if role == ROLE_SUPER_ADMIN:
            return current_user
        if current_user.organization_id is None:
            raise ForbiddenException("User is not associated with any organization.")

        from app.modules.organizations.models import Organization

        org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
        if org is None:
            raise ForbiddenException("Your organization no longer exists.")
        if not org.is_active:
            raise ForbiddenException(
                "Your organization is suspended. Please contact support to regain access."
            )
        return current_user

    return _check_subscription
