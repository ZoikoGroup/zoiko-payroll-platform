"""
modules/auth/models.py
----------------------
User + single-use security action tokens.

User is the login-user record for the whole platform. It replaces the old
platform's `employees` table as the target of every created_by/approved_by
style FK in the Payroll module (those FK strings are remapped from
"employees.id" to "users.id").

Roles:
    super_admin   → platform-level, organization_id is NULL
    org_admin     → owns an organization
    payroll_admin → runs payroll day-to-day inside an org
    employee      → self-service inside an org
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    PAYROLL_ADMIN = "payroll_admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(200), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

    role = Column(Enum(UserRole), nullable=False, default=UserRole.PAYROLL_ADMIN)
    # NULL for super_admin; required for every org-scoped role.
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    phone = Column(String(40), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship(
        "Organization",
        back_populates="users",
        foreign_keys=[organization_id],
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r} role={self.role}>"


class SecurityActionPurpose(str, enum.Enum):
    INVITE = "invite"
    RESET = "reset"


class SecurityActionToken(Base):
    """Single-use action token (invite / password reset). Only the SHA-256
    hash is stored; the raw token goes in the emailed link."""

    __tablename__ = "security_action_tokens"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(200), index=True, nullable=False)
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    purpose = Column(Enum(SecurityActionPurpose), nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    # §04 supersession: set when a newer token for the same email+purpose is
    # issued. A superseded token can never be consumed or validated.
    superseded_at = Column(DateTime, nullable=True)
    # §04 idempotency key: tenant|event|recipient|template|material version.
    idempotency_key = Column(String(160), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RevokedToken(Base):
    """A JWT revoked before its own `exp` -- currently only via explicit
    logout (see auth/router.py). `jti` is the token's own random id claim
    (added to every access/refresh token at issuance, core/security.py),
    not a secret, so it's stored as-is rather than hashed like
    SecurityActionToken.token_hash above. `expires_at` mirrors the
    token's original `exp` claim purely so the cleanup sweep
    (auth/scheduler.py) knows when a row is safe to delete -- once the
    token itself would have expired naturally, keeping its revocation
    record around serves no purpose."""

    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuthEmailEvent(Base):
    """Persisted audit + double-send guard for every auth-module email.

    The row is INSERTed (outcome="pending") BEFORE any SMTP call; the UNIQUE
    idempotency_key is the structural guard — a duplicate request hits the
    constraint, records outcome="skipped_duplicate", and never reaches SMTP.
    After the send the same row's outcome is updated from the real smtplib
    result. This table is auth's record of truth; every send is also written
    to the platform-wide communication_events table (modules/communications),
    which carries retry attempt counts. The old log-only "email_audit" lines
    have been removed (§04).

    Two idempotency key families (see auth/service.py):
      - link-free notification events (password changed / replaced / reset
        completed / role changed / deactivated): strict unique on the base
        key, so a double-click or retried request collapses to one send.
      - token-link flows (reset request / invite): the base key is suffixed
        with the fresh token's hash prefix, so every legitimate re-request
        (each mints a new superseding token, and the latest email carries the
        only live link) records its own row while still being structurally
        unique.
    """

    __tablename__ = "auth_email_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    template_id = Column(String(20), nullable=False)
    recipient_email = Column(String(200), index=True, nullable=False)
    # NULL before a User row exists (e.g. mid-registration).
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Who triggered the event (e.g. the org admin who deactivated someone).
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # tenant | event | recipient | template | material version (+ token hash
    # prefix for token-link flows).
    idempotency_key = Column(String(220), unique=True, index=True, nullable=False)
    # sent / failed / skipped_duplicate (pending is the transient in-flight state).
    outcome = Column(String(24), nullable=False, default="pending")
    # SMTP provider detail on failure (e.g. "smtplib.SMTPAuthenticationError: ...").
    provider_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<AuthEmailEvent id={self.id} event_type={self.event_type} outcome={self.outcome} recipient={self.recipient_email}>"
