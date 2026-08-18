"""
modules/payroll/enterprise/router.py
----------------------------------------
HTTP endpoints for Enterprise Policy jurisdiction onboarding.

DEPRECATION NOTICE (Phase 9 cleanup inventory, see
backend/scripts/HIERARCHY_V2_CLEANUP_INVENTORY.md): this module's
PayrollEnterpriseJurisdiction + its own contribution-rate storage is the
duplicate system the jurisdiction hierarchy engine
(app/modules/payroll/hierarchy/) is meant to eventually fold into via
OrganizationJurisdictionAssignment (multiple assignments = the "Enterprise"
UI state). NOT removed or functionally changed here — zero organizations
are cut over to the hierarchy engine yet, and this module is what today's
live Enterprise-mode payroll actually runs on. Do not delete/rename
anything in this file until the inventory doc's fold-in step is actually
executed for every org still using it.

Mounted as a sub-router of payroll_router (see app/modules/payroll/router.py
"payroll_router.include_router(enterprise_router)"), exactly like policy_router.

  GET    /enterprise/jurisdictions                          -> list org's jurisdictions
  POST   /enterprise/jurisdictions                          -> add a jurisdiction (admin only)
  PUT    /enterprise/jurisdictions/{id}                     -> update config / mark configured (admin only)
  POST   /enterprise/jurisdictions/{id}/verify               -> verify (admin only)
  DELETE /enterprise/jurisdictions/{id}                     -> remove (admin only)
  PUT    /enterprise/jurisdictions/{id}/contribution-rates/{component_key} -> upsert a rate (admin only)
  GET    /enterprise/validation                              -> activation readiness check
  POST   /enterprise/activate                                -> activate Enterprise Policy (admin only)
  POST   /enterprise/deactivate                              -> revert to Standard (admin only)
  GET    /enterprise/dashboard                               -> compliance dashboard stats
"""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_user, get_current_payroll_operator
from app.modules.payroll.enterprise import service
from app.modules.payroll.enterprise.schemas import (
    JurisdictionResponse, JurisdictionCreate, JurisdictionConfigUpdate,
    ValidationResponse, ActivationResponse, EnterpriseDashboardResponse, SuccessResponse,
    ContributionRateNumericResponse,
)

enterprise_router = APIRouter(prefix="/enterprise", tags=["Enterprise Payroll Onboarding"])


class ContributionRateUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    employee_rate_pct: Optional[Decimal] = Field(None, alias="employeeRatePct")
    employer_rate_pct: Optional[Decimal] = Field(None, alias="employerRatePct")
    flat_amount: Optional[Decimal] = Field(None, alias="flatAmount")


@enterprise_router.get(
    "/jurisdictions", response_model=list[JurisdictionResponse], response_model_by_alias=True,
    summary="List this organization's Enterprise jurisdictions",
)
def list_jurisdictions(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.get_jurisdictions(db, current_user.organization_id)


@enterprise_router.post(
    "/jurisdictions", response_model=JurisdictionResponse, response_model_by_alias=True,
    summary="Add a jurisdiction to Enterprise onboarding (org admin only)",
)
def add_jurisdiction(
    data: JurisdictionCreate, db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.add_jurisdiction(db, current_user.organization_id, data.country_code, actor_id=current_user.id)


@enterprise_router.put(
    "/jurisdictions/{jurisdiction_id}", response_model=JurisdictionResponse, response_model_by_alias=True,
    summary="Update a jurisdiction's compliance configuration (org admin only)",
)
def update_jurisdiction(
    jurisdiction_id: int, data: JurisdictionConfigUpdate, db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.update_jurisdiction_config(db, current_user.organization_id, jurisdiction_id, data, actor_id=current_user.id)


@enterprise_router.post(
    "/jurisdictions/{jurisdiction_id}/verify", response_model=JurisdictionResponse, response_model_by_alias=True,
    summary="Verify a configured jurisdiction (org admin only)",
)
def verify_jurisdiction(
    jurisdiction_id: int, db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    return service.verify_jurisdiction(db, current_user.organization_id, jurisdiction_id, actor_id=current_user.id)


@enterprise_router.delete(
    "/jurisdictions/{jurisdiction_id}", response_model=SuccessResponse,
    summary="Remove a jurisdiction from Enterprise onboarding (org admin only)",
)
def delete_jurisdiction(
    jurisdiction_id: int, db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    service.remove_jurisdiction(db, current_user.organization_id, jurisdiction_id, actor_id=current_user.id)
    return {"success": True, "message": "Jurisdiction removed."}


@enterprise_router.get(
    "/jurisdictions/{jurisdiction_id}/contribution-rates",
    response_model=list[ContributionRateNumericResponse], response_model_by_alias=True,
    summary="Numeric contribution rates for a jurisdiction's config panel",
)
def list_jurisdiction_contribution_rates(
    jurisdiction_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user),
):
    jurisdiction = service.get_jurisdiction_by_id(db, current_user.organization_id, jurisdiction_id)
    return service.get_contribution_rates_numeric(db, current_user.organization_id, jurisdiction.country_code)


@enterprise_router.put(
    "/jurisdictions/{jurisdiction_id}/contribution-rates/{component_key}",
    summary="Update a single contribution rate's percentages for a jurisdiction (org admin only)",
)
def update_contribution_rate(
    jurisdiction_id: int, component_key: str, data: ContributionRateUpdateRequest,
    db: Session = Depends(get_db), current_user=Depends(get_current_payroll_operator),
):
    jurisdiction = service.get_jurisdiction_by_id(db, current_user.organization_id, jurisdiction_id)
    row = service.upsert_contribution_rate(
        db, current_user.organization_id, jurisdiction.country_code, component_key,
        employee_rate_pct=data.employee_rate_pct, employer_rate_pct=data.employer_rate_pct,
        flat_amount=data.flat_amount, actor_id=current_user.id,
    )
    return {
        "componentKey": row.component_key,
        "employeeRatePct": row.employee_rate_pct,
        "employerRatePct": row.employer_rate_pct,
        "flatAmount": row.flat_amount,
    }


@enterprise_router.get(
    "/validation", response_model=ValidationResponse, response_model_by_alias=True,
    summary="Check whether Enterprise Payroll can be activated",
)
def get_validation(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.validate_enterprise_readiness(db, current_user.organization_id)


@enterprise_router.post(
    "/activate", response_model=ActivationResponse, response_model_by_alias=True,
    summary="Activate Enterprise Payroll (org admin only)",
)
def activate(db: Session = Depends(get_db), current_user=Depends(get_current_payroll_operator)):
    return service.activate_enterprise(db, current_user.organization_id, actor_id=current_user.id)


@enterprise_router.post(
    "/deactivate", response_model=ActivationResponse, response_model_by_alias=True,
    summary="Deactivate Enterprise Payroll, revert to Standard (org admin only)",
)
def deactivate(db: Session = Depends(get_db), current_user=Depends(get_current_payroll_operator)):
    return service.deactivate_enterprise(db, current_user.organization_id, actor_id=current_user.id)


@enterprise_router.get(
    "/dashboard", response_model=EnterpriseDashboardResponse, response_model_by_alias=True,
    summary="Enterprise compliance dashboard stats",
)
def get_dashboard(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.get_dashboard(db, current_user.organization_id)
