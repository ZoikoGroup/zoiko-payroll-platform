"""
modules/payroll/policy/router.py
------------------------------------
HTTP endpoints for Payroll Policy Management.

Mounted under the same /api/payroll prefix as the existing payroll router
(see integration notes at the bottom of this file for how to register it
alongside — not instead of — the existing payroll_router).

  GET   /policy/active                                           -> current org's active policy (get-or-create)
  PUT   /policy/{policy_id}                                      -> update policy (admin only)
  POST  /policy/{policy_id}/integrations/{category}/{key}/enable
  POST  /policy/{policy_id}/integrations/{category}/{key}/disable
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import (
    get_current_user, get_current_payroll_operator, get_organization_id, require_active_subscription,
)
from app.modules.payroll.policy import service
from app.modules.payroll.policy.schemas import (
    PayrollPolicyResponse, PayrollPolicyUpdate, IntegrationResponse, SuccessResponse,
)

policy_router = APIRouter(
    prefix="/policy",
    tags=["Payroll Policy Management"],
    dependencies=[Depends(require_active_subscription("payroll"))],
)


@policy_router.get(
    "/active", response_model=PayrollPolicyResponse, response_model_by_alias=True,
    summary="Get the current organization's active payroll policy (auto-created if none exists)",
)
def get_active_policy(
    db: Session = Depends(get_db),
    organization_id: int = Depends(get_organization_id),
):
    # organization_id ALWAYS comes from the authenticated token, never from
    # a query param or request body — see earlier audit finding on cross-tenant risk.
    # get_organization_id (not a raw current_user.organization_id read) is what
    # actually enforces that: it raises a clean 403 for a Super Admin token
    # (which has no organization_id) instead of this get-or-create endpoint
    # crashing with a raw NOT NULL constraint violation trying to auto-seed
    # a policy row for organization_id=None.
    return service.get_active_policy(db, organization_id)


@policy_router.put(
    "/{policy_id}", response_model=PayrollPolicyResponse, response_model_by_alias=True,
    summary="Update a payroll policy (org admin only)",
)
def update_policy(
    policy_id: int,
    data: PayrollPolicyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),   # admin-only, matching existing compliance/company-details pattern
):
    return service.update_policy(db, policy_id, data, current_user.organization_id)


@policy_router.post(
    "/{policy_id}/integrations/{category}/{provider_key}/enable",
    response_model=IntegrationResponse, response_model_by_alias=True,
    summary="Enable an integration on a policy (org admin only)",
)
def enable_integration(
    policy_id: int, category: str, provider_key: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.set_integration_enabled(
        db, policy_id, category, provider_key, enabled=True, organization_id=current_user.organization_id,
    )


@policy_router.post(
    "/{policy_id}/integrations/{category}/{provider_key}/disable",
    response_model=IntegrationResponse, response_model_by_alias=True,
    summary="Disable an integration on a policy (org admin only)",
)
def disable_integration(
    policy_id: int, category: str, provider_key: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.set_integration_enabled(
        db, policy_id, category, provider_key, enabled=False, organization_id=current_user.organization_id,
    )


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION NOTE — where to register this router (do this by hand):
#
# Wherever payroll_router is currently included in your main app (e.g.
# app/main.py or app/api.py), add ONE line directly below it:
#
#     from app.modules.payroll.router import payroll_router
#     from app.modules.payroll.policy.router import policy_router   # ADD THIS
#
#     app.include_router(payroll_router, prefix="/api")
#     app.include_router(policy_router, prefix="/api")               # ADD THIS
#
# No existing include_router calls need to change.
# ═══════════════════════════════════════════════════════════════════════