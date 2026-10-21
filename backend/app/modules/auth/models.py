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
    # ZP-PRIV A.1 platform roles: never any tenant payroll permission.
    SUPPORT_OPERATOR = "support_operator"
    PLATFORM_SECURITY = "platform_security"
    # Temporary, read-only, grant-bound tenant user (JIT Support Access).
    SUPPORT_TEMP = "support_temp"
    # Employee own-record persona (policy only; self-service login stays
    # disabled - ZP-PRIV decision 2).
    EMPLOYEE = "employee"


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

    # ZP-PRIV D.2: temporary support accounts. Login, refresh and the
    # per-request auth check all refuse a user whose access_expires_at has
    # passed; the account is also deactivated when its grant ends.
    access_expires_at = Column(DateTime, nullable=True)
    is_temporary = Column(Boolean, default=False, nullable=False, server_default="0")
    support_grant_id = Column(Integer, nullable=True, index=True)
    # Employee persona only: the PayrollEmployee this login represents.
    self_service_employee_id = Column(Integer, nullable=True)

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


class AuthAuditEvent(Base):
    """G5 F-5: append-only login / authentication audit (immutable, F-6).

    Never stores a password or token. An email that matches no account is kept
    only as a SHA-256 (`email_sha256`), so typos of other people's addresses are
    not collected in clear."""

    __tablename__ = "auth_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = Column(String(40), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    organization_id = Column(Integer, nullable=True, index=True)
    email_sha256 = Column(String(64), nullable=True)
    reason = Column(String(80), nullable=True)
    client_address = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)


class AuthzDecisionEvent(Base):
    """ZP-PRIV A04: append-only record of every PDP denial (immutable, F-6).

    Deliberately stores no payload and no token. The reason code lives only
    here, never in the response body, so a caller cannot learn whether an
    object exists in another tenant. One row per denied request."""

    __tablename__ = "authz_decision_events"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    principal_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    principal_role = Column(String(40), nullable=False)
    organization_id = Column(Integer, nullable=True, index=True)
    method = Column(String(10), nullable=False)
    route_template = Column(String(300), nullable=False)
    action = Column(String(20), nullable=False)
    resource = Column(String(80), nullable=False)
    data_class = Column(String(40), nullable=False)
    reason_code = Column(String(60), nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    client_address = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    path_params = Column(Text, nullable=True)



class MfaCredential(Base):
    """ZP-PRIV B08: one TOTP credential per user. The seed is encrypted with
    core/secretbox (purpose "mfa-totp"); confirmed_at is set only after the
    user proves possession with a valid code. last_used_step blocks replay
    of a code inside its own 30-second window."""

    __tablename__ = "mfa_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    type = Column(String(20), nullable=False, default="TOTP")
    secret_encrypted = Column(Text, nullable=False)
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    last_used_step = Column(Integer, nullable=True)


class MfaRecoveryCode(Base):
    """Single-use recovery codes, stored only as SHA-256 hashes. Shown to the
    user exactly once, at generation."""

    __tablename__ = "mfa_recovery_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_at = Column(DateTime, nullable=True)


class RefreshTokenRecord(Base):
    """ZP-PRIV B08: refresh-token rotation with reuse detection. Every issued
    refresh token is a row; using one marks it used and issues its successor
    in the same family. Presenting an already-used (or revoked) token revokes
    the whole family — the signature of a stolen token being replayed."""

    __tablename__ = "auth_refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    family_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    issued_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(String(40), nullable=True)
    # Risk signals for privileged re-authentication (hashes, never raw).
    client_fingerprint = Column(String(64), nullable=True)
    mfa_at = Column(Integer, nullable=True)


from app.core import audit_immutability as _audit_immutability  # noqa: E402

_audit_immutability.register(Base.metadata)
