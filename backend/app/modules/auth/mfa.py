"""
modules/auth/mfa.py
-------------------
TOTP multi-factor authentication and step-up (ZP-PRIV B08).

* Mandatory for privileged roles (MFA_REQUIRED_ROLES) when
  settings.MFA_ENFORCEMENT == "enforce" (production refuses anything else,
  see config.py). Optional for payroll admins.
* The seed is encrypted at rest (core/secretbox, purpose "mfa-totp").
* A code is accepted once: last_used_step blocks replay within the same or an
  earlier 30-second step (one step of clock drift either way is tolerated).
* Recovery codes: 10, single-use, stored as SHA-256 hashes, shown once.
* Step-up: a fresh code mints an access token whose ``mfa_at`` claim is now;
  sensitive actions require ``mfa_at`` within MFA_STEP_UP_MAX_AGE_SECONDS.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime
from typing import List, Optional

import pyotp
from sqlalchemy.orm import Session

from app.config import settings
from app.core import secretbox
from app.core.exceptions import BadRequestException, ForbiddenException, ZoikoException

SECRET_PURPOSE = "mfa-totp"
MFA_REQUIRED_ROLES = frozenset({"super_admin", "support_operator", "platform_security", "org_admin"})
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes


def _role(user) -> str:
    role = getattr(user, "role", "") or ""
    return role.value if hasattr(role, "value") else str(role)


def enforcement_on() -> bool:
    return settings.MFA_ENFORCEMENT.strip().lower() == "enforce"


def mfa_required_for(user) -> bool:
    return enforcement_on() and _role(user) in MFA_REQUIRED_ROLES


def _credential(db: Session, user_id: int):
    from app.modules.auth.models import MfaCredential

    return db.query(MfaCredential).filter(MfaCredential.user_id == user_id).first()


def is_enrolled(db: Session, user) -> bool:
    cred = _credential(db, user.id)
    return cred is not None and cred.confirmed_at is not None


def status(db: Session, user) -> dict:
    from app.modules.auth.models import MfaRecoveryCode

    cred = _credential(db, user.id)
    remaining = (
        db.query(MfaRecoveryCode)
        .filter(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
        .count()
    )
    return {
        "enrolled": bool(cred and cred.confirmed_at),
        "required": mfa_required_for(user),
        "type": cred.type if cred else None,
        "enrolledAt": cred.confirmed_at if cred and cred.confirmed_at else None,
        "recoveryCodesRemaining": remaining,
    }


def begin_enrollment(db: Session, user) -> dict:
    """Create (or replace an unconfirmed) TOTP seed and return it once."""
    from app.modules.auth.models import MfaCredential

    cred = _credential(db, user.id)
    if cred is not None and cred.confirmed_at is not None:
        raise ZoikoException(409, "MFA_ALREADY_ENROLLED", "Multi-factor authentication is already set up.")
    secret = pyotp.random_base32()
    if cred is None:
        cred = MfaCredential(user_id=user.id, type="TOTP")
        db.add(cred)
    cred.secret_encrypted = secretbox.encrypt(secret, SECRET_PURPOSE)
    cred.enrolled_at = datetime.utcnow()
    cred.confirmed_at = None
    cred.last_used_step = None
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.MFA_ISSUER_NAME)
    return {"secret": secret, "otpauthUri": uri, "issuer": settings.MFA_ISSUER_NAME, "account": user.email}


def _verify_totp(db: Session, cred, code: str) -> bool:
    secret = secretbox.decrypt(cred.secret_encrypted, SECRET_PURPOSE)
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    now_step = int(time.time() // 30)
    for step in (now_step - 1, now_step, now_step + 1):
        if secrets.compare_digest(totp.at(step * 30), code):
            if cred.last_used_step is not None and step <= cred.last_used_step:
                return False  # replay of an already-used code
            cred.last_used_step = step
            db.commit()
            return True
    return False


def _hash_recovery(code: str) -> str:
    normalized = (code or "").strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _new_recovery_codes(db: Session, user_id: int) -> List[str]:
    from app.modules.auth.models import MfaRecoveryCode

    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user_id).delete(synchronize_session=False)
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        code = f"{raw[:5]}-{raw[5:]}"
        codes.append(code)
        db.add(MfaRecoveryCode(user_id=user_id, code_hash=_hash_recovery(code)))
    db.commit()
    return codes


def confirm_enrollment(db: Session, user, code: str, request=None) -> List[str]:
    """Prove possession of the new seed; returns recovery codes (once)."""
    from app.modules.auth import audit as auth_audit

    cred = _credential(db, user.id)
    if cred is None or cred.confirmed_at is not None:
        raise BadRequestException("Start multi-factor setup first.")
    if not _verify_totp(db, cred, code):
        auth_audit.record(db, auth_audit.MFA_FAILED, user=user, request=request, reason="ENROLL_BAD_CODE")
        raise BadRequestException("That code is not valid. Check your authenticator app and try again.")
    cred.confirmed_at = datetime.utcnow()
    db.commit()
    codes = _new_recovery_codes(db, user.id)
    auth_audit.record(db, auth_audit.MFA_ENROLLED, user=user, request=request)
    return codes


def verify_second_factor(db: Session, user, *, code: Optional[str] = None,
                         recovery_code: Optional[str] = None, request=None,
                         failure_event: Optional[str] = None) -> bool:
    """True when a TOTP code or an unused recovery code is valid. Audited."""
    from app.modules.auth import audit as auth_audit
    from app.modules.auth.models import MfaRecoveryCode

    cred = _credential(db, user.id)
    if cred is None or cred.confirmed_at is None:
        return False
    if code and _verify_totp(db, cred, code):
        return True
    if recovery_code:
        row = (
            db.query(MfaRecoveryCode)
            .filter(MfaRecoveryCode.user_id == user.id,
                    MfaRecoveryCode.code_hash == _hash_recovery(recovery_code),
                    MfaRecoveryCode.used_at.is_(None))
            .first()
        )
        if row is not None:
            row.used_at = datetime.utcnow()
            db.commit()
            auth_audit.record(db, auth_audit.MFA_RECOVERY_CODE_USED, user=user, request=request)
            return True
    auth_audit.record(db, failure_event or auth_audit.MFA_FAILED, user=user, request=request,
                      reason="BAD_CODE")
    return False


def regenerate_recovery_codes(db: Session, user, request=None) -> List[str]:
    from app.modules.auth import audit as auth_audit

    if not is_enrolled(db, user):
        raise BadRequestException("Multi-factor authentication is not set up.")
    codes = _new_recovery_codes(db, user.id)
    auth_audit.record(db, auth_audit.MFA_RECOVERY_CODES_REGENERATED, user=user, request=request)
    return codes


def disable(db: Session, user, request=None) -> None:
    """Only for roles where MFA is optional; requires a recent step-up
    (enforced by the route)."""
    from app.modules.auth import audit as auth_audit
    from app.modules.auth.models import MfaCredential, MfaRecoveryCode

    if mfa_required_for(user):
        raise ForbiddenException("Multi-factor authentication is mandatory for your role.")
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete(synchronize_session=False)
    db.query(MfaCredential).filter(MfaCredential.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    auth_audit.record(db, auth_audit.MFA_DISABLED, user=user, request=request)
