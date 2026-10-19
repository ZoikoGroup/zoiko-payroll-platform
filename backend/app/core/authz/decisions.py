"""
core/authz/decisions.py
-----------------------
The PDP's output: an allow/deny Decision with a stable reason code and a
decision-trace id, plus the one uniform way a denial leaves the API.

Denials are uniform (ZP-PRIV A04 / A.4):
  * 404 NOT_FOUND  — the object is outside the principal's scope. Same body
    whether the object exists in another tenant or does not exist at all, so
    no existence can be inferred.
  * 403 ACCESS_DENIED — the action is not permitted for this principal.
  * 401 UNAUTHORIZED — no usable principal (kept from the auth layer).
Every denial body has the same shape: {success, error, message, detail, trace:
{decisionId}} — never the reason code (that is in the audit row only).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.core.exceptions import ZoikoException

# Reason codes (audit only; never returned to the caller).
ALLOW = "ALLOW"
PUBLIC_ROUTE = "PUBLIC_ROUTE"
NO_PRINCIPAL = "NO_PRINCIPAL"
ROUTE_NOT_REGISTERED = "ROUTE_NOT_REGISTERED"
ROUTE_RETIRED = "ROUTE_RETIRED"
ROLE_NOT_PERMITTED = "ROLE_NOT_PERMITTED"
ACTION_NOT_PERMITTED = "ACTION_NOT_PERMITTED"
TENANT_SCOPE_MISSING = "TENANT_SCOPE_MISSING"
OBJECT_NOT_IN_SCOPE = "ACCESS_DENIED_OUT_OF_SCOPE"
EXPORT_DENIED = "EXPORT_ATTEMPT_DENIED"
GRANT_REQUIRED = "SUPPORT_GRANT_REQUIRED"
SELF_ONLY = "EMPLOYEE_SELF_ONLY"
PDP_ERROR = "PDP_ERROR"

DENY_MESSAGE_403 = "You do not have permission to perform this action."
DENY_MESSAGE_404 = "Resource not found."


def new_decision_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    decision_id: str = field(default_factory=new_decision_id)
    # 403 for "action not permitted", 404 for "object outside scope".
    status_code: int = 200
    detail: Optional[str] = None  # internal note for the audit row only

    @classmethod
    def allow(cls, reason: str = ALLOW) -> "Decision":
        return cls(True, reason, status_code=200)

    @classmethod
    def deny(cls, reason: str, status_code: int = 403, detail: Optional[str] = None) -> "Decision":
        return cls(False, reason, status_code=status_code, detail=detail)


class AccessDenied(ZoikoException):
    """The single exception every PDP denial raises."""

    def __init__(self, decision: Decision):
        if decision.status_code == 404:
            super().__init__(404, "NOT_FOUND", DENY_MESSAGE_404)
        else:
            super().__init__(403, "ACCESS_DENIED", DENY_MESSAGE_403)
        self.decision = decision
        self.trace = {"decisionId": decision.decision_id}
