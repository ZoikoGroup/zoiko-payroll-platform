"""
modules/payroll/hierarchy/router.py
--------------------------------------
API surface for the new jurisdiction/tax hierarchy engine.

Two routers, mirroring the plan's two audiences:
  - hierarchy_super_admin_router  -> /super-admin/tax-hierarchy/*  (Super Admin CRUD)
  - hierarchy_org_router          -> /organizations/{id}/compliance/*  (Org Admin read + assignment/override actions)

Old /super-admin/compliance/* and /payroll/compliance/* endpoints
(app/modules/super_admin/router.py, app/modules/payroll/router.py) are
completely untouched — they keep serving the old JurisdictionPack/
ContributionRate/TaxSlab data exactly as before. This is a second,
additive API surface, not a replacement.
"""

from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_org_admin, get_current_super_admin, get_current_user, require_organization_access,
)
from app.database import get_db
from app.modules.payroll.hierarchy import service
from app.modules.payroll.hierarchy.schemas import (
    ApplicableComplianceConfigurationResponse,
    CountryResponse, JurisdictionDetail, JurisdictionLevelResponse,
    JurisdictionNodeSummary, JurisdictionUpsert,
    OrganizationJurisdictionAssignmentResponse, OrganizationJurisdictionAssignmentUpsert,
    SuccessResponse, TaxParameterResponse, TaxParameterUpsert,
    TaxResponse, TaxRuleRateUpsert, TaxRuleResponse, TaxRuleSlabUpsert, TaxRuleUpsert,
    TaxUpsert, TaxVersionDetail, TaxVersionStatusUpdate, TaxVersionSummary, TaxVersionUpsert,
)

hierarchy_super_admin_router = APIRouter(prefix="/super-admin/tax-hierarchy", tags=["Tax Hierarchy - Super Admin"])
hierarchy_org_router = APIRouter(prefix="/organizations", tags=["Tax Hierarchy - Organization Compliance"])


# ── Static reference metadata ────────────────────────────────────────────

@hierarchy_super_admin_router.get("/countries", response_model=List[CountryResponse])
def list_countries(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_countries(db)


@hierarchy_super_admin_router.get("/countries/{country_id}/levels", response_model=List[JurisdictionLevelResponse])
def list_jurisdiction_levels(country_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_jurisdiction_levels(db, country_id)


# ── Jurisdiction tree ────────────────────────────────────────────────────

@hierarchy_super_admin_router.get("/jurisdictions", response_model=List[JurisdictionNodeSummary])
def list_jurisdiction_children(
    parent_id: Optional[int] = Query(None), country_id: Optional[int] = Query(None),
    current_user=Depends(get_current_super_admin), db: Session = Depends(get_db),
):
    return service.list_jurisdiction_children(db, parent_id=parent_id, country_id=country_id)


@hierarchy_super_admin_router.get("/jurisdictions/{jurisdiction_id}", response_model=JurisdictionDetail)
def get_jurisdiction_detail(jurisdiction_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.get_jurisdiction_detail(db, jurisdiction_id)


@hierarchy_super_admin_router.put("/jurisdictions", response_model=JurisdictionDetail)
def upsert_jurisdiction(data: JurisdictionUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    row = service.upsert_jurisdiction(db, data, actor_id=current_user.id)
    return service.get_jurisdiction_detail(db, row.id)


# ── Tax ──────────────────────────────────────────────────────────────────

@hierarchy_super_admin_router.get("/jurisdictions/{jurisdiction_id}/taxes", response_model=List[TaxResponse])
def list_taxes_for_jurisdiction(jurisdiction_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_taxes_for_jurisdiction(db, jurisdiction_id)


@hierarchy_super_admin_router.put("/taxes", response_model=TaxResponse)
def upsert_tax(data: TaxUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.upsert_tax(db, data, actor_id=current_user.id)


# ── TaxVersion ───────────────────────────────────────────────────────────

@hierarchy_super_admin_router.get("/taxes/{tax_id}/versions", response_model=List[TaxVersionSummary])
def list_tax_versions(tax_id: int, jurisdiction_id: int = Query(...), current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_tax_versions(db, tax_id, jurisdiction_id)


@hierarchy_super_admin_router.get("/tax-versions/{tax_version_id}", response_model=TaxVersionDetail)
def get_tax_version_detail(tax_version_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.get_tax_version_detail(db, tax_version_id)


@hierarchy_super_admin_router.put("/tax-versions", response_model=TaxVersionDetail)
def upsert_tax_version(data: TaxVersionUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.upsert_tax_version(db, data, actor_id=current_user.id)


@hierarchy_super_admin_router.put("/tax-versions/{tax_version_id}/status", response_model=TaxVersionDetail)
def update_tax_version_status(
    tax_version_id: int, payload: TaxVersionStatusUpdate,
    current_user=Depends(get_current_super_admin), db: Session = Depends(get_db),
):
    return service.transition_tax_version_status(db, tax_version_id, payload.status, actor_id=current_user.id)


# ── TaxRule / TaxRuleSlab / TaxRuleRate ─────────────────────────────────

@hierarchy_super_admin_router.get("/tax-versions/{tax_version_id}/rules", response_model=List[TaxRuleResponse])
def list_tax_rules(tax_version_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_tax_rules_with_children(db, tax_version_id)


@hierarchy_super_admin_router.put("/tax-rules")
def upsert_tax_rule(data: TaxRuleUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    row = service.upsert_tax_rule(db, data, actor_id=current_user.id)
    return {"id": row.id}


@hierarchy_super_admin_router.delete("/tax-rules/{tax_rule_id}", response_model=SuccessResponse)
def delete_tax_rule(tax_rule_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    service.delete_tax_rule(db, tax_rule_id, actor_id=current_user.id)
    return {"message": "Tax rule deleted."}


@hierarchy_super_admin_router.put("/tax-rule-slabs")
def upsert_tax_rule_slab(data: TaxRuleSlabUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    row = service.upsert_tax_rule_slab(db, data, actor_id=current_user.id)
    return {"id": row.id}


@hierarchy_super_admin_router.delete("/tax-rule-slabs/{slab_id}", response_model=SuccessResponse)
def delete_tax_rule_slab(slab_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    service.delete_tax_rule_slab(db, slab_id, actor_id=current_user.id)
    return {"message": "Slab deleted."}


@hierarchy_super_admin_router.put("/tax-rule-rates")
def upsert_tax_rule_rate(data: TaxRuleRateUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    row = service.upsert_tax_rule_rate(db, data, actor_id=current_user.id)
    return {"id": row.id}


@hierarchy_super_admin_router.delete("/tax-rule-rates/{rate_id}", response_model=SuccessResponse)
def delete_tax_rule_rate(rate_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    service.delete_tax_rule_rate(db, rate_id, actor_id=current_user.id)
    return {"message": "Rate deleted."}


# ── TaxParameter ─────────────────────────────────────────────────────────

@hierarchy_super_admin_router.get("/tax-versions/{tax_version_id}/parameters", response_model=List[TaxParameterResponse])
def list_tax_parameters(tax_version_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_tax_parameters(db, tax_version_id)


@hierarchy_super_admin_router.put("/tax-parameters", response_model=TaxParameterResponse)
def upsert_tax_parameter(data: TaxParameterUpsert, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.upsert_tax_parameter(db, data, actor_id=current_user.id)


@hierarchy_super_admin_router.delete("/tax-parameters/{parameter_id}", response_model=SuccessResponse)
def delete_tax_parameter(parameter_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    service.delete_tax_parameter(db, parameter_id, actor_id=current_user.id)
    return {"message": "Parameter deleted."}


# ── Applicability / Audit ────────────────────────────────────────────────

@hierarchy_super_admin_router.get("/jurisdictions/{jurisdiction_id}/applicability")
def list_jurisdiction_applicability(jurisdiction_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_jurisdiction_applicability(db, jurisdiction_id)


@hierarchy_super_admin_router.get("/tax-versions/{tax_version_id}/audit")
def list_tax_version_audit(tax_version_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return service.list_tax_version_audit(db, tax_version_id)


# ── Organization-facing ───────────────────────────────────────────────────
# Unlike every other org-scoped route in this codebase (which never takes
# an organization_id path param at all, deriving it from
# current_user.organization_id), these three intentionally DO take one —
# they're meant to be reachable both by an Org Admin viewing their own
# organization AND by Super Admin viewing any organization (e.g. from the
# Jurisdiction Explorer's Applicability tab). require_organization_access
# is this codebase's existing purpose-built guard for exactly that shape
# of route: Super Admin passes through unconditionally, anyone else is
# rejected unless organization_id matches their own — without it here,
# any authenticated user could read or write another organization's
# compliance data just by changing the URL.

@hierarchy_org_router.get("/{organization_id}/compliance/applicable", response_model=ApplicableComplianceConfigurationResponse)
def get_applicable_compliance_configuration(
    organization_id: int, payroll_date: Optional[date] = Query(None),
    current_user=Depends(get_current_user), db: Session = Depends(get_db),
):
    require_organization_access(organization_id, current_user)
    return service.resolve_applicable_compliance_configuration(db, organization_id, payroll_date=payroll_date)


@hierarchy_org_router.get("/{organization_id}/compliance/jurisdiction-assignments", response_model=List[OrganizationJurisdictionAssignmentResponse])
def list_org_jurisdiction_assignments(organization_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_organization_access(organization_id, current_user)
    return service.list_org_jurisdiction_assignments(db, organization_id)


@hierarchy_org_router.put("/{organization_id}/compliance/jurisdiction-assignments", response_model=OrganizationJurisdictionAssignmentResponse)
def upsert_org_jurisdiction_assignment(
    organization_id: int, data: OrganizationJurisdictionAssignmentUpsert,
    current_user=Depends(get_current_org_admin), db: Session = Depends(get_db),
):
    require_organization_access(organization_id, current_user)
    return service.upsert_org_jurisdiction_assignment(db, organization_id, data, actor_id=current_user.id)
