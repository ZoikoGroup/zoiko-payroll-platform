"""
modules/auth/schemas.py
-----------------------
"""
from datetime import datetime
from typing import List, Optional

import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.auth.models import UserRole


# ── Auth ────────────────────────────────────────────────────────────────────

REGISTRATION_PASSWORD_MIN_LENGTH = 12
REGISTRATION_PASSWORD_RULE = (
    f"Password must be at least {REGISTRATION_PASSWORD_MIN_LENGTH} characters and include "
    "a letter, a number and a symbol."
)


def registration_password_error(password: str) -> Optional[str]:
    """None when `password` meets the registration rule (the sign-up page
    shows the same rule), else the reason."""
    if (len(password or "") < REGISTRATION_PASSWORD_MIN_LENGTH
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"[0-9]", password)
            or not re.search(r"[^A-Za-z0-9]", password)):
        return REGISTRATION_PASSWORD_RULE
    return None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    organization: str = Field(..., min_length=1, max_length=200)
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=REGISTRATION_PASSWORD_MIN_LENGTH, max_length=128)
    industry: Optional[str] = None
    company_type: Optional[str] = None
    tax_no: Optional[str] = None
    registration_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = "UTC"
    phone: Optional[str] = None
    terms_accepted: bool = Field(..., description="Whether the registration terms were accepted")
    # Jurisdiction-aware tax/registration identifiers collected on the Register
    # Page once a country is selected — keyed by the field keys in
    # app/core/jurisdiction.py (gstin/pan/cin, ein/state_tax_id, crn/vat_number,
    # ust_idnr/steuernummer/hrb, abn/acn). Validated server-side against the
    # selected country's schema before persisting.
    tax_identifiers: Optional[dict] = None
    # The plan chosen on RegisterPage.jsx's Stage 1 plan picker — checkout
    # itself doesn't happen until PlanReviewPage (a later, separate call),
    # so this is purely informational at registration time: it lets the
    # welcome email name the actual plan the customer is signing up for,
    # instead of every plan's email being byte-identical. Never used for
    # billing/entitlement decisions here — POST /billing/checkout remains
    # the only place a plan is actually committed.
    plan_code: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _password_rule(cls, value: str) -> str:
        error = registration_password_error(value)
        if error:
            raise ValueError(error)
        return value

    @field_validator("timezone")
    @classmethod
    def _timezone_shape(cls, value: Optional[str]) -> Optional[str]:
        # An IANA zone name such as "Asia/Kolkata", stored on the organisation.
        value = (value or "").strip()
        if not value:
            return None
        if len(value) > 64 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*", value):
            raise ValueError("Timezone must be an IANA time zone name such as Asia/Kolkata.")
        return value


class TrialRegisterRequest(BaseModel):
    """Minimal payload for the 30-day Professional Evaluation signup
    (/auth/register-trial). Deliberately has no tax fields, and extra fields
    are forbidden — a client sending tax_no / tax_identifiers / address data
    is rejected at the schema level (422) rather than silently discarded, so
    the evaluation path can never persist compliance data it does not own."""

    model_config = ConfigDict(extra="forbid")

    organization: str = Field(..., min_length=1, max_length=200)
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    country: str = Field(..., min_length=1, max_length=100)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    # Optional -- revoking the refresh token too is the frontend's choice
    # (only possible if it still has the refresh token on hand to send).
    refresh_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class TokenPasswordRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class GeneratedPasswordResponse(BaseModel):
    password: str


# ── Responses ───────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    organization_id: Optional[int] = None
    organization_code: Optional[str] = None
    first_name: str
    last_name: str
    phone: Optional[str] = None
    is_active: bool
    created_at: datetime
    # Only for a temporary support login (role support_temp): what this
    # session is for, so its read-only screen can show it. Never personal data.
    support_session: Optional[dict] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginResponse(BaseModel):
    """Login / registration / refresh outcome (ZP-PRIV B08). Either a session
    (access + refresh token) or an MFA step: ``mfa_required`` (enter a code
    via /auth/mfa/challenge) or ``mfa_enrollment_required`` (set up TOTP via
    /auth/mfa/enroll/*). ``recovery_codes`` appears once, right after
    enrolment."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserResponse] = None
    mfa_required: bool = False
    mfa_enrollment_required: bool = False
    mfa_token: Optional[str] = None
    recovery_codes: Optional[List[str]] = None


class MfaChallengeRequest(BaseModel):
    mfa_token: str = Field(..., alias="mfaToken")
    code: Optional[str] = None
    recovery_code: Optional[str] = Field(None, alias="recoveryCode")
    model_config = ConfigDict(populate_by_name=True)


class MfaTokenRequest(BaseModel):
    mfa_token: str = Field(..., alias="mfaToken")
    model_config = ConfigDict(populate_by_name=True)


class MfaEnrollConfirmRequest(BaseModel):
    mfa_token: Optional[str] = Field(None, alias="mfaToken")
    code: str
    model_config = ConfigDict(populate_by_name=True)


class MfaCodeRequest(BaseModel):
    code: Optional[str] = None
    recovery_code: Optional[str] = Field(None, alias="recoveryCode")
    model_config = ConfigDict(populate_by_name=True)


class SuccessResponse(BaseModel):
    message: str


# ── Org Admin manages users ────────────────────────────────────────────────

class UserCreateRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    role: UserRole
    phone: Optional[str] = None
    send_invite: bool = True


class UserUpdateRequest(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=120)
    last_name: Optional[str] = Field(None, min_length=1, max_length=120)
    role: Optional[UserRole] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


# ── Trial banner ────────────────────────────────────────────────────────────

class TrialStatusResponse(BaseModel):
    """GET /auth/me/trial-status — everything the frontend trial banner
    needs, derived for the current user's organization.

    - ``workspace_type`` is read live from Organization (never inferred from
      the plan name — a real Professional-plan customer and an evaluation
      one can share the same plan code, only the workspace type differs).
    - ``trial_status`` is "ACTIVE"/"GRACE_READONLY"/"CLOSED"/None mapped from
      the org's BillingSubscription as derived in auth.service.
    - ``trial_expires_at`` comes from BillingSubscription.current_period_end
      (single source of truth — no second date field exists)."""

    workspace_type: str
    trial_status: Optional[str] = None
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
