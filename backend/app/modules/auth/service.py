"""
modules/auth/service.py
-----------------------
Auth business logic: login, org registration, action tokens (invite /
reset), change password, and org-admin user management.
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.code_generation import generate_employee_code, generate_organization_code
from app.core.exceptions import (
    AlreadyExistsException,
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.modules.auth.models import SecurityActionPurpose, SecurityActionToken, User, UserRole
from app.modules.auth.schemas import RegisterRequest
from app.modules.organizations.models import Organization

logger = logging.getLogger("zoiko_payroll.auth")

TOKEN_TTL_HOURS = 24
INVALID_TOKEN_MESSAGE = "This link is no longer valid. Please request a new one."

# Governance: Zoiko Payroll Email Communications System v2.0.0 — template
# IAM-007 (Password reset requested, Class P1, family IAM).
RESET_TEMPLATE_ID = "IAM-007"
RESET_EVENT_TYPE = "identity.password_reset_requested"
# Governance: template IAM-002 (User invitation, Class P1, family IAM).
INVITE_TEMPLATE_ID = "IAM-002"
INVITE_EVENT_TYPE = "identity.invitation_created"
# Bump when the template copy or TTL changes materially (§04 idempotency key).
TOKEN_MATERIAL_VERSION = "v2"

# Human-readable role names for invitation copy (IAM-002 {{role_name}}).
ROLE_DISPLAY_LABELS = {
    UserRole.SUPER_ADMIN: "Platform Administrator",
    UserRole.ORG_ADMIN: "Organization Administrator",
    UserRole.PAYROLL_ADMIN: "Payroll Administrator",
}


# ── Action tokens (invite / password reset) ────────────────────────────────

def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _action_link(purpose: SecurityActionPurpose, raw_token: str) -> str:
    """Reset links open the React app's /reset-password page (which calls the
    JSON API). Invite links open the backend-hosted claim page that issues a
    one-time temporary password. NOTE: routers are mounted under "/api" in
    main.py, so backend URLs must include that prefix."""
    from app.config import settings

    # §07 secure-action: opaque random token only — no email/user_id or any
    # readable data in the query string.
    query = f"token={raw_token}"
    if purpose == SecurityActionPurpose.INVITE:
        api_base = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
        return f"{api_base}/api/auth/accept-invite?{query}"
    base = os.environ.get("ACTION_BASE_URL", "").rstrip("/") or settings.FRONTEND_URL.rstrip("/")
    return f"{base}/reset-password?{query}"


def _format_expiry_local(expires_at: datetime) -> str:
    """Absolute expiry rendered with a named time zone (§10 copy standard).
    Never a relative 'in N hours' string."""
    return f"{expires_at.strftime('%d %B %Y at %H:%M')} UTC"


def _reference_id(raw_token: str, prefix: str = "ZK", suffix: str = "SEC") -> str:
    """Short non-secret reference for support conversations. Derived from the
    token hash prefix — reveals nothing about the token itself."""
    return f"{prefix}-{int(_token_hash(raw_token)[:8], 16) % 10000:04d}-{suffix}"


def _idempotency_key(organization_id, event_type: str, email: str, template_id: str) -> str:
    """§04 idempotency key: tenant | event | recipient | template | material
    version."""
    return "|".join([
        str(organization_id or "platform"),
        event_type,
        email.lower(),
        template_id,
        TOKEN_MATERIAL_VERSION,
    ])


def _supersede_active_tokens(db: Session, email: str, purpose) -> int:
    """§04 supersession: invalidate every still-live (unused, unexpired,
    un-superseded) token for this email+purpose before issuing a new one, so
    at most one valid link is ever outstanding."""
    from sqlalchemy import text

    result = db.execute(
        text(
            """
            UPDATE security_action_tokens
            SET superseded_at = CURRENT_TIMESTAMP
            WHERE email = :email
              AND purpose = :purpose
              AND used_at IS NULL
              AND superseded_at IS NULL
              AND expires_at > :now
            """
        ),
        {"email": email, "purpose": purpose.name, "now": datetime.utcnow()},
    )
    return result.rowcount or 0


def _issue_action_token(
    db: Session,
    email: str,
    organization_id,
    purpose,
    idempotency_key: Optional[str] = None,
) -> tuple[str, datetime]:
    superseded = _supersede_active_tokens(db, email, purpose)
    if superseded:
        logger.info(
            "email_audit event=%s recipient=%s purpose=%s superseded_tokens=%d",
            RESET_EVENT_TYPE if purpose == SecurityActionPurpose.RESET else INVITE_EVENT_TYPE,
            email,
            purpose.name,
            superseded,
        )
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
    db.add(SecurityActionToken(
        email=email,
        organization_id=organization_id,
        purpose=purpose,
        token_hash=_token_hash(raw_token),
        expires_at=expires_at,
        idempotency_key=idempotency_key,
    ))
    db.flush()
    return raw_token, expires_at


def _consume_action_token(db: Session, raw_token: str, purpose) -> Optional[dict]:
    """Atomically consume a single-use token (UPDATE ... RETURNING). Returns
    {"email":..., "organization_id":...} or None for every invalid state.
    Click-time state (used/expired/superseded) is rechecked here."""
    from sqlalchemy import text

    row = db.execute(
        text(
            """
            UPDATE security_action_tokens
            SET used_at = CURRENT_TIMESTAMP
            WHERE token_hash = :hash
              AND purpose = :purpose
              AND used_at IS NULL
              AND superseded_at IS NULL
              AND expires_at > :now
            RETURNING email, organization_id
            """
        ),
        {"hash": _token_hash(raw_token), "purpose": purpose.name, "now": datetime.utcnow()},
    ).fetchone()
    if row is None:
        return None
    return {"email": row[0], "organization_id": row[1]}


def validate_action_token(db: Session, raw_token: str, purpose) -> Optional[dict]:
    from sqlalchemy import text

    row = db.execute(
        text("SELECT email, organization_id, expires_at, used_at, purpose, superseded_at FROM security_action_tokens WHERE token_hash = :hash"),
        {"hash": _token_hash(raw_token)},
    ).fetchone()
    if row is None:
        return None
    email, organization_id, expires_at, used_at, purpose_stored, superseded_at = row
    # Raw SQL on SQLite yields naive datetimes as strings; normalise so the
    # expiry comparison works identically on Postgres and SQLite.
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            return None
    if (
        used_at is not None
        or superseded_at is not None
        or purpose_stored != purpose.name
        or expires_at <= datetime.utcnow()
    ):
        return None
    return {"token": raw_token, "email": email, "organization_id": organization_id}


def claim_invitation(db: Session, raw_token: str) -> Optional[tuple[User, str]]:
    """One-click invite acceptance (IAM-002): atomically consume the token,
    generate a one-time temporary password for the invited user, mark the
    account active + claimed. Returns (user, temp_password) or None for every
    invalid state. The temporary password is returned exactly once and never
    stored in plaintext."""
    consumed = _consume_action_token(db, raw_token, SecurityActionPurpose.INVITE)
    if consumed is None:
        return None

    user = db.query(User).filter(User.email == consumed["email"]).first()
    # §06 accept-time re-resolution: claimed (verified) or deactivated
    # accounts can never be taken over by replaying a still-live link.
    if user is None or not user.is_active or user.is_verified:
        db.rollback()
        return None

    temp_password = secrets.token_urlsafe(12)
    user.hashed_password = hash_password(temp_password)
    user.is_active = True
    user.is_verified = True
    db.commit()
    db.refresh(user)
    logger.info(
        "email_audit event=identity.invitation_accepted recipient=%s user_id=%s organization_id=%s",
        user.email,
        user.id,
        user.organization_id,
    )
    return user, temp_password


def complete_action_token(db: Session, raw_token: str, purpose, new_password: str) -> dict:
    consumed = _consume_action_token(db, raw_token, purpose)
    if consumed is None:
        raise BadRequestException(INVALID_TOKEN_MESSAGE)

    user = db.query(User).filter(User.email == consumed["email"]).first()
    # §06 recipient resolution: re-check existence AND active state at the
    # moment the password is set, not only at request time.
    if user is None or not user.is_active:
        raise BadRequestException(INVALID_TOKEN_MESSAGE)
    # §06 invite claim-guard: a claimed (already set-up) account can never be
    # taken over by replaying a still-circulating invite link.
    if purpose == SecurityActionPurpose.INVITE and user.is_verified:
        raise BadRequestException(INVALID_TOKEN_MESSAGE)

    user.hashed_password = hash_password(new_password)
    user.is_active = True
    if purpose == SecurityActionPurpose.INVITE:
        user.is_verified = True
    db.commit()
    db.refresh(user)
    logger.info(
        "email_audit event=%s recipient=%s user_id=%s",
        "identity.password_reset_completed" if purpose == SecurityActionPurpose.RESET
        else "identity.invitation_accepted",
        user.email,
        user.id,
    )
    return {"message": "Password set successfully. You can now sign in."}


# ── Login ───────────────────────────────────────────────────────────────────

def login_user(db: Session, email: str, password: str) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(password, user.hashed_password):
        raise UnauthorizedException("Invalid email or password.")

    if user.organization_id:
        org = db.query(Organization).filter(Organization.id == user.organization_id).first()
        if org is not None and not org.is_active:
            raise UnauthorizedException(
                "Your organization has been suspended. Please contact support."
            )

    if not user.is_active:
        raise UnauthorizedException("Your account has been deactivated.")

    token_payload = {
        "sub": user.email,
        "role": user.role.value,
        "user_id": user.id,
        "organization_id": user.organization_id,
    }
    access_token = create_access_token(data=token_payload)
    refresh_token = create_refresh_token(data=token_payload)

    logger.info("User %s (%s) logged in", user.email, user.role.value)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }


def refresh_user_token(db: Session, refresh_token: str) -> dict:
    from app.core.security import decode_refresh_token

    payload = decode_refresh_token(refresh_token)
    if payload is None:
        raise UnauthorizedException("Invalid or expired refresh token.")

    user = db.query(User).filter(User.id == payload.get("user_id")).first()
    if user is None or not user.is_active:
        raise UnauthorizedException("User not found or inactive.")

    if user.organization_id:
        org = db.query(Organization).filter(Organization.id == user.organization_id).first()
        if org is not None and not org.is_active:
            raise UnauthorizedException("Your organization has been suspended.")

    new_access = create_access_token(data={
        "sub": user.email,
        "role": user.role.value,
        "user_id": user.id,
        "organization_id": user.organization_id,
    })
    return {
        "access_token": new_access,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }


# ── Registration (public self-serve onboarding) ─────────────────────────────

def register_enterprise(db: Session, data: RegisterRequest) -> dict:
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise AlreadyExistsException("User", "email")

    # Deduplication / reuse rule: only ever persist tax identifiers that match
    # the selected jurisdiction's schema. Unknown keys and blank values are
    # dropped rather than stored — so repeated registrations / resubmissions
    # never create redundant tax records. The org itself is keyed uniquely by
    # its generated code and the admin email (checked above).
    from app.core.jurisdiction import primary_tax_value, validate_tax_identifiers_or_raise

    tax_identifiers = validate_tax_identifiers_or_raise(data.country, data.tax_identifiers) \
        if data.tax_identifiers else None
    tax_no = data.tax_no or primary_tax_value(data.country, tax_identifiers)

    org_code = generate_organization_code(data.organization, db)

    org = Organization(
        organization_name=data.organization,
        organization_code=org_code,
        industry=data.industry,
        company_type=data.company_type,
        tax_no=tax_no,
        tax_identifiers=tax_identifiers,
        registration_number=data.registration_number,
        address=data.address,
        city=data.city,
        state=data.state,
        country=data.country,
        email=data.email,
        phone=data.phone,
        is_active=True,
    )
    db.add(org)
    db.flush()

    name_parts = data.name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else "Admin"

    admin = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.ORG_ADMIN,
        organization_id=org.id,
        first_name=first_name,
        last_name=last_name,
        phone=data.phone or "",
        is_active=True,
        is_verified=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.refresh(org)

    logger.info("New organization %s registered by %s", org.organization_code, data.email)

    try:
        from app.services.email_service import (
            send_organization_created_email,
            send_super_admin_org_created_notification_email,
        )
        ref_id = f"ORG-{org.id:04d}-INIT"
        send_organization_created_email(
            email=admin.email,
            recipient_first_name=first_name,
            organization_name=org.organization_name,
            reference_id=ref_id,
            organization_id=org.id,
            db=db,
        )
        logger.info(
            "email_audit event=commercial.organization_created template_id=COM-001 recipient=%s org_id=%s reference_id=%s",
            admin.email, org.id, ref_id,
        )
        # Notify Super Admins with full org & primary admin metadata
        send_super_admin_org_created_notification_email(
            org=org,
            admin_user=admin,
            reference_id=f"ADM-ORG-{org.id:04d}",
            db=db,
        )
    except Exception as exc:
        logger.warning("Failed to dispatch org created emails for org %s: %s", org.id, exc)

    token_payload = {
        "sub": admin.email,
        "role": admin.role.value,
        "user_id": admin.id,
        "organization_id": admin.organization_id,
    }
    return {
        "access_token": create_access_token(data=token_payload),
        "refresh_token": create_refresh_token(data=token_payload),
        "token_type": "bearer",
        "user": admin,
    }


# ── Password flows ──────────────────────────────────────────────────────────

def request_password_reset(db: Session, email: str) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if user is not None and user.is_active:
        # §04 idempotency key: tenant | event | recipient | template | material
        # version — a double "Forgot password" submit can never leave two live,
        # independently-valid tokens (the older one is superseded).
        idempotency_key = _idempotency_key(
            user.organization_id, RESET_EVENT_TYPE, user.email, RESET_TEMPLATE_ID,
        )
        raw_token, expires_at = _issue_action_token(
            db,
            user.email,
            user.organization_id,
            SecurityActionPurpose.RESET,
            idempotency_key=idempotency_key,
        )
        link = _action_link(SecurityActionPurpose.RESET, raw_token)
        db.commit()
        sent = _send_reset_email(
            db, user, link,
            expires_at_local=_format_expiry_local(expires_at),
            reference_id=_reference_id(raw_token),
        )
        # §04 audit/evidence: durable record of event, template, recipient and
        # outcome. Never log the raw token or the link.
        logger.info(
            "email_audit event=%s template_id=%s recipient=%s user_id=%s organization_id=%s sent_at=%s outcome=%s",
            RESET_EVENT_TYPE,
            RESET_TEMPLATE_ID,
            user.email,
            user.id,
            user.organization_id,
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "sent" if sent else "failed",
        )
    else:
        db.rollback()
    # Always return the same message to avoid email enumeration.
    return {"message": "If that email is registered, a password reset link has been sent."}


def change_password(db: Session, user_id: int, current_password: str, new_password: str) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise NotFoundException("User", "id")
    if not verify_password(current_password, user.hashed_password):
        raise BadRequestException("Current password is incorrect.")
    user.hashed_password = hash_password(new_password)
    db.commit()
    return {"message": "Password changed successfully."}


def generate_random_password(db: Session, user_id: int) -> dict:
    """Self-service: immediately replace the caller's own password with a
    freshly generated random one and return it once, in-band — for use when
    email delivery can't be relied on (e.g. SMTP unconfigured). Never stored
    or logged in plaintext beyond this single response."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise NotFoundException("User", "id")
    new_password = secrets.token_urlsafe(12)
    user.hashed_password = hash_password(new_password)
    db.commit()
    logger.info("User %s generated a new random password for their own account.", user.email)
    return {"password": new_password}


def invite_user(db: Session, actor, data) -> User:
    """Org admin invites a payroll_admin / employee into their own org."""
    from app.modules.auth.schemas import UserCreateRequest
    from app.core.dependencies import can_create_role

    if not can_create_role(actor.role.value, data.role.value):
        raise ForbiddenException(
            f"Role {actor.role.value} cannot create users with role {data.role.value}."
        )
    if actor.organization_id is None:
        raise ForbiddenException("Super Admin must create users via the super-admin API.")

    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise AlreadyExistsException("User", "email")

    user = User(
        email=data.email,
        hashed_password=hash_password(secrets.token_urlsafe(24)),
        role=data.role,
        organization_id=actor.organization_id,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone or "",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.flush()

    if data.send_invite:
        _dispatch_invite_email(db, user, actor)

    db.commit()
    db.refresh(user)
    return user


def resend_user_invite(db: Session, actor, user: User) -> None:
    """Re-send an invitation for an existing, not-yet-claimed user. Same
    supersession + idempotency + audit path as the original invite (§04):
    the fresh link invalidates any earlier one."""
    raw = _dispatch_invite_email(db, user, actor)
    db.commit()
    return raw


def _dispatch_invite_email(db: Session, user: User, actor) -> bool:
    """Issue the invite token and send IAM-002. Shared by invite_user and
    the resend endpoint so both get identical §04 treatment:
    - prior live INVITE tokens for this email are superseded
    - idempotency key = tenant|identity.invitation_created|recipient|IAM-002|v2
    - structured audit record with outcome; never logs the token/link"""
    idempotency_key = _idempotency_key(
        user.organization_id, INVITE_EVENT_TYPE, user.email, INVITE_TEMPLATE_ID,
    )
    raw_token, expires_at = _issue_action_token(
        db,
        user.email,
        user.organization_id,
        SecurityActionPurpose.INVITE,
        idempotency_key=idempotency_key,
    )
    link = _action_link(SecurityActionPurpose.INVITE, raw_token)
    sent = _send_invite_email(
        db, user, actor, link,
        expires_at_local=_format_expiry_local(expires_at),
        reference_id=_reference_id(raw_token, prefix="INV", suffix="ORG"),
    )
    logger.info(
        "email_audit event=%s template_id=%s recipient=%s actor_id=%s organization_id=%s sent_at=%s outcome=%s",
        INVITE_EVENT_TYPE,
        INVITE_TEMPLATE_ID,
        user.email,
        actor.id if actor is not None else None,
        user.organization_id,
        datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "sent" if sent else "failed",
    )
    return sent


# ── Email notifications ─────────────────────────────────────────────────────

def _send_reset_email(
    db: Session,
    user: User,
    link: str,
    expires_at_local: str = "",
    reference_id: str = "",
) -> bool:
    from app.services.email_service import send_org_admin_password_reset_email

    # One canonical IAM-007 template serves both org_admin and payroll_admin
    # recipients — resolution is by user record, not role.
    return send_org_admin_password_reset_email(
        db=db,
        email=user.email,
        first_name=user.first_name,
        reset_link=link,
        expires_at_local=expires_at_local or _format_expiry_local(datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)),
        reference_id=reference_id,
        organization_id=user.organization_id,
    )


def _send_invite_email(
    db: Session,
    user: User,
    actor,
    link: str,
    expires_at_local: str = "",
    reference_id: str = "",
) -> bool:
    from app.services.email_service import send_user_invite_email

    return send_user_invite_email(
        db=db,
        email=user.email,
        first_name=user.first_name,
        invite_link=link,
        inviter_name=actor.full_name if actor is not None else "",
        role_name=ROLE_DISPLAY_LABELS.get(user.role, user.role.value.replace("_", " ").title()),
        expires_at_local=expires_at_local,
        reference_id=reference_id,
        organization_id=user.organization_id,
    )
